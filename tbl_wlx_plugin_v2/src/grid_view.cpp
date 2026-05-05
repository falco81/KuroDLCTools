#include "grid_view.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace tbl {

namespace {

std::wstring U8ToW(const std::string& s) {
    if (s.empty()) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(),
                                nullptr, 0);
    std::wstring w(n, 0);
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(),
                        w.data(), n);
    return w;
}

std::string WToU8(const std::wstring& w) {
    if (w.empty()) return "";
    int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(),
                                nullptr, 0, nullptr, nullptr);
    std::string s(n, 0);
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(),
                        s.data(), n, nullptr, nullptr);
    return s;
}

std::wstring FormatCell(const mj::Json& v, const TblDataType& ft) {
    constexpr size_t kMaxLen = 200;
    auto trunc = [&](std::wstring s) {
        if (s.size() > kMaxLen) {
            s.resize(kMaxLen - 1);
            s.push_back(L'\u2026');
        }
        return s;
    };
    char buf[64];
    switch (ft.kind) {
        case TblBaseKind::Float: {
            double d = v.IsNumber() ? v.AsReal()
                     : v.IsStr()    ? std::strtod(v.AsStr().c_str(), nullptr)
                     : 0.0;
            std::snprintf(buf, sizeof(buf), "%.6g", d);
            return U8ToW(buf);
        }
        case TblBaseKind::Byte:  case TblBaseKind::UByte:
        case TblBaseKind::Short: case TblBaseKind::UShort:
        case TblBaseKind::Int:   case TblBaseKind::UInt:
        case TblBaseKind::Long:  case TblBaseKind::ULong: {
            int64_t iv = v.IsNumber() ? v.AsInt()
                       : v.IsStr()    ? std::strtoll(v.AsStr().c_str(), nullptr, 10)
                       : 0;
            std::snprintf(buf, sizeof(buf), "%lld", (long long)iv);
            return U8ToW(buf);
        }
        case TblBaseKind::TOffset:
            return trunc(U8ToW(v.IsStr() ? v.AsStr() : ""));
        case TblBaseKind::U8Array:
        case TblBaseKind::U16Array:
        case TblBaseKind::U32Array: {
            if (!v.IsArr()) return L"[]";
            const auto& a = v.AsArr();
            std::string s = "[" + std::to_string(a.size()) + ": ";
            const size_t kInline = 8;
            for (size_t i = 0; i < a.size() && i < kInline; ++i) {
                if (i > 0) s += ",";
                if (a[i].IsInt()) s += std::to_string(a[i].AsInt());
                else if (a[i].IsReal()) {
                    char b2[32];
                    std::snprintf(b2, sizeof(b2), "%.6g", a[i].AsReal());
                    s += b2;
                }
            }
            if (a.size() > kInline) s += ",\xE2\x80\xA6";   // UTF-8 ellipsis
            s += "]";
            return trunc(U8ToW(s));
        }
        case TblBaseKind::Nested: {
            std::string s = v.IsArr()
                ? "{nested:" + std::to_string(v.AsArr().size()) + "}"
                : "{}";
            return U8ToW(s);
        }
    }
    return L"?";
}

std::string TypeName(const TblDataType& ft) {
    switch (ft.kind) {
        case TblBaseKind::Byte:    return "byte";
        case TblBaseKind::UByte:   return "ubyte";
        case TblBaseKind::Short:   return "short";
        case TblBaseKind::UShort:  return "ushort";
        case TblBaseKind::Int:     return "int";
        case TblBaseKind::UInt:    return "uint";
        case TblBaseKind::Long:    return "long";
        case TblBaseKind::ULong:   return "ulong";
        case TblBaseKind::Float:   return "float";
        case TblBaseKind::TOffset: return "toffset";
        case TblBaseKind::U8Array:  return "u8array";
        case TblBaseKind::U16Array: return "u16array";
        case TblBaseKind::U32Array: return "u32array";
        case TblBaseKind::Nested:
            return "nested[" + std::to_string(ft.nestedSize) + "]";
    }
    return "?";
}

