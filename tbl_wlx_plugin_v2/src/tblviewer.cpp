// Total Commander Lister (.wlx) plugin for Falcom #TBL files.
// JSON view + per-section grid view + Config tab. F3 opens read-only;
// F4 toggles read/edit mode. Esc closes. Sub-grid popups for nested
// cells.
//
// Layout:
//   +-----------------------------------------------+
//   | Tab1   Tab2  ... [JSON]  [Config]             |
//   +-----------------------------------------------+
//   |                                               |
//   |       active grid / Edit / Config             |
//   |                                               |
//   +-----------------------------------------------+
//   |  ●file.tbl  | section meta | RO / EDIT MODE   |  status bar
//   +-----------------------------------------------+
//
// Tabs are populated in this order:
//   - one tab per section (all decoded sections become grids;
//     sections without a schema or in raw mode become read-only
//     JSON tabs explaining what happened),
//   - "JSON" tab with the whole-file pretty-printed JSON,
//   - "Config" tab with the INI-bound settings.

#include <windows.h>
#include <commctrl.h>
#include <commdlg.h>
#include <shlwapi.h>

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

#include "listplug.h"
#include "ini_settings.h"
#include "json.h"
#include "schemas.h"
#include "tbl_file.h"
#include "grid_view.h"

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------
static HINSTANCE                       g_hInstance     = nullptr;
static std::wstring                    g_iniPath;
static std::unique_ptr<tbl::SchemaDB>  g_schemaDB;
static bool                            g_schemaLoaded  = false;
static std::vector<std::string>        g_schemaErrors;
static tbl::IniSettings                g_settings;

// Custom message used to forward F4 toggles from child controls back
// to the host window proc.
constexpr UINT WM_TBL_TOGGLE_EDIT_MODE = WM_APP + 1;
constexpr UINT_PTR TIMER_APPLY_WINSTATE = 0x7F01;

// Which kind of content the tab holds.
enum class TabKind { Grid, JsonWhole, JsonNote, Config };

struct UndoEntry {
    int          gridIdx;     // index into PluginInst::grids
    int          modelRow;
    std::string  fieldName;
    mj::Json     oldVal;
    mj::Json     newVal;
};

struct PluginInst;

// One tab descriptor. `kind` tells us which child window to show /
// what content to emit. For grid tabs `gridIdx` indexes into
// PluginInst::grids; for JSON tabs it's the EDIT control; for the
// Config tab it's the config panel.
struct TabDesc {
    TabKind kind        = TabKind::Grid;
    int     gridIdx     = -1;          // grid tabs only
    int     sectionIdx  = -1;          // grid + JsonNote tabs
    HWND    hContent    = nullptr;     // EDIT for json/note tabs; nullptr for grid (use grids[])
    std::string note;                  // JsonNote tabs: the placeholder text
    std::wstring caption;
};

struct PluginInst {
    HWND                                          parentList = nullptr;
    HWND                                          hwnd       = nullptr;
    HWND                                          hTabs      = nullptr;
    // Custom bottom status strip — three STATIC labels positioned
    // manually as direct children of the host. Replaces the standard
    // STATUSCLASSNAME control because that one wasn't reliably honouring
    // grey filler / part widths under TC's Lister parenting.
    HWND                                          hLblFile    = nullptr;
    HWND                                          hLblSection = nullptr;
    HWND                                          hLblMode    = nullptr;
    HBRUSH                                        hModeBrush  = nullptr;   // pale red for EDIT
    HWND                                          hJsonEdit  = nullptr;   // whole-file JSON tab
    HWND                                          hConfig    = nullptr;   // Config tab panel
    WNDPROC                                       origJsonEditProc = nullptr;
    HFONT                                         hFontMono  = nullptr;
    std::wstring                                  filePath;
    bool                                          editMode    = false;    // false = RO
    bool                                          canSave     = false;    // false if any-raw section
    bool                                          jsonBuilt   = false;    // lazy build flag
    bool                                          jsonDirty   = false;    // edit text > model
    bool                                          modelDirty  = false;    // model > edit text
    int                                           activeTab   = 0;
    std::unique_ptr<tbl::TblFile>                 model;
    std::vector<std::unique_ptr<tbl::GridView>>   grids;
    std::vector<TabDesc>                          tabs;
    std::vector<UndoEntry>                        undoStack;
    std::vector<UndoEntry>                        redoStack;
};

static const wchar_t* kViewerClass = L"TBLViewerHostV2";

// ---------------------------------------------------------------------------
// Forward decls
// ---------------------------------------------------------------------------
static void UpdateStatusBar(PluginInst* p);
static void SwitchTab(PluginInst* p, int tabIdx);
static int  SaveCurrent(PluginInst* p, std::string* errOut);
static void ApplyEditModeToUI(PluginInst* p);
static void ToggleEditMode(PluginInst* p);
static std::string BuildJsonText(const tbl::TblFile& t,
                                 const std::wstring& path);
static std::wstring EditTextW(HWND hEdit);
static int  RefreshModelFromJsonEdit(PluginInst* p, std::string* errOut);
static void RebuildJsonEditFromModel(PluginInst* p);
static void DoUndo(PluginInst* p);
static void DoRedo(PluginInst* p);
static void SubclassNavKeys(HWND ctrl);
static void OpenSubGridForCell(PluginInst* p, int gridIdx,
                               int modelRow,
                               const std::string& fieldName);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
static std::wstring DllDir() {
    wchar_t buf[MAX_PATH] = {};
    GetModuleFileNameW(g_hInstance, buf, MAX_PATH);
    std::wstring s = buf;
    size_t slash = s.find_last_of(L"/\\");
    if (slash != std::wstring::npos) s.resize(slash);
    return s;
}

static std::wstring U8ToW(const std::string& s) {
    if (s.empty()) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(),
                                nullptr, 0);
    std::wstring w(n, 0);
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(),
                        w.data(), n);
    return w;
}

static std::string WToU8(const std::wstring& w) {
    if (w.empty()) return "";
    int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(),
                                nullptr, 0, nullptr, nullptr);
    std::string s(n, 0);
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(),
                        s.data(), n, nullptr, nullptr);
    return s;
}

static std::wstring AnsiToW(const char* s) {
    if (!s || !*s) return L"";
    int n = MultiByteToWideChar(CP_ACP, 0, s, -1, nullptr, 0);
    std::wstring w(n ? n - 1 : 0, 0);
    if (n) MultiByteToWideChar(CP_ACP, 0, s, -1, w.data(), n);
    return w;
}

// Convert UTF-8 text with bare \n line endings to UTF-16 with \r\n —
// what the Win32 EDIT control expects for proper multiline display.
static std::wstring U8WithCRLF(const std::string& s) {
    std::string crlf;
    crlf.reserve(s.size() + s.size() / 16);
    for (size_t i = 0; i < s.size(); ++i) {
        char c = s[i];
        if (c == '\n') {
            // Don't double-CRLF if input already has CR.
            if (!(i > 0 && s[i - 1] == '\r')) crlf.push_back('\r');
            crlf.push_back('\n');
        } else if (c == '\r') {
            // bare CR: keep but ensure LF follows
            crlf.push_back('\r');
            if (i + 1 >= s.size() || s[i + 1] != '\n') crlf.push_back('\n');
        } else {
            crlf.push_back(c);
        }
    }
    return U8ToW(crlf);
}

static void EnsureSchemasLoaded() {
    if (g_schemaLoaded) return;
    g_schemaLoaded = true;
    g_schemaDB = std::make_unique<tbl::SchemaDB>();
    std::wstring dir = DllDir() + L"\\schemas";
    if (GetFileAttributesW(dir.c_str()) == INVALID_FILE_ATTRIBUTES) return;
    g_schemaDB->LoadFromDir(dir, &g_schemaErrors);
}

