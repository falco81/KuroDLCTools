# TBL Lister Plugin — source distribution

This is the source code for the **TBL WLX Lister plugin** for Total
Commander, version 1.3.43. The plugin reads, browses, and edits Falcom
`#TBL` data tables (Trails of Cold Steel, Trails through Daybreak,
Trails in the Sky 1, Ys X, etc.).

For the **end-user binary**, get `tbl_wlx_plugin.zip` instead — it
bundles the prebuilt `tbl_wlx.dll` and the schema files.

## Quick start (Windows)

1. Install **Lazarus 3.x for Win64** from
   https://www.lazarus-ide.org/. It bundles `fpc` and MinGW-w64 GCC.
2. Add Lazarus binaries to PATH (Win+Pause Break → Environment Variables):
   - `C:\lazarus\fpc\3.2.2\bin\x86_64-win64`
   - `C:\lazarus\mingw\x86_64-win64\bin`
3. Open `cmd.exe` in this directory and run:
   ```cmd
   build.bat
   ```
4. `tbl_wlx.dll` will appear (~728 KB).

## Quick start (Linux: Debian/Ubuntu)

```bash
sudo apt install fpc fp-units-fcl fp-compiler-source gcc-mingw-w64-x86-64 zip
./build.sh
```

## Quick start (Linux: AlmaLinux/RHEL/Rocky)

The official AlmaLinux repos don't ship `fpc`. See
[BUILD.md](BUILD.md), section B.2 for full instructions including the
fpc tarball install.

Short version:
```bash
sudo dnf install epel-release
sudo dnf install mingw64-gcc zip
# Install fpc 3.2.2 from upstream tarball:
cd /opt
sudo wget https://downloads.freepascal.org/fpc/dist/3.2.2/x86_64-linux/fpc-3.2.2.x86_64-linux.tar
sudo tar xf fpc-3.2.2.x86_64-linux.tar
cd fpc-3.2.2.x86_64-linux && sudo ./install.sh
# Get fpc source for cross-compile of fcl-base / fcl-json:
cd /opt
sudo wget https://downloads.freepascal.org/fpc/dist/3.2.2/source/fpc-3.2.2.source.tar.gz
sudo tar xzf fpc-3.2.2.source.tar.gz
# Now build:
cd <this-source-dir>
export FPCSRC=/opt/fpc-3.2.2
./build.sh
```

## What's in here

```
.
├── README.md          ← this file
├── BUILD.md           ← detailed build instructions per platform
├── CHANGELOG.md       ← v1.0 → v1.3.37 highlights
├── TROUBLESHOOTING.md ← common end-user issues
├── build.sh           ← Linux/macOS cross-compile to Win64
├── build.bat          ← Windows native build
├── run-tests.sh       ← Linux smoke test runner
├── pluginst.inf       ← TC plugin installer manifest
├── src/               ← Pascal source (~5400 lines, 16 modules)
│   ├── *.pas
│   └── zstd/          ← bundled single-file ZSTD decoder
├── tests/             ← Pascal regression tests (~1700 lines)
│   ├── *.pas
│   └── cle_fixtures/  ← Python-generated CLE test fixtures
└── schemas/           ← KuroTools header schemas (363 JSONs)
```

## Smoke test (Linux only)

```bash
./run-tests.sh
```

For the full 411-file regression you also need an extracted Falcom
TBL corpus (e.g. from `script_eng.p3a`):

```bash
CORPUS=/path/to/extracted/tbls ./run-tests.sh
```

## License

MIT for the Pascal code in `src/` and `tests/`.

The bundled `src/zstd/` is from
[Facebook's zstd](https://github.com/facebook/zstd), BSD/GPL
dual-licensed.

The bundled `schemas/` are from
[KuroTools](https://github.com/nnguyen259/KuroTools) and inherit that
project's license.

## Reporting bugs

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for self-diagnosis. If
that doesn't help, file an issue with:

- Total Commander version
- Plugin version (1.3.37 if from this source tree)
- The misbehaving `.tbl` file (or its first 256 bytes)
- A copy of your `tbl_wlx.ini` if you've changed `PreferredGame`
