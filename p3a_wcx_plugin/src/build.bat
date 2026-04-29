@echo off
REM ===================================================================
REM   Build script for the P3A WCX plugin (Windows native build)
REM
REM   Requires:
REM     - Free Pascal Compiler 3.2.2+ (fpc.exe in PATH or specified below)
REM     - MinGW-w64 GCC (x86_64-w64-mingw32-gcc, gcc.exe, or similar)
REM
REM   Output: p3a.wcx64 in this directory
REM ===================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

REM --- Configure tools (override here if needed) ---
if "%FPC%"=="" set FPC=fpc
if "%CC%"==""  set CC=gcc

echo.
echo === [1/2] Compiling LZ4 reference C implementation ===
echo.
%CC% -c -O3 -o src\lz4obj.o src\lz4\lz4.c
if errorlevel 1 (
    echo.
    echo ERROR: failed to compile src\lz4\lz4.c
    echo Make sure you have MinGW-w64 GCC installed and in PATH,
    echo or set CC environment variable to your C compiler:
    echo     set CC=x86_64-w64-mingw32-gcc
    echo     build.bat
    exit /b 1
)

echo.
echo === [2/2] Compiling Pascal plugin ===
echo.
cd src
%FPC% -O2 -CX -XX p3a_wcx.pas -op3a.wcx64
set FPCERR=%errorlevel%
cd ..
if not "%FPCERR%"=="0" (
    echo.
    echo ERROR: Pascal compilation failed
    echo Make sure Free Pascal 3.2.2+ for Win64 is installed and fpc.exe is in PATH.
    exit /b 1
)

if exist src\p3a.wcx64 move /Y src\p3a.wcx64 . > nul

echo.
echo === Done ===
echo.
echo Output: p3a.wcx64
dir /B p3a.wcx64

REM Clean up intermediate files
del /Q src\lz4obj.o 2>nul
del /Q src\*.ppu 2>nul
del /Q src\*.o 2>nul
del /Q src\*.or 2>nul

exit /b 0
