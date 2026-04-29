#!/bin/bash
# =====================================================================
# Cross-compile the P3A WCX plugin from Linux to Windows x64.
#
# Requires:
#   - Free Pascal Compiler 3.2.2+ with Win64 cross-compile target
#     (Debian/Ubuntu: apt install fpc fp-units-fcl)
#   - MinGW-w64 GCC (Debian/Ubuntu: apt install gcc-mingw-w64-x86-64)
#
# Output: p3a.wcx64 in this directory
# =====================================================================

set -e
cd "$(dirname "$0")"

CC="${CC:-x86_64-w64-mingw32-gcc}"
FPC="${FPC:-fpc}"

echo
echo "=== [1/3] Cross-compiling LZ4 reference C implementation ==="
echo
"$CC" -c -O3 -o src/lz4obj.o src/lz4/lz4.c

echo
echo "=== [2/3] Cross-compiling ZSTD reference C implementation ==="
echo
"$CC" -c -O2 -DZSTDLIB_VISIBILITY= -DZSTD_DISABLE_ASM \
      -o src/zstdobj.o src/zstd/zstddeclib.c

echo
echo "=== [3/3] Cross-compiling Pascal plugin to Win64 ==="
echo
cd src
"$FPC" -Twin64 -Px86_64 -O2 -CX -XX p3a_wcx.pas -op3a.wcx64
cd ..
mv src/p3a.wcx64 .

# Clean intermediate files
rm -f src/lz4obj.o src/zstdobj.o src/*.ppu src/*.o src/*.or

echo
echo "=== Done ==="
echo
ls -la p3a.wcx64
file p3a.wcx64
