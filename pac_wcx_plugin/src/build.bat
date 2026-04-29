@echo off
REM ===================================================================
REM   Build script for the PAC WCX plugin (Windows native build)
REM
REM   Requires:
REM     - Free Pascal Compiler 3.2.2+ (fpc.exe in PATH or specified below)
REM
REM   Output: pac.wcx64 in this directory
REM ===================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

if "%FPC%"=="" set FPC=fpc

echo.
echo === Compiling Pascal plugin ===
echo.
cd src
%FPC% -O2 -CX -XX pac_wcx.pas -opac.wcx64
set FPCERR=%errorlevel%
cd ..
if not "%FPCERR%"=="0" (
    echo.
    echo ERROR: Pascal compilation failed
    echo Make sure Free Pascal 3.2.2+ for Win64 is installed and fpc.exe is in PATH.
    exit /b 1
)

if exist src\pac.wcx64 move /Y src\pac.wcx64 . > nul

echo.
echo === Done ===
echo.
echo Output: pac.wcx64
dir /B pac.wcx64

del /Q src\*.ppu 2>nul
del /Q src\*.o 2>nul
del /Q src\*.or 2>nul

exit /b 0