// Width in pixels per type for the column auto-sizing.
int DefaultColWidth(TblBaseKind k) {
    switch (k) {
        case TblBaseKind::TOffset:  return 220;
        case TblBaseKind::U8Array:
        case TblBaseKind::U16Array:
        case TblBaseKind::U32Array: return 160;
        case TblBaseKind::Nested:   return 130;
        case TblBaseKind::Long:
        case TblBaseKind::ULong:    return 110;
        default:                    return 90;
    }
}

} // namespace

bool GridView::IsKindEditable(TblBaseKind k) {
    switch (k) {
        case TblBaseKind::Byte:  case TblBaseKind::UByte:
        case TblBaseKind::Short: case TblBaseKind::UShort:
        case TblBaseKind::Int:   case TblBaseKind::UInt:
        case TblBaseKind::Long:  case TblBaseKind::ULong:
        case TblBaseKind::Float:
        case TblBaseKind::TOffset:
            return true;
        default:
            return false;
    }
}

GridView::GridView(HWND parent, HINSTANCE hInst,
                   TblSection*       section,
                   const FieldList*  fields,
                   const bool*       editModeFlag,
                   bool*             dirtyFlag,
                   OnCellEdit        onEdit,
                   OnHotkey          onUndo,
                   OnHotkey          onRedo,
                   OnOpenSub         onSub,
                   OnRowAdd          onAdd,
                   OnRowDelete       onDel)
    : hInst_(hInst), section_(section), fields_(fields),
      editModeFlag_(editModeFlag),
      dirtyFlag_(dirtyFlag),
      onEdit_(std::move(onEdit)),
      onUndo_(std::move(onUndo)),
      onRedo_(std::move(onRedo)),
      onSub_(std::move(onSub)),
      onAdd_(std::move(onAdd)),
      onDel_(std::move(onDel)) {
    hList_ = CreateWindowExW(
        WS_EX_CLIENTEDGE,
        WC_LISTVIEWW, L"",
        WS_CHILD | WS_VISIBLE | WS_TABSTOP
        | LVS_REPORT | LVS_OWNERDATA | LVS_SHOWSELALWAYS,
        0, 0, 100, 100,
        parent, nullptr, hInst, nullptr);
    if (!hList_) return;

    ListView_SetExtendedListViewStyle(
        hList_, LVS_EX_FULLROWSELECT | LVS_EX_GRIDLINES
              | LVS_EX_HEADERDRAGDROP | LVS_EX_DOUBLEBUFFER);

    // Stash a backref so the cell-edit subclass can find us.
    SetWindowLongPtrW(hList_, GWLP_USERDATA, (LONG_PTR)this);

    BuildColumns();
    Refresh();
    // Do NOT auto-size here — caller decides via AutoSizeColumns()
    // after construction. Some users prefer fixed default widths.
}

GridView::~GridView() {
    if (hCellEdit_) { DestroyWindow(hCellEdit_); hCellEdit_ = nullptr; }
    if (hList_)     { DestroyWindow(hList_);     hList_     = nullptr; }
}

void GridView::BuildColumns() {
    if (!fields_) return;

    LVCOLUMNW col = {};
    col.mask    = LVCF_TEXT | LVCF_WIDTH | LVCF_FMT;
    col.fmt     = LVCFMT_RIGHT;
    col.pszText = (LPWSTR)L"#";
    col.cx      = 60;
    ListView_InsertColumn(hList_, 0, &col);

    int idx = 1;
    for (const auto& f : fields_->fields) {
        std::wstring header = U8ToW(f.name) + L" : "
                            + U8ToW(TypeName(f.dataType));
        LVCOLUMNW c = {};
        c.mask    = LVCF_TEXT | LVCF_WIDTH;
        c.pszText = (LPWSTR)header.c_str();
        c.cx      = DefaultColWidth(f.dataType.kind);
        ListView_InsertColumn(hList_, idx++, &c);
    }
}

