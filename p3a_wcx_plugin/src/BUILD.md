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

## Manual procedure (if the build script fails)

If you want to know exactly what's happening, or need to debug:

### Step 1 — compile LZ4 to an object file

From the directory containing this `BUILD.md`:

```bash
gcc -c -O3 -o src/lz4obj.o src/lz4/lz4.c
```

Linux cross-compile:
```bash
x86_64-w64-mingw32-gcc -c -O3 -o src/lz4obj.o src/lz4/lz4.c
```

This creates `src/lz4obj.o` (~110 KB). The file `src/lz4comp.pas`
finds it via `{$L lz4obj.o}` (relative path — so it must sit in the
same directory as the Pascal sources).

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

Produces `src/p3a.wcx64` (~450 KB DLL).

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
├── p3alib.pas          P3A format: read + write
├── p3a_wcx.pas         main DLL: WCX entry points, exports
└── lz4/
    ├── lz4.c           LZ4 reference C implementation (BSD 2-Clause)
    ├── lz4.h           header
    └── LICENSE         BSD 2-Clause license

tests/
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