// ---------------------------------------------------------------------------
// JSON view rendering (tabs banner + body)
// ---------------------------------------------------------------------------
static std::string BuildJsonText(const tbl::TblFile& t,
                                 const std::wstring& path) {
    std::string out;
    out += "// Falcom #TBL viewer  -  ";
    out += std::to_string(t.Sections().size());
    out += " section(s)\n";
    out += "// File: " + WToU8(path) + "\n";
    if (t.WasCLEWrapped()) {
        out += "// (file was CLE-wrapped - decrypted/decompressed automatically)\n";
    }
    int idx = 0;
    for (const auto& s : t.Sections()) {
        char buf[256];
        std::snprintf(buf, sizeof(buf),
                      "//   [%d] %-32s len=%-5d mode=%s%s%s\n",
                      idx++, s.name.c_str(), s.entryLength,
                      (s.mode == tbl::TblSectionMode::Decoded ? "decoded" : "raw"),
                      s.gameTag.empty() ? "" : "  game=",
                      s.gameTag.c_str());
        out += buf;
    }
    if (!t.SchemaWarnings().empty()) {
        out += "// Schema warnings:\n";
        for (const auto& w : t.SchemaWarnings()) {
            out += "//   " + w + "\n";
        }
    }
    out += "\n";
    out += mj::Dump(t.ToJson(), 2);
    return out;
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------
static int kTabBarHeight = 26;
constexpr int kStatusHeight     = 22;     // bottom strip height
constexpr int kStatusFileWidth  = 280;
constexpr int kStatusModeMargin = 120;    // grey filler from right edge

// Compute the mode-label width based on the longest text we might
// display, so the label width stays stable across F4 toggles.
static int ComputeModeLabelWidth(HWND ref) {
    static const wchar_t* longest = L"  EDIT MODE  -  F4: read-only  ";
    HDC dc = GetDC(ref);
    if (!dc) return 240;
    HFONT f = (HFONT)SendMessageW(ref, WM_GETFONT, 0, 0);
    if (!f) f = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    HFONT old = (HFONT)SelectObject(dc, f);
    SIZE sz{};
    GetTextExtentPoint32W(dc, longest, (int)wcslen(longest), &sz);
    SelectObject(dc, old);
    ReleaseDC(ref, dc);
    int w = sz.cx + 14;
    if (w < 160) w = 160;
    if (w > 360) w = 360;
    return w;
}

static void LayoutChildren(HWND hwnd, PluginInst* p) {
    if (!p) return;
    RECT r; GetClientRect(hwnd, &r);

    int statusH = (p->hLblFile || p->hLblSection || p->hLblMode)
                  ? kStatusHeight : 0;

    if (p->hTabs) {
        SetWindowPos(p->hTabs, nullptr, 0, 0,
                     r.right, kTabBarHeight,
                     SWP_NOZORDER | SWP_NOACTIVATE);
    }
    int contentY = p->hTabs ? kTabBarHeight : 0;
    int contentH = r.bottom - contentY - statusH;
    if (contentH < 0) contentH = 0;

    if (p->hJsonEdit) {
        SetWindowPos(p->hJsonEdit, nullptr, 0, contentY,
                     r.right, contentH,
                     SWP_NOZORDER | SWP_NOACTIVATE);
    }
    if (p->hConfig) {
        SetWindowPos(p->hConfig, nullptr, 0, contentY,
                     r.right, contentH,
                     SWP_NOZORDER | SWP_NOACTIVATE);
    }
    for (auto& g : p->grids) {
        if (g) g->Resize(0, contentY, r.right, contentH);
    }
    // Note tabs use the same EDIT-control kind; they're part of TabDesc::hContent.
    for (const auto& td : p->tabs) {
        if ((td.kind == TabKind::JsonNote) && td.hContent) {
            SetWindowPos(td.hContent, nullptr, 0, contentY,
                         r.right, contentH,
                         SWP_NOZORDER | SWP_NOACTIVATE);
        }
    }

    // ---- Status strip at the bottom ------------------------------
    int sy = r.bottom - kStatusHeight + 2;
    int sh = kStatusHeight - 4;
    int modeW = ComputeModeLabelWidth(p->hLblMode ? p->hLblMode : hwnd);
    int modeX = r.right - kStatusModeMargin - modeW;
    int midX  = kStatusFileWidth + 8;
    int midW  = modeX - midX - 4;
    if (midW < 60) { midW = 60; }
    if (p->hLblFile) {
        SetWindowPos(p->hLblFile, nullptr, 4, sy, kStatusFileWidth, sh,
                     SWP_NOZORDER | SWP_NOACTIVATE);
    }
    if (p->hLblSection) {
        SetWindowPos(p->hLblSection, nullptr, midX, sy, midW, sh,
                     SWP_NOZORDER | SWP_NOACTIVATE);
    }
    if (p->hLblMode) {
        SetWindowPos(p->hLblMode, nullptr, modeX, sy, modeW, sh,
                     SWP_NOZORDER | SWP_NOACTIVATE);
    }
    // Force a redraw of the bottom strip's grey filler.
    RECT bot = { 0, r.bottom - kStatusHeight, r.right, r.bottom };
    InvalidateRect(hwnd, &bot, TRUE);
}

// ---------------------------------------------------------------------------
// Edit-mode toggle
// ---------------------------------------------------------------------------
static void ApplyEditModeToUI(PluginInst* p) {
    if (!p) return;
    bool enabled = p->editMode && p->canSave;
    // EDIT control read-only flag
    if (p->hJsonEdit) {
        SendMessageW(p->hJsonEdit, EM_SETREADONLY, !enabled, 0);
    }
    UpdateStatusBar(p);
}

static void ToggleEditMode(PluginInst* p) {
    if (!p) return;
    if (!p->canSave) {
        // Mode is forced RO when file isn't savable (any-raw section).
        MessageBeep(MB_ICONASTERISK);
        return;
    }
    p->editMode = !p->editMode;
    ApplyEditModeToUI(p);
}

// ---------------------------------------------------------------------------
// Banner-strip + JSON ↔ model sync
// ---------------------------------------------------------------------------
static std::string StripBanner(const std::string& text) {
    size_t i = 0;
    while (i < text.size()) {
        size_t lineStart = i;
        while (i < text.size() && text[i] != '\n') ++i;
        bool skip = false;
        if (i - lineStart >= 2
            && text[lineStart] == '/' && text[lineStart + 1] == '/') {
            skip = true;
        } else {
            size_t k = lineStart;
            bool allWs = true;
            while (k < i) {
                char c = text[k++];
                if (c != ' ' && c != '\t' && c != '\r') { allWs = false; break; }
            }
            skip = allWs;
        }
        if (!skip) return text.substr(lineStart);
        if (i < text.size() && text[i] == '\n') ++i;
    }
    return "";
}

static std::wstring EditTextW(HWND hEdit) {
    int len = GetWindowTextLengthW(hEdit);
    std::wstring wbuf((size_t)len, 0);
    if (len > 0) GetWindowTextW(hEdit, wbuf.data(), len + 1);
    return wbuf;
}

static int RefreshModelFromJsonEdit(PluginInst* p, std::string* errOut) {
    if (!p || !p->canSave || !p->model) return 0;
    if (!p->jsonDirty)            return 0;        // already in sync
    std::wstring w = EditTextW(p->hJsonEdit);
    std::string  s = WToU8(w);
    // EDIT gives us CRLF; mj::Parse handles whitespace fine.
    std::string body = StripBanner(s);
    try {
        mj::Json parsed = mj::Parse(body);
        p->model->FromJson(parsed);
    } catch (std::exception& e) {
        if (errOut) *errOut = e.what();
        return 1;
    }
    p->jsonDirty = false;
    return 0;
}

static void RebuildJsonEditFromModel(PluginInst* p) {
    if (!p || !p->model || !p->hJsonEdit) return;
    std::string fresh = BuildJsonText(*p->model, p->filePath);
    if (!p->canSave) {
        fresh = "// NOTE: this file has at least one section without a known\n"
                "//       schema (raw mode). Saving is disabled to avoid\n"
                "//       corruption - F4 cannot enable edit mode.\n"
                + fresh;
    }
    SetWindowTextW(p->hJsonEdit, U8WithCRLF(fresh).c_str());
    p->jsonBuilt  = true;
    p->jsonDirty  = false;
    p->modelDirty = false;
}

// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------
static int SaveCurrent(PluginInst* p, std::string* errOut) {
    if (!p) { if (errOut) *errOut = "internal: no instance"; return 1; }
    if (!p->canSave) {
        if (errOut) *errOut = "Cannot save: file has unknown sections.";
        return 1;
    }
    if (!p->editMode) {
        if (errOut) *errOut = "Read-only mode. Press F4 to enable edits.";
        return 1;
    }
    if (!p->model) {
        if (errOut) *errOut = "internal: no model";
        return 1;
    }
    // If we're on JSON tab and dirty, sync to model first.
    if (p->activeTab >= 0 && p->activeTab < (int)p->tabs.size()
        && p->tabs[p->activeTab].kind == TabKind::JsonWhole
        && p->jsonDirty) {
        std::string err;
        if (RefreshModelFromJsonEdit(p, &err) != 0) {
            if (errOut) *errOut = std::string("JSON parse error: ") + err;
            return 1;
        }
    }
    try {
        p->model->WriteToFile(p->filePath);
    } catch (std::exception& e) {
        if (errOut) *errOut = std::string("Write error: ") + e.what();
        return 1;
    }
    p->modelDirty = false;
    UpdateStatusBar(p);
    return 0;
}

// ---------------------------------------------------------------------------
// Status strip (custom: three STATIC labels at the bottom of host)
// ---------------------------------------------------------------------------
static void UpdateStatusBar(PluginInst* p) {
    if (!p) return;

    // Left: filename + dirty marker
    if (p->hLblFile) {
        std::wstring nm = p->filePath;
        size_t slash = nm.find_last_of(L"/\\");
        if (slash != std::wstring::npos) nm = nm.substr(slash + 1);
        std::wstring left = (p->jsonDirty || p->modelDirty)
                          ? (L"  \u25CF " + nm)
                          : (L"  "        + nm);
        SetWindowTextW(p->hLblFile, left.c_str());
    }

    // Middle: section / tab description
    if (p->hLblSection) {
        std::wstring mid;
        if (p->activeTab >= 0 && p->activeTab < (int)p->tabs.size()) {
            const TabDesc& td = p->tabs[p->activeTab];
            if (td.kind == TabKind::Grid && td.sectionIdx >= 0 && p->model) {
                const auto& s = p->model->Sections()[td.sectionIdx];
                int rowCount = s.rows.IsArr() ? (int)s.rows.AsArr().size() : 0;
                wchar_t buf[256];
                std::wstring wname = U8ToW(s.name);
                std::wstring wgame = U8ToW(s.gameTag);
                if (!s.gameTag.empty()) {
                    std::swprintf(buf, 256,
                                  L"%ls  (%d rows, %d B/row, game=%ls)",
                                  wname.c_str(), rowCount, s.entryLength,
                                  wgame.c_str());
                } else {
                    std::swprintf(buf, 256,
                                  L"%ls  (%d rows, %d B/row)",
                                  wname.c_str(), rowCount, s.entryLength);
                }
                mid = buf;
                // Show keyboard-shortcut hint when actually editable.
                if (p->editMode && p->canSave) {
                    mid += L"  -  Ins: add row | Del: remove "
                           L"| Ctrl+S: save | F2/dblclk: edit cell";
                }
            } else if (td.kind == TabKind::JsonWhole) {
                mid = (p->editMode && p->canSave)
                    ? L"JSON view (whole file)  -  Ctrl+S = save"
                    : L"JSON view (whole file, read-only)";
            } else if (td.kind == TabKind::JsonNote) {
                mid = L"Section note";
            } else if (td.kind == TabKind::Config) {
                mid = L"Configuration";
            }
        }
        SetWindowTextW(p->hLblSection, mid.c_str());
    }

    // Right: RO / EDIT marker. Re-paint via WM_CTLCOLORSTATIC.
    if (p->hLblMode) {
        std::wstring rightText;
        if (!p->canSave)      rightText = L"  READ-ONLY (no schema)";
        else if (p->editMode) rightText = L"  EDIT MODE  -  F4: read-only";
        else                  rightText = L"  READ-ONLY  -  F4: edit";
        SetWindowTextW(p->hLblMode, rightText.c_str());
        InvalidateRect(p->hLblMode, nullptr, TRUE);
    }
}

// ---------------------------------------------------------------------------
// Window state persistence (TC's Lister parent)
// ---------------------------------------------------------------------------
static HWND ListerTopLevel(HWND hostWnd) {
    HWND p = GetParent(hostWnd);
    if (!p) return nullptr;
    HWND root = GetAncestor(p, GA_ROOT);
    return root ? root : p;
}

static void ApplyWindowState(HWND hostWnd) {
    HWND lister = ListerTopLevel(hostWnd);
    if (!lister) return;

    if (g_settings.maximizeOnOpen) {
        ShowWindow(lister, SW_MAXIMIZE);
        return;
    }
    if (!g_settings.rememberWinSize) return;

    int x = g_settings.lastWinX, y = g_settings.lastWinY;
    int w = g_settings.lastWinW, h = g_settings.lastWinH;
    bool isMax = g_settings.lastWinMax;

    // If we have nothing useful, just leave the window alone.
    bool haveCoords = (x != -1 && y != -1 && w > 50 && h > 50
                       && x >= -10000 && x <= 30000
                       && y >= -10000 && y <= 30000);
    if (!haveCoords && !isMax) return;

    // Use SetWindowPlacement — it handles BOTH the normal-rect
    // restore position AND the maximized state in a single atomic
    // call, so we don't fight TC's own SetWindowPos timing.
    WINDOWPLACEMENT pl = {};
    pl.length = sizeof(pl);
    GetWindowPlacement(lister, &pl);
    pl.flags   = 0;
    pl.showCmd = isMax ? SW_SHOWMAXIMIZED : SW_SHOWNORMAL;
    if (haveCoords) {
        pl.rcNormalPosition.left   = x;
        pl.rcNormalPosition.top    = y;
        pl.rcNormalPosition.right  = x + w;
        pl.rcNormalPosition.bottom = y + h;
    }
    SetWindowPlacement(lister, &pl);
}

static void CaptureWindowState(HWND hostWnd) {
    HWND lister = ListerTopLevel(hostWnd);
    if (!lister) return;
    WINDOWPLACEMENT pl = {};
    pl.length = sizeof(pl);
    if (!GetWindowPlacement(lister, &pl)) return;
    bool isMax = (pl.showCmd == SW_SHOWMAXIMIZED);
    g_settings.lastWinMax = isMax;
    if (!isMax) {
        // Only overwrite the normal-state geometry when we're
        // actually in a normal window state. If the user closed
        // the window while maximized, we keep the previously-saved
        // restore position so unmaximizing later restores to the
        // expected place.
        RECT r = pl.rcNormalPosition;
        g_settings.lastWinX = r.left;
        g_settings.lastWinY = r.top;
        g_settings.lastWinW = r.right  - r.left;
        g_settings.lastWinH = r.bottom - r.top;
    }
    g_settings.SaveWindowState(g_iniPath);
}

// ---------------------------------------------------------------------------
// Undo / redo (grid cell edits only)
// ---------------------------------------------------------------------------
constexpr size_t kMaxUndoStack = 200;

static void RecordCellEdit(PluginInst* p, int gridIdx,
                           int modelRow, const std::string& fname,
                           mj::Json oldVal, mj::Json newVal) {
    if (!p) return;
    UndoEntry e;
    e.gridIdx   = gridIdx;
    e.modelRow  = modelRow;
    e.fieldName = fname;
    e.oldVal    = std::move(oldVal);
    e.newVal    = std::move(newVal);
    p->undoStack.push_back(std::move(e));
    if (p->undoStack.size() > kMaxUndoStack) {
        p->undoStack.erase(p->undoStack.begin());
    }
    p->redoStack.clear();
    UpdateStatusBar(p);
}

static void ApplyEntryToModel(PluginInst* p, const UndoEntry& e,
                              const mj::Json& valToApply) {
    if (!p || !p->model) return;
    if (e.gridIdx < 0 || e.gridIdx >= (int)p->grids.size()) return;
    // Find the section for this grid by scanning tabs.
    int secIdx = -1;
    for (const auto& td : p->tabs) {
        if (td.kind == TabKind::Grid && td.gridIdx == e.gridIdx) {
            secIdx = td.sectionIdx; break;
        }
    }
    if (secIdx < 0) return;
    auto& secs = p->model->MutableSections();
    if (secIdx >= (int)secs.size()) return;
    auto& sect = secs[secIdx];
    if (!sect.rows.IsArr()) return;
    if (e.modelRow < 0 || e.modelRow >= (int)sect.rows.AsArr().size()) return;
    auto& rowJ = sect.rows.AsArr()[e.modelRow];
    if (!rowJ.IsObj()) return;
    rowJ.At(e.fieldName) = valToApply;
    p->modelDirty = true;
    if (p->grids[e.gridIdx]) p->grids[e.gridIdx]->Refresh();
}

static void DoUndo(PluginInst* p) {
    if (!p || p->undoStack.empty()) return;
    UndoEntry e = std::move(p->undoStack.back());
    p->undoStack.pop_back();
    ApplyEntryToModel(p, e, e.oldVal);
    p->redoStack.push_back(std::move(e));
    UpdateStatusBar(p);
}

static void DoRedo(PluginInst* p) {
    if (!p || p->redoStack.empty()) return;
    UndoEntry e = std::move(p->redoStack.back());
    p->redoStack.pop_back();
    ApplyEntryToModel(p, e, e.newVal);
    p->undoStack.push_back(std::move(e));
    UpdateStatusBar(p);
}

// ---------------------------------------------------------------------------
// Sub-grid popup (Array / Nested cells)
// ---------------------------------------------------------------------------
// When the user double-clicks an array or nested cell, we open a
// modal popup window with its own GridView wrapped on the cell's
// data. On OK we write back; on Cancel we discard. Position/size is
// persisted via INI (LastSubX/Y/W/H).
struct SubGridContext {
    HWND                                 popup       = nullptr;
    // Bottom status strip — same layout as the main host's strip:
    // file label / section label / mode marker. No buttons; user
    // drives everything via keyboard (Ins/Del/Esc/F4/Ctrl+S).
    HWND                                 hLblFile    = nullptr;
    HWND                                 hLblSection = nullptr;
    HWND                                 hLblMode    = nullptr;
    HBRUSH                               hModeBrush  = nullptr;
    PluginInst*                          parent      = nullptr;
    std::unique_ptr<tbl::TblSection>     wrapped;
    std::unique_ptr<tbl::FieldList>      wrappedFields;
    std::unique_ptr<tbl::GridView>       grid;
    mj::Json*                            targetCell  = nullptr;
    bool                                 isWrappedArray = false;
    bool                                 closing     = false;
    std::string                          fieldName;
};

static const wchar_t* kSubGridClass = L"TBLViewerSubGridV1";

// Forward decls.
static void SubGridLayout(SubGridContext* ctx);
static void UpdateSubGridStatus(SubGridContext* ctx);
static void SubGridApplyToCell(SubGridContext* ctx);
static void SubGridCaptureGeometry(SubGridContext* ctx);

// Closes the popup. Whatever the wrapped section now contains will
// be applied back to the target cell — there's no discard path. The
// user explicitly asked for Esc to mean "apply and close" rather than
// "cancel". File save is a separate action (Ctrl+S in the main window
// or the Yes-on-close prompt).
static void SubGridFinish(SubGridContext* ctx) {
    if (!ctx || ctx->closing) return;
    ctx->closing  = true;
    SubGridCaptureGeometry(ctx);
    if (ctx->popup && IsWindow(ctx->popup)) {
        DestroyWindow(ctx->popup);
    }
}

// Apply the wrapped section's data back to the original cell.
// Used by both OK (Ctrl+Enter) and Ctrl+S (which also chains into a
// main-file save afterwards).
static void SubGridApplyToCell(SubGridContext* ctx) {
    if (!ctx || !ctx->targetCell || !ctx->wrapped) return;
    if (ctx->isWrappedArray) {
        mj::Json arr = mj::Json::MakeArr();
        if (ctx->wrapped->rows.IsArr()) {
            for (const auto& r : ctx->wrapped->rows.AsArr()) {
                if (r.IsObj()) {
                    for (const auto& kv : r.AsObj()) {
                        if (kv.first == "value") {
                            arr.AsArr().push_back(kv.second);
                            break;
                        }
                    }
                }
            }
        }
        *ctx->targetCell = std::move(arr);
    } else {
        // Nested: rows array IS the new value.
        *ctx->targetCell = ctx->wrapped->rows;
    }
    if (ctx->parent && ctx->parent->canSave) {
        ctx->parent->modelDirty = true;
    }
}

static void SubGridLayout(SubGridContext* ctx) {
    if (!ctx || !ctx->popup) return;
    RECT r; GetClientRect(ctx->popup, &r);
    int statusH = kStatusHeight;
    int gridH   = r.bottom - statusH;
    if (gridH < 60) gridH = 60;

    if (ctx->grid && ctx->grid->Hwnd()) {
        ctx->grid->Resize(0, 0, r.right, gridH);
    }

    // Bottom status strip — three labels in same layout as main host.
    int sy = gridH + 2;
    int sh = statusH - 4;
    int modeW = ComputeModeLabelWidth(ctx->hLblMode ? ctx->hLblMode
                                                    : ctx->popup);
    int modeX = r.right - kStatusModeMargin - modeW;
    int midX  = kStatusFileWidth + 8;
    int midW  = modeX - midX - 4;
    if (midW < 60) midW = 60;
    if (ctx->hLblFile) {
        SetWindowPos(ctx->hLblFile, nullptr, 4, sy,
                     kStatusFileWidth, sh,
                     SWP_NOZORDER | SWP_NOACTIVATE);
    }
    if (ctx->hLblSection) {
        SetWindowPos(ctx->hLblSection, nullptr, midX, sy, midW, sh,
                     SWP_NOZORDER | SWP_NOACTIVATE);
    }
    if (ctx->hLblMode) {
        SetWindowPos(ctx->hLblMode, nullptr, modeX, sy, modeW, sh,
                     SWP_NOZORDER | SWP_NOACTIVATE);
    }
    // Force the bottom-strip filler area to repaint.
    RECT bot = { 0, gridH, r.right, r.bottom };
    InvalidateRect(ctx->popup, &bot, TRUE);
}

// Update status-strip label text. Mirrors UpdateStatusBar's structure
// but uses the wrapped-section data + the parent's edit-mode state.
static void UpdateSubGridStatus(SubGridContext* ctx) {
    if (!ctx) return;
    bool editable = ctx->parent
                 && ctx->parent->editMode
                 && ctx->parent->canSave;

    // Left: field name (with an icon-like prefix).
    if (ctx->hLblFile) {
        std::wstring lbl = L"  \"" + U8ToW(ctx->fieldName) + L"\"";
        SetWindowTextW(ctx->hLblFile, lbl.c_str());
    }

    // Middle: row count + (only when editable) keyboard shortcuts.
    if (ctx->hLblSection) {
        int n = ctx->wrapped && ctx->wrapped->rows.IsArr()
              ? (int)ctx->wrapped->rows.AsArr().size() : 0;
        wchar_t buf[256];
        if (ctx->isWrappedArray) {
            std::swprintf(buf, 256,
                          L"array, %d element(s)", n);
        } else {
            std::swprintf(buf, 256,
                          L"nested, %d record(s)", n);
        }
        std::wstring mid = buf;
        if (editable) {
            if (ctx->isWrappedArray) {
                mid += L"  -  Ins: add | Del: remove | F2/dblclk: edit "
                       L"| Ctrl+S: save | Esc: close";
            } else {
                mid += L"  -  F2/dblclk: edit | Ctrl+S: save "
                       L"| Esc: close";
            }
        } else {
            mid += L"  -  read-only (F4 in main window first)";
        }
        SetWindowTextW(ctx->hLblSection, mid.c_str());
    }

    // Right: RO/EDIT marker. Re-paint via WM_CTLCOLORSTATIC.
    if (ctx->hLblMode) {
        std::wstring r;
        if (ctx->parent && !ctx->parent->canSave)
            r = L"  READ-ONLY (no schema)";
        else if (editable)
            r = L"  EDIT MODE  -  F4: read-only";
        else
            r = L"  READ-ONLY  -  F4: edit";
        SetWindowTextW(ctx->hLblMode, r.c_str());
        InvalidateRect(ctx->hLblMode, nullptr, TRUE);
    }
    SubGridLayout(ctx);
}

static void SubGridCaptureGeometry(SubGridContext* ctx) {
    if (!ctx || !ctx->popup) return;
    WINDOWPLACEMENT pl = {};
    pl.length = sizeof(pl);
    if (!GetWindowPlacement(ctx->popup, &pl)) return;
    bool isMax = (pl.showCmd == SW_SHOWMAXIMIZED);
    g_settings.lastSubMax = isMax;
    if (!isMax) {
        RECT r = pl.rcNormalPosition;
        g_settings.lastSubX = r.left;
        g_settings.lastSubY = r.top;
        g_settings.lastSubW = r.right - r.left;
        g_settings.lastSubH = r.bottom - r.top;
    }
    if (!g_iniPath.empty()) g_settings.SaveSubGridState(g_iniPath);
}

static LRESULT CALLBACK SubGridWndProc(HWND hwnd, UINT msg,
                                       WPARAM wp, LPARAM lp) {
    SubGridContext* ctx = (SubGridContext*)GetWindowLongPtrW(
        hwnd, GWLP_USERDATA);
    switch (msg) {
        case WM_CREATE: {
            CREATESTRUCT* cs = (CREATESTRUCT*)lp;
            SetWindowLongPtrW(hwnd, GWLP_USERDATA,
                              (LONG_PTR)cs->lpCreateParams);
            return 0;
        }
        case WM_KEYDOWN: {
            bool ctrl = (GetKeyState(VK_CONTROL) & 0x8000) != 0;
            // Esc → apply pending changes and close. There is no
            // discard path on purpose.
            if (wp == VK_ESCAPE) {
                SubGridFinish(ctx);
                return 0;
            }
            // F4 → toggle main edit mode (shared flag); refresh UI.
            if (wp == VK_F4 && ctx && ctx->parent) {
                ToggleEditMode(ctx->parent);
                UpdateSubGridStatus(ctx);
                return 0;
            }
            // Ctrl+S → apply current state to cell + save the file.
            if (ctrl && (wp == 'S' || wp == 's') && ctx && ctx->parent) {
                if (!ctx->parent->canSave || !ctx->parent->editMode) {
                    MessageBeep(MB_ICONHAND);
                    return 0;
                }
                SubGridApplyToCell(ctx);
                std::string err;
                if (SaveCurrent(ctx->parent, &err) != 0) {
                    std::wstring werr = U8ToW(err);
                    MessageBoxW(hwnd, werr.c_str(),
                                L"TBLViewer - save failed",
                                MB_OK | MB_ICONERROR);
                } else {
                    MessageBeep(MB_OK);
                }
                UpdateSubGridStatus(ctx);
                return 0;
            }
            break;
        }
        case WM_SIZE:
            SubGridLayout(ctx);
            return 0;
        case WM_NOTIFY: {
            NMHDR* hdr = (NMHDR*)lp;
            if (hdr && ctx && ctx->grid) {
                LRESULT res = 0;
                if (ctx->grid->HandleNotify(hdr, &res)) return res;
            }
            break;
        }
        case WM_CTLCOLORSTATIC: {
            HDC dc = (HDC)wp;
            HWND ctl = (HWND)lp;
            if (!ctx) break;
            bool editable = ctx->parent
                         && ctx->parent->editMode
                         && ctx->parent->canSave;
            if (ctl == ctx->hLblMode) {
                if (editable) {
                    SetTextColor(dc, RGB(0x88, 0x00, 0x00));
                    SetBkColor(dc, RGB(0xFA, 0xE0, 0xE0));
                    if (!ctx->hModeBrush) {
                        ctx->hModeBrush =
                            CreateSolidBrush(RGB(0xFA, 0xE0, 0xE0));
                    }
                    return (LRESULT)ctx->hModeBrush;
                }
                SetTextColor(dc, GetSysColor(COLOR_BTNTEXT));
                SetBkColor(dc, GetSysColor(COLOR_BTNFACE));
                return (LRESULT)GetSysColorBrush(COLOR_BTNFACE);
            }
            if (ctl == ctx->hLblFile || ctl == ctx->hLblSection) {
                SetTextColor(dc, GetSysColor(COLOR_BTNTEXT));
                SetBkColor(dc, GetSysColor(COLOR_BTNFACE));
                return (LRESULT)GetSysColorBrush(COLOR_BTNFACE);
            }
            break;
        }
        case WM_ERASEBKGND: {
            // Fill the bottom strip area (where the labels sit) with
            // grey so the filler region right of the mode label is
            // properly painted.
            HDC dc = (HDC)wp;
            RECT r; GetClientRect(hwnd, &r);
            RECT bot = { 0, r.bottom - kStatusHeight, r.right, r.bottom };
            FillRect(dc, &bot, GetSysColorBrush(COLOR_BTNFACE));
            return 1;
        }
        case WM_CLOSE:
            SubGridFinish(ctx);
            return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

static void RegisterSubGridClass() {
    static bool reg = false;
    if (reg) return;
    reg = true;
    WNDCLASSEXW wc = {};
    wc.cbSize        = sizeof(wc);
    wc.style         = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc   = SubGridWndProc;
    wc.hInstance     = g_hInstance;
    wc.hCursor       = LoadCursor(nullptr, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    wc.lpszClassName = kSubGridClass;
    RegisterClassExW(&wc);
}

// Open a modal sub-grid popup. The cell's data is mutated in place
// when the popup closes (Esc / X / WM_CLOSE / Ctrl+S all "apply").
// File save is a separate action — Ctrl+S inside the subgrid, Ctrl+S
// in the main window, or the Yes-on-close prompt.
static void OpenSubGridForCell(PluginInst* p, int gridIdx,
                               int modelRow,
                               const std::string& fieldName) {
    if (!p || !p->model) return;
    int sectionIdx = -1;
    for (const auto& td : p->tabs) {
        if (td.kind == TabKind::Grid && td.gridIdx == gridIdx) {
            sectionIdx = td.sectionIdx; break;
        }
    }
    if (sectionIdx < 0) return;

    auto& sect = p->model->MutableSections()[sectionIdx];
    if (!sect.rows.IsArr()
        || modelRow < 0 || modelRow >= (int)sect.rows.AsArr().size()) {
        return;
    }
    auto& rowJ = sect.rows.AsArr()[modelRow];
    if (!rowJ.IsObj()) return;
    mj::Json* targetCell = nullptr;
    for (auto& kv : rowJ.AsObj()) {
        if (kv.first == fieldName) { targetCell = &kv.second; break; }
    }
    if (!targetCell) return;

    const tbl::SchemaVariant* var = g_schemaDB->FindVariant(
        sect.name, sect.entryLength, sect.gameTag);
    if (!var || !var->fields) return;
    const tbl::TblDataType* ft = nullptr;
    for (const auto& f : var->fields->fields) {
        if (f.name == fieldName) { ft = &f.dataType; break; }
    }
    if (!ft) return;

    bool isArray = (ft->kind == tbl::TblBaseKind::U8Array
                 || ft->kind == tbl::TblBaseKind::U16Array
                 || ft->kind == tbl::TblBaseKind::U32Array);
    bool isNested = (ft->kind == tbl::TblBaseKind::Nested);
    if (!isArray && !isNested) return;

    RegisterSubGridClass();

    auto* ctx = new SubGridContext;
    ctx->parent         = p;
    ctx->targetCell     = targetCell;
    ctx->isWrappedArray = isArray;
    ctx->fieldName      = fieldName;
    ctx->wrapped        = std::make_unique<tbl::TblSection>();
    ctx->wrappedFields  = std::make_unique<tbl::FieldList>();
    ctx->wrapped->name        = fieldName;
    ctx->wrapped->entryLength = 0;

    if (isArray) {
        tbl::TblDataType elemType;
        elemType.kind = (ft->kind == tbl::TblBaseKind::U8Array)
                            ? tbl::TblBaseKind::UByte
                      : (ft->kind == tbl::TblBaseKind::U16Array)
                            ? tbl::TblBaseKind::UShort
                            : tbl::TblBaseKind::UInt;
        ctx->wrapped->rows = mj::Json::MakeArr();
        if (targetCell->IsArr()) {
            for (const auto& e : targetCell->AsArr()) {
                mj::Json row = mj::Json::MakeObj();
                row.At("value") = e;
                ctx->wrapped->rows.AsArr().push_back(std::move(row));
            }
        }
        tbl::NamedField nf;
        nf.name = "value";
        nf.dataType = elemType;
        ctx->wrappedFields->fields.push_back(std::move(nf));
    } else {
        if (targetCell->IsArr()) {
            ctx->wrapped->rows = *targetCell;
        } else {
            ctx->wrapped->rows = mj::Json::MakeArr();
        }
        if (ft->nestedFields) {
            *ctx->wrappedFields = *ft->nestedFields;
        }
    }

    int x = g_settings.lastSubX;
    int y = g_settings.lastSubY;
    int w = g_settings.lastSubW > 100 ? g_settings.lastSubW : 700;
    int h = g_settings.lastSubH > 100 ? g_settings.lastSubH : 500;
    if (x == -1 || y == -1) {
        RECT pr; GetWindowRect(p->hwnd, &pr);
        x = pr.left + (pr.right - pr.left - w) / 2;
        y = pr.top  + (pr.bottom - pr.top  - h) / 2;
    }

    HWND owner = ListerTopLevel(p->hwnd);
    if (!owner) owner = p->hwnd;

    std::wstring title = L"Edit \"" + U8ToW(fieldName) + L"\"";

    EnableWindow(owner, FALSE);
    ctx->popup = CreateWindowExW(
        WS_EX_DLGMODALFRAME,
        kSubGridClass, title.c_str(),
        WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU
        | WS_MINIMIZEBOX | WS_MAXIMIZEBOX,
        x, y, w, h, owner, nullptr, g_hInstance, ctx);
    if (!ctx->popup) {
        EnableWindow(owner, TRUE);
        delete ctx;
        return;
    }
    ShowWindow(ctx->popup,
               g_settings.lastSubMax ? SW_SHOWMAXIMIZED : SW_SHOWNORMAL);

    // Three STATIC labels mirroring the main host's status strip.
    HFONT uiFont = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    ctx->hLblFile = CreateWindowExW(0, L"STATIC", L"",
        WS_CHILD | WS_VISIBLE | SS_LEFT | SS_NOPREFIX,
        0, 0, kStatusFileWidth, kStatusHeight - 4,
        ctx->popup, nullptr, g_hInstance, nullptr);
    if (ctx->hLblFile) SendMessageW(ctx->hLblFile, WM_SETFONT, (WPARAM)uiFont, TRUE);
    ctx->hLblSection = CreateWindowExW(0, L"STATIC", L"",
        WS_CHILD | WS_VISIBLE | SS_LEFT | SS_NOPREFIX,
        0, 0, 200, kStatusHeight - 4,
        ctx->popup, nullptr, g_hInstance, nullptr);
    if (ctx->hLblSection) SendMessageW(ctx->hLblSection, WM_SETFONT, (WPARAM)uiFont, TRUE);
    ctx->hLblMode = CreateWindowExW(0, L"STATIC", L"",
        WS_CHILD | WS_VISIBLE | SS_CENTER | SS_NOPREFIX | SS_NOTIFY,
        0, 0, 240, kStatusHeight - 4,
        ctx->popup, nullptr, g_hInstance, nullptr);
    if (ctx->hLblMode) SendMessageW(ctx->hLblMode, WM_SETFONT, (WPARAM)uiFont, TRUE);

    // Inner GridView. Wire add/delete callbacks for U*Array so the
    // user can press Insert / Delete in the inner list and add or
    // remove rows in the wrapped data.
    auto innerOnAdd = [ctx]() {
        if (!ctx || !ctx->isWrappedArray) {
            MessageBeep(MB_ICONASTERISK);
            return;
        }
        if (!ctx->wrapped->rows.IsArr()) {
            ctx->wrapped->rows = mj::Json::MakeArr();
        }
        mj::Json row = mj::Json::MakeObj();
        row.At("value") = mj::Json::MakeInt(0);
        ctx->wrapped->rows.AsArr().push_back(std::move(row));
        if (ctx->grid) ctx->grid->Refresh();
        UpdateSubGridStatus(ctx);
    };
    auto innerOnDel = [ctx](int modelRow) {
        if (!ctx || !ctx->isWrappedArray) {
            MessageBeep(MB_ICONASTERISK);
            return;
        }
        if (!ctx->wrapped->rows.IsArr()) return;
        auto& arr = ctx->wrapped->rows.AsArr();
        if (modelRow < 0 || modelRow >= (int)arr.size()) return;
        arr.erase(arr.begin() + modelRow);
        if (ctx->grid) ctx->grid->Refresh();
        UpdateSubGridStatus(ctx);
    };

    ctx->grid = std::make_unique<tbl::GridView>(
        ctx->popup, g_hInstance,
        ctx->wrapped.get(), ctx->wrappedFields.get(),
        &p->editMode, nullptr,
        tbl::GridView::OnCellEdit{},
        tbl::GridView::OnHotkey{},
        tbl::GridView::OnHotkey{},
        tbl::GridView::OnOpenSub{},          // no recursive sub-grids
        innerOnAdd, innerOnDel);
    if (ctx->grid && ctx->grid->Hwnd()) {
        ShowWindow(ctx->grid->Hwnd(), SW_SHOW);
        SendMessageW(ctx->grid->Hwnd(), WM_SETFONT, (WPARAM)uiFont, TRUE);
    }

    UpdateSubGridStatus(ctx);
    SubGridLayout(ctx);
    SetFocus(ctx->grid ? ctx->grid->Hwnd() : ctx->popup);

    // Private message pump until the popup is destroyed.
    MSG m;
    while (IsWindow(ctx->popup) && !ctx->closing
           && GetMessageW(&m, nullptr, 0, 0)) {
        if (m.message == WM_KEYDOWN) {
            HWND focused = GetFocus();
            HWND fr = focused;
            bool inPopup = false;
            while (fr) {
                if (fr == ctx->popup) { inPopup = true; break; }
                fr = GetParent(fr);
            }
            if (inPopup) {
                bool ctrl = (GetKeyState(VK_CONTROL) & 0x8000) != 0;
                // Esc → apply and close (no discard).
                if (m.wParam == VK_ESCAPE) {
                    SubGridFinish(ctx);
                    continue;
                }
                // F4 → toggle edit mode (shared with main host).
                if (m.wParam == VK_F4) {
                    ToggleEditMode(ctx->parent);
                    UpdateSubGridStatus(ctx);
                    continue;
                }
                // Ctrl+S → apply current state + save the file.
                if (ctrl && (m.wParam == 'S' || m.wParam == 's')) {
                    if (ctx->parent && ctx->parent->canSave
                        && ctx->parent->editMode) {
                        SubGridApplyToCell(ctx);
                        std::string err;
                        if (SaveCurrent(ctx->parent, &err) != 0) {
                            std::wstring werr = U8ToW(err);
                            MessageBoxW(ctx->popup, werr.c_str(),
                                        L"TBLViewer - save failed",
                                        MB_OK | MB_ICONERROR);
                        } else {
                            MessageBeep(MB_OK);
                        }
                        UpdateSubGridStatus(ctx);
                    } else {
                        MessageBeep(MB_ICONHAND);
                    }
                    continue;
                }
            }
        }
        if (!IsDialogMessageW(ctx->popup, &m)) {
            TranslateMessage(&m);
            DispatchMessageW(&m);
        }
    }

    // Always apply pending changes — there is no Cancel path.
    SubGridApplyToCell(ctx);

    if (ctx->hModeBrush) DeleteObject(ctx->hModeBrush);

    EnableWindow(owner, TRUE);
    SetForegroundWindow(p->hwnd);
    SetFocus(p->grids[gridIdx] ? p->grids[gridIdx]->Hwnd() : p->hwnd);

    if (gridIdx >= 0 && gridIdx < (int)p->grids.size()
        && p->grids[gridIdx]) {
        p->grids[gridIdx]->Refresh();
    }
    UpdateStatusBar(p);

    delete ctx;
}

// ---------------------------------------------------------------------------
// Add / Delete row in main grid
// ---------------------------------------------------------------------------
// Build a JSON-shaped default row for the given field list. Used when
// the user presses Insert in a grid to append a new row.
static mj::Json BuildDefaultRow(const tbl::FieldList& fl) {
    mj::Json row = mj::Json::MakeObj();
    for (const auto& f : fl.fields) {
        mj::Json v;
        switch (f.dataType.kind) {
            case tbl::TblBaseKind::Float:
                v = mj::Json::MakeReal(0.0); break;
            case tbl::TblBaseKind::TOffset:
                v = mj::Json::MakeStr(""); break;
            case tbl::TblBaseKind::U8Array:
            case tbl::TblBaseKind::U16Array:
            case tbl::TblBaseKind::U32Array:
                v = mj::Json::MakeArr(); break;
            case tbl::TblBaseKind::Nested: {
                v = mj::Json::MakeArr();
                if (f.dataType.nestedFields) {
                    for (int i = 0; i < f.dataType.nestedSize; ++i) {
                        v.AsArr().push_back(BuildDefaultRow(*f.dataType.nestedFields));
                    }
                }
                break;
            }
            default:
                v = mj::Json::MakeInt(0); break;
        }
        row.At(f.name) = std::move(v);
    }
    return row;
}

static int FindSectionIdxForGrid(PluginInst* p, int gridIdx) {
    for (const auto& td : p->tabs) {
        if (td.kind == TabKind::Grid && td.gridIdx == gridIdx) {
            return td.sectionIdx;
        }
    }
    return -1;
}

static void AddRowToGrid(PluginInst* p, int gridIdx) {
    if (!p || !p->canSave || !p->model) return;
    int sectionIdx = FindSectionIdxForGrid(p, gridIdx);
    if (sectionIdx < 0) return;
    auto& sect = p->model->MutableSections()[sectionIdx];
    if (!sect.rows.IsArr()) sect.rows = mj::Json::MakeArr();
    const tbl::SchemaVariant* var = g_schemaDB->FindVariant(
        sect.name, sect.entryLength, sect.gameTag);
    if (!var || !var->fields) return;
    sect.rows.AsArr().push_back(BuildDefaultRow(*var->fields));
    p->modelDirty = true;
    if (gridIdx < (int)p->grids.size() && p->grids[gridIdx]) {
        p->grids[gridIdx]->Refresh();
        int newIdx = (int)sect.rows.AsArr().size() - 1;
        HWND lv = p->grids[gridIdx]->Hwnd();
        if (lv && newIdx >= 0) {
            ListView_SetItemState(lv, -1, 0,
                                  LVIS_SELECTED | LVIS_FOCUSED);
            ListView_SetItemState(lv, newIdx,
                                  LVIS_SELECTED | LVIS_FOCUSED,
                                  LVIS_SELECTED | LVIS_FOCUSED);
            ListView_EnsureVisible(lv, newIdx, FALSE);
        }
    }
    UpdateStatusBar(p);
}

static void DeleteRowFromGrid(PluginInst* p, int gridIdx, int modelRow) {
    if (!p || !p->canSave || !p->model) return;
    int sectionIdx = FindSectionIdxForGrid(p, gridIdx);
    if (sectionIdx < 0) return;
    auto& sect = p->model->MutableSections()[sectionIdx];
    if (!sect.rows.IsArr()) return;
    auto& arr = sect.rows.AsArr();
    if (modelRow < 0 || modelRow >= (int)arr.size()) return;
    int res = MessageBoxW(p->hwnd,
        L"Delete the focused row?\n\nThis is not undoable. Save first if unsure.",
        L"TBLViewer - confirm row delete",
        MB_YESNO | MB_ICONQUESTION);
    if (res != IDYES) return;
    arr.erase(arr.begin() + modelRow);
    p->modelDirty = true;
    if (gridIdx < (int)p->grids.size() && p->grids[gridIdx]) {
        p->grids[gridIdx]->Refresh();
    }
    UpdateStatusBar(p);
}

static void HideAllContent(PluginInst* p) {
    if (p->hJsonEdit) ShowWindow(p->hJsonEdit, SW_HIDE);
    if (p->hConfig)   ShowWindow(p->hConfig,   SW_HIDE);
    for (auto& g : p->grids) {
        if (g && g->Hwnd()) ShowWindow(g->Hwnd(), SW_HIDE);
    }
    for (auto& td : p->tabs) {
        if (td.kind == TabKind::JsonNote && td.hContent) {
            ShowWindow(td.hContent, SW_HIDE);
        }
    }
}

static void SwitchTab(PluginInst* p, int tabIdx) {
    if (!p || tabIdx < 0 || tabIdx >= (int)p->tabs.size()) return;
    if (p->activeTab == tabIdx) return;

    int prev = p->activeTab;
    const TabDesc& outgoing = (prev >= 0 && prev < (int)p->tabs.size())
                              ? p->tabs[prev] : p->tabs[0];
    const TabDesc& incoming = p->tabs[tabIdx];

    // Leaving JSON tab while text > model: parse, sync to model.
    if (outgoing.kind == TabKind::JsonWhole && p->jsonDirty
        && p->canSave && p->editMode) {
        std::string err;
        if (RefreshModelFromJsonEdit(p, &err) != 0) {
            std::wstring werr = U8ToW(err);
            MessageBoxW(p->hwnd, werr.c_str(),
                        L"TBLViewer - JSON parse error",
                        MB_OK | MB_ICONERROR);
            TabCtrl_SetCurSel(p->hTabs, prev);
            return;
        }
        for (auto& g : p->grids) if (g) g->Refresh();
    }
    // Entering JSON tab with model > text: rebuild text.
    if (incoming.kind == TabKind::JsonWhole) {
        if (!p->jsonBuilt || p->modelDirty) {
            RebuildJsonEditFromModel(p);
        }
    }

    p->activeTab = tabIdx;
    HideAllContent(p);
    HWND focusTo = nullptr;
    switch (incoming.kind) {
        case TabKind::Grid:
            if (incoming.gridIdx >= 0
                && incoming.gridIdx < (int)p->grids.size()
                && p->grids[incoming.gridIdx]) {
                ShowWindow(p->grids[incoming.gridIdx]->Hwnd(), SW_SHOW);
                p->grids[incoming.gridIdx]->Refresh();
                focusTo = p->grids[incoming.gridIdx]->Hwnd();
            }
            break;
        case TabKind::JsonWhole:
            if (p->hJsonEdit) {
                ShowWindow(p->hJsonEdit, SW_SHOW);
                focusTo = p->hJsonEdit;
            }
            break;
        case TabKind::JsonNote:
            if (incoming.hContent) {
                ShowWindow(incoming.hContent, SW_SHOW);
                focusTo = incoming.hContent;
            }
            break;
        case TabKind::Config:
            if (p->hConfig) {
                ShowWindow(p->hConfig, SW_SHOW);
                focusTo = p->hConfig;
            }
            break;
    }
    LayoutChildren(p->hwnd, p);
    UpdateStatusBar(p);
    if (focusTo) SetFocus(focusTo);
}

// ---------------------------------------------------------------------------
// Forward standard navigation keys (Esc/F3/F7/Ctrl+F/F4) up to TC.
// Called from both child-control subclasses and from the host wndproc.
// ---------------------------------------------------------------------------
static bool ForwardNavKey(HWND childWnd, WPARAM vk, LPARAM lp,
                          PluginInst* p) {
    if (!p) return false;
    bool ctrl = (GetKeyState(VK_CONTROL) & 0x8000) != 0;

    // Esc -> close Lister (TC's parent).
    if (vk == VK_ESCAPE) {
        HWND lister = GetParent(p->hwnd);
        if (lister) PostMessageW(lister, WM_KEYDOWN, VK_ESCAPE, lp);
        return true;
    }
    // F3 / F7 / Ctrl+F -> TC's Find dialog.
    if (vk == VK_F3 || vk == VK_F7
        || (ctrl && (vk == 'F' || vk == 'f'))) {
        HWND lister = GetParent(p->hwnd);
        if (lister) PostMessageW(lister, WM_KEYDOWN, vk, lp);
        return true;
    }
    // F4 -> toggle edit/RO mode.
    if (vk == VK_F4) {
        ToggleEditMode(p);
        return true;
    }
    // Ctrl+S -> save (only when editable).
    if (ctrl && (vk == 'S' || vk == 's')) {
        if (!p->editMode || !p->canSave) {
            MessageBeep(MB_ICONHAND);
            return true;
        }
        std::string err;
        if (SaveCurrent(p, &err) != 0) {
            std::wstring werr = U8ToW(err);
            MessageBoxW(p->hwnd, werr.c_str(),
                        L"TBLViewer - save failed",
                        MB_OK | MB_ICONERROR);
        } else {
            MessageBeep(MB_OK);
        }
        return true;
    }
    (void)childWnd;
    return false;
}

// ---------------------------------------------------------------------------
// JSON Edit subclass — forwards nav keys to host, marks dirty
// ---------------------------------------------------------------------------
static LRESULT CALLBACK JsonEditProc(HWND hwnd, UINT msg,
                                     WPARAM wp, LPARAM lp) {
    PluginInst* p = (PluginInst*)GetWindowLongPtrW(
        GetParent(hwnd), GWLP_USERDATA);

    if (msg == WM_GETDLGCODE) {
        return DLGC_WANTALLKEYS | DLGC_WANTCHARS
             | DLGC_WANTARROWS  | DLGC_WANTTAB;
    }
    if (msg == WM_KEYDOWN && p) {
        if (ForwardNavKey(hwnd, wp, lp, p)) return 0;
    }
    if (msg == WM_CHAR && p) {
        // Swallow Esc beep
        if (wp == 0x1B) return 0;
        // Mark dirty on any printable mutation. (Read-only flag on
        // EDIT means WM_CHAR already gets blocked when in RO mode.)
        if (p->canSave && p->editMode) {
            bool was = p->jsonDirty;
            p->jsonDirty = true;
            if (!was) UpdateStatusBar(p);
        }
    }
    if (p && p->origJsonEditProc) {
        return CallWindowProcW(p->origJsonEditProc, hwnd, msg, wp, lp);
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

// Generic subclass for child controls in our panels (Config tab,
// sub-grid popup, etc). Forwards Esc / F3 / F4 / F7 / Ctrl+F /
// Ctrl+S to the relevant top-level container so the user isn't
// trapped after clicking a button.
//
// Walks up the parent chain looking for either:
//   - a window with class kViewerClass (= main host), or
//   - a window with class kSubGridClass (= sub-grid popup),
// and posts the WM_KEYDOWN there.
static LRESULT CALLBACK NavKeyForwarderProc(HWND hwnd, UINT msg,
                                            WPARAM wp, LPARAM lp) {
    WNDPROC orig = (WNDPROC)GetPropW(hwnd, L"TBL.OrigProc");
    if (msg == WM_KEYDOWN || msg == WM_SYSKEYDOWN) {
        bool ctrl = (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        if (wp == VK_ESCAPE || wp == VK_F3 || wp == VK_F4 || wp == VK_F7
            || (ctrl && (wp == 'F' || wp == 'S'))) {
            wchar_t cls[64];
            HWND walker = hwnd;
            HWND target = nullptr;
            for (int i = 0; i < 8 && walker; ++i) {
                walker = GetParent(walker);
                if (!walker) break;
                if (GetClassNameW(walker, cls, 64) > 0) {
                    if (wcscmp(cls, kViewerClass) == 0
                        || wcscmp(cls, kSubGridClass) == 0) {
                        target = walker;
                        break;
                    }
                }
            }
            if (target) PostMessageW(target, WM_KEYDOWN, wp, lp);
            return 0;
        }
    }
    if (orig) return CallWindowProcW(orig, hwnd, msg, wp, lp);
    return DefWindowProcW(hwnd, msg, wp, lp);
}

static void SubclassNavKeys(HWND ctrl) {
    if (!ctrl) return;
    WNDPROC orig = (WNDPROC)SetWindowLongPtrW(
        ctrl, GWLP_WNDPROC, (LONG_PTR)NavKeyForwarderProc);
    SetPropW(ctrl, L"TBL.OrigProc", (HANDLE)orig);
}

// ---------------------------------------------------------------------------
// Config tab — functional INI-bound controls (mirrors Pascal upstream)
// ---------------------------------------------------------------------------
static const wchar_t* kConfigClass = L"TBLViewerConfigPanelV2";

namespace {
constexpr int ID_CMB_GAME       = 1001;
constexpr int ID_CHK_EDITMODE   = 1002;
constexpr int ID_CHK_REMEMBER   = 1003;
constexpr int ID_CHK_MAXIMIZE   = 1004;
constexpr int ID_BTN_SAVE       = 1010;
constexpr int ID_BTN_RESET      = 1011;
constexpr int ID_BTN_OPENINI    = 1012;
constexpr int ID_BTN_EXPORTJSON = 1013;
constexpr int ID_LBL_STATUS     = 1020;
constexpr int ID_LBL_INIPATH    = 1021;
constexpr int ID_LBL_LASTWIN    = 1022;
constexpr int ID_LBL_SCHEMAS    = 1023;

// Game tags + display labels (parallel arrays).
const wchar_t* const kGameLabels[] = {
    L"(auto-detect)",
    L"Kuro1 (Trails through Daybreak)",
    L"Kuro2 (Trails through Daybreak II)",
    L"Sora1 (Trails in the Sky FC)",
    L"Ys_X",
    L"Kai"
};
const char* const kGameTags[] = {
    "", "Kuro1", "Kuro2", "Sora1", "Ys_X", "Kai"
};
constexpr int kGameCount = 6;
} // namespace

static int FindGameIndex(const std::string& tag) {
    for (int i = 0; i < kGameCount; ++i) {
        if (tag == kGameTags[i]) return i;
    }
    return 0;
}

static void ConfigSetText(HWND panel, int id, const std::wstring& text) {
    HWND h = GetDlgItem(panel, id);
    if (h) SetWindowTextW(h, text.c_str());
}

static void ConfigPopulateInfoLabels(HWND panel) {
    if (g_iniPath.empty()) {
        ConfigSetText(panel, ID_LBL_INIPATH,
                      L"INI file: (TC has not yet supplied a path)");
    } else {
        ConfigSetText(panel, ID_LBL_INIPATH,
                      L"INI file: " + g_iniPath);
    }
    wchar_t buf[256];
    if (g_settings.lastWinX == -1 && g_settings.lastWinY == -1
        && g_settings.lastWinW == -1 && g_settings.lastWinH == -1) {
        ConfigSetText(panel, ID_LBL_LASTWIN,
                      L"Last window state: (not yet captured)");
    } else {
        std::swprintf(buf, 256,
                      L"Last window state: X=%d Y=%d W=%d H=%d%ls",
                      g_settings.lastWinX, g_settings.lastWinY,
                      g_settings.lastWinW, g_settings.lastWinH,
                      g_settings.lastWinMax ? L" (maximized)" : L"");
        ConfigSetText(panel, ID_LBL_LASTWIN, buf);
    }
    int total    = g_schemaDB ? g_schemaDB->HeaderCount()  : 0;
    int variants = g_schemaDB ? g_schemaDB->VariantCount() : 0;
    std::swprintf(buf, 256,
                  L"Schemas loaded: %d header(s), %d variant(s)",
                  total, variants);
    ConfigSetText(panel, ID_LBL_SCHEMAS, buf);
}

static void ConfigLoadFromSettings(HWND panel) {
    HWND cmb = GetDlgItem(panel, ID_CMB_GAME);
    if (cmb) {
        SendMessageW(cmb, CB_SETCURSEL,
                     (WPARAM)FindGameIndex(g_settings.preferredGame), 0);
    }
    auto setCheck = [&](int id, bool v) {
        HWND h = GetDlgItem(panel, id);
        if (h) SendMessageW(h, BM_SETCHECK, v ? BST_CHECKED : BST_UNCHECKED, 0);
    };
    setCheck(ID_CHK_EDITMODE, g_settings.defaultEditMode);
    setCheck(ID_CHK_REMEMBER, g_settings.rememberWinSize);
    setCheck(ID_CHK_MAXIMIZE, g_settings.maximizeOnOpen);
    ConfigPopulateInfoLabels(panel);
}

static void ConfigSaveToSettings(HWND panel) {
    HWND cmb = GetDlgItem(panel, ID_CMB_GAME);
    if (cmb) {
        int idx = (int)SendMessageW(cmb, CB_GETCURSEL, 0, 0);
        if (idx >= 0 && idx < kGameCount) {
            g_settings.preferredGame = kGameTags[idx];
        }
    }
    auto getCheck = [&](int id) -> bool {
        HWND h = GetDlgItem(panel, id);
        if (!h) return false;
        return (SendMessageW(h, BM_GETCHECK, 0, 0) == BST_CHECKED);
    };
    g_settings.defaultEditMode = getCheck(ID_CHK_EDITMODE);
    g_settings.rememberWinSize = getCheck(ID_CHK_REMEMBER);
    g_settings.maximizeOnOpen  = getCheck(ID_CHK_MAXIMIZE);

    if (!g_iniPath.empty()) {
        g_settings.SaveOptions(g_iniPath);
        ConfigSetText(panel, ID_LBL_STATUS,
                      L"Saved to " + g_iniPath);
    } else {
        ConfigSetText(panel, ID_LBL_STATUS,
                      L"Settings updated in memory "
                      L"(no INI path - TC didn't supply one).");
    }
    ConfigPopulateInfoLabels(panel);
}

static void ConfigResetToDefaults(HWND panel) {
    HWND cmb = GetDlgItem(panel, ID_CMB_GAME);
    if (cmb) SendMessageW(cmb, CB_SETCURSEL, 0, 0);
    auto setCheck = [&](int id, bool v) {
        HWND h = GetDlgItem(panel, id);
        if (h) SendMessageW(h, BM_SETCHECK, v ? BST_CHECKED : BST_UNCHECKED, 0);
    };
    setCheck(ID_CHK_EDITMODE, false);
    setCheck(ID_CHK_REMEMBER, true);
    setCheck(ID_CHK_MAXIMIZE, false);
    ConfigSetText(panel, ID_LBL_STATUS,
                  L"Defaults loaded. Click Save to persist.");
}

static void ConfigOpenIniInEditor(HWND panel) {
    if (g_iniPath.empty()) {
        ConfigSetText(panel, ID_LBL_STATUS,
                      L"No INI path available - TC hasn't supplied one yet.");
        return;
    }
    ShellExecuteW(panel, L"open", g_iniPath.c_str(),
                  nullptr, nullptr, SW_SHOWNORMAL);
}

// Export the currently-loaded TBL's full JSON (banner + body) to a
// user-chosen file path via GetSaveFileName.
static void ConfigExportTblAsJson(HWND panel) {
    PluginInst* p = (PluginInst*)GetWindowLongPtrW(
        GetParent(panel), GWLP_USERDATA);
    if (!p || !p->model) {
        ConfigSetText(panel, ID_LBL_STATUS,
                      L"No file is loaded.");
        return;
    }
    // Default filename: <basename>.json next to the source TBL.
    std::wstring suggested = p->filePath;
    size_t dot = suggested.find_last_of(L'.');
    if (dot != std::wstring::npos) suggested = suggested.substr(0, dot);
    suggested += L".json";

    wchar_t pathBuf[MAX_PATH * 2] = {};
    wcsncpy(pathBuf, suggested.c_str(), MAX_PATH * 2 - 1);

    OPENFILENAMEW ofn = {};
    ofn.lStructSize = sizeof(ofn);
    ofn.hwndOwner   = panel;
    ofn.lpstrFilter = L"JSON files (*.json)\0*.json\0All files (*.*)\0*.*\0\0";
    ofn.lpstrFile   = pathBuf;
    ofn.nMaxFile    = MAX_PATH * 2;
    ofn.lpstrDefExt = L"json";
    ofn.lpstrTitle  = L"Export TBL as JSON";
    ofn.Flags       = OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR;

    if (!GetSaveFileNameW(&ofn)) {
        ConfigSetText(panel, ID_LBL_STATUS, L"Export cancelled.");
        return;
    }

    std::string body = BuildJsonText(*p->model, p->filePath);
    HANDLE h = CreateFileW(pathBuf, GENERIC_WRITE, 0, nullptr,
                           CREATE_ALWAYS,
                           FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) {
        ConfigSetText(panel, ID_LBL_STATUS, L"Failed to open file for writing.");
        return;
    }
    DWORD written = 0;
    // Write a UTF-8 BOM so editors recognize the encoding correctly.
    static const unsigned char bom[3] = { 0xEF, 0xBB, 0xBF };
    WriteFile(h, bom, 3, &written, nullptr);
    WriteFile(h, body.data(), (DWORD)body.size(), &written, nullptr);
    CloseHandle(h);

    std::wstring msg = L"Exported to " + std::wstring(pathBuf);
    ConfigSetText(panel, ID_LBL_STATUS, msg.c_str());
}

static LRESULT CALLBACK ConfigPanelProc(HWND hwnd, UINT msg,
                                        WPARAM wp, LPARAM lp) {
    PluginInst* p = (PluginInst*)GetWindowLongPtrW(
        GetParent(hwnd), GWLP_USERDATA);
    switch (msg) {
        case WM_KEYDOWN:
            if (p && ForwardNavKey(hwnd, wp, lp, p)) return 0;
            break;
        case WM_ERASEBKGND: {
            HDC dc = (HDC)wp;
            RECT r; GetClientRect(hwnd, &r);
            FillRect(dc, &r, (HBRUSH)(COLOR_BTNFACE + 1));
            return 1;
        }
        case WM_CTLCOLORSTATIC: {
            // Make labels show through with the panel background.
            HDC dc = (HDC)wp;
            SetBkMode(dc, TRANSPARENT);
            return (LRESULT)GetSysColorBrush(COLOR_BTNFACE);
        }
        case WM_COMMAND: {
            int id = LOWORD(wp);
            switch (id) {
                case ID_BTN_SAVE:
                    ConfigSaveToSettings(hwnd);
                    if (p && p->hwnd) SetFocus(p->hwnd);
                    return 0;
                case ID_BTN_RESET:
                    ConfigResetToDefaults(hwnd);
                    if (p && p->hwnd) SetFocus(p->hwnd);
                    return 0;
                case ID_BTN_OPENINI:
                    ConfigOpenIniInEditor(hwnd);
                    if (p && p->hwnd) SetFocus(p->hwnd);
                    return 0;
                case ID_BTN_EXPORTJSON:
                    ConfigExportTblAsJson(hwnd);
                    if (p && p->hwnd) SetFocus(p->hwnd);
                    return 0;
            }
            break;
        }
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

static void RegisterConfigClass() {
    static bool reg = false;
    if (reg) return;
    reg = true;
    WNDCLASSEXW wc = {};
    wc.cbSize        = sizeof(wc);
    wc.style         = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc   = ConfigPanelProc;
    wc.hInstance     = g_hInstance;
    wc.hCursor       = LoadCursor(nullptr, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    wc.lpszClassName = kConfigClass;
    RegisterClassExW(&wc);
}

// Build the Config panel's child controls. Called once per panel
// after the panel itself is created.
static void BuildConfigControls(HWND panel) {
    constexpr int ROW_HEIGHT  = 28;
    constexpr int LABEL_WIDTH = 240;
    constexpr int CTRL_LEFT   = 260;
    constexpr int CTRL_WIDTH  = 320;
    constexpr int PAD_LEFT    = 20;
    constexpr int PAD_TOP     = 20;

    HFONT uiFont = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    auto setFont = [&](HWND h) {
        SendMessageW(h, WM_SETFONT, (WPARAM)uiFont, TRUE);
    };
    auto installCtrl = [&](HWND h) {
        setFont(h);
        SubclassNavKeys(h);
    };

    int y = PAD_TOP;

    // Row 1: PreferredGame
    HWND lbl = CreateWindowExW(0, L"STATIC",
        L"Preferred game (header tie-break):",
        WS_CHILD | WS_VISIBLE | SS_LEFT,
        PAD_LEFT, y + 4, LABEL_WIDTH, 18,
        panel, nullptr, g_hInstance, nullptr);
    setFont(lbl);
    HWND cmb = CreateWindowExW(0, L"COMBOBOX", nullptr,
        WS_CHILD | WS_VISIBLE | WS_VSCROLL | CBS_DROPDOWNLIST | WS_TABSTOP,
        CTRL_LEFT, y, CTRL_WIDTH, 200,
        panel, (HMENU)(INT_PTR)ID_CMB_GAME, g_hInstance, nullptr);
    installCtrl(cmb);
    for (int i = 0; i < kGameCount; ++i) {
        SendMessageW(cmb, CB_ADDSTRING, 0, (LPARAM)kGameLabels[i]);
    }

    // Row 2: DefaultEditMode
    y += ROW_HEIGHT;
    HWND chk = CreateWindowExW(0, L"BUTTON",
        L"Default edit mode (open in edit mode, skip F4 toggle)",
        WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX | WS_TABSTOP,
        PAD_LEFT, y + 2, LABEL_WIDTH + CTRL_WIDTH, 22,
        panel, (HMENU)(INT_PTR)ID_CHK_EDITMODE, g_hInstance, nullptr);
    installCtrl(chk);

    // Row 3: RememberWindowSize
    y += ROW_HEIGHT;
    chk = CreateWindowExW(0, L"BUTTON",
        L"Remember window position and size between sessions",
        WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX | WS_TABSTOP,
        PAD_LEFT, y + 2, LABEL_WIDTH + CTRL_WIDTH, 22,
        panel, (HMENU)(INT_PTR)ID_CHK_REMEMBER, g_hInstance, nullptr);
    installCtrl(chk);

    // Row 4: MaximizeOnOpen
    y += ROW_HEIGHT;
    chk = CreateWindowExW(0, L"BUTTON",
        L"Always maximize Lister on open (overrides remembered size)",
        WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX | WS_TABSTOP,
        PAD_LEFT, y + 2, LABEL_WIDTH + CTRL_WIDTH, 22,
        panel, (HMENU)(INT_PTR)ID_CHK_MAXIMIZE, g_hInstance, nullptr);
    installCtrl(chk);

    // Row 5: Buttons
    y += ROW_HEIGHT * 2;
    HWND btn = CreateWindowExW(0, L"BUTTON", L"Save",
        WS_CHILD | WS_VISIBLE | BS_DEFPUSHBUTTON | WS_TABSTOP,
        PAD_LEFT, y, 100, 28,
        panel, (HMENU)(INT_PTR)ID_BTN_SAVE, g_hInstance, nullptr);
    installCtrl(btn);
    btn = CreateWindowExW(0, L"BUTTON", L"Reset to defaults",
        WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON | WS_TABSTOP,
        PAD_LEFT + 110, y, 140, 28,
        panel, (HMENU)(INT_PTR)ID_BTN_RESET, g_hInstance, nullptr);
    installCtrl(btn);
    btn = CreateWindowExW(0, L"BUTTON", L"Open INI in editor",
        WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON | WS_TABSTOP,
        PAD_LEFT + 260, y, 160, 28,
        panel, (HMENU)(INT_PTR)ID_BTN_OPENINI, g_hInstance, nullptr);
    installCtrl(btn);

    // Row 5b: Export TBL as JSON (separate row so it stands out from
    // the INI-related buttons above).
    y += 36;
    btn = CreateWindowExW(0, L"BUTTON", L"Export current TBL as JSON...",
        WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON | WS_TABSTOP,
        PAD_LEFT, y, 250, 28,
        panel, (HMENU)(INT_PTR)ID_BTN_EXPORTJSON, g_hInstance, nullptr);
    installCtrl(btn);

    // Row 6+: read-only info labels
    y += 40;
    HWND inip = CreateWindowExW(0, L"STATIC", L"",
        WS_CHILD | WS_VISIBLE | SS_LEFT | SS_PATHELLIPSIS,
        PAD_LEFT, y, LABEL_WIDTH + CTRL_WIDTH + 200, 18,
        panel, (HMENU)(INT_PTR)ID_LBL_INIPATH, g_hInstance, nullptr);
    setFont(inip);

    y += 22;
    HWND wlbl = CreateWindowExW(0, L"STATIC", L"",
        WS_CHILD | WS_VISIBLE | SS_LEFT,
        PAD_LEFT, y, LABEL_WIDTH + CTRL_WIDTH + 200, 18,
        panel, (HMENU)(INT_PTR)ID_LBL_LASTWIN, g_hInstance, nullptr);
    setFont(wlbl);

    y += 22;
    HWND slbl = CreateWindowExW(0, L"STATIC", L"",
        WS_CHILD | WS_VISIBLE | SS_LEFT,
        PAD_LEFT, y, LABEL_WIDTH + CTRL_WIDTH + 200, 18,
        panel, (HMENU)(INT_PTR)ID_LBL_SCHEMAS, g_hInstance, nullptr);
    setFont(slbl);

    // Status line (save confirmations)
    y += 30;
    HWND st = CreateWindowExW(0, L"STATIC", L"",
        WS_CHILD | WS_VISIBLE | SS_LEFT,
        PAD_LEFT, y, LABEL_WIDTH + CTRL_WIDTH + 200, 18,
        panel, (HMENU)(INT_PTR)ID_LBL_STATUS, g_hInstance, nullptr);
    setFont(st);

    ConfigLoadFromSettings(panel);
}

// ---------------------------------------------------------------------------
// Host window proc
// ---------------------------------------------------------------------------
static LRESULT CALLBACK ViewerWndProc(HWND hwnd, UINT msg,
                                      WPARAM wp, LPARAM lp) {
    PluginInst* p = (PluginInst*)GetWindowLongPtrW(hwnd, GWLP_USERDATA);
    switch (msg) {
        case WM_CREATE: {
            CREATESTRUCT* cs = (CREATESTRUCT*)lp;
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, (LONG_PTR)cs->lpCreateParams);
            return 0;
        }
        case WM_GETDLGCODE:
            return DLGC_WANTALLKEYS | DLGC_WANTCHARS
                 | DLGC_WANTARROWS  | DLGC_WANTTAB;
        case WM_ERASEBKGND: {
            // Children cover most of the client area, but the bottom
            // status strip needs a grey fill where there's no STATIC
            // (i.e. the trailing filler area to the right of the
            // mode label).
            HDC dc = (HDC)wp;
            RECT r; GetClientRect(hwnd, &r);
            RECT bot = { 0, r.bottom - kStatusHeight, r.right, r.bottom };
            FillRect(dc, &bot, GetSysColorBrush(COLOR_BTNFACE));
            return 1;
        }
        case WM_KEYDOWN:
            if (p && ForwardNavKey(hwnd, wp, lp, p)) return 0;
            break;
        case WM_TBL_TOGGLE_EDIT_MODE:
            ToggleEditMode(p);
            return 0;
        case WM_TIMER:
            if (wp == TIMER_APPLY_WINSTATE) {
                KillTimer(hwnd, TIMER_APPLY_WINSTATE);
                ApplyWindowState(hwnd);
                return 0;
            }
            break;
        case WM_SIZE:
            LayoutChildren(hwnd, p);
            return 0;
        case WM_SETFOCUS: {
            if (p && p->activeTab >= 0
                && p->activeTab < (int)p->tabs.size()) {
                const TabDesc& td = p->tabs[p->activeTab];
                if (td.kind == TabKind::Grid && td.gridIdx >= 0
                    && td.gridIdx < (int)p->grids.size()
                    && p->grids[td.gridIdx]) {
                    SetFocus(p->grids[td.gridIdx]->Hwnd());
                } else if (td.kind == TabKind::JsonWhole && p->hJsonEdit) {
                    SetFocus(p->hJsonEdit);
                } else if (td.kind == TabKind::JsonNote && td.hContent) {
                    SetFocus(td.hContent);
                } else if (td.kind == TabKind::Config && p->hConfig) {
                    SetFocus(p->hConfig);
                }
            }
            return 0;
        }
        case WM_NOTIFY: {
            NMHDR* hdr = (NMHDR*)lp;
            if (!hdr || !p) break;
            if (hdr->hwndFrom == p->hTabs && hdr->code == TCN_SELCHANGE) {
                int sel = TabCtrl_GetCurSel(p->hTabs);
                SwitchTab(p, sel);
                return 0;
            }
            // Forward to the active grid only (cheaper than scanning
            // all grids — and ListView dispinfo callbacks fire only
            // on the visible grid anyway).
            if (p->activeTab >= 0 && p->activeTab < (int)p->tabs.size()) {
                const TabDesc& td = p->tabs[p->activeTab];
                if (td.kind == TabKind::Grid
                    && td.gridIdx >= 0
                    && td.gridIdx < (int)p->grids.size()
                    && p->grids[td.gridIdx]) {
                    LRESULT res = 0;
                    if (p->grids[td.gridIdx]->HandleNotify(hdr, &res)) {
                        return res;
                    }
                }
            }
            break;
        }
        case WM_CTLCOLORSTATIC: {
            // Paint the status-strip labels:
            //   - File / Section labels: COLOR_BTNFACE bg, plain text
            //   - Mode label: pale red bg + dark red text in EDIT mode
            HDC dc = (HDC)wp;
            HWND ctl = (HWND)lp;
            if (!p) break;
            if (ctl == p->hLblMode) {
                if (p->canSave && p->editMode) {
                    SetTextColor(dc, RGB(0x88, 0x00, 0x00));
                    SetBkColor(dc, RGB(0xFA, 0xE0, 0xE0));
                    if (!p->hModeBrush) {
                        p->hModeBrush =
                            CreateSolidBrush(RGB(0xFA, 0xE0, 0xE0));
                    }
                    return (LRESULT)p->hModeBrush;
                }
                SetTextColor(dc, GetSysColor(COLOR_BTNTEXT));
                SetBkColor(dc, GetSysColor(COLOR_BTNFACE));
                return (LRESULT)GetSysColorBrush(COLOR_BTNFACE);
            }
            if (ctl == p->hLblFile || ctl == p->hLblSection) {
                SetTextColor(dc, GetSysColor(COLOR_BTNTEXT));
                SetBkColor(dc, GetSysColor(COLOR_BTNFACE));
                return (LRESULT)GetSysColorBrush(COLOR_BTNFACE);
            }
            break;
        }
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

static void RegisterViewerClass() {
    static bool reg = false;
    if (reg) return;
    reg = true;
    WNDCLASSEXW wc = {};
    wc.cbSize        = sizeof(wc);
    wc.style         = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc   = ViewerWndProc;
    wc.hInstance     = g_hInstance;
    wc.hCursor       = LoadCursor(nullptr, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    wc.lpszClassName = kViewerClass;
    RegisterClassExW(&wc);
}

// ---------------------------------------------------------------------------
// DoLoad
// ---------------------------------------------------------------------------
static HWND DoLoad(HWND parent, const std::wstring& path) {
    EnsureSchemasLoaded();
    if (g_iniPath.empty()) {
        g_iniPath = DllDir() + L"\\tblviewer.ini";
    }
    g_settings.Load(g_iniPath);

    auto p = std::make_unique<PluginInst>();
    p->parentList = parent;
    p->filePath   = path;

    // Parse file (best-effort).
    p->model = std::make_unique<tbl::TblFile>(g_schemaDB.get());
    bool loadOk = false;
    std::string loadErr;
    try {
        p->model->ReadFromFile(path, g_settings.preferredGame);
        p->canSave = !p->model->AnyRawSection();
        loadOk = true;
    } catch (std::exception& e) {
        loadErr = e.what();
        p->canSave = false;
    }

    // Default edit mode honours INI; RO if not savable anyway.
    p->editMode = (p->canSave && g_settings.defaultEditMode);

    // Container window.
    RegisterViewerClass();
    RegisterConfigClass();
    RECT pr; GetClientRect(parent, &pr);
    HWND hwnd = CreateWindowExW(
        0, kViewerClass, L"",
        WS_CHILD | WS_VISIBLE | WS_TABSTOP,
        0, 0, pr.right - pr.left, pr.bottom - pr.top,
        parent, nullptr, g_hInstance, p.get());
    if (!hwnd) return nullptr;
    PluginInst* raw = p.release();
    raw->hwnd = hwnd;

    // Tab strip. Variable-width tabs so long captions like
    // "CostumeAttachOffset [1]" don't get truncated.
    raw->hTabs = CreateWindowExW(
        0, WC_TABCONTROLW, L"",
        WS_CHILD | WS_VISIBLE | TCS_TOOLTIPS | TCS_FOCUSNEVER,
        0, 0, pr.right - pr.left, kTabBarHeight,
        hwnd, nullptr, g_hInstance, nullptr);
    if (raw->hTabs) {
        SendMessageW(raw->hTabs, WM_SETFONT,
                     (WPARAM)GetStockObject(DEFAULT_GUI_FONT), TRUE);
        // Set min-width per tab item so very short names still get
        // some breathing room.
        TabCtrl_SetMinTabWidth(raw->hTabs, 60);
    }

    // Monospace font for JSON / note tabs.
    int pt = -g_settings.fontSize;
    raw->hFontMono = CreateFontW(
        pt, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
        DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
        CLEARTYPE_QUALITY, FIXED_PITCH | FF_MODERN, L"Consolas");
    if (!raw->hFontMono) {
        raw->hFontMono = (HFONT)GetStockObject(ANSI_FIXED_FONT);
    }

    // ---- Build tabs ----
    auto addGridTab = [&](int sectionIdx) {
        const auto& s = raw->model->Sections()[sectionIdx];
        std::wstring caption = U8ToW(s.name) + L" [" +
                               std::to_wstring(sectionIdx) + L"]";
        const tbl::SchemaVariant* var = g_schemaDB
            ? g_schemaDB->FindVariant(s.name, s.entryLength, s.gameTag)
            : nullptr;
        if (!var || !var->fields) {
            // Note tab.
            std::string note = "// Section \"" + s.name +
                "\" decoded but no schema variant available.\n";
            HWND hNote = CreateWindowExW(
                WS_EX_CLIENTEDGE, L"EDIT", L"",
                WS_CHILD | WS_VSCROLL | WS_HSCROLL | ES_MULTILINE
                | ES_READONLY | ES_AUTOVSCROLL | ES_AUTOHSCROLL,
                0, 0, 100, 100, hwnd, nullptr, g_hInstance, nullptr);
            SendMessageW(hNote, WM_SETFONT, (WPARAM)raw->hFontMono, FALSE);
            SetWindowTextW(hNote, U8WithCRLF(note).c_str());
            ShowWindow(hNote, SW_HIDE);
            TabDesc td;
            td.kind       = TabKind::JsonNote;
            td.hContent   = hNote;
            td.sectionIdx = sectionIdx;
            td.caption    = caption;
            td.note       = note;
            raw->tabs.push_back(std::move(td));
            return;
        }
        // Real grid.
        bool* dirtyPtr = raw->canSave ? &raw->modelDirty : nullptr;
        int gridIdx = (int)raw->grids.size();
        auto onEdit = [raw, gridIdx](int modelRow, const std::string& fn,
                                     mj::Json oldV, mj::Json newV) {
            RecordCellEdit(raw, gridIdx, modelRow, fn,
                           std::move(oldV), std::move(newV));
        };
        auto onUndo = [raw]() { DoUndo(raw); };
        auto onRedo = [raw]() { DoRedo(raw); };
        auto onSub  = [raw, gridIdx](int modelRow, const std::string& fn) {
            OpenSubGridForCell(raw, gridIdx, modelRow, fn);
        };
        auto onAdd  = [raw, gridIdx]() {
            AddRowToGrid(raw, gridIdx);
        };
        auto onDel  = [raw, gridIdx](int modelRow) {
            DeleteRowFromGrid(raw, gridIdx, modelRow);
        };
        auto& sect = raw->model->MutableSections()[sectionIdx];
        auto g = std::make_unique<tbl::GridView>(
            hwnd, g_hInstance, &sect, var->fields.get(),
            &raw->editMode,
            dirtyPtr,
            raw->canSave ? onEdit : tbl::GridView::OnCellEdit{},
            raw->canSave ? onUndo : tbl::GridView::OnHotkey{},
            raw->canSave ? onRedo : tbl::GridView::OnHotkey{},
            onSub,                                   // sub-grid always allowed (RO too)
            raw->canSave ? onAdd : tbl::GridView::OnRowAdd{},
            raw->canSave ? onDel : tbl::GridView::OnRowDelete{});
        if (g->Hwnd()) {
            ShowWindow(g->Hwnd(), SW_HIDE);
            SendMessageW(g->Hwnd(), WM_SETFONT,
                         (WPARAM)GetStockObject(DEFAULT_GUI_FONT), TRUE);
        }
        raw->grids.push_back(std::move(g));
        TabDesc td;
        td.kind       = TabKind::Grid;
        td.gridIdx    = gridIdx;
        td.sectionIdx = sectionIdx;
        td.caption    = caption;
        raw->tabs.push_back(std::move(td));
    };

    auto addJsonRawNote = [&](int sectionIdx) {
        const auto& s = raw->model->Sections()[sectionIdx];
        std::wstring caption = U8ToW(s.name) + L" [" +
                               std::to_wstring(sectionIdx) + L"]";
        std::string note =
            "// Section \"" + s.name +
            "\" is in raw passthrough mode (no schema match).\n"
            "// Bytes: " + std::to_string(s.rawBytes.size()) + "\n";
        HWND hNote = CreateWindowExW(
            WS_EX_CLIENTEDGE, L"EDIT", L"",
            WS_CHILD | WS_VSCROLL | WS_HSCROLL | ES_MULTILINE
            | ES_READONLY | ES_AUTOVSCROLL | ES_AUTOHSCROLL,
            0, 0, 100, 100, hwnd, nullptr, g_hInstance, nullptr);
        SendMessageW(hNote, WM_SETFONT, (WPARAM)raw->hFontMono, FALSE);
        SetWindowTextW(hNote, U8WithCRLF(note).c_str());
        ShowWindow(hNote, SW_HIDE);
        TabDesc td;
        td.kind       = TabKind::JsonNote;
        td.hContent   = hNote;
        td.sectionIdx = sectionIdx;
        td.caption    = caption;
        td.note       = note;
        raw->tabs.push_back(std::move(td));
    };

    if (loadOk) {
        for (size_t i = 0; i < raw->model->Sections().size(); ++i) {
            const auto& s = raw->model->Sections()[i];
            if (s.mode == tbl::TblSectionMode::Decoded) addGridTab((int)i);
            else                                        addJsonRawNote((int)i);
        }
    }

    // JSON whole-file tab (created lazily — Edit control is empty
    // until the user actually clicks the tab; saves a SetWindowText
    // of potentially MB of text on every Lister open).
    {
        DWORD editStyle = WS_CHILD | WS_VSCROLL | WS_HSCROLL
                        | ES_MULTILINE | ES_AUTOVSCROLL | ES_AUTOHSCROLL
                        | ES_NOHIDESEL | ES_WANTRETURN;
        if (!raw->canSave || !raw->editMode) editStyle |= ES_READONLY;
        raw->hJsonEdit = CreateWindowExW(
            WS_EX_CLIENTEDGE, L"EDIT", L"",
            editStyle, 0, 0, 100, 100,
            hwnd, nullptr, g_hInstance, nullptr);
        SendMessageW(raw->hJsonEdit, WM_SETFONT,
                     (WPARAM)raw->hFontMono, TRUE);
        SendMessageW(raw->hJsonEdit, EM_SETLIMITTEXT, 0x7FFFFFFE, 0);
        ShowWindow(raw->hJsonEdit, SW_HIDE);
        // Initial banner placeholder so the tab isn't empty if user
        // never clicks it but does scroll past.
        if (!loadOk) {
            std::string err = "// Falcom #TBL viewer\n"
                              "// File: " + WToU8(path) + "\n"
                              "// ERROR: " + loadErr + "\n";
            SetWindowTextW(raw->hJsonEdit, U8WithCRLF(err).c_str());
            raw->jsonBuilt = true;
        } else {
            std::string ph =
                "// JSON view will be built when this tab is first activated.\n"
                "// (Avoids the slow SetWindowText for huge files on plugin load.)\n";
            SetWindowTextW(raw->hJsonEdit, U8WithCRLF(ph).c_str());
        }
        // Subclass for nav-key forwarding + dirty tracking.
        SetWindowLongPtrW(raw->hJsonEdit, GWLP_USERDATA, (LONG_PTR)raw);
        raw->origJsonEditProc = (WNDPROC)SetWindowLongPtrW(
            raw->hJsonEdit, GWLP_WNDPROC, (LONG_PTR)JsonEditProc);

        TabDesc td;
        td.kind     = TabKind::JsonWhole;
        td.hContent = raw->hJsonEdit;
        td.caption  = L"JSON";
        raw->tabs.push_back(std::move(td));
    }

    // Config tab — last.
    {
        raw->hConfig = CreateWindowExW(
            0, kConfigClass, L"",
            WS_CHILD,
            0, 0, 100, 100, hwnd, nullptr, g_hInstance, nullptr);
        if (raw->hConfig) {
            BuildConfigControls(raw->hConfig);
            ShowWindow(raw->hConfig, SW_HIDE);
        }
        TabDesc td;
        td.kind     = TabKind::Config;
        td.hContent = raw->hConfig;
        td.caption  = L"Config";
        raw->tabs.push_back(std::move(td));
    }

    // Insert tab strip items.
    for (size_t i = 0; i < raw->tabs.size(); ++i) {
        TCITEMW ti = {};
        ti.mask    = TCIF_TEXT;
        ti.pszText = (LPWSTR)raw->tabs[i].caption.c_str();
        TabCtrl_InsertItem(raw->hTabs, (int)i, &ti);
    }
    TabCtrl_SetCurSel(raw->hTabs, 0);

    // ---- Bottom status strip — three STATIC labels ---------------
    // (Custom layout instead of STATUSCLASSNAMEW so we get reliable
    //  positioning of the EDIT-mode marker with grey filler to the
    //  right of it.)
    HFONT uiFont = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    raw->hLblFile = CreateWindowExW(0, L"STATIC", L"",
        WS_CHILD | WS_VISIBLE | SS_LEFT | SS_NOPREFIX,
        0, 0, kStatusFileWidth, kStatusHeight - 4,
        hwnd, nullptr, g_hInstance, nullptr);
    if (raw->hLblFile) {
        SendMessageW(raw->hLblFile, WM_SETFONT, (WPARAM)uiFont, TRUE);
    }
    raw->hLblSection = CreateWindowExW(0, L"STATIC", L"",
        WS_CHILD | WS_VISIBLE | SS_LEFT | SS_NOPREFIX,
        0, 0, 200, kStatusHeight - 4,
        hwnd, nullptr, g_hInstance, nullptr);
    if (raw->hLblSection) {
        SendMessageW(raw->hLblSection, WM_SETFONT, (WPARAM)uiFont, TRUE);
    }
    raw->hLblMode = CreateWindowExW(0, L"STATIC", L"",
        WS_CHILD | WS_VISIBLE | SS_CENTER | SS_NOPREFIX | SS_NOTIFY,
        0, 0, 240, kStatusHeight - 4,
        hwnd, nullptr, g_hInstance, nullptr);
    if (raw->hLblMode) {
        SendMessageW(raw->hLblMode, WM_SETFONT, (WPARAM)uiFont, TRUE);
    }

    // Show first tab.
    raw->activeTab = -1;        // force SwitchTab to actually act
    SwitchTab(raw, 0);
    LayoutChildren(hwnd, raw);
    ApplyEditModeToUI(raw);

    // Defer window-state apply so TC has finished its plugin-load
    // dance. 100ms is enough.
    SetTimer(hwnd, TIMER_APPLY_WINSTATE, 100, nullptr);

    return hwnd;
}

// ---------------------------------------------------------------------------
// Search (TC's F3/F7 path)
// ---------------------------------------------------------------------------
static int SearchInJsonEdit(PluginInst* p, const std::wstring& needle,
                            int searchFlags) {
    if (!p || !p->hJsonEdit || needle.empty()) return LISTPLUGIN_ERROR;
    bool caseSens  = (searchFlags & lcs_matchcase) != 0;
    bool backwards = (searchFlags & lcs_backwards) != 0;
    bool firstHit  = (searchFlags & lcs_findfirst) != 0;

    DWORD selStart = 0, selEnd = 0;
    SendMessageW(p->hJsonEdit, EM_GETSEL,
                 (WPARAM)&selStart, (LPARAM)&selEnd);
    DWORD cursor = backwards ? selStart : selEnd;
    int len = GetWindowTextLengthW(p->hJsonEdit);
    std::wstring text((size_t)len, 0);
    if (len > 0) GetWindowTextW(p->hJsonEdit, text.data(), len + 1);
    if (firstHit) cursor = backwards ? (DWORD)text.size() : 0;
    if (text.size() < needle.size()) return LISTPLUGIN_ERROR;

    auto eqi = [&](wchar_t a, wchar_t b) {
        if (caseSens) return a == b;
        if (a >= L'A' && a <= L'Z') a = (wchar_t)(a + 32);
        if (b >= L'A' && b <= L'Z') b = (wchar_t)(b + 32);
        return a == b;
    };
    auto match = [&](size_t pos) -> bool {
        if (pos + needle.size() > text.size()) return false;
        for (size_t k = 0; k < needle.size(); ++k) {
            if (!eqi(text[pos + k], needle[k])) return false;
        }
        return true;
    };
    int found = -1;
    if (backwards) {
        if (cursor > text.size()) cursor = (DWORD)text.size();
        for (size_t i = (size_t)cursor; i-- > 0;) {
            if (match(i)) { found = (int)i; break; }
        }
        if (found < 0) {
            for (size_t i = text.size(); i-- > (size_t)cursor;) {
                if (match(i)) { found = (int)i; break; }
            }
        }
    } else {
        for (size_t i = (size_t)cursor; i + needle.size() <= text.size(); ++i) {
            if (match(i)) { found = (int)i; break; }
        }
        if (found < 0) {
            for (size_t i = 0; i + needle.size() <= (size_t)cursor; ++i) {
                if (match(i)) { found = (int)i; break; }
            }
        }
    }
    if (found < 0) {
        MessageBeep(MB_ICONASTERISK);
        return LISTPLUGIN_ERROR;
    }
    SendMessageW(p->hJsonEdit, EM_SETSEL,
                 (WPARAM)found, (LPARAM)(found + (int)needle.size()));
    SendMessageW(p->hJsonEdit, EM_SCROLLCARET, 0, 0);
    return LISTPLUGIN_OK;
}

// Find the active tab's grid; scan its rows × columns linearly.
// Persists row/col cursor across calls in PluginInst-wide state.
struct GridSearchPos { int gridIdx = -1; int row = 0; int col = 0; std::wstring lastNeedle; };
static GridSearchPos g_gridSearchPos;

static int SearchInGrid(PluginInst* p, int gridIdx,
                        const std::wstring& needle, int searchFlags) {
    if (!p || gridIdx < 0 || gridIdx >= (int)p->grids.size()
        || !p->grids[gridIdx]) return LISTPLUGIN_ERROR;
    bool caseSens = (searchFlags & lcs_matchcase) != 0;
    bool firstHit = (searchFlags & lcs_findfirst) != 0;
    int  secIdx = -1;
    for (const auto& td : p->tabs) {
        if (td.kind == TabKind::Grid && td.gridIdx == gridIdx) {
            secIdx = td.sectionIdx; break;
        }
    }
    if (secIdx < 0 || !p->model) return LISTPLUGIN_ERROR;
    const auto& sect = p->model->Sections()[secIdx];
    if (!sect.rows.IsArr()) return LISTPLUGIN_ERROR;
    const auto& rows = sect.rows.AsArr();
    int rowCount = (int)rows.size();
    if (rowCount == 0) return LISTPLUGIN_ERROR;

    bool changed = (needle != g_gridSearchPos.lastNeedle)
                || (g_gridSearchPos.gridIdx != gridIdx);
    if (firstHit || changed) {
        g_gridSearchPos.gridIdx    = gridIdx;
        g_gridSearchPos.row        = 0;
        g_gridSearchPos.col        = 0;
        g_gridSearchPos.lastNeedle = needle;
    }
    std::wstring needleLow = needle;
    if (!caseSens) {
        for (auto& c : needleLow) {
            if (c >= L'A' && c <= L'Z') c = (wchar_t)(c + 32);
        }
    }
    HWND hList = p->grids[gridIdx]->Hwnd();
    int colCount = Header_GetItemCount(ListView_GetHeader(hList));
    int row = g_gridSearchPos.row;
    int col = g_gridSearchPos.col;
    while (row < rowCount) {
        while (col < colCount) {
            // Pull cell text via ListView_GetItemText (triggers our
            // GETDISPINFO callback for the formatted value).
            wchar_t buf[512] = {};
            ListView_GetItemText(hList, row, col, buf, 512);
            std::wstring hay = buf;
            if (!caseSens) {
                for (auto& c : hay) {
                    if (c >= L'A' && c <= L'Z') c = (wchar_t)(c + 32);
                }
            }
            if (hay.find(needleLow) != std::wstring::npos) {
                ListView_SetItemState(hList, -1, 0,
                                      LVIS_SELECTED | LVIS_FOCUSED);
                ListView_SetItemState(hList, row,
                                      LVIS_SELECTED | LVIS_FOCUSED,
                                      LVIS_SELECTED | LVIS_FOCUSED);
                ListView_EnsureVisible(hList, row, FALSE);
                InvalidateRect(hList, nullptr, TRUE);
                SetFocus(hList);
                g_gridSearchPos.row = row;
                g_gridSearchPos.col = col + 1;
                if (g_gridSearchPos.col >= colCount) {
                    g_gridSearchPos.col = 0;
                    g_gridSearchPos.row = row + 1;
                }
                return LISTPLUGIN_OK;
            }
            ++col;
        }
        col = 0;
        ++row;
    }
    g_gridSearchPos.row = 0;
    g_gridSearchPos.col = 0;
    MessageBeep(MB_ICONASTERISK);
    return LISTPLUGIN_ERROR;
}

static int DoSearch(PluginInst* p, const std::wstring& needle, int flags) {
    if (!p || p->activeTab < 0 || p->activeTab >= (int)p->tabs.size()) {
        return LISTPLUGIN_ERROR;
    }
    const TabDesc& td = p->tabs[p->activeTab];
    if (td.kind == TabKind::JsonWhole || td.kind == TabKind::JsonNote) {
        // For Note tabs use that specific EDIT; for Whole use hJsonEdit.
        // Both share the same SearchInJsonEdit code path keyed off hJsonEdit;
        // for Note tabs we'd need to factor it. Simple approach: only
        // search on JsonWhole.
        if (td.kind == TabKind::JsonWhole) {
            return SearchInJsonEdit(p, needle, flags);
        }
        return LISTPLUGIN_ERROR;
    }
    if (td.kind == TabKind::Grid) {
        return SearchInGrid(p, td.gridIdx, needle, flags);
    }
    return LISTPLUGIN_ERROR;
}

// ---------------------------------------------------------------------------
// Plugin exports
// ---------------------------------------------------------------------------
extern "C" {

__declspec(dllexport)
void __stdcall ListGetDetectString(char* DetectString, int maxlen) {
    if (!DetectString || maxlen <= 0) return;
    static const char* k =
        "EXT=\"TBL\" | "
        "([0]=35 & [1]=84 & [2]=66 & [3]=76) | "
        "([0]=249 & [1]=186) | "
        "([0]=217 & [1]=186) | "
        "([0]=201 & [1]=186)";
    size_t n = std::strlen(k);
    if ((int)n >= maxlen) n = (size_t)maxlen - 1;
    std::memcpy(DetectString, k, n);
    DetectString[n] = 0;
}

__declspec(dllexport)
HWND __stdcall ListLoad(HWND ParentWin, char* FileToLoad, int /*ShowFlags*/) {
    return DoLoad(ParentWin, AnsiToW(FileToLoad));
}

__declspec(dllexport)
HWND __stdcall ListLoadW(HWND ParentWin, wchar_t* FileToLoad, int /*ShowFlags*/) {
    return DoLoad(ParentWin, FileToLoad ? FileToLoad : L"");
}

__declspec(dllexport)
void __stdcall ListCloseWindow(HWND ListWin) {
    if (!ListWin) return;
    PluginInst* p = (PluginInst*)GetWindowLongPtrW(ListWin, GWLP_USERDATA);
    if (p) {
        // Save-on-close prompt when there are unsaved changes. Lister
        // doesn't give us a way to *cancel* the close, so the choice
        // is just save-or-discard.
        bool hasChanges = (p->jsonDirty || p->modelDirty)
                       && p->canSave;
        // If we're sitting on the JSON tab and the edit text differs
        // from the model, count that too.
        if (!hasChanges && p->canSave && p->jsonDirty) hasChanges = true;
        if (hasChanges) {
            int res = MessageBoxW(ListWin,
                L"This file has unsaved changes.\n\n"
                L"Save before closing?",
                L"TBLViewer",
                MB_YESNO | MB_ICONQUESTION | MB_TASKMODAL);
            if (res == IDYES) {
                std::string err;
                if (SaveCurrent(p, &err) != 0) {
                    std::wstring werr = U8ToW(err);
                    MessageBoxW(ListWin, werr.c_str(),
                                L"TBLViewer - save failed",
                                MB_OK | MB_ICONERROR);
                }
            }
        }
        // Persist window state.
        CaptureWindowState(ListWin);
        if (p->hFontMono)  DeleteObject(p->hFontMono);
        if (p->hModeBrush) DeleteObject(p->hModeBrush);
        delete p;
    }
    DestroyWindow(ListWin);
}

__declspec(dllexport)
int __stdcall ListSearchText(HWND ListWin, char* SearchString, int SearchParameter) {
    PluginInst* p = (PluginInst*)GetWindowLongPtrW(ListWin, GWLP_USERDATA);
    return DoSearch(p, AnsiToW(SearchString), SearchParameter);
}

__declspec(dllexport)
int __stdcall ListSearchTextW(HWND ListWin, wchar_t* SearchString, int SearchParameter) {
    PluginInst* p = (PluginInst*)GetWindowLongPtrW(ListWin, GWLP_USERDATA);
    return DoSearch(p, SearchString ? SearchString : L"", SearchParameter);
}

__declspec(dllexport)
int __stdcall ListSendCommand(HWND ListWin, int Command, int /*Parameter*/) {
    PluginInst* p = (PluginInst*)GetWindowLongPtrW(ListWin, GWLP_USERDATA);
    if (!p) return LISTPLUGIN_ERROR;
    switch (Command) {
        case lc_copy:
            // For grid: copy current cell. For Edit: WM_COPY.
            if (p->activeTab >= 0 && p->activeTab < (int)p->tabs.size()) {
                const TabDesc& td = p->tabs[p->activeTab];
                if (td.kind == TabKind::JsonWhole && p->hJsonEdit) {
                    SendMessageW(p->hJsonEdit, WM_COPY, 0, 0);
                    return LISTPLUGIN_OK;
                }
                if (td.kind == TabKind::JsonNote && td.hContent) {
                    SendMessageW(td.hContent, WM_COPY, 0, 0);
                    return LISTPLUGIN_OK;
                }
            }
            return LISTPLUGIN_OK;
        case lc_selectall:
            if (p->activeTab >= 0 && p->activeTab < (int)p->tabs.size()) {
                const TabDesc& td = p->tabs[p->activeTab];
                if (td.kind == TabKind::JsonWhole && p->hJsonEdit) {
                    SendMessageW(p->hJsonEdit, EM_SETSEL, 0, -1);
                    return LISTPLUGIN_OK;
                }
            }
            return LISTPLUGIN_OK;
        case lc_newparams:
            return LISTPLUGIN_OK;
    }
    return LISTPLUGIN_ERROR;
}

__declspec(dllexport)
void __stdcall ListSetDefaultParams(ListDefaultParamStruct* dps) {
    if (!dps || dps->size < (int)sizeof(int) * 4) return;
    if (dps->DefaultIniName[0]) {
        g_iniPath = AnsiToW(dps->DefaultIniName);
    }
    // Fallback when TC doesn't supply a path: write next to the DLL.
    if (g_iniPath.empty()) {
        g_iniPath = DllDir() + L"\\tblviewer.ini";
    }
    g_settings.Load(g_iniPath);
}

} // extern "C"

// ---------------------------------------------------------------------------
// DllMain
// ---------------------------------------------------------------------------
BOOL WINAPI DllMain(HINSTANCE hInst, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_hInstance = hInst;
        DisableThreadLibraryCalls(hInst);
        INITCOMMONCONTROLSEX icc = {};
        icc.dwSize = sizeof(icc);
        icc.dwICC  = ICC_TAB_CLASSES | ICC_LISTVIEW_CLASSES | ICC_BAR_CLASSES;
        InitCommonControlsEx(&icc);
    }
    return TRUE;
}