// Re-size every column to fit the widest text it actually contains
// (header + sampled rows). Virtual ListView (LVS_OWNERDATA) doesn't
// support LVSCW_AUTOSIZE so we measure manually with GetTextExtent.
//
// Strategy:
//   - Sample up to kSampleLimit rows (covers most tables fully; for
//     huge tables it's an approximation but more than enough for
//     sane widths).
//   - Per-cell text is measured up to 300 chars — long descriptions
//     legitimately need wide columns, but a freak megastring still
//     gets clamped.
//   - Max column width depends on column type: numeric / index ~250,
//     toffset (free text) up to 1200. This keeps small columns tight
//     while letting prose-heavy ones breathe.
void GridView::AutoSizeColumns() {
    if (!hList_ || !fields_ || !section_) return;
    if (!section_->rows.IsArr()) return;

    HWND hHdr = ListView_GetHeader(hList_);
    int colCount = Header_GetItemCount(hHdr);
    int rowCount = (int)section_->rows.AsArr().size();
    constexpr int kSampleLimit = 1000;
    int sampleCount = rowCount < kSampleLimit ? rowCount : kSampleLimit;

    HDC dc = GetDC(hList_);
    if (!dc) return;
    HFONT hf = (HFONT)SendMessageW(hList_, WM_GETFONT, 0, 0);
    if (!hf) hf = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
    HFONT oldFont = (HFONT)SelectObject(dc, hf);

    auto measure = [&](const wchar_t* s, int len) -> int {
        if (len <= 0) return 0;
        SIZE sz{};
        GetTextExtentPoint32W(dc, s, len, &sz);
        return sz.cx;
    };

    for (int c = 0; c < colCount; ++c) {
        // Header text (extra padding for sort arrow + a little air).
        wchar_t hdrBuf[256] = {};
        HDITEMW hd = {};
        hd.mask = HDI_TEXT;
        hd.pszText = hdrBuf;
        hd.cchTextMax = 256;
        Header_GetItem(hHdr, c, &hd);
        int w = measure(hdrBuf, (int)wcslen(hdrBuf)) + 28;

        // Sample rows.
        for (int row = 0; row < sampleCount; ++row) {
            std::wstring t = CellText(row, c);
            int len = (int)t.size();
            // Per-cell cap at 300 chars (one freak megastring won't
            // blow the column to absurd width, but normal long
            // descriptions still fit).
            if (len > 300) len = 300;
            int cw = measure(t.c_str(), len) + 18;
            if (cw > w) w = cw;
        }

        // Per-type max: prose (toffset / unknown) gets a generous
        // ceiling; numeric columns stay tight.
        int maxW = 250;
        if (c >= 1 && fields_) {
            int fi = c - 1;
            if (fi >= 0 && fi < (int)fields_->fields.size()) {
                auto k = fields_->fields[fi].dataType.kind;
                if (k == TblBaseKind::TOffset) {
                    maxW = 1200;
                } else if (k == TblBaseKind::U8Array
                        || k == TblBaseKind::U16Array
                        || k == TblBaseKind::U32Array
                        || k == TblBaseKind::Nested) {
                    maxW = 600;
                } else if (k == TblBaseKind::Float) {
                    maxW = 200;
                }
            }
        } else if (c == 0) {
            maxW = 80;          // # column, just the row index
        }

        // Min / max bounds.
        if (w < 50)   w = 50;
        if (w > maxW) w = maxW;
        ListView_SetColumnWidth(hList_, c, w);
    }

    SelectObject(dc, oldFont);
    ReleaseDC(hList_, dc);
}

