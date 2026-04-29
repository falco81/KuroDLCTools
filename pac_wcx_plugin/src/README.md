# PAC WCX plugin — source

WCX plugin for Total Commander (Windows x64) that handles `.pac`
archives from Trails in the Sky FC (Falcom FPAC format).

## What the plugin can do

- Browse `.pac` archives in TC like a folder.
- Extract files (F5 from archive panel to disk).
- Add / replace files (drag & drop, F5 onto archive, File → Pack).
- Create folder inside the archive (F7) — via a sidecar file
  `<archive>.empty_dirs`. The sidecar is hidden on Windows, the
  archive itself stays clean for external extractors.
- Delete files (F8 / Delete inside archive).
- Detection by content — TC recognizes FPAC even without `.pac`
  extension.

## Format

FPAC is the archive format used by Trails in the Sky FC (and later
Sky entries). It's much simpler than the P3A format used in the
Kuro / Daybreak entries:

```
16 B   header   'FPAC' magic + count + header_size + unk(=1)
N×32 B entries  hash-sorted entry table
M B    name pool  null-terminated UTF-8 strings
...    raw data  uncompressed file contents
```

Each 32-byte entry: `hash` (uint32, CRC32 of name with final XOR
undone), padding (uint32 = 0), `name_offset` (uint64),
`size` (uint64), `data_offset` (uint64).

There is no compression and no version byte. The Sky engine does a
binary search on the hash table at runtime, which is why the writer
sorts entries by hash before emitting them.

## How to build

```bash
./build.sh           # Linux cross-compile to Win64
build.bat            # Windows native (Free Pascal must be in PATH)
```

Produces `pac.wcx64` (~350 KB on Linux cross-compile).

The plugin only depends on Free Pascal — no C compiler needed (unlike
the sister P3A plugin which static-links LZ4 and ZSTD).

## Installation

After building, double-click `pac.wcx64` (with `pluginst.inf` next to
it) inside TC for auto-install. Or manually via Configuration →
Options → Packer → Configure packer extension WCXs.

## Project layout

```
.
├── README.md           this file
├── build.bat           Windows native build script
├── build.sh            Linux cross-compile build script
├── pluginst.inf        TC install manifest
├── src/
│   ├── crc32pac.pas    CRC32 for the FPAC entry hash
│   ├── paclib.pas      FPAC format: read + write
│   └── pac_wcx.pas     main DLL: 19 WCX entry points
└── tests/
    ├── testcrc32pac.pas    CRC32 verified against reference hashes
    ├── testpac.pas         basic read + round-trip
    └── testpacfull.pas     content-equivalence after round-trip
```

## Design notes

The plugin is intentionally a sibling to the P3A WCX plugin and
shares its general structure (TArcHandle, sidecar approach, atomic
writes, 19 WCX exports). The differences are all format-specific:

- `paclib.pas` replaces `p3alib.pas`. Reader returns plain
  `TPACEntry` records (`Name`, `Size`, `DataOffset`, `Hash`). The
  writer's `WriteToFile` sorts the entry table by hash and lays out
  the name pool in insertion order, matching the reference Python
  tool (`sky_create_pac.py` from the kuro_mdl_tool repository).
- `crc32pac.pas` is a tiny pure-Pascal CRC32 implementation that
  computes "zlib CRC32 with the final XOR undone" — i.e., the value
  the reference Python tool produces via
  `zlib.crc32(name) ^ 0xFFFFFFFF`. Verified bit-exactly against six
  hashes pulled out of real game archives (`layout.pac`, `misc.pac`).
- `pac_wcx.pas` is structurally a fork of `p3a_wcx.pas` with
  compression-related fields stripped (no `CmpType`/`CmpSize`/
  `UncSize`/`UncHash`/dictionary), and `CarryOverExisting` simplified
  to `ReadRawBytes` + `AddRaw`.
- The `.empty_dirs` sidecar approach is identical — same file layout,
  same logic, even the same legacy `.p3a_keep` cleanup hook (in case
  someone's archive has them from somewhere else).

## License

Pascal sources: do whatever you want.
