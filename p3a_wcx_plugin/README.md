# P3A WCX Plugin for Total Commander

A Total Commander packer plugin that lets you browse Falcom **P3A** archives
(the Kuro no Kiseki / Trails through Daybreak engine format) directly in TC,
the same way you browse `.zip` files.

This is a **read-only** plugin in v1: open, browse contents, and extract.
Pack / modify / delete are not supported (see "Roadmap" below).

## Files in this package

| File | Purpose |
|---|---|
| `p3a.wcx64` | The plugin DLL — drop in TC's plugin folder. |
| `pluginst.inf` | Auto-install metadata for TC. |
| `p3a_wcx.pas` etc. | Pascal source. Rebuild with Free Pascal 3.2+ if you want. |
| `README.md` | This file. |

## Install (the easy way)

1. In Total Commander, navigate **into** the `.zip` you downloaded this
   plugin from (the same way Total Commander showed you `ModManager.zip`
   contents in your screenshot).
2. TC will pop up a dialog asking whether to install this plugin — click
   **Yes**.
3. TC reads `pluginst.inf` and asks you to confirm the file extension to
   associate (`p3a` is pre-filled). Click **OK**.
4. Done. From now on, double-click any `.p3a` file and TC will step into
   it as if it were a folder.

## Install (manual)

1. Copy `p3a.wcx64` somewhere permanent, e.g.
   `C:\Users\<you>\AppData\Roaming\GHISLER\plugins\wcx\p3a\p3a.wcx64`.
2. In Total Commander: **Configuration → Options... → Packer →
   "Configure packer extension WCXs..."**.
3. Type `p3a` in the box on the left and click **New type**.
4. Browse to `p3a.wcx64` from step 1 and click **Open**.
5. Click **OK** in all the open dialogs.

You can now open `.p3a` files like folders.

## What it does

- **Browse**: step into a `.p3a` (Enter or Ctrl+PgDown) — TC shows the file
  tree exactly as if it were a directory.
- **Extract single file**: select a file, press F5 (or drag to the other
  panel) — it extracts just that file to your destination.
- **Extract everything**: open the archive in TC, select all (Ctrl+A),
  press F5.
- **Quick view**: F3 on a file inside the archive — TC silently extracts
  to a temp file and shows it.

The plugin reports the `PK_CAPS_BY_CONTENT` capability, so TC can also
auto-detect P3A files that have been renamed to other extensions
(e.g. `.pak`, `.dat`) — they'll still open correctly.

## Limitations

- **Read-only.** F5 *into* an archive (packing) is not implemented in v1.
  Use the original `kuro_dlc_tool` (`p3a_archive.py`) or the
  `kuro_mdl_rename.py --p3a` option for repacking.
- **Compression types**: `none` (0) and **lz4** (1) are supported.
  `zstd` (2) and `zstd-dict` (3) are NOT decompressed in this build.
  Practically all P3A files in modding scenes use lz4, so this should
  be fine for typical use; a file-list browse still works regardless of
  compression type.
- **Hash verification**: skipped on extract for speed. The data is
  decompressed and written as-is; if a P3A is corrupt, lz4 will refuse
  the bad block.
- **No multi-volume support**, no encryption, no comments.

## Roadmap

If there's interest, v2 could add:
- Pack/modify/delete support (full read-write WCX).
- ZSTD decompression (the format constants are already parsed; just need
  a ZSTD decoder ported to Pascal or linked from a static lib).
- Optional hash verification with a checkbox.

## Building from source

The plugin is pure Free Pascal — no external dependencies, no DLLs to
distribute alongside it. To rebuild from this directory:

```bash
# On Linux (cross-compile to Windows):
fpc -Twin64 -Px86_64 -O2 p3a_wcx.pas -op3a.wcx64

# On Windows with FPC installed:
fpc -O2 p3a_wcx.pas -op3a.wcx64
```

The source files are:

- `xxhash64.pas` — pure-Pascal XXH64 (verified against the reference
  implementation on 5 test vectors).
- `lz4dec.pas`   — pure-Pascal LZ4 block decompressor (verified against
  Python's `lz4.block` on 7 test vectors).
- `p3alib.pas`   — P3A v1100/v1200 archive reader.
- `p3a_wcx.pas`  — Total Commander WCX entry points (this is the library).

## Note on testing

This plugin was developed on Linux and cross-compiled to a real Windows
PE32+ DLL. The format-handling pieces (xxhash, lz4, p3a parsing) were
each verified in isolation on Linux against reference implementations
and against a real `pyrixia.p3a` sample (55 files, all extracted
correctly). The Windows-side WCX entry points themselves were not
runtime-tested due to a broken Wine in the build environment, so if you
hit something weird, please report it — the source is included so you
can rebuild after a fix.

## License & credits

P3A format reverse-engineered by [eArmada8 / kuro_dlc_tool](https://github.com/eArmada8/kuro_dlc_tool).
Plugin written for use with that ecosystem.