void GridView::Refresh() {
    if (!hList_ || !section_) return;
    if (!section_->rows.IsArr()) return;
    int n = (int)section_->rows.AsArr().size();
    // Re-build permutation if row count changed.
    if ((int)permutation_.size() != n) {
        permutation_.resize(n);
        for (int i = 0; i < n; ++i) permutation_[i] = i;
        sortCol_ = -1;
        sortDescending_ = false;
        UpdateHeaderSortArrow();
    }
    ListView_SetItemCountEx(hList_, n, LVSICF_NOSCROLL);
    InvalidateRect(hList_, nullptr, FALSE);
}

int GridView::ModelRow(int displayRow) const {
    if (displayRow < 0 || displayRow >= (int)permutation_.size()) {
        return displayRow;
    }
    return permutation_[displayRow];
}

void GridView::SortByColumn(int col) {
    if (!fields_ || !section_ || !section_->rows.IsArr()) return;
    int n = (int)section_->rows.AsArr().size();
    if (n == 0) return;

    // First column = "#" (row index). Sorting by it just resets to
    // identity (or descending = reverse).
    bool isIdxCol = (col == 0);
    int  fIdx     = col - 1;
    if (!isIdxCol && (fIdx < 0 || fIdx >= (int)fields_->fields.size())) return;

    // Toggle direction if clicking the same column; otherwise default
    // to ascending.
    if (col == sortCol_) {
        sortDescending_ = !sortDescending_;
    } else {
        sortCol_        = col;
        sortDescending_ = false;
    }

    // Build comparator over model-row indices.
    const auto& rows = section_->rows.AsArr();
    permutation_.resize(n);
    for (int i = 0; i < n; ++i) permutation_[i] = i;

    auto getCellSortable = [&](int row, int sortCol) {
        // Returns (kind, ival, dval, sval) — kind tells caller which to use.
        struct V {
            int          kind = 0;   // 0 unset, 1 int, 2 real, 3 str
            int64_t      iv   = 0;
            double       dv   = 0.0;
            std::string  sv;
        };
        V out;
        if (sortCol == 0) {       // # column
            out.kind = 1; out.iv = row;
            return out;
        }
        if (!rows[row].IsObj()) return out;
        const auto& f = fields_->fields[sortCol - 1];
        const mj::Json* val = rows[row].Find(f.name);
        if (!val) return out;
        switch (f.dataType.kind) {
            case TblBaseKind::Float:
                out.kind = 2;
                out.dv = val->IsNumber() ? val->AsReal()
                       : val->IsStr()    ? std::strtod(val->AsStr().c_str(), nullptr)
                       : 0.0;
                break;
            case TblBaseKind::Byte:  case TblBaseKind::UByte:
            case TblBaseKind::Short: case TblBaseKind::UShort:
            case TblBaseKind::Int:   case TblBaseKind::UInt:
            case TblBaseKind::Long:  case TblBaseKind::ULong:
                out.kind = 1;
                out.iv = val->IsNumber() ? val->AsInt()
                       : val->IsStr()    ? std::strtoll(val->AsStr().c_str(), nullptr, 10)
                       : 0;
                break;
            case TblBaseKind::TOffset:
                out.kind = 3;
                if (val->IsStr()) out.sv = val->AsStr();
                break;
            default:
                // arrays / nested: not directly sortable; use 0
                out.kind = 1; out.iv = row;
                break;
        }
        return out;
    };

    bool desc = sortDescending_;
    std::stable_sort(permutation_.begin(), permutation_.end(),
        [&](int a, int b) {
            auto va = getCellSortable(a, col);
            auto vb = getCellSortable(b, col);
            int cmp = 0;
            if (va.kind != vb.kind) {
                cmp = va.kind - vb.kind;
            } else if (va.kind == 1) {
                cmp = (va.iv < vb.iv) ? -1 : (va.iv > vb.iv) ? 1 : 0;
            } else if (va.kind == 2) {
                cmp = (va.dv < vb.dv) ? -1 : (va.dv > vb.dv) ? 1 : 0;
            } else if (va.kind == 3) {
                cmp = va.sv.compare(vb.sv);
            }
            if (cmp == 0) cmp = (a < b) ? -1 : (a > b) ? 1 : 0;
            return desc ? (cmp > 0) : (cmp < 0);
        });

    UpdateHeaderSortArrow();
    InvalidateRect(hList_, nullptr, FALSE);
}

