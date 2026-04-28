library p3a_wcx;

{$mode objfpc}{$H+}

// Total Commander WCX packer plugin for Falcom P3A archives
// (Kuro no Kiseki / Trails through Daybreak engine).
//
// Read-only support:
//   - Open .p3a, browse contents in TC like a directory.
//   - Extract single files / whole directories.
//   - Compression types supported: 0 (none), 1 (lz4).
//   - Compression types reported but not supported: 2 (zstd), 3 (zstd-dict).
//
// Capabilities reported: PK_CAPS_BY_CONTENT only -- TC will probe by
// the 'PH3ARCV\0' magic instead of relying on the file extension.

uses
  Windows, SysUtils, Classes, p3alib;

const
  // GetPackerCaps flag bits
  PK_CAPS_NEW         = 1;
  PK_CAPS_MODIFY      = 2;
  PK_CAPS_MULTIPLE    = 4;
  PK_CAPS_DELETE      = 8;
  PK_CAPS_OPTIONS     = 16;
  PK_CAPS_MEMPACK     = 32;
  PK_CAPS_BY_CONTENT  = 64;
  PK_CAPS_SEARCHTEXT  = 128;
  PK_CAPS_HIDE        = 4096;
  PK_CAPS_ENCRYPT     = 8192;

  // ProcessFile operations
  PK_SKIP    = 0;
  PK_TEST    = 1;
  PK_EXTRACT = 2;

  // OpenArchiveData modes
  PK_OM_LIST    = 0;
  PK_OM_EXTRACT = 1;

  // Error codes
  E_END_ARCHIVE = 10;
  E_NO_MEMORY   = 11;
  E_BAD_DATA    = 12;
  E_BAD_ARCHIVE = 13;
  E_UNKNOWN_FORMAT = 14;
  E_EOPEN       = 15;
  E_ECREATE     = 16;
  E_ECLOSE      = 17;
  E_EREAD       = 18;
  E_EWRITE      = 19;
  E_NOT_SUPPORTED = 24;

  // Header data Flags bits
  RHDF_DIRECTORY = $40;  // entry is a directory

type
  TOpenArchiveData = record
    ArcName: PAnsiChar;
    OpenMode: Integer;
    OpenResult: Integer;
    CmtBuf: PAnsiChar;
    CmtBufSize: Integer;
    CmtSize: Integer;
    CmtState: Integer;
  end;
  POpenArchiveData = ^TOpenArchiveData;

  // Wide variant (TC sends Unicode paths via *W functions).
  TOpenArchiveDataW = record
    ArcName: PWideChar;
    OpenMode: Integer;
    OpenResult: Integer;
    CmtBuf: PWideChar;
    CmtBufSize: Integer;
    CmtSize: Integer;
    CmtState: Integer;
  end;
  POpenArchiveDataW = ^TOpenArchiveDataW;

  THeaderDataExA = record
    ArcName:     array[0..1023] of AnsiChar;
    FileName:    array[0..1023] of AnsiChar;
    Flags:       LongInt;
    PackSize:    LongInt;        // low 32 bits
    PackSizeHigh:LongInt;        // high 32 bits
    UnpSize:     LongInt;
    UnpSizeHigh: LongInt;
    HostOS:      LongInt;
    FileCRC:     LongInt;
    FileTime:    LongInt;
    UnpVer:      LongInt;
    Method:      LongInt;
    FileAttr:    LongInt;
    CmtBuf:      PAnsiChar;
    CmtBufSize:  Integer;
    CmtSize:     Integer;
    CmtState:    Integer;
  end;

  THeaderDataExW = record
    ArcName:     array[0..1023] of WideChar;
    FileName:    array[0..1023] of WideChar;
    Flags:       LongInt;
    PackSize:    LongInt;
    PackSizeHigh:LongInt;
    UnpSize:     LongInt;
    UnpSizeHigh: LongInt;
    HostOS:      LongInt;
    FileCRC:     LongInt;
    FileTime:    LongInt;
    UnpVer:      LongInt;
    Method:      LongInt;
    FileAttr:    LongInt;
    CmtBuf:      PAnsiChar;       // intentionally PAnsi -- comments stay ANSI
    CmtBufSize:  Integer;
    CmtSize:     Integer;
    CmtState:    Integer;
  end;

  // Per-archive handle returned to TC.
  PArcHandle = ^TArcHandle;
  TArcHandle = record
    Archive: TP3AArchive;
    CurrentIndex: Integer;       // last index returned by ReadHeader (-1 = before-first)
  end;

  TProcessDataProc  = function (FileName: PAnsiChar;  Size: Integer): Integer; stdcall;
  TProcessDataProcW = function (FileName: PWideChar;  Size: Integer): Integer; stdcall;

