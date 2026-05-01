# Building from source

This document covers building `tbl_wlx.wlx64` from the source ZIP on
Linux (cross-compiling to Windows). Building natively on Windows is
also possible with FPC for Windows installed, but is not covered here.

The build is a Linux → Win64 cross-compile that produces a single
`tbl_wlx.wlx64` PE32+ DLL plus the `schemas/` folder. The script
`build.sh` is self-checking and will bootstrap any missing Win64 cross
units automatically.

---

## 1. Prerequisites

You need three things:

1. **Free Pascal Compiler 3.2.x** with the x86_64-win64 cross-target.
2. **MinGW-w64 GCC** for compiling the ZSTD reference C implementation
   to a Win64 object file.
3. **FPC source tree** — needed because the plugin uses fcl-base /
   fcl-json which are pre-built only for the host platform on most
   distributions, and may also be needed to bootstrap Win64 RTL.

How you get each depends on your distribution. Two paths are documented
below: the easy one (Debian/Ubuntu, where everything is in apt) and the
manual one (AlmaLinux/RHEL/Fedora and similar, where FPC has to be
installed by hand).

---

## 2. Debian / Ubuntu

```bash
sudo apt update
sudo apt install fpc fp-units-fcl fp-compiler-source gcc-mingw-w64-x86-64
```

That's everything. FPC includes Win64 cross-units in the package, and
the source tree lives in `/usr/share/fpcsrc/<version>/`.

Build:

```bash
unzip tbl_wlx_v1.x.x_source.zip
cd tbl_wlx_v1.x.x_source
chmod +x build.sh
./build.sh
```

Output: `tbl_wlx.wlx64` (~750 KB) plus `schemas/` and `pluginst.inf`,
ready to zip and install in Total Commander.

---

## 3. AlmaLinux / RHEL / Fedora — manual install

AlmaLinux 8 / 9 doesn't ship FPC in dnf. The MinGW cross-compiler is in
EPEL. You'll need to install FPC from the upstream tarball.

This is the **exact** procedure that was used to verify the build works
on AlmaLinux 8 (April 2026).

### 3.1 Install MinGW cross-compiler

```bash
sudo dnf install epel-release -y
sudo dnf install mingw64-gcc -y

# Verify
x86_64-w64-mingw32-gcc --version
```

### 3.2 Install FPC

The upstream Linux tarball's `install.sh` has a known bug with
interactive prompts in some shells. Use this incantation:

```bash
cd /opt
wget https://downloads.freepascal.org/fpc/dist/3.2.2/x86_64-linux/fpc-3.2.2.x86_64-linux.tar
tar xf fpc-3.2.2.x86_64-linux.tar
cd fpc-3.2.2.x86_64-linux

# Pre-feed the install prompts. Three lines = three answers:
#   line 1: install prefix
#   line 2: 'n' = skip docs
#   line 3: 'n' = skip demos
printf "/opt/fpc-3.2.2\nn\nn\n" | sudo ./install.sh
```

If the install **completes silently** (no `gtar: Cannot open` errors),
you're good. If you see those errors, your shell ate the prompts; fall
back to running `./install.sh` and typing `/opt/fpc-3.2.2` followed by
**Enter**, then `n` Enter, then `n` Enter.

Verify:

```bash
ls /opt/fpc-3.2.2/lib/fpc/3.2.2/
# Expected: fpmkinst  ide  msg  ppcx64  samplecfg  units
```

### 3.3 Add FPC to PATH

The installer doesn't symlink into PATH on its own.

```bash
sudo ln -sf /opt/fpc-3.2.2/bin/fpc    /usr/local/bin/fpc
sudo ln -sf /opt/fpc-3.2.2/bin/ppcx64 /usr/local/bin/ppcx64

# Refresh bash command cache (only needed if you had old fpc earlier):
hash -r

fpc -iV
# Expected: 3.2.2
```

### 3.4 Generate /etc/fpc.cfg

```bash
sudo /opt/fpc-3.2.2/lib/fpc/3.2.2/samplecfg /opt/fpc-3.2.2/lib/fpc/3.2.2 /etc
```