void GridView::UpdateHeaderSortArrow() {
    HWND hHdr = ListView_GetHeader(hList_);
    if (!hHdr) return;
    int colCount = Header_GetItemCount(hHdr);
    for (int i = 0; i < colCount; ++i) {
        HDITEMW hd = {};
        hd.mask = HDI_FORMAT;
        Header_GetItem(hHdr, i, &hd);
        hd.fmt &= ~(HDF_SORTDOWN | HDF_SORTUP);
        if (i == sortCol_) {
            hd.fmt |= sortDescending_ ? HDF_SORTDOWN : HDF_SORTUP;
        }
        Header_SetItem(hHdr, i, &hd);
    }
}

void GridView::RebuildPermutation() {
    if (!section_ || !section_->rows.IsArr()) {
        permutation_.clear();
        return;
    }
    int n = (int)section_->rows.AsArr().size();
    if ((int)permutation_.size() != n) {
        permutation_.resize(n);
        for (int i = 0; i < n; ++i) permutation_[i] = i;
        sortCol_ = -1;
        sortDescending_ = false;
        UpdateHeaderSortArrow();
    }
}

void GridView::Resize(int x, int y, int w, int h) {
    if (hList_) {
        SetWindowPos(hList_, nullptr, x, y, w, h,
                     SWP_NOZORDER | SWP_NOACTIVATE);
    }
}

std::wstring GridView::CellText(int displayRow, int col) const {
    if (!section_ || !fields_) return L"";
    if (!section_->rows.IsArr()) return L"";
    const auto& rows = section_->rows.AsArr();
    int row = (displayRow >= 0 && displayRow < (int)permutation_.size())
              ? permutation_[displayRow] : displayRow;
    if (row < 0 || row >= (int)rows.size()) return L"";

    if (col == 0) {
        char buf[16];
        std::snprintf(buf, sizeof(buf), "%d", row);
        return U8ToW(buf);
    }
    int fIdx = col - 1;
    if (fIdx < 0 || fIdx >= (int)fields_->fields.size()) return L"";
    const auto& f    = fields_->fields[fIdx];
    const auto& rowJ = rows[row];
    if (!rowJ.IsObj()) return L"<bad>";
    const mj::Json* val = rowJ.Find(f.name);
    if (!val) return L"";
    return FormatCell(*val, f.dataType);
}

