# TBLViewer — Falcom #TBL Lister plugin (C++ port)

A Total Commander Lister (`.wlx` / `.wlx64`) plugin that decodes,
displays, and **edits** Falcom's `#TBL` data tables — the binary format
used across *Trails of Cold Steel*, *Trails through Daybreak*, *Trails in
the Sky*, and *Ys X*. Files that ship encrypted (`F9BA` / `C9BA`) or
zstd-compressed (`D9BA`) are unwrapped automatically.

This is a clean-room C++17 rewrite of the original Free Pascal
[TBL Lister Plugin](https://github.com/) (v1.3.43). The on-disk
format, the schema database, and the `KuroTools` JSON shape are all
preserved bit-for-bit so output round-trips with the upstream tools
where the original did.

## What this version does

When you press **F3** on a `.tbl` file in TC, you get a tabbed view:

- **JSON** tab — pretty-printed JSON of the whole file. Edit values
  here, hit Ctrl+S to save back. The banner up top shows section
  metadata (schema variant matched, byte length, decoded vs raw).
- **One tab per decoded section** — a typed grid with one row per
  record and one column per schema field. Column headers show
  `name : type` (e.g. `id : uint`, `desc : toffset`,
  `unk_arr : u32array`). **Double-click or F2** on a primitive cell
  to edit it; Enter commits, Esc cancels, focus loss commits. Editable
  kinds: int / uint / short / long / float / toffset (string).
  Arrays and nested records stay read-only in the grid — edit those
  in the JSON tab.

The two views stay in sync:

- Type in the JSON tab → switch to a grid tab → JSON gets re-parsed
  into the model and the grid refreshes. If the JSON has a syntax
  error, a dialog appears and you stay on the JSON tab to fix it.
- Edit a cell in a grid tab → switch to the JSON tab → the JSON text
  is re-rendered from the model so you see the change reflected.

```
[ JSON ] [ ItemTableData ] [ NpcTableData ] [ ... ]
+------------------------------------------+
|  #  | id : uint | name : toffset | ...  |
|-----+-----------+-----------------+------|
|  0  | 100       | "Healing Salve" | ...  |
|  1  | 101       | "Tactics Manual"| ...  |
+------------------------------------------+
```

Inside any tab:

- **Ctrl+S** — save edits back to the file. Re-packs the binary using
  the matched schema variant; the result is written as a plain `#TBL`
  (no CLE wrapper, even if the input was encrypted).
- **F7 / F3** — Lister's standard search (in the JSON tab; grid uses
  ListView's built-in incremental keyboard search by row label).
- **Ctrl+A** / **Ctrl+C** — select all / copy in the JSON tab.
- **Ctrl+Z / Ctrl+Y** — undo / redo grid cell edits (200-entry
  per-file history). The JSON tab uses the EDIT control's own undo
  buffer independently.
- Click a column header to sort by that column (toggle ascending /
  descending). The header shows a small arrow indicating direction.
  Sort doesn't auto-apply after edits — re-click the header to refresh.
- Sections without a known schema only show up in the JSON tab as raw
  hex under `"raw": "..."` — they don't get a grid tab. Files
  containing any raw section are opened **read-only** to avoid
  corrupting them.

A status bar at the bottom shows: filename (with a `●` marker when
unsaved), the current section's name + row count + entry length +
matched game variant, and `editable` / `read-only` mode.

## INI options (optional)

The plugin honours these keys in the TC plugin INI (TC creates this
file the first time the plugin is installed; path is shown in TC's
Options → Plugins → Lister):

```
[TBLViewer]
PreferredGame=Kuro2     ; tie-break for headers with multiple variants
                        ; matching the same entry length
                        ; values: Kuro1, Kuro2, Sora1, Ys_X, ...
FontSize=14             ; editor point size
ConfirmSave=1           ; (reserved)
```

All keys are optional; defaults match the values shown above.

## What's deferred to a later release

- **Array / nested cell editing in grid** — only primitive cells (int,
  float, toffset) take a cell editor; for arrays and nested records
  switch to the JSON tab.
- **Auto re-sort after cell edit** — manual re-click of the header is
  the workaround. The grid stays correct (cells reflect new values),
  but rows don't move themselves.
- **CLE re-wrap on save** — the bundled ZSTD library is decoder-only
  (no encoder available without pulling in ~100 KB more code), so we
  always write plain `#TBL`. Use an external CLE tool to re-wrap if
  the game requires it.
- **Settings dialog** — INI options (`PreferredGame`, `FontSize`) are
  edited by hand for now.

## Install

1. Build (or download) the plugin:

   ```bash
   ./build-linux.sh       # cross-compile from Linux  →  TBLViewer-plugin.zip
   build-windows.bat      # native build on Windows   →  TBLViewer-plugin.zip
   ```

   See [BUILDING.md](BUILDING.md) for the per-distro details
   (AlmaLinux 8/9, Debian/Ubuntu, Windows 10/11 with MSYS2).

2. In Total Commander, click on `TBLViewer-plugin.zip`. TC reads
   `pluginst.inf` and offers to install the plugin into its plugins
   folder.

3. The schema database (`schemas/`) is bundled inside the ZIP and
   ends up next to the DLL. It's loaded lazily on the first `.tbl`
   open and cached for the rest of the TC session.

## File layout

```
.
├── README.md                  this file
├── BUILDING.md                build instructions per platform
├── CHANGELOG.md               upstream Pascal v1.0 → v1.3.43 history
├── Makefile                   cross-compile + packaging
├── build-linux.sh             one-shot build on Linux
├── build-windows.bat          one-shot build on Windows
├── pluginst.inf               TC plugin installer manifest
├── listplug.h                 TC Lister plugin API constants
├── tblviewer.cpp              plugin entry points (ListLoad etc.)
├── tblviewer.def              DLL exports
├── tbl_file.{h,cpp}           binary format reader/writer, JSON serializer
├── tbl_types.{h,cpp}          schema field types (primitives, arrays, nested)
├── schemas.{h,cpp}            schema database loader
├── grid_view.{h,cpp}          read-only ListView wrapper for one section
├── ini_settings.{h,cpp}       per-user INI preferences
├── blowfish.{h,cpp}           CLE blowfish key schedule + CTR mode
├── blowfish_const.h           Blowfish π-derived initial constants
├── cle.{h,cpp}                CLE wrapping (peels F9BA / C9BA / D9BA)
├── crc32.{h,cpp}              zlib-style CRC32 used by FPAC entry hash
├── json.{h,cpp}               minimal JSON parser + serializer
├── zstd/                      bundled zstd single-file decoder (BSD/GPL)
└── schemas/                   363 KuroTools header schemas (MIT)
```

## License

MIT for the C++ code in this repository.

The bundled `zstd/` is from
[Facebook's zstd](https://github.com/facebook/zstd), BSD-3-Clause /
GPL-2 dual-licensed.

The bundled `schemas/` are from
[KuroTools](https://github.com/nnguyen259/KuroTools) and inherit that
project's license.
