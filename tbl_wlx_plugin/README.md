# TBL Lister Plugin v1.3.37 for Total Commander

Read, browse, and edit Falcom `#TBL` data tables (Trails of Cold
Steel, Trails through Daybreak, Trails in the Sky 1, Ys X, Kai)
directly from inside Total Commander.

## Install

### Easy method (recommended)

1. **In Total Commander**, navigate to this ZIP file (don't unzip it
   yet) and press **Enter** on it (or double-click).
2. TC reads `pluginst.inf` and shows: *"This archive contains a
   Lister plugin. Install?"* — click **Yes**.
3. Confirm the install path (default: `<TC>\Plugins\wlx\tbl_wlx\`).
4. Done. Press **F3** on any `.tbl` file to open the viewer.

### Manual method

1. Unzip everything into a folder of your choice (e.g.
   `C:\Tools\TC\Plugins\wlx\tbl_wlx\`).
2. In Total Commander: **Configuration → Options → Plugins → Lister
   (WLX) → Configure → Add**, navigate to that folder, select
   `tbl_wlx.wlx64`, and click Open.
3. The detection rule auto-populates with the bundled detect string.

## Use

### Opening a file

- **F3** in Total Commander on any `.tbl` file → opens the plugin in
  **read-only mode** (default). Press **F4 inside the plugin** to
  flip into edit mode.
- **Ctrl+Q** (Quick View Panel) → also read-only.
- **Esc** → close the viewer.

The plugin remembers the last window position/size and restores it
on the next open. To always start maximized, set `MaximizeOnOpen=1`
in `tbl_wlx.ini` (see Settings below).

> Tip: Total Commander has its own *Options → Save position* in the
> Lister menu. The plugin's window-state memory is independent of
> that — both work; pick whichever you prefer.

### Skip the F4 step: `DefaultEditMode=1` in INI

If you always want F3 to open in edit mode (you mostly use the
plugin to edit, not to read), add this to `tbl_wlx.ini`:

```ini
[TBL_WLX]
DefaultEditMode=1
```

The INI file lives next to your `wincmd.ini` (typically in
`%APPDATA%\GHISLER\`).

### Tabbed view

- One tab per TBL section (showing rows in a spreadsheet-style grid)
- One **JSON** tab for raw text editing
- One **Config** tab at the very end with a GUI for the INI settings
- Click section tabs at the top, or use Ctrl+Tab to cycle

### Grid editing (only in edit mode)

- **Double-click a cell** to edit
- **Enter** commits, **Escape** cancels
- Click outside the cell: cancels
- Arrays render as `[a, b, c]` — read-only in the grid; use the JSON
  tab to edit them
- Nested struct fields show as `[N rows]` — **double-click** to open
  a sub-grid where you can edit each nested entry

### JSON tab (only in edit mode)

- Edit JSON freely. Header `//` lines are decorative — they're
  stripped on save.
- **Ctrl+S** saves changes back to the file.

### Search (F3 / F7)

Press **F3** (or **F7** on numeric keypad) inside the plugin window
to bring up TC's standard Find dialog. The plugin searches:

- The active grid tab's cells, scanning left-to-right, top-to-bottom
- If no hit on the active tab, it wraps through subsequent tabs
- The JSON tab is included in the wrap-around as a fallback
- Hit found → row gets selected, scrolled into view, and the tab
  switches automatically if the match was on a different tab
- Press F3 again to find next; the cursor advances one cell each time

The search is plain substring, case-insensitive by default (toggle
with TC's *Match case* checkbox).

### Other shortcuts

| Key            | Action                                            |
|----------------|---------------------------------------------------|
| **F3 / F7**    | Search text in grids and JSON tab                 |
| **F4**         | Toggle edit / read-only mode (beeps for feedback) |
| **F2**         | Reload the file from disk (asks first if dirty)   |
| **Ctrl+S**     | Save (only in edit mode + JSON tab)               |
| **Esc**        | Close the viewer                                  |

## Settings (`tbl_wlx.ini`)

```ini
[TBL_WLX]
PreferredGame=Kuro2          ; or '', Kuro1, Sora1, Ys_X, Kai
DefaultEditMode=0            ; 0 = read-only on F3 (default);
                             ; 1 = edit mode on F3 (skip F4)
RememberWindowSize=1         ; 1 = restore last pos+size on open
MaximizeOnOpen=0             ; 1 = always maximize on open

; Auto-updated by the plugin on close — don't normally edit:
LastWinX=…
LastWinY=…
LastWinW=…
LastWinH=…
LastWinMax=…
```

`PreferredGame`: when multiple game variants share the same entry
length for a header, the preferred game wins. Empty = first match.

`DefaultEditMode`: see "Skip the F4 step" above.

`RememberWindowSize` (default 1): plugin saves Lister window pos/size
to `LastWin*` on close, restores it on next open.

`MaximizeOnOpen` (default 0): plugin always opens the Lister
maximized, overriding the saved size. Useful for primary-display
work where you always want full screen.

## File detection

The plugin only opens files that match one of these:

- File extension is `.tbl`
- First 4 bytes are exactly `#TBL` (plain TBL)
- First 2 bytes are `F9 BA` (CLE encrypted)
- First 2 bytes are `D9 BA` (CLE encrypted + compressed)

## Round-trip guarantees

For files where ALL sections decode against a known schema, open + save
is bit-identical for 99.3% of files in our 411-file test corpus
(Kuro 1 `script_eng.p3a`); the rest match KuroTools Python
`json2tbl` byte-for-byte.

For files with at least one unknown section (raw mode), open + save
is verbatim passthrough (lossless).

## Limitations

- **No CLE re-wrap on save**: if the original was F9BA/D9BA encrypted,
  the saved file is plain `#TBL`. Games tested so far accept this.
- **Array fields** (u8/u16/u32 arrays) are read-only in the grid —
  edit those via the JSON tab.

## Files

```
tbl_wlx.wlx64         the plugin (PE32+ x86-64 DLL with .wlx64 extension, ~735 KB)
pluginst.inf          TC plugin installer manifest
schemas/              KuroTools header schemas (must sit next to the plugin)
  headers/            282 *.json header field schemas
  t_*.json            81 top-level table-header lists
README.md             this file
CHANGELOG.md          version history
TROUBLESHOOTING.md    common issues
```

## Source code

Full sources for this plugin are in `tbl_wlx_v1.3.37_source.zip`. The
build instructions cover Windows (Lazarus, manual fpc), Debian/Ubuntu,
AlmaLinux/RHEL, Fedora, Arch, and macOS.

## Bugs and feedback

Report issues with:
- Total Commander version
- Plugin version (1.3.37)
- The misbehaving `.tbl` file (or its first 256 bytes)
- A copy of your `tbl_wlx.ini`