// ---------------------------------------------------------------------------
// Inline cell editor
// ---------------------------------------------------------------------------
bool GridView::BeginEdit(int displayRow, int col) {
    if (!hList_ || !section_ || !fields_) return false;
    if (col == 0) return false;                  // # column
    int fIdx = col - 1;
    if (fIdx < 0 || fIdx >= (int)fields_->fields.size()) return false;
    const auto& f = fields_->fields[fIdx];
    int modelRow = ModelRow(displayRow);

    // Array / nested cells: open sub-grid popup instead of inline
    // editor. Works in both RO and edit mode — viewing the nested
    // rows is always allowed; the sub-grid itself honours the parent
    // edit-mode flag for any actual cell edits inside it.
    if (f.dataType.kind == TblBaseKind::Nested
     || f.dataType.kind == TblBaseKind::U8Array
     || f.dataType.kind == TblBaseKind::U16Array
     || f.dataType.kind == TblBaseKind::U32Array) {
        if (onSub_) onSub_(modelRow, f.name);
        return false;
    }

    // Runtime read-only check — F4 toggles this. Inline editor only.
    if (editModeFlag_ && !*editModeFlag_) {
        MessageBeep(MB_ICONASTERISK);
        return false;
    }
    if (!IsKindEditable(f.dataType.kind)) {
        MessageBeep(MB_ICONASTERISK);
        return false;
    }
    if (modelRow < 0 || !section_->rows.IsArr()
        || modelRow >= (int)section_->rows.AsArr().size()) return false;

    // End any in-flight edit (commit it).
    if (hCellEdit_) EndEdit(true);

    // Position EDIT inside the cell rect.
    RECT rc;
    if (col == 0) {
        ListView_GetItemRect(hList_, displayRow, &rc, LVIR_LABEL);
    } else {
        ListView_GetSubItemRect(hList_, displayRow, col, LVIR_LABEL, &rc);
    }

    editRow_ = modelRow;        // store the MODEL row, not display
    editCol_ = col;

    DWORD style = WS_CHILD | WS_VISIBLE | WS_BORDER
                | ES_AUTOHSCROLL | ES_LEFT;
    hCellEdit_ = CreateWindowExW(
        0, L"EDIT", L"", style,
        rc.left, rc.top,
        rc.right - rc.left, rc.bottom - rc.top,
        hList_, nullptr, hInst_, nullptr);
    if (!hCellEdit_) {
        editRow_ = editCol_ = -1;
        return false;
    }

    HFONT hf = (HFONT)SendMessageW(hList_, WM_GETFONT, 0, 0);
    if (hf) SendMessageW(hCellEdit_, WM_SETFONT, (WPARAM)hf, FALSE);

    const auto& rowJ = section_->rows.AsArr()[modelRow];
    const mj::Json* val = rowJ.IsObj() ? rowJ.Find(f.name) : nullptr;
    std::wstring init;
    if (val) {
        if (val->IsStr()) init = U8ToW(val->AsStr());
        else if (val->IsInt())  init = std::to_wstring(val->AsInt());
        else if (val->IsReal()) {
            // Show the SHORTEST decimal representation that
            // round-trips through float32 (TBL stores 32-bit floats).
            // This keeps "4.1f" displayed as "4.1" instead of
            // "4.099999904632568" while preserving full precision
            // when the user actually needs more digits.
            double dv = val->AsReal();
            float  f32 = (float)dv;
            char b[64];
            int chosen = 17;
            for (int prec = 1; prec <= 9; ++prec) {
                std::snprintf(b, sizeof(b), "%.*g", prec, dv);
                char* end = nullptr;
                float back = (float)std::strtod(b, &end);
                if (back == f32) { chosen = prec; break; }
            }
            if (chosen > 9) {
                std::snprintf(b, sizeof(b), "%.17g", dv);
            } else {
                std::snprintf(b, sizeof(b), "%.*g", chosen, dv);
            }
            init = U8ToW(b);
        }
    }
    SetWindowTextW(hCellEdit_, init.c_str());
    SendMessageW(hCellEdit_, EM_SETSEL, 0, -1);

    SetWindowLongPtrW(hCellEdit_, GWLP_USERDATA, (LONG_PTR)this);
    origCellEditProc_ = (WNDPROC)SetWindowLongPtrW(
        hCellEdit_, GWLP_WNDPROC, (LONG_PTR)CellEditProc);

    SetFocus(hCellEdit_);
    return true;
}

