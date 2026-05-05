# =============================================================================
#  TBLViewer Makefile
# =============================================================================
#  Cross-compiles 32-bit and 64-bit Win64 DLLs (tblviewer.wlx /
#  tblviewer.wlx64) from a Linux host using mingw-w64 toolchains.
#  Native Windows builds work too via MSYS2 — see build-windows.bat.
# =============================================================================

CXX32 := i686-w64-mingw32-g++
CXX64 := x86_64-w64-mingw32-g++
CC32  := i686-w64-mingw32-gcc
CC64  := x86_64-w64-mingw32-gcc

CXXFLAGS := -O2 -s -std=c++17 -Wall -Wextra -Wno-unused-parameter \
            -static-libgcc -static-libstdc++ \
            -DUNICODE -D_UNICODE \
            -DWINVER=0x0600 -D_WIN32_WINNT=0x0600

# zstd's bundled C decoder generates a few signed/unsigned warnings on
# old mingw — silence them so the build log stays readable.
CFLAGS := -O2 -s -std=c99 -w \
          -DZSTD_DISABLE_ASM=1 -DZSTD_LEGACY_SUPPORT=0

LDFLAGS := -shared -Wl,--enable-stdcall-fixup -Wl,--kill-at \
           -static -static-libgcc -static-libstdc++

LIBS := -lcomctl32 -lshlwapi -luser32 -lkernel32 -lgdi32 -ladvapi32 \
        -lshell32 -lcomdlg32 -lole32

CPP_SRCS := tblviewer.cpp tbl_file.cpp tbl_types.cpp schemas.cpp \
            ini_settings.cpp grid_view.cpp \
            json.cpp blowfish.cpp cle.cpp crc32.cpp
C_SRCS   := zstd/zstddeclib.c

.PHONY: all clean

all: tblviewer.wlx tblviewer.wlx64 plugin

tblviewer.wlx: $(CPP_SRCS) $(C_SRCS) tblviewer.def
	$(CC32) $(CFLAGS) -c zstd/zstddeclib.c -o zstddeclib_32.o
	$(CXX32) $(CXXFLAGS) $(CPP_SRCS) zstddeclib_32.o tblviewer.def \
	    -o tblviewer.wlx $(LDFLAGS) $(LIBS)
	rm -f zstddeclib_32.o

tblviewer.wlx64: $(CPP_SRCS) $(C_SRCS) tblviewer.def
	$(CC64) $(CFLAGS) -c zstd/zstddeclib.c -o zstddeclib_64.o
	$(CXX64) $(CXXFLAGS) $(CPP_SRCS) zstddeclib_64.o tblviewer.def \
	    -o tblviewer.wlx64 $(LDFLAGS) $(LIBS)
	rm -f zstddeclib_64.o

# Plugin install ZIP: pluginst.inf + both DLLs + schemas/ folder.
plugin: tblviewer.wlx tblviewer.wlx64
	rm -f TBLViewer-plugin.zip
	zip -r TBLViewer-plugin.zip pluginst.inf tblviewer.wlx tblviewer.wlx64 \
	    schemas/

clean:
	rm -f tblviewer.wlx tblviewer.wlx64 TBLViewer-plugin.zip *.o