The "Could not find libgcc" warnings are harmless on a system without
native FPC C bindings — we don't use them for the cross build.

### 3.5 Install FPC source tree

```bash
cd /opt
wget https://downloads.freepascal.org/fpc/dist/3.2.2/source/fpc-3.2.2.source.tar.gz
sudo mkdir -p /usr/share/fpcsrc/3.2.2
sudo tar xzf fpc-3.2.2.source.tar.gz \
             -C /usr/share/fpcsrc/3.2.2 --strip-components=1

# Verify
ls /usr/share/fpcsrc/3.2.2/packages/fcl-json/src/fpjson.pp
```

### 3.6 First build — Win64 RTL gets bootstrapped automatically

```bash
unzip tbl_wlx_v1.x.x_source.zip
cd tbl_wlx_v1.x.x_source
chmod +x build.sh

# The script will detect missing Win64 RTL + winunits-base and
# build them from FPC source. Takes 1-3 minutes the first time;
# subsequent builds reuse the bootstrapped units.
sudo ./build.sh
```

The reason `sudo` is needed on first run is that the bootstrap writes
to `/opt/fpc-3.2.2/lib/fpc/3.2.2/units/x86_64-win64/{rtl,winunits-base}/`.
If you'd rather not run the whole thing as root, pre-create the dirs
and chown them once:

```bash
sudo mkdir -p /opt/fpc-3.2.2/lib/fpc/3.2.2/units/x86_64-win64/{rtl,winunits-base}
sudo chown -R "$USER" /opt/fpc-3.2.2/lib/fpc/3.2.2/units/x86_64-win64/
./build.sh
```

After the first successful build, you can run `./build.sh` as a normal
user — only re-bootstrap (deleting the units dirs) needs write access.

### 3.7 What the bootstrap does internally

For reference, this is what `build.sh` does behind the scenes when it
detects missing units. You don't need to run these by hand.

Build Win64 RTL from source:

```bash
cd /usr/share/fpcsrc/3.2.2/rtl
sudo make all OS_TARGET=win64 CPU_TARGET=x86_64 PP=/usr/local/bin/fpc
# `make install` doesn't work — fpcmake utility isn't in the Linux
# tarball — so we copy units manually:
sudo mkdir -p /opt/fpc-3.2.2/lib/fpc/3.2.2/units/x86_64-win64/rtl
sudo cp /usr/share/fpcsrc/3.2.2/rtl/units/x86_64-win64/*.{ppu,o} \
        /opt/fpc-3.2.2/lib/fpc/3.2.2/units/x86_64-win64/rtl/
```

Build the additional objpas units that aren't part of the rtl Makefile
(`varutils`, `variants`, `strutils`, `dateutils`):

```bash
RTL=/opt/fpc-3.2.2/lib/fpc/3.2.2/units/x86_64-win64/rtl
SRC=/usr/share/fpcsrc/3.2.2/packages/rtl-objpas/src

sudo /usr/local/bin/fpc -Twin64 -O2 -Sh \
  -Fu"$RTL" -FU"$RTL" \
  -Fi"$SRC/inc" \
  "$SRC/win/varutils.pp"

sudo /usr/local/bin/fpc -Twin64 -O2 -Sh \
  -Fu"$RTL" -FU"$RTL" \
  "$SRC/inc/variants.pp"

sudo /usr/local/bin/fpc -Twin64 -O2 -Sh \
  -Fu"$RTL" -FU"$RTL" \
  "$SRC/inc/strutils.pp"
```

Build winunits-base (`commctrl`, `commdlg`, `activex`):

```bash
WUB=/opt/fpc-3.2.2/lib/fpc/3.2.2/units/x86_64-win64/winunits-base
sudo mkdir -p "$WUB"

cd /usr/share/fpcsrc/3.2.2/packages/winunits-base/src

sudo /usr/local/bin/fpc -Twin64 -O2 -Sh \
  -Fu"$RTL" -Fu"$WUB" -FU"$WUB" \
  commdlg.pp

sudo /usr/local/bin/fpc -Twin64 -O2 -Sh \
  -Fu"$RTL" -Fu"$WUB" -FU"$WUB" \
  commctrl.pp     # also pulls in activex automatically
```

