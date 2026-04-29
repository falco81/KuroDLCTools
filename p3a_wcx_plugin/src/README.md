# P3A WCX plugin — source

WCX plugin for Total Commander (Windows x64) that handles `.p3a`
archives from Falcom games (Kuro no Kiseki / Trails through Daybreak).

## What the plugin can do

- Browse `.p3a` archives in TC like a folder (Enter / Ctrl+PgDn).
- Extract files (F5 from archive panel to disk).
- Add / replace files (drag & drop into archive, F5 onto archive,
  File → Pack).
- Create folder inside the archive (F7) — via a sidecar file
  `<archive>.empty_dirs` (P3A format has no native concept of empty
  folders). The sidecar is hidden on Windows and the archive itself
  stays clean for external extractors.
- Delete files from archive (F8 / Delete inside archive).
- Detection by content — TC recognizes P3A even without the extension.
- File timestamps in archive = mtime of the `.p3a` file itself
  (P3A format doesn't store per-file times).

## Compression

- **Reading**: cmp_type 0 (none) and 1 (lz4). ZSTD (type 2/3) not
  supported yet.
- **Writing**: lz4 (cmp_type=1), with automatic fallback to
  uncompressed (cmp_type=0) when lz4 doesn't shrink the file.
  Existing entries are kept verbatim during archive modification
  (no needless recompression).
- Format version: **reads** v1100 and v1200, **writes** v1100.

## How to build

See **`BUILD.md`** for the full guide (native Windows + Linux
cross-compile). TL;DR if you have Lazarus IDE with mingw:

```cmd
build.bat
```

Produces `p3a.wcx64`.

## How to install

(See README in the binary zip, or: produce `p3a.wcx64`, double-click
it in TC for auto-install, or manually via Configuration → Options
→ Packer → Configure packer extension WCXs.)

## Project layout

```
.
├── README.md           this file
├── BUILD.md            detailed build instructions
├── build.bat           Windows native build script
├── build.sh            Linux cross-compile build script
├── pluginst.inf        TC install manifest (copied into the binary zip)
├── src/                Pascal and C source code
│   ├── xxhash64.pas
│   ├── lz4dec.pas
│   ├── lz4comp.pas
│   ├── p3alib.pas
│   ├── p3a_wcx.pas
│   └── lz4/            LZ4 reference C implementation (BSD 2-Clause)
│       ├── lz4.c
│       ├── lz4.h
│       └── LICENSE
└── tests/              verification programs (optional)
    ├── testxxh.pas
    ├── testlz4.pas
    ├── testlz4c.pas
    ├── testp3a.pas
    ├── testwrite.pas
    ├── testroundtrip.pas
    ├── testmarker.pas
    ├── testcleanup.pas
    └── testsidecar.pas
```

## Design notes

Key design decisions:

- **Pure Pascal for hot read paths.** XXH64 hash and LZ4 decompression
  live in `xxhash64.pas` and `lz4dec.pas` as pure Pascal
  implementations. No libc runtime dependency, small DLL.

- **Static linking of C code for LZ4 compression.** Reimplementing
  LZ4 compression in Pascal would take days and the algorithm is
  occasionally optimized. Instead, the official `lib/lz4.c`
  (BSD 2-Clause) is linked via the FPC `{$L lz4obj.o}` directive.
  Stubs for `memcpy`/`memmove`/`memset`/`calloc`/`free`/`__chkstk_ms`
  in `lz4comp.pas` route to the FPC runtime so the DLL doesn't
  need to link libc.

- **TP3AWriter copy-vs-compress.** When modifying an existing archive
  (adding one file, deleting), the plugin **doesn't decompress** the
  original entries — it copies them verbatim via `ReadCompressedBytes`
  → `AddFromCompressed`. Only new files are LZ4-compressed.

- **Atomic writes.** Every modification goes first to
  `<archive>.tmp_p3awcx`, the original is replaced only after the
  write succeeds. A crash mid-write leaves the original archive
  untouched.

- **Sidecar file for empty folders.** P3A format has no directory
  entries, only file entries. So that F7 in TC can work without
  polluting the archive with marker files, the plugin maintains a
  list of "F7-created" empty folders in a **sidecar file**
  `<archive>.empty_dirs` (plain text, one folder per line, hidden
  on Windows). It's loaded on `OpenArchive` and emitted as virtual
  directory entries in `ReadHeader*`. F7 adds to the sidecar; adding
  a file into an empty folder removes it from the sidecar (recursively
  through all ancestors). On every archive modification the plugin
  also auto-strips any leftover `.p3a_keep` markers from the older
  plugin versions, so upgrading is lossless.

## License

- Pascal code in `src/*.pas` and build scripts: do whatever you want.
- LZ4 C code in `src/lz4/`: BSD 2-Clause by Yann Collet (see
  `src/lz4/LICENSE`).
