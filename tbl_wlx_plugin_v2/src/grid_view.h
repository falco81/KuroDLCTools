// Read-only-ish grid view for one decoded TBL section. Wraps a Win32
// ListView in virtual / report mode (LVS_OWNERDATA + LVS_REPORT) so
// scrolling, scrollbars, column resizing, keyboard nav, multi-select
// and the header bar are all "free" — we just have to provide cell
// text via LVN_GETDISPINFO.
//
// **Cell editing:** F2 (or double-click) on a primitive cell pops a
// borderless EDIT control overlay sized to the cell. Enter commits,
// Esc cancels, focus loss commits. Editable kinds: int / uint / etc.,
// float, toffset (string). u*array and nested cells are read-only in
// the grid (use the JSON tab for those).
//
// When a commit happens the GridView writes the new value back into
// the section's row JSON and flips `*dirtyFlag` (passed at ctor) so
// the parent knows to re-sync the JSON tab on switch.
#pragma once

#include <windows.h>
#include <commctrl.h>

#include "tbl_file.h"
#include "tbl_types.h"

#include <functional>
#include <string>
#include <vector>

namespace tbl {

class GridView {
public:
    // Callback fired when the user successfully commits a cell edit.
    // Caller can use it to record an undo entry or refresh UI.
    using OnCellEdit = std::function<void(int modelRow,
                                          const std::string& fieldName,
                                          mj::Json oldVal,
                                          mj::Json newVal)>;
    // Fired when user pressed Ctrl+Z / Ctrl+Y inside the grid.
    using OnHotkey   = std::function<void()>;
    // Fired on double-click of a cell whose type doesn't fit an
    // inline editor (arrays, nested records). Caller opens a sub-grid
    // popup window for editing.
    using OnOpenSub  = std::function<void(int modelRow,
                                          const std::string& fieldName)>;
    // Fired when user pressed Insert / Ctrl+Delete in the grid to
    // add/remove a top-level row. Caller decides default values
    // (using the schema) and tracks the change.
    using OnRowAdd    = std::function<void()>;
    using OnRowDelete = std::function<void(int modelRow)>;

    // `section` is mutated when the user edits cells. `fields` is
    // const — schema doesn't change at runtime.
    // `editModeFlag` is checked at every BeginEdit; grid blocks the
    // cell editor when *editModeFlag is false (RO mode).
    // `dirtyFlag` is set to true on any successful cell edit.
    GridView(HWND parent, HINSTANCE hInst,
             TblSection*       section,
             const FieldList*  fields,
             const bool*       editModeFlag,
             bool*             dirtyFlag,
             OnCellEdit        onEdit  = {},
             OnHotkey          onUndo  = {},
             OnHotkey          onRedo  = {},
             OnOpenSub         onSub   = {},
             OnRowAdd          onAdd   = {},
             OnRowDelete       onDel   = {});
    ~GridView();

    HWND Hwnd() const { return hList_; }

    // Call after the underlying section's rows change externally
    // (e.g. JSON edit got synced into the model).
    void Refresh();

    // Forward a notification (received by parent's WM_NOTIFY) to us.
    // Returns true if we handled it.
    bool HandleNotify(NMHDR* hdr, LRESULT* outResult);

    void Resize(int x, int y, int w, int h);

    // The EDIT subclass needs to reach into us.
    static LRESULT CALLBACK CellEditProc(HWND hwnd, UINT msg,
                                         WPARAM wp, LPARAM lp);

private:
    HWND               hList_       = nullptr;
    HINSTANCE          hInst_       = nullptr;
    TblSection*        section_     = nullptr;     // mutable
    const FieldList*   fields_      = nullptr;
    const bool*        editModeFlag_ = nullptr;    // checked at edit time
    bool*              dirtyFlag_   = nullptr;
    OnCellEdit         onEdit_;
    OnHotkey           onUndo_;
    OnHotkey           onRedo_;
    OnOpenSub          onSub_;
    OnRowAdd           onAdd_;
    OnRowDelete        onDel_;

    // Per-call scratch buffer for GETDISPINFO.
    std::wstring       cellScratch_;

    // Inline cell editor state.
    HWND               hCellEdit_   = nullptr;
    int                editRow_     = -1;
    int                editCol_     = -1;       // listview sub-item column
    WNDPROC            origCellEditProc_ = nullptr;

    // Sort state. permutation_[displayRow] = modelRow. Identity means
    // "no sort" (display order == model order).
    std::vector<int>   permutation_;
    int                sortCol_       = -1;     // -1 = unsorted
    bool               sortDescending_ = false;

    void BuildColumns();
    void AutoSizeColumns();          // measure widest text per column
    std::wstring CellText(int displayRow, int col) const;
    int  ModelRow(int displayRow) const;        // honors permutation
    void SortByColumn(int col);
    void RebuildPermutation();
    void UpdateHeaderSortArrow();

    // Cell editing.
    bool BeginEdit(int displayRow, int col);
    void EndEdit(bool commit);
    static bool IsKindEditable(TblBaseKind k);
};

} // namespace tbl
