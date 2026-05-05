#!/usr/bin/env bash
# build-linux.sh
# -----------------------------------------------------------------------------
# One-shot build script for TBLViewer on Linux.
#
# Tested targets:
#   * AlmaLinux 9 / RHEL 9 / Rocky 9 / CentOS Stream 9
#   * AlmaLinux 8 / RHEL 8 / Rocky 8
#   * Fedora 38+
#   * Ubuntu 20.04+ / Debian 11+
#
# What it does:
#   1. Detects the distribution.
#   2. Installs MinGW-w64 cross-compilers (32-bit and 64-bit), make, and zip.
#      On RHEL-family it enables EPEL and CRB/PowerTools first.
#   3. Runs `make all`, producing:
#         tblviewer.wlx          - 32-bit DLL
#         tblviewer.wlx64        - 64-bit DLL
#         TBLViewer-plugin.zip   - Total Commander install package
#
# Run from the source directory:
#     chmod +x build-linux.sh
#     ./build-linux.sh
# -----------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ANSI colors (only if attached to a TTY)
if [ -t 1 ]; then
    C_BLUE=$'\033[1;34m'; C_GREEN=$'\033[1;32m'; C_RED=$'\033[1;31m'
    C_YELLOW=$'\033[1;33m'; C_RESET=$'\033[0m'
else
    C_BLUE=''; C_GREEN=''; C_RED=''; C_YELLOW=''; C_RESET=''
fi

info()  { echo "${C_BLUE}[*]${C_RESET} $*"; }
ok()    { echo "${C_GREEN}[OK]${C_RESET} $*"; }
warn()  { echo "${C_YELLOW}[!]${C_RESET} $*"; }
fail()  { echo "${C_RED}[X]${C_RESET} $*" >&2; exit 1; }

# -----------------------------------------------------------------------------
# 1. Detect distribution
# -----------------------------------------------------------------------------
DISTRO=""
DISTRO_VERSION=""

if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    DISTRO_ID="${ID:-}"
    DISTRO_LIKE="${ID_LIKE:-}"
    DISTRO_VERSION="${VERSION_ID:-}"

    case "$DISTRO_ID" in
        almalinux|rhel|rocky|centos|fedora)
            DISTRO="rhel"
            ;;
        debian|ubuntu)
            DISTRO="debian"
            ;;
        *)
            # Fall back to ID_LIKE
            case "$DISTRO_LIKE" in
                *rhel*|*fedora*) DISTRO="rhel" ;;
                *debian*)        DISTRO="debian" ;;
            esac
            ;;
    esac
fi

[ -n "$DISTRO" ] || fail "Unsupported distribution. Please install MinGW-w64 manually."

info "Detected: ${DISTRO_ID:-unknown} ${DISTRO_VERSION} (family: ${DISTRO})"

# -----------------------------------------------------------------------------
# 2. Install dependencies
# -----------------------------------------------------------------------------
need_install=0
for cmd in i686-w64-mingw32-g++ x86_64-w64-mingw32-g++ make zip; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        need_install=1
        warn "Missing: $cmd"
    fi
done

# Pick sudo only if we're not root
if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo"
    command -v sudo >/dev/null 2>&1 || fail "sudo not available and not running as root."
fi

if [ "$need_install" -eq 1 ]; then
    info "Installing build dependencies..."

    if [ "$DISTRO" = "rhel" ]; then
        # Need EPEL for the mingw* packages.
        $SUDO dnf install -y epel-release || \
            $SUDO yum install -y epel-release || \
            fail "Failed to install epel-release."

        # CRB (RHEL 9 / Alma 9) or PowerTools (RHEL 8 / Alma 8) is needed
        # for some build dependencies of mingw packages.
        if command -v dnf >/dev/null 2>&1; then
            # Try config-manager plugin; install if missing
            $SUDO dnf -y install dnf-plugins-core >/dev/null 2>&1 || true

            $SUDO dnf config-manager --set-enabled crb 2>/dev/null \
                || $SUDO dnf config-manager --set-enabled powertools 2>/dev/null \
                || $SUDO dnf config-manager --set-enabled PowerTools 2>/dev/null \
                || warn "Could not enable CRB/PowerTools; if mingw packages fail to install, enable it manually."

            $SUDO dnf install -y \
                mingw32-gcc-c++ mingw64-gcc-c++ \
                mingw32-winpthreads-static mingw64-winpthreads-static \
                make zip \
                || fail "dnf install failed. See messages above."
        else
            $SUDO yum install -y \
                mingw32-gcc-c++ mingw64-gcc-c++ \
                mingw32-winpthreads-static mingw64-winpthreads-static \
                make zip \
                || fail "yum install failed. See messages above."
        fi

    elif [ "$DISTRO" = "debian" ]; then
        $SUDO apt-get update
        $SUDO apt-get install -y \
            mingw-w64 \
            g++-mingw-w64-i686 \
            g++-mingw-w64-x86-64 \
            make zip \
            || fail "apt-get install failed. See messages above."
    fi

    ok "Dependencies installed."
else
    ok "All build dependencies already present."
fi

# Sanity check
for cmd in i686-w64-mingw32-g++ x86_64-w64-mingw32-g++ make zip; do
    command -v "$cmd" >/dev/null 2>&1 || fail "Required tool still missing after install: $cmd"
done

# -----------------------------------------------------------------------------
# 3. Compile
# -----------------------------------------------------------------------------
info "Cleaning previous build..."
make clean >/dev/null 2>&1 || true

info "Compiling 32-bit and 64-bit DLLs and packaging..."
make all

echo
ok "Build successful."
echo
echo "Artifacts:"
ls -lh tblviewer.wlx tblviewer.wlx64 TBLViewer-plugin.zip 2>/dev/null
echo
echo "To install in Total Commander:"
echo "  1. Copy TBLViewer-plugin.zip to a Windows machine running Total Commander."
echo "  2. In TC, click the ZIP - TC will offer to install the plugin."
echo "     (Or drag pluginst.inf out of the ZIP onto a TC window.)"