var
  GProcessDataProc:  TProcessDataProc  = nil;
  GProcessDataProcW: TProcessDataProcW = nil;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// TC expects backslashes in archive entry paths on Windows.
function ToWinPath(const S: AnsiString): AnsiString;
var i: Integer;
begin
  Result := S;
  for i := 1 to Length(Result) do
    if Result[i] = '/' then Result[i] := '\';
end;

procedure StoreAnsiPath(var Dst: array of AnsiChar; const Src: AnsiString; MaxLen: Integer);
var L, i: Integer;
begin
  L := Length(Src);
  if L >= MaxLen then L := MaxLen - 1;
  for i := 0 to L - 1 do Dst[i] := Src[i + 1];
  Dst[L] := #0;
end;

procedure StoreWidePath(var Dst: array of WideChar; const Src: AnsiString; MaxLen: Integer);
var W: WideString; L, i: Integer;
begin
  W := UTF8Decode(Src);
  L := Length(W);
  if L >= MaxLen then L := MaxLen - 1;
  for i := 0 to L - 1 do Dst[i] := W[i + 1];
  Dst[L] := #0;
end;

function OpenP3A(const FileName: AnsiString; out Reason: Integer): PArcHandle;
begin
  Result := nil;
  Reason := 0;
  try
    New(Result);
    Result^.Archive := TP3AArchive.Create(FileName);
    Result^.CurrentIndex := -1;
  except
    on E: Exception do
    begin
      if Result <> nil then Dispose(Result);
      Result := nil;
      Reason := E_BAD_ARCHIVE;
    end;
  end;
end;

// ---------------------------------------------------------------------------
// WCX API
// ---------------------------------------------------------------------------

function OpenArchive(var ArchiveData: TOpenArchiveData): THandle; stdcall;
var
  H: PArcHandle;
  Reason: Integer;
begin
  H := OpenP3A(AnsiString(ArchiveData.ArcName), Reason);
  if H = nil then
  begin
    ArchiveData.OpenResult := Reason;
    Result := 0;
    Exit;
  end;
  ArchiveData.OpenResult := 0;
  Result := THandle(H);
end;

function OpenArchiveW(var ArchiveData: TOpenArchiveDataW): THandle; stdcall;
var
  H: PArcHandle;
  Reason: Integer;
  AName: AnsiString;
begin
  AName := UTF8Encode(WideString(ArchiveData.ArcName));
  H := OpenP3A(AName, Reason);
  if H = nil then
  begin
    ArchiveData.OpenResult := Reason;
    Result := 0;
    Exit;
  end;
  ArchiveData.OpenResult := 0;
  Result := THandle(H);
end;

function ReadHeaderEx(hArcData: THandle; var HeaderData: THeaderDataExA): Integer; stdcall;
var
  H: PArcHandle;
  E: TP3AEntry;
begin
  H := PArcHandle(hArcData);
  Inc(H^.CurrentIndex);
  if H^.CurrentIndex >= Length(H^.Archive.Entries) then
  begin
    Result := E_END_ARCHIVE;
    Exit;
  end;
  E := H^.Archive.Entries[H^.CurrentIndex];

  FillChar(HeaderData, SizeOf(HeaderData), 0);
  StoreAnsiPath(HeaderData.FileName, ToWinPath(E.Name), 1024);

  HeaderData.PackSize     := LongInt(E.CmpSize and $FFFFFFFF);
  HeaderData.PackSizeHigh := LongInt((E.CmpSize shr 32) and $FFFFFFFF);
  HeaderData.UnpSize      := LongInt(E.UncSize and $FFFFFFFF);
  HeaderData.UnpSizeHigh  := LongInt((E.UncSize shr 32) and $FFFFFFFF);

  HeaderData.HostOS  := 0;
  HeaderData.Method  := Integer(E.CmpType);
  HeaderData.FileTime := 0;
  HeaderData.FileAttr := 0;

  Result := 0;
end;

function ReadHeaderExW(hArcData: THandle; var HeaderData: THeaderDataExW): Integer; stdcall;
var
  H: PArcHandle;
  E: TP3AEntry;
