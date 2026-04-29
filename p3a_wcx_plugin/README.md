# P3A WCX plugin for Total Commander

WCX plugin for Total Commander (Windows x64) that handles `.p3a`
archives from Falcom games (Kuro no Kiseki / Trails through Daybreak).

## What the plugin can do

- Browse `.p3a` archives in TC like a folder (Enter / Ctrl+PgDn).
- Extract files (F5 from archive panel to disk).
- Add / replace files (drag & drop into archive, F5 onto archive,
  File → Pack).
- Create folder inside an archive (F7) — via sidecar file (see below).
- Delete files from archive (F8 / Delete inside archive).
- LZ4 compression / decompression.

## Installation

### Auto-install

1. In TC, double-click on `p3a_wcx_plugin.zip`.
2. TC will ask whether to install the plugin → **Yes**.
3. Done.

If TC doesn't react (can happen if you've already entered the zip
before): open another zip and come back, OR restart TC, OR delete
and re-download the zip. In TC, make sure **Configuration → Options
→ Packer → Treat archives like directories** is enabled.

### Manual installation

1. Unpack the zip to `C:\totalcmd\plugins\wcx\p3a\` (anywhere is fine,
   just keep it where it lives).
2. **Configuration → Options → Packer → Configure packer extension WCXs...**
3. In the box on the left type `p3a`, click **New type**.
4. Select `p3a.wcx64`. OK.

## Creating folders (F7)

P3A format physically cannot store empty folders. The plugin works
around this with a **sidecar file** next to the archive —
`<archive>.p3a.empty_dirs`. This text file (hidden on Windows) holds
the list of folders you've created via F7.

**What this means:**

- F7 in TC shows the folder and stores it in the sidecar. The folder
  survives closing and reopening the archive.
- The `.p3a` file itself stays format-clean — Python tools, the game,
  or any other extractor will not see any foreign files in the archive.
- When you add a real file into such a folder, the plugin automatically
  removes it from the sidecar (the folder isn't empty anymore, no
  marker needed).
- When you delete the last file from a folder, the folder disappears.
  If you want to keep it as an empty folder, F7 it again.

**What you should know:**

- If you move/copy the `.p3a` archive elsewhere, **also take
  `<archive>.p3a.empty_dirs` with it**, otherwise you'll lose info
  about empty folders (the data in the archive itself stays fine).
- If you accidentally delete the sidecar, the empty folders just
  vanish. Just F7 them again — no harm done.
- If you have leftover `.p3a_keep` files in archives from older
  plugin versions (v2.0–v2.2), they will be automatically stripped
  on the first modification of the archive.

## Known limitations

- **ZSTD compression** (cmp_type=2/3) is neither read nor written.
  If an archive has ZSTD entries, the plugin will list them but
  cannot extract. For ZSTD use Python tools (`p3a_tool.exe`,
  `kuro_mdl_rename.py`).
- **v1200 write** is not supported (v1200 read works). Plugin always
  writes v1100.
- **File timestamps**: P3A doesn't store per-file times, so the plugin
  reports the archive file's mtime for all entries.
- **Attributes**: P3A doesn't store them; plugin reports "archive"
  for all entries.
- 64-bit only.

## Atomic writes

The plugin writes modifications to a temp file `<archive>.tmp_p3awcx`
and only replaces the original after the write succeeds. If you ever
find a leftover `*.tmp_p3awcx`, it's an artefact of an interrupted
operation — safe to delete.

## Source code

Available as a separate source zip with full Pascal/C code and a
build guide. The plugin can be rebuilt from Free Pascal + MinGW-w64 GCC.