void GridView::EndEdit(bool commit) {
    if (!hCellEdit_) return;

    if (commit && editRow_ >= 0 && editCol_ > 0) {
        int fIdx = editCol_ - 1;
        if (fIdx < (int)fields_->fields.size()) {
            const auto& f = fields_->fields[fIdx];

            int len = GetWindowTextLengthW(hCellEdit_);
            std::wstring wbuf((size_t)len, 0);
            if (len > 0) GetWindowTextW(hCellEdit_, wbuf.data(), len + 1);
            std::string text = WToU8(wbuf);

            if (section_->rows.IsArr()
             && editRow_ < (int)section_->rows.AsArr().size()) {
                mj::Json& rowJ = section_->rows.AsArr()[editRow_];
                if (rowJ.IsObj()) {
                    bool valid = true;
                    mj::Json newVal;
                    switch (f.dataType.kind) {
                        case TblBaseKind::Float: {
                            char* endp = nullptr;
                            double d = std::strtod(text.c_str(), &endp);
                            if (text.empty() || endp == text.c_str()) {
                                valid = false;
                            } else {
                                newVal = mj::Json::MakeReal(d);
                            }
                            break;
                        }
                        case TblBaseKind::Byte:  case TblBaseKind::UByte:
                        case TblBaseKind::Short: case TblBaseKind::UShort:
                        case TblBaseKind::Int:   case TblBaseKind::UInt:
                        case TblBaseKind::Long:  case TblBaseKind::ULong: {
                            char* endp = nullptr;
                            long long v = std::strtoll(text.c_str(), &endp, 10);
                            if (text.empty() || endp == text.c_str()) {
                                valid = false;
                            } else {
                                newVal = mj::Json::MakeInt((int64_t)v);
                            }
                            break;
                        }
                        case TblBaseKind::TOffset:
                            newVal = mj::Json::MakeStr(text);
                            break;
                        default:
                            valid = false;
                            break;
                    }
                    if (valid) {
                        // Capture old value for undo before mutating.
                        mj::Json oldCopy;
                        if (const mj::Json* old = rowJ.Find(f.name)) {
                            oldCopy = *old;
                        }
                        rowJ.At(f.name) = newVal;        // copy, keep newVal
                        if (dirtyFlag_) *dirtyFlag_ = true;
                        if (onEdit_) {
                            onEdit_(editRow_, f.name,
                                    std::move(oldCopy), std::move(newVal));
                        }
                        // Find the display row that maps to editRow_
                        // (which is the model row) and repaint it.
                        int displayRow = editRow_;
                        for (size_t k = 0; k < permutation_.size(); ++k) {
                            if (permutation_[k] == editRow_) {
                                displayRow = (int)k;
                                break;
                            }
                        }
                        ListView_RedrawItems(hList_, displayRow, displayRow);
                    } else {
                        MessageBeep(MB_ICONHAND);
                    }
                }
            }
        }
    }

    // Restore + destroy the EDIT.
    if (origCellEditProc_) {
        SetWindowLongPtrW(hCellEdit_, GWLP_WNDPROC,
                          (LONG_PTR)origCellEditProc_);
    }
    HWND h = hCellEdit_;
    hCellEdit_       = nullptr;
    origCellEditProc_ = nullptr;
    editRow_ = editCol_ = -1;
    DestroyWindow(h);
    SetFocus(hList_);
}

LRESULT CALLBACK GridView::CellEditProc(HWND hwnd, UINT msg,
                                        WPARAM wp, LPARAM lp) {
    GridView* self = (GridView*)GetWindowLongPtrW(hwnd, GWLP_USERDATA);
    WNDPROC orig = self ? self->origCellEditProc_ : nullptr;

    if (msg == WM_GETDLGCODE) {
        // Tell ListView we want all keys (Enter, Esc, Tab).
        return DLGC_WANTALLKEYS | DLGC_WANTCHARS | DLGC_WANTARROWS;
    }
    if (msg == WM_KEYDOWN && self) {
        switch (wp) {
            case VK_RETURN: self->EndEdit(true);  return 0;
            case VK_ESCAPE: self->EndEdit(false); return 0;
        }
    }
    if (msg == WM_KILLFOCUS && self) {
        // Match the Pascal upstream: focus loss CANCELS rather than
        // commits. Silent commit on click-elsewhere is confusing.
        self->EndEdit(false);
        return 0;
    }
    if (orig) return CallWindowProcW(orig, hwnd, msg, wp, lp);
    return DefWindowProcW(hwnd, msg, wp, lp);
}