begin
  H := PArcHandle(hArcData);
  Inc(H^.CurrentIndex);
  if H^.CurrentIndex >= Length(H^.Archive.Entries) then
  begin
    Result := E_END_ARCHIVE;
    Exit;
  end;
  E := H^.Archive.Entries[H^.CurrentIndex];

  FillChar(HeaderData, SizeOf(HeaderData), 0);
  StoreWidePath(HeaderData.FileName, ToWinPath(E.Name), 1024);

  HeaderData.PackSize     := LongInt(E.CmpSize and $FFFFFFFF);
  HeaderData.PackSizeHigh := LongInt((E.CmpSize shr 32) and $FFFFFFFF);
  HeaderData.UnpSize      := LongInt(E.UncSize and $FFFFFFFF);
  HeaderData.UnpSizeHigh  := LongInt((E.UncSize shr 32) and $FFFFFFFF);

  HeaderData.HostOS  := 0;
  HeaderData.Method  := Integer(E.CmpType);
  HeaderData.FileTime := 0;
  HeaderData.FileAttr := 0;

  Result := 0;
end;

// Older non-extended ReadHeader -- TC may still call it for some operations.
function ReadHeader(hArcData: THandle; HeaderData: PPointer): Integer; stdcall;
type
  THeaderDataA = record
    ArcName:    array[0..259] of AnsiChar;
    FileName:   array[0..259] of AnsiChar;
    Flags:      LongInt;
    PackSize:   LongInt;
    UnpSize:    LongInt;
    HostOS:     LongInt;
    FileCRC:    LongInt;
    FileTime:   LongInt;
    UnpVer:     LongInt;
    Method:     LongInt;
    FileAttr:   LongInt;
    CmtBuf:     PAnsiChar;
    CmtBufSize: Integer;
    CmtSize:    Integer;
    CmtState:   Integer;
  end;
  PHeaderDataA = ^THeaderDataA;
var
  H: PArcHandle;
  E: TP3AEntry;
  HD: PHeaderDataA;
begin
  HD := PHeaderDataA(HeaderData);
  H := PArcHandle(hArcData);
  Inc(H^.CurrentIndex);
  if H^.CurrentIndex >= Length(H^.Archive.Entries) then
  begin
    Result := E_END_ARCHIVE;
    Exit;
  end;
  E := H^.Archive.Entries[H^.CurrentIndex];

  FillChar(HD^, SizeOf(HD^), 0);
  StoreAnsiPath(HD^.FileName, ToWinPath(E.Name), 260);

  // Cap to 32-bit -- this struct doesn't have a high-32 part. For files
  // bigger than ~2 GB TC should call ReadHeaderEx anyway.
  if E.CmpSize > MaxInt then HD^.PackSize := MaxInt
  else HD^.PackSize := LongInt(E.CmpSize);
  if E.UncSize > MaxInt then HD^.UnpSize := MaxInt
  else HD^.UnpSize := LongInt(E.UncSize);

  HD^.Method := Integer(E.CmpType);
  Result := 0;
end;

function ProcessFile(hArcData: THandle; Operation: Integer;
                     DestPath, DestName: PAnsiChar): Integer; stdcall;
var
  H: PArcHandle;
  E: TP3AEntry;
  Buf: PByte;
  Full: AnsiString;
  F: TFileStream;
  Aborted: Boolean;
  Cont: Integer;
