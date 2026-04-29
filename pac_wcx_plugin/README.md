# PAC WCX plugin for Total Commander

WCX plugin for Total Commander (Windows x64) that handles `.pac`
archives from Trails in the Sky FC (Falcom FPAC format).

## What the plugin can do

- Browse `.pac` archives in TC like a folder (Enter / Ctrl+PgDn).
- Extract files (F5 from archive panel to disk).
- Add / replace files (drag & drop into archive, F5 onto archive,
  File → Pack).
- Create folder inside an archive (F7) — via sidecar file (see below).
- Delete files from archive (F8 / Delete inside archive).
- The FPAC format has no compression, so files are stored raw and
  extracted instantly.

## Installation

### Auto-install

1. In TC, double-click on `pac_wcx_plugin.zip`.
2. TC will ask whether to install the plugin → **Yes**.
3. Done.

### Manual installation

1. Unpack the zip somewhere stable, e.g.
   `C:\totalcmd\plugins\wcx\pac\`.
2. **Configuration → Options → Packer → Configure packer extension WCXs...**
3. In the box on the left type `pac`, click **New type**.
4. Select `pac.wcx64`. OK.

## Creating folders (F7)

FPAC format physically cannot store empty folders. The plugin works
around this with a **sidecar file** next to the archive —
`<archive>.empty_dirs` (hidden on Windows). This text file holds the
list of folders you've created via F7. Same approach as the P3A
plugin from the Kuro mod toolchain.

- F7 in TC shows the folder and stores it in the sidecar. The folder
  survives closing and reopening the archive.
- The `.pac` file itself stays format-clean — Python tools and the
  game don't see any foreign files in the archive.
- When you add a real file into a sidecar folder, the plugin removes
  it from the sidecar automatically.
- If you move/copy the archive elsewhere, also take the
  `<archive>.empty_dirs` along, otherwise empty folders are lost
  (real archive contents are unaffected).

## Atomic writes

Modifications go to a temp file `<archive>.tmp_pacwcx` first; the
original is replaced only after the new file is fully written. A
crashed write leaves the original intact.

## Format notes

- **No compression** — files are stored raw, no LZ4/ZSTD/zlib.
- **Hash-sorted entry table** — the writer sorts entries by their
  CRC32-based hash before writing, so the game can binary-search the
  table at runtime.
- **File timestamps** — FPAC doesn't store per-file times, so the
  plugin reports the archive file's mtime for all entries.
- **Attributes** — FPAC doesn't store them; plugin reports "archive"
  for all entries.
- 64-bit only.

## Source code

Available as a separate source zip with full Pascal code and a build
guide. Builds with Free Pascal alone — no C compiler dependency
(unlike the P3A plugin, no LZ4/ZSTD libraries to link).