After this one-time setup, the build script just compiles the plugin
itself.

---

## 4. Windows (native build)

If you're on Windows itself rather than cross-compiling from Linux,
use `build.bat` from a regular `cmd.exe` prompt. The script is
analogous to `build.sh`: it auto-detects what's installed and
bootstraps anything missing.

### What you need

- **Free Pascal Compiler 3.2.x for Win64.** The easiest way is to
  install [Lazarus IDE](https://www.lazarus-ide.org/), which bundles
  FPC. Alternatively, install FPC standalone from
  [freepascal.org](https://www.freepascal.org/download.html).
- **Internet connection on first build.** `build.bat` will download
  a portable C toolchain (~56 MB) the first time, if you don't
  already have a working `gcc` on your PATH. Subsequent builds use
  the cached copy and need no internet.

That's it. No need to install MinGW separately, no need to mess with
PATH manually beyond making sure `fpc.exe` is reachable.

### Build

Open `cmd.exe`, `cd` into the unzipped source folder, and run:

```cmd
build.bat
```

Output: `tbl_wlx.wlx64` in the current directory.

### What the script does

1. **Locates `fpc.exe`.** Looks at PATH first, then probes a handful
   of common Lazarus install paths (`C:\lazarus\fpc\3.2.2\...`,
   `C:\fpcupdeluxe\...`, `Program Files\Lazarus\...`). Errors out
   with installation instructions if none of those work.
2. **Locates a working `gcc.exe`.** The check is "compile a stub
   that includes `<limits.h>` and `<stddef.h>`." This is necessary
   because FPC ships a stripped-down `cc.exe` that's also called
   `gcc`-like in some bundles but doesn't have stdlib headers, and
   would fail compilation of the ZSTD source.
3. **Bootstraps if needed.** If no working gcc is found, downloads
   [w64devkit](https://github.com/skeeto/w64devkit) (a portable
   mingw-w64 distribution) into `tools\w64devkit\` next to the
   script. The tool is self-extracting; no manual unzipping needed.
   Subsequent builds reuse the cached toolchain.
4. **Compiles ZSTD** to `src\zstdobj_win64.o` via gcc.
5. **Compiles Pascal** plugin via fpc, producing `tbl_wlx.wlx64`.
6. Cleans up intermediate `.ppu` and `.o` files.

### Where things end up

```
.\tbl_wlx.wlx64                  the plugin DLL (~760 KB)
.\schemas\                       363 JSON schema files
.\pluginst.inf                   TC plugin installer manifest
.\tools\w64devkit\               cached portable C toolchain
                                 (~400 MB unpacked; safe to delete
                                 if you have your own gcc)
```

### Troubleshooting Windows builds

**"No include path in which to find limits.h" during step [3/4]**
You have an `fpc-bundled cc.exe` that masquerades as gcc but lacks
stdlib headers. Move that out of PATH, or just delete `tools\` and
re-run — `build.bat` will then download w64devkit and use it instead.

**"curl.exe not found" during w64devkit download**
You're on a Windows version older than 10 1803. Update Windows, or
download w64devkit-x64-2.7.0.7z.exe manually from
[the GitHub releases page](https://github.com/skeeto/w64devkit/releases/tag/v2.7.0)
and place it in the `tools\` folder, then re-run `build.bat`.

**"fpc.exe not found"**
Either Lazarus isn't installed, or it's at a non-standard path. Add
its `bin\x86_64-win64\` directory to PATH and re-run, or install
Lazarus from [lazarus-ide.org](https://www.lazarus-ide.org/).

**Antivirus quarantines `tbl_wlx.wlx64`**
Some AVs flag freshly-built unsigned DLLs. Add an exclusion for the
build output folder, or sign the DLL yourself.

---

## 5. What the build produces

```
tbl_wlx.wlx64        ~750 KB   PE32+ DLL, the actual plugin
schemas/             363 JSONs Falcom TBL section schemas
pluginst.inf                   TC plugin installer manifest
README.md
CHANGELOG.md
TROUBLESHOOTING.md
```

To package for distribution:

```bash
zip -r tbl_wlx_plugin.zip tbl_wlx.wlx64 schemas pluginst.inf \
                          README.md CHANGELOG.md TROUBLESHOOTING.md
```

---

## 6. Installing in Total Commander

1. Copy the ZIP (or its contents) to your TC plugins folder, e.g.
   `%APPDATA%\GHISLER\plugins\wlx\tbl_wlx\`.
2. In TC: **Configuration → Options → Plugins → Lister Plugins → Configure**.
3. **Add** → pick `tbl_wlx.wlx64`.
4. The detect string from `pluginst.inf` is auto-loaded:
   ```
   EXT="TBL" | ([0]=35 & [1]=84 & [2]=66 & [3]=76)
            | ([0]=249 & [1]=186)
            | ([0]=217 & [1]=186)
   ```
5. **OK** and press **F3** on any `.tbl` file.

Or quicker: open the ZIP in TC (Enter on it like a folder), select
`pluginst.inf`, press **Enter**. TC will prompt for confirmation and
install everything for you.

---

## 7. Smoke tests (optional, Linux side only)

`run-tests.sh` builds and runs a regression suite against a corpus of
real TBL files. The tests are Linux ELF binaries (not Win64), so they
need:

- `fcl-base` and `fcl-json` units for **x86_64-linux** (Debian: comes
  with `fp-units-fcl`; AlmaLinux manual install: would need a similar
  bootstrap to what we did for Win64).
- A test corpus — set `CORPUS=/path/to/tbl/files` env var.

```bash
chmod +x run-tests.sh
CORPUS=/path/to/extracted/tbls ./run-tests.sh
```

Expected output: `Result: 14 pass, 0 fail`. Tests are not required for
producing a working DLL — they're a sanity check for code changes.

---

## 8. Troubleshooting

**`error: $FPC not found in PATH`**
> The `fpc` binary is not in your PATH. On manual installs run
> `which fpc`; if empty, `ln -sf /opt/fpc-3.2.2/bin/fpc /usr/local/bin/fpc`
> and `hash -r` to refresh the bash cache.

**`error: cannot locate FPC lib dir for version 3.2.2`**
> Your FPC install is in a non-standard location. Set the env var
> manually: `export FPC_LIB=/your/path/to/lib/fpc/3.2.2`.

**`Fatal: Can't find unit XXX used by YYY`** during plugin build
> A unit dependency wasn't bootstrapped. Common ones (and where to find
> them in FPC source):
>
> | Unit | Source |
> |------|--------|
> | `strutils`, `variants`, `dateutils`, `fmtbcd` | `packages/rtl-objpas/src/inc/` |
> | `varutils` | `packages/rtl-objpas/src/win/` |
> | `commctrl`, `commdlg`, `activex`, `ole2` | `packages/winunits-base/src/` |
> | `fpjson`, `jsonparser`, `jsonscanner`, `jsonreader` | `packages/fcl-json/src/` |
> | `contnrs` | `packages/fcl-base/src/` |
>
> Build the missing one with the pattern shown in section 3.7 above and
> re-run `./build.sh`.

**`Library libimpsysinit.a not found, Linking may fail !`** warning
> Harmless on cross-builds — these are import stubs that linux FPC
> uses only when targeting Linux. The Win64 link still succeeds because
> imports come from MSVCRT and Windows DLLs.

**RTL bootstrap fails with `__missing_command_FPCMAKE: Command not found`**
> The Linux FPC tarball doesn't ship `fpcmake`. The build script handles
> this by skipping `make install` and copying `.ppu`/`.o` files
> manually. If you see this error from `./build.sh`, you've found a bug
> — please report.

**`error: Can't find ppc<arch> compiler binary`**
> Sometimes happens when `/etc/fpc.cfg` was generated for a different
> install. Re-run `samplecfg`:
> `sudo /opt/fpc-3.2.2/lib/fpc/3.2.2/samplecfg /opt/fpc-3.2.2/lib/fpc/3.2.2 /etc`