begin
  H := PArcHandle(hArcData);

  if (H^.CurrentIndex < 0) or (H^.CurrentIndex >= Length(H^.Archive.Entries)) then
  begin
    Result := E_BAD_DATA;
    Exit;
  end;

  if Operation = PK_SKIP then begin Result := 0; Exit; end;

  E := H^.Archive.Entries[H^.CurrentIndex];

  // ZSTD compression is reported but not implemented in this build.
  if not (E.CmpType in [0, 1]) then
  begin
    Result := E_NOT_SUPPORTED;
    Exit;
  end;

  Buf := nil;
  if E.UncSize > 0 then GetMem(Buf, E.UncSize);
  try
    if not H^.Archive.ExtractEntry(H^.CurrentIndex, Buf, E.UncSize) then
    begin
      Result := E_BAD_DATA;
      Exit;
    end;

    // Notify TC we processed UncSize bytes (used for the progress bar).
    Aborted := False;
    if Assigned(GProcessDataProcW) then
    begin
      Cont := GProcessDataProcW(nil, LongInt(E.UncSize and $FFFFFFFF));
      if Cont = 0 then Aborted := True;
    end
    else if Assigned(GProcessDataProc) then
    begin
      Cont := GProcessDataProc(nil, LongInt(E.UncSize and $FFFFFFFF));
      if Cont = 0 then Aborted := True;
    end;
    if Aborted then begin Result := E_EWRITE; Exit; end;

    if Operation = PK_TEST then begin Result := 0; Exit; end;

    // PK_EXTRACT: write the buffer to disk.
    if DestPath <> nil then
      Full := AnsiString(DestPath) + AnsiString(DestName)
    else
      Full := AnsiString(DestName);
    ForceDirectories(ExtractFilePath(Full));

    try
      F := TFileStream.Create(Full, fmCreate);
      try
        if E.UncSize > 0 then F.WriteBuffer(Buf^, E.UncSize);
      finally
        F.Free;
      end;
    except
      Result := E_EWRITE;
      Exit;
    end;

    Result := 0;
  finally
    if Buf <> nil then FreeMem(Buf);
  end;
end;

function ProcessFileW(hArcData: THandle; Operation: Integer;
                      DestPath, DestName: PWideChar): Integer; stdcall;
var
  PA, NA: AnsiString;
begin
  if DestPath <> nil then PA := UTF8Encode(WideString(DestPath)) else PA := '';
  if DestName <> nil then NA := UTF8Encode(WideString(DestName)) else NA := '';
  if PA <> '' then
    Result := ProcessFile(hArcData, Operation, PAnsiChar(PA), PAnsiChar(NA))
  else
    Result := ProcessFile(hArcData, Operation, nil, PAnsiChar(NA));
end;

function CloseArchive(hArcData: THandle): Integer; stdcall;
var H: PArcHandle;
begin
  H := PArcHandle(hArcData);
  if H <> nil then
  begin
    if H^.Archive <> nil then H^.Archive.Free;
    Dispose(H);
  end;
  Result := 0;
end;

procedure SetChangeVolProc(hArcData: THandle; pChangeVolProc: Pointer); stdcall;
begin
  // No multi-volume support, ignore.
end;

procedure SetChangeVolProcW(hArcData: THandle; pChangeVolProc: Pointer); stdcall;
begin
  // No multi-volume support, ignore.
end;

procedure SetProcessDataProc(hArcData: THandle; pProc: TProcessDataProc); stdcall;
begin
  GProcessDataProc := pProc;
end;

procedure SetProcessDataProcW(hArcData: THandle; pProc: TProcessDataProcW); stdcall;
begin
  GProcessDataProcW := pProc;
end;

function GetPackerCaps: Integer; stdcall;
begin
  // PK_CAPS_BY_CONTENT lets TC detect P3A by magic bytes regardless of
  // file extension -- handy for archives renamed to .pak / .dat etc.
  Result := PK_CAPS_BY_CONTENT;
end;

function CanYouHandleThisFile(FileName: PAnsiChar): Boolean; stdcall;
var
  F: file of Byte;
  Magic: array[0..7] of AnsiChar;
  ReadCount: Int64;
  i: Integer;
begin
  Result := False;
  AssignFile(F, AnsiString(FileName));
  {$I-} Reset(F); {$I+}
  if IOResult <> 0 then Exit;
  try
    BlockRead(F, Magic, 8, ReadCount);
    if ReadCount <> 8 then Exit;
    for i := 0 to 7 do
      if Magic[i] <> AnsiChar(PAnsiChar('PH3ARCV'#0)[i]) then Exit;
    Result := True;
  finally
    CloseFile(F);
  end;
end;

function CanYouHandleThisFileW(FileName: PWideChar): Boolean; stdcall;
var
  AName: AnsiString;
begin
  AName := UTF8Encode(WideString(FileName));
  Result := CanYouHandleThisFile(PAnsiChar(AName));
end;

exports
  OpenArchive,
  OpenArchiveW,
  ReadHeader,
  ReadHeaderEx,
  ReadHeaderExW,
  ProcessFile,
  ProcessFileW,
  CloseArchive,
  SetChangeVolProc,
  SetChangeVolProcW,
  SetProcessDataProc,
  SetProcessDataProcW,
  GetPackerCaps,
  CanYouHandleThisFile,
  CanYouHandleThisFileW;

begin
end.
