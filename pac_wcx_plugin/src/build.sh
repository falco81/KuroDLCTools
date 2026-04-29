#!/bin/bash
# =====================================================================
# Cross-compile the PAC WCX plugin from Linux to Windows x64.
#
# Requires:
#   - Free Pascal Compiler 3.2.2+ with Win64 cross-compile target
#     (Debian/Ubuntu: apt install fpc fp-units-fcl)
#
# Output: pac.wcx64 in this directory
# =====================================================================

set -e
cd "$(dirname "$0")"

FPC="${FPC:-fpc}"

echo
echo "=== Cross-compiling Pascal plugin to Win64 ==="
echo
cd src
"$FPC" -Twin64 -Px86_64 -O2 -CX -XX pac_wcx.pas -opac.wcx64
cd ..
mv src/pac.wcx64 .

# Clean intermediate files
rm -f src/*.ppu src/*.o src/*.or

echo
echo "=== Done ==="
echo
ls -la pac.wcx64
file pac.wcx64
