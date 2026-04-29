# How to build the P3A WCX plugin from source

The plugin is written in Free Pascal and statically links the LZ4
reference C implementation. So compilation needs **two tools**:

1. **Free Pascal Compiler (fpc)** version 3.2.2 or newer
2. **C compiler** (MinGW-w64 GCC) — for LZ4

Once both are installed, just run `build.bat` (Windows) or
`build.sh` (Linux).

---

## Option A: native build on Windows (recommended)

### A.1 Install via Lazarus (easiest)

[Lazarus IDE](https://www.lazarus-ide.org/) bundles **fpc** and
**MinGW-w64 gcc**, so you don't need to install anything else.

1. Download **Lazarus 3.x for Win64** from
   https://www.lazarus-ide.org/index.php?page=downloads
   (installer like `lazarus-3.x.x-fpc-3.2.2-win64.exe`).
2. Install with default options. After install, `fpc.exe` should be
   in `C:\lazarus\fpc\3.2.2\bin\x86_64-win64\`.
3. **Add the Lazarus binaries to PATH**:
   - Win+Pause Break → Advanced system settings → Environment Variables
   - Edit `Path` (user or system) and add:
     - `C:\lazarus\fpc\3.2.2\bin\x86_64-win64`
     - `C:\lazarus\mingw\x86_64-win64\bin` *(or similar — find `gcc.exe`)*
4. Open a fresh **cmd.exe** and verify:
   ```cmd
   fpc -h
   gcc --version
   ```
   Both should print versions.
5. In this directory run:
   ```cmd
   build.bat
   ```
6. Done. `p3a.wcx64` will appear.

### A.2 Manual install (if you don't want Lazarus)

#### Free Pascal Compiler

1. Download **fpc 3.2.2 for Win64** from
   https://www.freepascal.org/download.html (choose
   "Win64 / FreePascal").
2. Install. Default location `C:\FPC\3.2.2\` is fine.
3. The installer should add `fpc.exe` to PATH automatically.
   Verify in cmd:
   ```cmd
   fpc -h
   ```

#### MinGW-w64 GCC

Three options, pick one:

**Option 1 — MSYS2 (recommended):**
1. Download MSYS2 from https://www.msys2.org/ and install.
2. Open the "MSYS2 MinGW 64-bit" terminal and run:
   ```bash
   pacman -S mingw-w64-x86_64-gcc
   ```
3. Add `C:\msys64\mingw64\bin` to PATH.

**Option 2 — WinLibs (standalone):**
1. Download from https://winlibs.com/, x86_64 edition.
2. Unpack anywhere (e.g. `C:\mingw64\`).
3. Add `C:\mingw64\bin` to PATH.

**Option 3 — TDM-GCC:**
1. Download from https://jmeubank.github.io/tdm-gcc/ → 64-bit edition.
2. Installer adds it to PATH automatically.

#### Run the build

In this directory open **cmd.exe** and run:
```cmd
build.bat
```

If `gcc.exe` isn't directly in PATH but you have it elsewhere
(typically `x86_64-w64-mingw32-gcc.exe`), you can tell the script:
```cmd
set CC=x86_64-w64-mingw32-gcc
build.bat
```

---

## Option B: cross-compile from Linux (Debian/Ubuntu)

```bash
sudo apt install fpc fp-units-fcl gcc-mingw-w64-x86-64
chmod +x build.sh
./build.sh
```

Produces `p3a.wcx64` for Windows.

---

## Option C: cross-compile from Linux (AlmaLinux / Rocky / RHEL)

This is more involved than Debian because the EPEL `fpc` package on
the RHEL family ships only the Linux runtime — the win64 cross-RTL
units have to be built locally. The procedure below is verified
end-to-end on **AlmaLinux 8.10** with `fpc-3.2.0`. AlmaLinux 9 / Rocky
9 work the same way, only the secondary repo is named `crb` instead
of `powertools`.

### Step 1 — install the toolchain

```bash
# Enable EPEL (provides fpc, fpc-src) and PowerTools/CRB (provides mingw-w64-gcc)
sudo dnf install -y epel-release make
sudo dnf config-manager --set-enabled powertools     # AlmaLinux/Rocky 8
# sudo dnf config-manager --set-enabled crb          # AlmaLinux/Rocky 9 — use this line instead

# Install Free Pascal, its sources (needed for cross-RTL), and MinGW-w64
sudo dnf install -y fpc fpc-src mingw64-gcc
```

### Step 2 — build the win64 cross-RTL

The EPEL `fpc` package only includes pre-built units for `x86_64-linux`.
The `fpc-src` package puts the FPC source tree into `/usr/share/fpcsrc/`,
which is read-only. Copy it somewhere writable, build the win64 RTL,
and install:

```bash
cp -r /usr/share/fpcsrc /tmp/fpcsrc

cd /tmp/fpcsrc/rtl
make clean all install \
    OS_TARGET=win64 CPU_TARGET=x86_64 \
    BINUTILSPREFIX=x86_64-w64-mingw32- \
    INSTALL_BASEDIR=/usr/lib64/fpc/3.2.0
```

That's it for the FPC side. **You do not need to build the FCL** —
in FPC 3.2.0 (which is what EPEL ships), `Classes`, `SysUtils`, `Math`
and `Windows` are all part of RTL itself. If you try to build the FCL,
it will fail at the `fpmake` linker step (missing `crt*.o`,
`-lpthread`, `-lc`); that error is harmless and can be ignored —
you already have everything the plugin needs.

### Step 3 — verify and build

```bash
ls /usr/lib64/fpc/3.2.0/units/x86_64-win64/rtl/system.ppu
ls /usr/lib64/fpc/3.2.0/units/x86_64-win64/rtl/classes.ppu
ls /usr/lib64/fpc/3.2.0/units/x86_64-win64/rtl/sysutils.ppu
```

All three files must exist. Then build the plugin itself:

```bash
cd /path/to/p3a_wcx_source
./build.sh
```

Produces `p3a.wcx64` (~600 KB on EL8 with mingw GCC 7.2.0; the exact
size depends on the mingw version — newer mingw produces slightly
smaller binaries).

### Verify the DLL exports

```bash
x86_64-w64-mingw32-objdump -p p3a.wcx64 | grep -A 25 "\[Ordinal/Name"
```

You should see all 19 WCX entry points (CanYouHandleThisFile,
CanYouHandleThisFileW, CloseArchive, DeleteFiles, DeleteFilesW,
GetPackerCaps, OpenArchive, OpenArchiveW, PackFiles, PackFilesW,
ProcessFile, ProcessFileW, ReadHeader, ReadHeaderEx, ReadHeaderExW,
SetChangeVolProc, SetChangeVolProcW, SetProcessDataProc,
SetProcessDataProcW).

### Common pitfalls on RHEL family

**`No matching repo to modify: crb`** — you're on AlmaLinux 8, where
the repo is named `powertools`, not `crb`. (Or your distro doesn't
ship the AlmaLinux/Rocky default repo files, in which case
`dnf install -y almalinux-release` or `rocky-release` re-creates them.)

**`No match for argument: mingw64-gcc`** — the secondary repo isn't
enabled. `dnf repolist all` should show `powertools` (EL8) or `crb`
(EL9) as `enabled`. If `dnf config-manager` says it's missing too,
install `dnf-plugins-core` first, or just edit
`/etc/yum.repos.d/almalinux-powertools.repo` (or `-crb.repo`) and
flip `enabled=0` to `enabled=1`.

**`bash: make: command not found`** — minimal AlmaLinux installs don't
include `make`. `dnf install -y make` fixes it.

**`Fatal: Can't find unit system used by p3a_wcx`** — the win64
cross-RTL hasn't been installed. Step 2 above is what installs it.
After that step, `/usr/lib64/fpc/3.2.0/units/x86_64-win64/rtl/system.ppu`
must exist.

**FCL build fails with `cannot find -lpthread` / `crti.o not found`** —
ignore. As noted in Step 2, FCL is not needed for this plugin.

---

## Manual procedure (if the build script fails)

If you want to know exactly what's happening, or need to debug:

### Step 1 — compile LZ4 and ZSTD to object files

From the directory containing this `BUILD.md`:

```bash
gcc -c -O3 -o src/lz4obj.o src/lz4/lz4.c
gcc -c -O2 -DZSTDLIB_VISIBILITY= -DZSTD_DISABLE_ASM \
    -o src/zstdobj.o src/zstd/zstddeclib.c
```

Linux cross-compile (replace `gcc` with `x86_64-w64-mingw32-gcc`):
```bash
x86_64-w64-mingw32-gcc -c -O3 -o src/lz4obj.o src/lz4/lz4.c
x86_64-w64-mingw32-gcc -c -O2 -DZSTDLIB_VISIBILITY= -DZSTD_DISABLE_ASM \
    -o src/zstdobj.o src/zstd/zstddeclib.c
```

This creates `src/lz4obj.o` (~110 KB) and `src/zstdobj.o` (~150 KB).
The Pascal sources find them via `{$L lz4obj.o}` and `{$L zstdobj.o}`
(relative paths — so they must sit in the same directory as the
Pascal sources).

### Step 2 — compile the Pascal plugin

```bash
cd src
fpc -O2 -CX -XX p3a_wcx.pas -op3a.wcx64
```

For Linux cross-compile, add `-Twin64 -Px86_64`:
```bash
cd src
fpc -Twin64 -Px86_64 -O2 -CX -XX p3a_wcx.pas -op3a.wcx64
```

Produces `src/p3a.wcx64` (~580 KB DLL).

---

## Verify the DLL has all required exports

The plugin must export **19 functions** that TC will call. List them
(on Linux or in MSYS2):

```bash
x86_64-w64-mingw32-objdump -p p3a.wcx64 | grep -A 25 "\[Ordinal/Name"
```

You should see:
```
CanYouHandleThisFile      OpenArchive             ReadHeader
CanYouHandleThisFileW     OpenArchiveW            ReadHeaderEx
CloseArchive              PackFiles               ReadHeaderExW
DeleteFiles               PackFilesW              SetChangeVolProc
DeleteFilesW              ProcessFile             SetChangeVolProcW
GetPackerCaps             ProcessFileW            SetProcessDataProc
                                                  SetProcessDataProcW
```

---

## Running the tests (optional)

The `tests/` directory contains verification programs. Build them
natively for whichever platform you're on:

```bash
cd tests
fpc -O2 -CX -XX -Fu../src testxxh.pas       # XXH64 hash test
fpc -O2 -CX -XX -Fu../src testlz4.pas       # LZ4 decompression test
fpc -O2 -CX -XX -Fu../src testlz4c.pas      # LZ4 compress + decompress
fpc -O2 -CX -XX -Fu../src testsidecar.pas   # sidecar logic test
./testxxh && ./testlz4 && ./testlz4c && ./testsidecar
```

If they all pass, the write side of P3A is solid.

`-Fu../src` tells fpc where to find `xxhash64.pas`, `lz4dec.pas`, etc.
On Linux make sure `lz4obj.o` exists in `src/` (build via
`gcc -c -O3 -o src/lz4obj.o src/lz4/lz4.c`).

---

## Source layout

```
src/
├── xxhash64.pas        pure Pascal XXH64 hash (verified against reference)
├── lz4dec.pas          pure Pascal LZ4 decompression
├── lz4comp.pas         wrapper around LZ4 reference C code (static link)
├── zstddec.pas         wrapper around ZSTD single-file decoder (static link)
├── p3alib.pas          P3A format: read + write, all cmp_types, v1100/v1200
├── p3a_wcx.pas         main DLL: WCX entry points, exports
├── lz4/
│   ├── lz4.c           LZ4 reference C implementation (BSD 2-Clause)
│   ├── lz4.h           header
│   └── LICENSE         BSD 2-Clause license
└── zstd/
    ├── zstddeclib.c    ZSTD single-file decoder (amalgamated)
    ├── zstd.h          header
    └── LICENSE         BSD-3-Clause / GPLv2 dual license

tests/
├── testxxh.pas
├── testlz4.pas
├── testlz4c.pas
├── testp3a.pas
├── testwrite.pas
├── testroundtrip.pas
├── testroundv1200.pas  v1200+dict round-trip (read→write→read byte-identical)
├── testmarker.pas
├── testcleanup.pas
└── testsidecar.pas
```

## Common problems

**`Fatal: Can't find unit lz4comp`** — fpc is not running from `src/`.
Either `cd src` first, or use `-FUsrc` on the command line, or just
run `build.bat` / `build.sh`.

**`Error: Error while linking`** during fpc — `src/lz4obj.o` is missing
or was built for the wrong architecture (Win64 fpc needs a COFF object
from mingw, NOT an ELF object from Linux gcc).

**`gcc: command not found`** — MinGW isn't in PATH. Pass the full
path: `set CC=C:\path\to\gcc.exe & build.bat`

**`fpc: command not found`** — Free Pascal isn't in PATH. Same:
`set FPC=C:\FPC\3.2.2\bin\x86_64-win64\fpc.exe & build.bat`

**Build script succeeded but TC won't load the plugin** — check the
DLL has 19 exports (see "Verify" above). If any are missing, the
build was partial — try again after `del src\*.ppu src\*.o`.