bool GridView::HandleNotify(NMHDR* hdr, LRESULT* outResult) {
    if (!hdr || hdr->hwndFrom != hList_) return false;

    switch (hdr->code) {
        case LVN_GETDISPINFOW: {
            NMLVDISPINFOW* di = (NMLVDISPINFOW*)hdr;
            LVITEMW& it = di->item;
            if (it.mask & LVIF_TEXT) {
                cellScratch_ = CellText(it.iItem, it.iSubItem);
                it.pszText = (LPWSTR)cellScratch_.c_str();
            }
            if (outResult) *outResult = 0;
            return true;
        }
        case NM_DBLCLK: {
            NMITEMACTIVATE* ia = (NMITEMACTIVATE*)hdr;
            if (ia->iItem >= 0 && ia->iSubItem > 0) {
                BeginEdit(ia->iItem, ia->iSubItem);
            }
            if (outResult) *outResult = 0;
            return true;
        }
        case LVN_KEYDOWN: {
            NMLVKEYDOWN* kd = (NMLVKEYDOWN*)hdr;
            bool ctrl = (GetKeyState(VK_CONTROL) & 0x8000) != 0;
            // F2: start edit on focused row, first field column.
            if (kd->wVKey == VK_F2) {
                int row = ListView_GetNextItem(hList_, -1, LVNI_FOCUSED);
                if (row < 0) row = ListView_GetNextItem(hList_, -1, LVNI_SELECTED);
                if (row >= 0) BeginEdit(row, 1);
                if (outResult) *outResult = 0;
                return true;
            }
            // Insert: append a new row (only in edit mode).
            if (kd->wVKey == VK_INSERT && !ctrl) {
                if (editModeFlag_ && !*editModeFlag_) {
                    MessageBeep(MB_ICONASTERISK);
                } else if (onAdd_) {
                    onAdd_();
                }
                if (outResult) *outResult = 0;
                return true;
            }
            // Delete: drop the focused row (only in edit mode).
            // ListView's default Delete handler does nothing for
            // virtual lists, so we get the keystroke unmodified here.
            if (kd->wVKey == VK_DELETE && !ctrl) {
                if (editModeFlag_ && !*editModeFlag_) {
                    MessageBeep(MB_ICONASTERISK);
                } else if (onDel_) {
                    int displayRow = ListView_GetNextItem(hList_, -1, LVNI_FOCUSED);
                    if (displayRow < 0) {
                        displayRow = ListView_GetNextItem(hList_, -1, LVNI_SELECTED);
                    }
                    if (displayRow >= 0) {
                        int modelRow = ModelRow(displayRow);
                        onDel_(modelRow);
                    }
                }
                if (outResult) *outResult = 0;
                return true;
            }
            // Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z: undo / redo.
            if (ctrl && kd->wVKey == 'Z'
                && !(GetKeyState(VK_SHIFT) & 0x8000)) {
                if (onUndo_) onUndo_();
                if (outResult) *outResult = 0;
                return true;
            }
            if (ctrl && (kd->wVKey == 'Y'
                         || (kd->wVKey == 'Z'
                             && (GetKeyState(VK_SHIFT) & 0x8000)))) {
                if (onRedo_) onRedo_();
                if (outResult) *outResult = 0;
                return true;
            }
            // Esc / F3 / F7 / Ctrl+F / F4 / Ctrl+S: forward to host
            // window so it can route to TC's Lister parent or toggle
            // edit mode.
            if (kd->wVKey == VK_ESCAPE
             || kd->wVKey == VK_F3
             || kd->wVKey == VK_F4
             || kd->wVKey == VK_F7
             || (ctrl && (kd->wVKey == 'F' || kd->wVKey == 'S'))) {
                HWND host = GetParent(hList_);
                if (host) {
                    PostMessageW(host, WM_KEYDOWN, kd->wVKey, 0);
                }
                if (outResult) *outResult = 0;
                return true;
            }
            break;
        }
        case LVN_COLUMNCLICK: {
            NMLISTVIEW* lv = (NMLISTVIEW*)hdr;
            SortByColumn(lv->iSubItem);
            if (outResult) *outResult = 0;
            return true;
        }
    }
    return false;
}

} // namespace tbl
