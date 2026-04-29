# How to build the PAC WCX plugin from source

The plugin is written entirely in Free Pascal, with **no C
dependency** (unlike the P3A plugin, no LZ4 or ZSTD to link). So all
you need is a Free Pascal Compiler.

Once you have **fpc 3.2.2+ for Win64** available, just run
`build.bat` (Windows) or `build.sh` (Linux).

---

## Option A: native build on Windows (recommended)

The simplest install is via [Lazarus IDE](https://www.lazarus-ide.org/),
which bundles `fpc.exe`:

1. Download Lazarus 3.x for Win64.
2. Install with default options.
3. Add `C:\lazarus\fpc\3.2.2\bin\x86_64-win64` to PATH.
4. Open a fresh `cmd.exe` in this directory and run:
   ```cmd
   build.bat
   ```
5. Done. `pac.wcx64` is produced.

If you only want fpc without Lazarus, grab the standalone installer
from https://www.freepascal.org/download.html (Win64 / FreePascal),
install, and run `build.bat`.

---

## Option B: cross-compile from Linux (Debian/Ubuntu)

```bash
sudo apt install fpc fp-units-fcl
chmod +x build.sh
./build.sh
```

---

## Option C: cross-compile from Linux (AlmaLinux / Rocky / RHEL)

The EPEL `fpc` package only ships Linux RTL, so the win64 cross-RTL
must be built once locally. The procedure is identical to the P3A
plugin's:

```bash
# 1) Install toolchain
sudo dnf install -y epel-release make
sudo dnf config-manager --set-enabled powertools     # AlmaLinux 8
# sudo dnf config-manager --set-enabled crb          # AlmaLinux 9
sudo dnf install -y fpc fpc-src

# 2) Build win64 cross-RTL once (skip if you already did this for
#    the P3A plugin — same FPC, same RTL)
cp -r /usr/share/fpcsrc /tmp/fpcsrc
cd /tmp/fpcsrc/rtl
make clean all install \
    OS_TARGET=win64 CPU_TARGET=x86_64 \
    BINUTILSPREFIX=x86_64-w64-mingw32- \
    INSTALL_BASEDIR=/usr/lib64/fpc/3.2.0

# 3) Build the plugin
cd /path/to/pac_wcx_source
./build.sh
```

You don't need MinGW-w64 GCC for this plugin (FPAC has no compression).

---

## Verifying

After build, list DLL exports:

```bash
x86_64-w64-mingw32-objdump -p pac.wcx64 | grep -A 25 "\[Ordinal/Name"
```

Should show all 19 WCX entry points (CanYouHandleThisFile,
CanYouHandleThisFileW, CloseArchive, DeleteFiles, DeleteFilesW,
GetPackerCaps, OpenArchive, OpenArchiveW, PackFiles, PackFilesW,
ProcessFile, ProcessFileW, ReadHeader, ReadHeaderEx, ReadHeaderExW,
SetChangeVolProc, SetChangeVolProcW, SetProcessDataProc,
SetProcessDataProcW).

## Tests (optional)

```bash
cd tests
fpc -O2 -Fu../src testcrc32pac.pas    # CRC32 against known hashes
fpc -O2 -Fu../src testpac.pas          # round-trip a PAC file
fpc -O2 -Fu../src testpacfull.pas      # content-identity after round-trip
./testcrc32pac
./testpac /path/to/some.pac /tmp/out.pac
./testpacfull /path/to/some.pac /tmp/out.pac
```
