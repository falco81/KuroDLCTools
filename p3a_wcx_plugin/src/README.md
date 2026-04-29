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

- **Reading**: all P3A compression types are supported:
  `0` (none), `1` (LZ4), `2` (ZSTD), `3` (ZSTD with dictionary).
  When the archive carries a per-archive ZSTD training dictionary
  (`flags & 1 = 1`), the plugin loads it from the `P3ADICT` block
  and threads it into the decompressor for every type-3 entry.
- **Writing**: new entries are produced as LZ4 (cmp_type=1), with
  automatic fallback to uncompressed (cmp_type=0) when LZ4 doesn't
  shrink the file. Existing entries (any cmp_type, including ZSTD)
  are kept verbatim during archive modification (no needless
  decompress + recompress).
- **Format version round-trip**: a v1200 archive stays v1200 on save,
  a v1100 archive stays v1100. The ZSTD dictionary block, when
  present, is also preserved verbatim — read→write of an unchanged
  archive produces a byte-identical file.

## How to build

See **`BUILD.md`** for the full guide (native Windows + Linux
cross-compile). TL;DR if you have Lazarus IDE with mingw:

```cmd
build.bat
```

Produces `p3a.wcx64`.

The `src/zstd/zstddeclib.c` file in this distribution is the
single-file ZSTD decoder generated from the official
[facebook/zstd](https://github.com/facebook/zstd) repository
(`build/single_file_libs/create_single_file_decoder.sh`, version
v1.5.6). To regenerate it manually from a fresh clone:

```bash
git clone --depth 1 --branch v1.5.6 https://github.com/facebook/zstd
cd zstd/build/single_file_libs
./create_single_file_decoder.sh
cp zstddeclib.c /path/to/p3a_wcx_source/src/zstd/
```

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
│   ├── zstddec.pas
│   ├── p3alib.pas
│   ├── p3a_wcx.pas
│   ├── lz4/            LZ4 reference C implementation (BSD 2-Clause)
│   │   ├── lz4.c
│   │   ├── lz4.h
│   │   └── LICENSE
│   └── zstd/           ZSTD single-file decoder (BSD-3-Clause / GPLv2)
│       ├── zstddeclib.c   amalgamated decompressor
│       ├── zstd.h
│       └── LICENSE
└── tests/              verification programs (optional)
    ├── testxxh.pas
    ├── testlz4.pas
    ├── testlz4c.pas
    ├── testp3a.pas
    ├── testwrite.pas
    ├── testroundtrip.pas
    ├── testroundv1200.pas
    ├── testmarker.pas
    ├── testcleanup.pas
    └── testsidecar.pas
```

## Design notes

Key design decisions:

- **Pure Pascal for hot read paths.** XXH64 hash and LZ4 decompression
  live in `xxhash64.pas` and `lz4dec.pas` as pure Pascal
  implementations. No libc runtime dependency, small DLL.

- **Static linking of C code for LZ4 compression and ZSTD
  decompression.** Reimplementing these in Pascal would take a
  substantial amount of work and the algorithms occasionally get
  optimized. Instead, the official sources are linked via the FPC
  `{$L lz4obj.o}` / `{$L zstdobj.o}` directives. Stubs in
  `lz4comp.pas` (for `memcpy`/`memmove`/`memset`/`calloc`/`free`/
  `__chkstk_ms`) and `zstddec.pas` (`malloc`) route to the FPC
  runtime so the DLL doesn't pull in libc.

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
