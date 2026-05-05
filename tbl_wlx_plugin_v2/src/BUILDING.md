# Building TBLViewer

This document covers building `tblviewer.wlx` (32-bit) and
`tblviewer.wlx64` (64-bit) from source on Linux (cross-compiling to
Windows) and on Windows natively. Both produce the same DLLs.

The build chain is plain MinGW-w64 g++ + a single bundled C file
(`zstd/zstddeclib.c`) compiled separately as C99. No Pascal compiler
is needed for this rewrite.

---

## A. Cross-compile from Linux — quickest path

This is the recommended path because the cross toolchain is in every
mainstream distro's package manager and the result is a stripped PE
binary identical to a native MSYS2 build.

### A.1 AlmaLinux 9 / RHEL 9 / Rocky 9 / Fedora 38+

```bash
sudo dnf install -y epel-release
sudo dnf config-manager --set-enabled crb       # AlmaLinux 9 / RHEL 9 / Rocky 9
# or:
sudo dnf config-manager --set-enabled powertools  # AlmaLinux 8 / RHEL 8 / Rocky 8
sudo dnf install -y \
    mingw32-gcc-c++ mingw64-gcc-c++ \
    mingw32-winpthreads-static mingw64-winpthreads-static \
    make zip
```

### A.2 AlmaLinux 8 / RHEL 8

Same packages, but the repo to enable is `powertools` (older naming):

```bash
sudo dnf install -y epel-release
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --set-enabled powertools
sudo dnf install -y \
    mingw32-gcc-c++ mingw64-gcc-c++ \
    mingw32-winpthreads-static mingw64-winpthreads-static \
    make zip
```

The mingw packages on AlmaLinux 8 are GCC 7.2.0 (April 2017) — old
but works for C++17 with `-std=c++17`. If you want a newer compiler,
build via Docker on Alma 9 or Fedora.

### A.3 Debian / Ubuntu

```bash
sudo apt update
sudo apt install -y \
    mingw-w64 \
    g++-mingw-w64-i686 \
    g++-mingw-w64-x86-64 \
    make zip
```

### A.4 Build

Run the one-shot script:

```bash
chmod +x build-linux.sh
./build-linux.sh
```

It detects your distro, installs missing dependencies, and runs
`make all`. Outputs:

- `tblviewer.wlx`            — 32-bit DLL
- `tblviewer.wlx64`          — 64-bit DLL
- `TBLViewer-plugin.zip`     — TC install bundle (DLLs + pluginst.inf + schemas/)

Or call `make` directly:

```bash
make all       # build both DLLs and zip
make clean     # remove build artifacts
```

---

## B. Native build on Windows 10 / 11 — MSYS2 path

The script handles MSYS2 install, toolchain install, and compile.
The default install location is `C:\Program Files\msys64`; override
with `set MSYS2_HOME=...` before running if you want it elsewhere.

```cmd
build-windows.bat
```

Run as **Administrator** the first time so winget / MSYS2 install can
write into `C:\Program Files`. The script will:

1. Look for MSYS2 in this order:
   - `%MSYS2_HOME%` (env-var override)
   - `C:\Program Files\msys64` (preferred default)
   - `C:\msys64` (legacy default)

   If none exist, MSYS2 is installed via
   `winget install MSYS2.MSYS2 --location "C:\Program Files\msys64"`.

2. Run `pacman -Sy` and install:
   `mingw-w64-i686-gcc`, `mingw-w64-x86_64-gcc`, `make`, `zip`.

3. Compile both DLLs by invoking the discovered `g++.exe` directly.
   Before each compile call the script prepends the matching
   `mingw32\bin` (or `mingw64\bin`) to `PATH` so the internal
   `cc1plus.exe` (which lives under `libexec\gcc\...`) can find its
   companion DLLs (`libisl-23.dll`, `libgmp-10.dll`,
   `libgcc_s_dw2-1.dll`, `libmpc-3.dll`).

4. Package `TBLViewer-plugin.zip` with both DLLs plus `pluginst.inf`
   plus the `schemas\` folder.

### Manual MSYS2 build

If you'd rather drive MSYS2 by hand:

```bash
# in MSYS2 MinGW 64 shell
pacman -Syu --noconfirm
pacman -S --noconfirm --needed \
    mingw-w64-i686-gcc \
    mingw-w64-x86_64-gcc \
    make zip

cd /path/to/TBLViewer
make all
```

---

## C. What the build does internally

The Makefile compiles two TUs separately for each architecture:

1. `zstddeclib.c` (the bundled zstd single-file decoder) is built as
   C99 with `-DZSTD_DISABLE_ASM=1 -DZSTD_LEGACY_SUPPORT=0 -w` to keep
   the build log clean.

2. The eight C++ TUs (`tblviewer.cpp`, `tbl_file.cpp`,
   `tbl_types.cpp`, `schemas.cpp`, `json.cpp`, `blowfish.cpp`,
   `cle.cpp`, `crc32.cpp`) are compiled together into a shared
   library with `-static -static-libgcc -static-libstdc++` so the
   resulting DLL has no MinGW runtime dependencies.

3. The `.def` file lists the eight `List*` entry points TC expects.
   The `-Wl,--kill-at` flag keeps the names undecorated.

The libraries linked are: `comctl32`, `shlwapi`, `user32`, `kernel32`,
`gdi32`, `advapi32`, `shell32`, `comdlg32`, `ole32`. There's no D2D /
DirectWrite / WinHTTP dependency — the TBL viewer renders into a
plain Win32 EDIT control.

---

## D. Troubleshooting

**`error: 'PI_P' was not declared in this scope`** —
`blowfish_const.h` failed to convert from `blowfish_const.inc`. The
file should be a C++ header containing five `const uint32_t` arrays.
Re-extract from the source ZIP.

**`The code execution cannot proceed because libisl-23.dll was not
found`** on Windows — the `mingw32\bin` (or `mingw64\bin`) folder is
not on PATH when the compiler is invoked. The supplied
`build-windows.bat` handles this; if you're calling g++ manually,
set PATH yourself.

**`mingw32-gcc-c++` not found on AlmaLinux 8** — you need to enable
the PowerTools repo. See section A.2.

**TBLViewer-plugin.zip is several megabytes** — that's expected. The
schema database is 363 small JSON files (~2.1 MB on disk; ~700 KB
zipped). The DLLs are ~500 KB each.

**`Schema warnings:` shown in viewer** — the file contains a section
whose header name isn't in `schemas/headers/`, or whose entry length
doesn't match any known variant for that header. The viewer falls
back to raw hex for that section. This isn't a build error; it's a
schema gap.
