library pac_wcx;

{$mode objfpc}{$H+}

// Total Commander WCX packer plugin for Trails-in-the-Sky FPAC archives.
// Read + write + delete; full feature parity with the sister P3A plugin.

uses
  Windows, SysUtils, Classes,
  paclib;

const
  // GetPackerCaps flag bits
  PK_CAPS_NEW         = 1;
  PK_CAPS_MODIFY      = 2;
  PK_CAPS_MULTIPLE    = 4;
  PK_CAPS_DELETE      = 8;
  PK_CAPS_OPTIONS     = 16;
  PK_CAPS_MEMPACK     = 32;
  PK_CAPS_BY_CONTENT  = 64;

  // ProcessFile operations
  PK_SKIP    = 0;
  PK_TEST    = 1;
  PK_EXTRACT = 2;

  // OpenArchiveData modes
  PK_OM_LIST    = 0;
  PK_OM_EXTRACT = 1;

  // PackFiles flag bits
  PK_PACK_MOVE_FILES = 1;
  PK_PACK_SAVE_PATHS = 2;
  PK_PACK_ENCRYPT    = 4;

  // Error codes returned to TC
  E_END_ARCHIVE   = 10;
  E_NO_MEMORY     = 11;
  E_BAD_DATA      = 12;
  E_BAD_ARCHIVE   = 13;
  E_UNKNOWN_FORMAT= 14;
  E_EOPEN         = 15;
  E_ECREATE       = 16;
  E_ECLOSE        = 17;
  E_EREAD         = 18;
  E_EWRITE        = 19;
  E_NOT_SUPPORTED = 24;

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

  TOpenArchiveDataW = record
    ArcName: PWideChar;
    OpenMode: Integer;
    OpenResult: Integer;
    CmtBuf: PWideChar;
    CmtBufSize: Integer;
    CmtSize: Integer;
    CmtState: Integer;
  end;

  THeaderDataExA = record
    ArcName:     array[0..1023] of AnsiChar;
    FileName:    array[0..1023] of AnsiChar;
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
    CmtBuf:      PAnsiChar;
    CmtBufSize:  Integer;
    CmtSize:     Integer;
    CmtState:    Integer;
  end;

  PArcHandle = ^TArcHandle;
  TArcHandle = record
    Archive: TPACArchive;
    CurrentIndex: Integer;
    DosFileTime: LongInt;          // captured archive mtime, in DOS format
    EmptyDirs: TStringArray;       // sidecar: folders explicitly created via F7
  end;

  TProcessDataProc  = function (FileName: PAnsiChar;  Size: Integer): Integer; stdcall;
  TProcessDataProcW = function (FileName: PWideChar;  Size: Integer): Integer; stdcall;

var
  GProcessDataProc:  TProcessDataProc  = nil;
  GProcessDataProcW: TProcessDataProcW = nil;

// =========================================================================
// Helpers
// =========================================================================

function ToWinPath(const S: AnsiString): AnsiString;
var i: Integer;
begin
  Result := S;
  for i := 1 to Length(Result) do
    if Result[i] = '/' then Result[i] := '\';
end;

function ToUnixPath(const S: AnsiString): AnsiString;
var i: Integer;
begin
  Result := S;
  for i := 1 to Length(Result) do
    if Result[i] = '\' then Result[i] := '/';
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

// Convert TFileTime (UTC FILETIME) to DOS date/time. TC stores timestamps
// in the FAT/DOS format inside its packer-plugin headers.
function FileTimeToDosTime(const FT: TFileTime): LongInt;
var
  LocFT: TFileTime;
  HiW, LoW: Word;
begin
  Result := 0;
  if (FT.dwLowDateTime = 0) and (FT.dwHighDateTime = 0) then Exit;
  if not FileTimeToLocalFileTime(@FT, @LocFT) then Exit;
  if not FileTimeToDosDateTime(@LocFT, @HiW, @LoW) then Exit;
  Result := (LongInt(HiW) shl 16) or LongInt(LoW);
end;

// =====================================================================
// Sidecar file ("<archive>.empty_dirs"): list of folders that the user
// created via F7 inside an archive. P3A format itself can't store empty
// folders, so we keep this metadata next to the .p3a file. The archive
// itself stays format-clean for Python tools and the game.
//
// Sidecar format: plain UTF-8 text, one folder path per line, forward
// slashes, no trailing slash, lowercased. The file is set hidden on
// Windows so it doesn't clutter directory listings.
// =====================================================================

const SidecarSuffix = '.empty_dirs';

function SidecarPathOf(const ArchivePath: AnsiString): AnsiString;
begin
  Result := ArchivePath + SidecarSuffix;
end;

function NormalizeFolder(const S: AnsiString): AnsiString;
begin
  Result := LowerCase(Trim(ToUnixPath(S)));
  while (Result <> '') and (Result[Length(Result)] = '/') do
    SetLength(Result, Length(Result) - 1);
end;

function LoadSidecar(const ArchivePath: AnsiString): TStringArray;
var
  F: TextFile; Line: AnsiString;
begin
  Result := nil;
  if not FileExists(SidecarPathOf(ArchivePath)) then Exit;
  AssignFile(F, SidecarPathOf(ArchivePath));
  {$I-} Reset(F); {$I+}
  if IOResult <> 0 then Exit;
  try
    while not Eof(F) do
    begin
      ReadLn(F, Line);
      Line := NormalizeFolder(Line);
      if Line <> '' then
      begin
        SetLength(Result, Length(Result) + 1);
        Result[High(Result)] := Line;
      end;
    end;
  finally CloseFile(F); end;
end;

procedure SaveSidecar(const ArchivePath: AnsiString; const Dirs: TStringArray);
var
  F: TextFile; i: Integer; Path: AnsiString;
begin
  Path := SidecarPathOf(ArchivePath);
  if Length(Dirs) = 0 then
  begin
    DeleteFile(Path);
    Exit;
  end;
  AssignFile(F, Path);
  {$I-} Rewrite(F); {$I+}
  if IOResult <> 0 then Exit;
  try
    for i := 0 to High(Dirs) do
      WriteLn(F, Dirs[i]);
  finally CloseFile(F); end;
  // Hide the sidecar so it doesn't clutter directory listings.
  SetFileAttributesA(PAnsiChar(Path), FILE_ATTRIBUTE_HIDDEN);
end;

// Add a folder to sidecar list (deduplicated, case-insensitive).
procedure SidecarAdd(var Dirs: TStringArray; const FolderPath: AnsiString);
var i: Integer; N: AnsiString;
begin
  N := NormalizeFolder(FolderPath);
  if N = '' then Exit;
  for i := 0 to High(Dirs) do
    if Dirs[i] = N then Exit;     // already present
  SetLength(Dirs, Length(Dirs) + 1);
  Dirs[High(Dirs)] := N;
end;

procedure SidecarRemoveExact(var Dirs: TStringArray; const FolderPath: AnsiString);
var i: Integer; N: AnsiString;
begin
  N := NormalizeFolder(FolderPath);
  for i := 0 to High(Dirs) do
    if Dirs[i] = N then
    begin
      Dirs[i] := Dirs[High(Dirs)];
      SetLength(Dirs, Length(Dirs) - 1);
      Exit;
    end;
end;

// When a real file is added at FilePath, walk up its ancestors and
// remove any matching folder entries from sidecar — the folder is no
// longer empty, no need to remember it virtually.
procedure SidecarRemoveAncestors(var Dirs: TStringArray; const FilePath: AnsiString);
var P: AnsiString; j: Integer;
begin
  P := NormalizeFolder(FilePath);
  while True do
  begin
    j := -1;
    for j := Length(P) downto 1 do
      if P[j] = '/' then Break;
    if j < 1 then Exit;
    P := Copy(P, 1, j - 1);
    if P = '' then Exit;
    SidecarRemoveExact(Dirs, P);
  end;
end;

// .p3a_keep is the marker file we use to make empty folders visible
// (P3A format has no folder entries). We hide it from listings: any
// archive entry ending with "/.p3a_keep" is presented to TC as a
// directory entry instead, with FILE_ATTRIBUTE_DIRECTORY set.
const KeepMarker = '/.p3a_keep';

function IsKeepMarker(const Name: AnsiString): Boolean;
var L: Integer;
begin
  L := Length(KeepMarker);
  Result := (Length(Name) >= L)
            and (LowerCase(Copy(Name, Length(Name) - L + 1, L)) = KeepMarker);
end;

// Strip trailing "/.p3a_keep", convert to Win-style path, append backslash
// so TC reads it as a directory entry. Returns '' for malformed markers.
function MarkerToDirPath(const Name: AnsiString): AnsiString;
var Stripped: AnsiString;
begin
  Result := '';
  if not IsKeepMarker(Name) then Exit;
  Stripped := Copy(Name, 1, Length(Name) - Length(KeepMarker));
  if Stripped = '' then Exit;
  Result := ToWinPath(Stripped) + '\';
end;

// Parse a double-null-terminated list (e.g. "a\0b\0\0") into a string array.
function ParseDoubleNullList(P: PAnsiChar): TStringArray;
var
  Start: PAnsiChar;
  Cnt: Integer;
begin
  Result := nil;
  if P = nil then Exit;
  Cnt := 0;
  while P^ <> #0 do
  begin
    Start := P;
    while P^ <> #0 do Inc(P);
    SetLength(Result, Cnt + 1);
    SetString(Result[Cnt], Start, P - Start);
    Inc(Cnt);
    Inc(P); // skip the null
  end;
end;

function ParseDoubleNullListW(P: PWideChar): TStringArray;
var
  Start: PWideChar;
  Cnt: Integer;
  W: WideString;
begin
  Result := nil;
  if P = nil then Exit;
  Cnt := 0;
  while P^ <> #0 do
  begin
    Start := P;
    while P^ <> #0 do Inc(P);
    SetLength(W, P - Start);
    Move(Start^, W[1], (P - Start) * SizeOf(WideChar));
    SetLength(Result, Cnt + 1);
    Result[Cnt] := UTF8Encode(W);
    Inc(Cnt);
    Inc(P);
  end;
end;

// Recursive wildcard matcher for '*' and '?'.
// Both inputs assumed already uppercased.
function WildMatch(P, S: PAnsiChar): Boolean;
begin
  while True do
  begin
    if P^ = #0 then
    begin
      Result := (S^ = #0); Exit;
    end;
    if P^ = '*' then
    begin
      // Skip over consecutive *'s
      while P^ = '*' do Inc(P);
      if P^ = #0 then begin Result := True; Exit; end;
      // Try every position to match the rest
      while S^ <> #0 do
      begin
        if WildMatch(P, S) then begin Result := True; Exit; end;
        Inc(S);
      end;
      Result := WildMatch(P, S); Exit;
    end;
    if S^ = #0 then begin Result := False; Exit; end;
    if (P^ <> '?') and (P^ <> S^) then begin Result := False; Exit; end;
    Inc(P); Inc(S);
  end;
end;

// Does an archive entry path match ANY of the given patterns?
// Patterns and path are normalized to backslashes + uppercase first.
function MatchAnyPattern(const Path: AnsiString; const Patterns: TStringArray): Boolean;
var
  Up, Pat: AnsiString;
  i: Integer;
begin
  Result := False;
  Up := AnsiUpperCase(ToWinPath(Path));
  for i := 0 to High(Patterns) do
  begin
    Pat := AnsiUpperCase(ToWinPath(Patterns[i]));
    // Exact match first (fast path -- TC usually sends literal names)
    if Up = Pat then begin Result := True; Exit; end;
    // Then wildcard
    if (Pos('*', Pat) > 0) or (Pos('?', Pat) > 0) then
      if WildMatch(PAnsiChar(Pat), PAnsiChar(Up)) then begin Result := True; Exit; end;
  end;
end;

// =========================================================================
// WCX API: read side
// =========================================================================

function OpenArchiveImpl(const FileName: AnsiString; out Reason: Integer): PArcHandle;
begin
  Result := nil;
  Reason := 0;
  try
    New(Result);
    Result^.Archive := TPACArchive.Create(FileName);
    Result^.CurrentIndex := -1;
    Result^.DosFileTime := FileTimeToDosTime(Result^.Archive.MTime);
    Result^.EmptyDirs := LoadSidecar(FileName);
  except
    on E: Exception do
    begin
      if Result <> nil then Dispose(Result);
      Result := nil;
      Reason := E_BAD_ARCHIVE;
    end;
  end;
end;

function OpenArchive(var ArchiveData: TOpenArchiveData): THandle; stdcall;
var H: PArcHandle; Reason: Integer;
begin
  H := OpenArchiveImpl(AnsiString(ArchiveData.ArcName), Reason);
  if H = nil then begin ArchiveData.OpenResult := Reason; Result := 0; Exit; end;
  ArchiveData.OpenResult := 0;
  Result := THandle(H);
end;

function OpenArchiveW(var ArchiveData: TOpenArchiveDataW): THandle; stdcall;
var H: PArcHandle; Reason: Integer; A: AnsiString;
begin
  A := UTF8Encode(WideString(ArchiveData.ArcName));
  H := OpenArchiveImpl(A, Reason);
  if H = nil then begin ArchiveData.OpenResult := Reason; Result := 0; Exit; end;
  ArchiveData.OpenResult := 0;
  Result := THandle(H);
end;

function ReadHeaderEx(hArcData: THandle; var HeaderData: THeaderDataExA): Integer; stdcall;
var
  H: PArcHandle; E: TPACEntry; DirPath: AnsiString;
  RealCount, VirtIdx: Integer;
begin
  H := PArcHandle(hArcData);
  Inc(H^.CurrentIndex);
  RealCount := Length(H^.Archive.Entries);
  FillChar(HeaderData, SizeOf(HeaderData), 0);
  HeaderData.FileTime := H^.DosFileTime;

  if H^.CurrentIndex < RealCount then
  begin
    E := H^.Archive.Entries[H^.CurrentIndex];
    if IsKeepMarker(E.Name) then
    begin
      // Legacy marker from previous plugin version: present as directory
      // entry. Will get auto-stripped on next write.
      DirPath := MarkerToDirPath(E.Name);
      if DirPath = '' then DirPath := '.\';
      StoreAnsiPath(HeaderData.FileName, DirPath, 1024);
      HeaderData.FileAttr := FILE_ATTRIBUTE_DIRECTORY;
      Result := 0;
      Exit;
    end;
    StoreAnsiPath(HeaderData.FileName, ToWinPath(E.Name), 1024);
    HeaderData.PackSize     := LongInt(E.Size and $FFFFFFFF);
    HeaderData.PackSizeHigh := LongInt((E.Size shr 32) and $FFFFFFFF);
    HeaderData.UnpSize      := LongInt(E.Size and $FFFFFFFF);
    HeaderData.UnpSizeHigh  := LongInt((E.Size shr 32) and $FFFFFFFF);
    HeaderData.HostOS       := 0;
    HeaderData.Method       := 0;          // FPAC has no compression
    HeaderData.FileAttr     := FILE_ATTRIBUTE_ARCHIVE;
    Result := 0;
    Exit;
  end;

  // Past real entries — emit sidecar virtual empty directories
  VirtIdx := H^.CurrentIndex - RealCount;
  if VirtIdx >= Length(H^.EmptyDirs) then
  begin Result := E_END_ARCHIVE; Exit; end;

  StoreAnsiPath(HeaderData.FileName, ToWinPath(H^.EmptyDirs[VirtIdx]) + '\', 1024);
  HeaderData.FileAttr := FILE_ATTRIBUTE_DIRECTORY;
  Result := 0;
end;

function ReadHeaderExW(hArcData: THandle; var HeaderData: THeaderDataExW): Integer; stdcall;
var
  H: PArcHandle; E: TPACEntry; DirPath: AnsiString;
  RealCount, VirtIdx: Integer;
begin
  H := PArcHandle(hArcData);
  Inc(H^.CurrentIndex);
  RealCount := Length(H^.Archive.Entries);
  FillChar(HeaderData, SizeOf(HeaderData), 0);
  HeaderData.FileTime := H^.DosFileTime;

  if H^.CurrentIndex < RealCount then
  begin
    E := H^.Archive.Entries[H^.CurrentIndex];
    if IsKeepMarker(E.Name) then
    begin
      DirPath := MarkerToDirPath(E.Name);
      if DirPath = '' then DirPath := '.\';
      StoreWidePath(HeaderData.FileName, DirPath, 1024);
      HeaderData.FileAttr := FILE_ATTRIBUTE_DIRECTORY;
      Result := 0;
      Exit;
    end;
    StoreWidePath(HeaderData.FileName, ToWinPath(E.Name), 1024);
    HeaderData.PackSize     := LongInt(E.Size and $FFFFFFFF);
    HeaderData.PackSizeHigh := LongInt((E.Size shr 32) and $FFFFFFFF);
    HeaderData.UnpSize      := LongInt(E.Size and $FFFFFFFF);
    HeaderData.UnpSizeHigh  := LongInt((E.Size shr 32) and $FFFFFFFF);
    HeaderData.HostOS       := 0;
    HeaderData.Method       := 0;
    HeaderData.FileAttr     := FILE_ATTRIBUTE_ARCHIVE;
    Result := 0;
    Exit;
  end;

  VirtIdx := H^.CurrentIndex - RealCount;
  if VirtIdx >= Length(H^.EmptyDirs) then
  begin Result := E_END_ARCHIVE; Exit; end;

  StoreWidePath(HeaderData.FileName, ToWinPath(H^.EmptyDirs[VirtIdx]) + '\', 1024);
  HeaderData.FileAttr := FILE_ATTRIBUTE_DIRECTORY;
  Result := 0;
end;

// Older non-extended variant (small struct, 32-bit sizes).
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
  H: PArcHandle; E: TPACEntry; HD: PHeaderDataA; DirPath: AnsiString;
  RealCount, VirtIdx: Integer;
begin
  HD := PHeaderDataA(HeaderData);
  H := PArcHandle(hArcData);
  Inc(H^.CurrentIndex);
  RealCount := Length(H^.Archive.Entries);
  FillChar(HD^, SizeOf(HD^), 0);
  HD^.FileTime := H^.DosFileTime;

  if H^.CurrentIndex < RealCount then
  begin
    E := H^.Archive.Entries[H^.CurrentIndex];
    if IsKeepMarker(E.Name) then
    begin
      DirPath := MarkerToDirPath(E.Name);
      if DirPath = '' then DirPath := '.\';
      StoreAnsiPath(HD^.FileName, DirPath, 260);
      HD^.FileAttr := FILE_ATTRIBUTE_DIRECTORY;
      Result := 0;
      Exit;
    end;
    StoreAnsiPath(HD^.FileName, ToWinPath(E.Name), 260);
    if E.Size > MaxInt then HD^.PackSize := MaxInt else HD^.PackSize := LongInt(E.Size);
    if E.Size > MaxInt then HD^.UnpSize  := MaxInt else HD^.UnpSize  := LongInt(E.Size);
    HD^.Method   := 0;
    HD^.FileAttr := FILE_ATTRIBUTE_ARCHIVE;
    Result := 0;
    Exit;
  end;

  VirtIdx := H^.CurrentIndex - RealCount;
  if VirtIdx >= Length(H^.EmptyDirs) then
  begin Result := E_END_ARCHIVE; Exit; end;

  StoreAnsiPath(HD^.FileName, ToWinPath(H^.EmptyDirs[VirtIdx]) + '\', 260);
  HD^.FileAttr := FILE_ATTRIBUTE_DIRECTORY;
  Result := 0;
end;

function ProcessFile(hArcData: THandle; Operation: Integer;
                     DestPath, DestName: PAnsiChar): Integer; stdcall;
var
  H: PArcHandle; E: TPACEntry; Buf: PByte; Full: AnsiString; F: TFileStream;
  Aborted: Boolean;
begin
  H := PArcHandle(hArcData);
  if H^.CurrentIndex < 0 then
  begin Result := E_BAD_DATA; Exit; end;
  if Operation = PK_SKIP then begin Result := 0; Exit; end;

  // Virtual entry from sidecar (empty directory)
  if H^.CurrentIndex >= Length(H^.Archive.Entries) then
  begin
    if Operation = PK_EXTRACT then
    begin
      if DestPath <> nil then Full := AnsiString(DestPath) + AnsiString(DestName)
      else                    Full := AnsiString(DestName);
      while (Full <> '') and (Full[Length(Full)] = '\') do
        SetLength(Full, Length(Full) - 1);
      if Full <> '' then ForceDirectories(Full);
    end;
    Result := 0;
    Exit;
  end;

  E := H^.Archive.Entries[H^.CurrentIndex];

  // Legacy .p3a_keep marker entries -- same handling as virtual dirs.
  if IsKeepMarker(E.Name) then
  begin
    if Operation = PK_EXTRACT then
    begin
      if DestPath <> nil then Full := AnsiString(DestPath) + AnsiString(DestName)
      else                    Full := AnsiString(DestName);
      while (Full <> '') and (Full[Length(Full)] = '\') do
        SetLength(Full, Length(Full) - 1);
      if Full <> '' then ForceDirectories(Full);
    end;
    Result := 0;
    Exit;
  end;

  // PAC entries always store raw uncompressed bytes; no cmp_type check.
  Buf := nil;
  if E.Size > 0 then GetMem(Buf, E.Size);
  try
    if not H^.Archive.ExtractEntry(H^.CurrentIndex, Buf, E.Size) then
    begin Result := E_BAD_DATA; Exit; end;

    Aborted := False;
    if Assigned(GProcessDataProcW) then
      Aborted := (GProcessDataProcW(nil, LongInt(E.Size and $FFFFFFFF)) = 0)
    else if Assigned(GProcessDataProc) then
      Aborted := (GProcessDataProc(nil, LongInt(E.Size and $FFFFFFFF)) = 0);
    if Aborted then begin Result := E_EWRITE; Exit; end;

    if Operation = PK_TEST then begin Result := 0; Exit; end;

    if DestPath <> nil then Full := AnsiString(DestPath) + AnsiString(DestName)
    else                    Full := AnsiString(DestName);
    ForceDirectories(ExtractFilePath(Full));

    try
      F := TFileStream.Create(Full, fmCreate);
      try
        if E.Size > 0 then F.WriteBuffer(Buf^, E.Size);
      finally F.Free; end;
    except
      Result := E_EWRITE; Exit;
    end;
    Result := 0;
  finally
    if Buf <> nil then FreeMem(Buf);
  end;
end;

function ProcessFileW(hArcData: THandle; Operation: Integer;
                      DestPath, DestName: PWideChar): Integer; stdcall;
var PA, NA: AnsiString;
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

procedure SetChangeVolProc(hArcData: THandle; pChangeVolProc: Pointer); stdcall; begin end;
procedure SetChangeVolProcW(hArcData: THandle; pChangeVolProc: Pointer); stdcall; begin end;

procedure SetProcessDataProc(hArcData: THandle; pProc: TProcessDataProc); stdcall;
begin GProcessDataProc := pProc; end;

procedure SetProcessDataProcW(hArcData: THandle; pProc: TProcessDataProcW); stdcall;
begin GProcessDataProcW := pProc; end;

function GetPackerCaps: Integer; stdcall;
begin
  Result := PK_CAPS_NEW or PK_CAPS_MODIFY or PK_CAPS_MULTIPLE
            or PK_CAPS_DELETE or PK_CAPS_BY_CONTENT;
end;

function CanYouHandleThisFile(FileName: PAnsiChar): Boolean; stdcall;
var
  F: file of Byte;
  Magic: array[0..3] of AnsiChar;
  ReadCount: Int64;
  i: Integer;
  Want: array[0..3] of AnsiChar;
begin
  Result := False;
  Want := 'FPAC';
  AssignFile(F, AnsiString(FileName));
  {$I-} Reset(F); {$I+}
  if IOResult <> 0 then Exit;
  try
    BlockRead(F, Magic, 4, ReadCount);
    if ReadCount <> 4 then Exit;
    for i := 0 to 3 do if Magic[i] <> Want[i] then Exit;
    Result := True;
  finally CloseFile(F); end;
end;

function CanYouHandleThisFileW(FileName: PWideChar): Boolean; stdcall;
var A: AnsiString;
begin
  A := UTF8Encode(WideString(FileName));
  Result := CanYouHandleThisFile(PAnsiChar(A));
end;

// =========================================================================
// WCX API: write side
// =========================================================================

function ReadWholeFile(const FileName: AnsiString; out Buf: TBytes): Boolean;
var F: TFileStream;
begin
  Result := False;
  try
    F := TFileStream.Create(FileName, fmOpenRead or fmShareDenyNone);
    try
      SetLength(Buf, F.Size);
      if F.Size > 0 then F.ReadBuffer(Buf[0], F.Size);
    finally F.Free; end;
    Result := True;
  except
    Result := False;
  end;
end;

// Build a TPACWriter populated with all entries from the existing archive
// (verbatim, no decompression), MINUS the names listed in ExcludeSet.
// Returns nil on failure. Caller frees.
function CarryOverExisting(const ArcPath: AnsiString;
                           const Exclude: TStringArray;
                           ArchiveExists: Boolean): TPACWriter;
var
  Arc: TPACArchive;
  i: Integer;
  Buf: TBytes;
  E: TPACEntry;
  EntryWin: AnsiString;
begin
  Result := TPACWriter.Create;
  if not ArchiveExists then Exit;

  try
    Arc := TPACArchive.Create(ArcPath);
  except
    Result.Free; Result := nil; Exit;
  end;

  try
    for i := 0 to High(Arc.Entries) do
    begin
      E := Arc.Entries[i];

      // Auto-cleanup of legacy .p3a_keep markers from older plugin
      // versions: every time we rewrite the archive, drop these so they
      // don't leak to external extractors.
      if IsKeepMarker(E.Name) then Continue;

      EntryWin := ToWinPath(E.Name);
      if MatchAnyPattern(EntryWin, Exclude) then Continue;

      SetLength(Buf, E.Size);
      if (E.Size > 0) and not Arc.ReadRawBytes(i, @Buf[0]) then Continue;

      Result.AddRaw(E.Name, Buf);
    end;
  finally
    Arc.Free;
  end;
end;

// Replace the original archive atomically: write to a sibling temp file,
// delete the original (if any), rename.
function FinalizeWrite(W: TPACWriter; const ArcPath: AnsiString): Integer;
var
  TempPath: AnsiString;
begin
  TempPath := ArcPath + '.tmp_pacwcx';
  try
    W.WriteToFile(TempPath);
  except
    DeleteFile(TempPath);
    Result := E_EWRITE; Exit;
  end;

  if FileExists(ArcPath) then
    if not DeleteFile(ArcPath) then
    begin
      DeleteFile(TempPath);
      Result := E_EWRITE; Exit;
    end;

  if not RenameFile(TempPath, ArcPath) then
  begin
    DeleteFile(TempPath);
    Result := E_EWRITE; Exit;
  end;

  Result := 0;
end;

// Parent directory of a path (without trailing slash).
// Examples: "asset\foo\bar.txt" -> "asset\foo"
//           "asset\foo"         -> "asset"
//           "asset"             -> ""
function ParentDir(const Path: AnsiString): AnsiString;
var j: Integer;
begin
  Result := '';
  for j := Length(Path) downto 1 do
    if (Path[j] = '\') or (Path[j] = '/') then
    begin Result := Copy(Path, 1, j - 1); Exit; end;
end;

procedure AddReplace(var L: TStringArray; const S: AnsiString);
begin
  SetLength(L, Length(L) + 1);
  L[High(L)] := S;
end;

// Walk up the directory tree from StartDir, queueing each ancestor's
// .p3a_keep marker for removal. Used so that when we add real content
// somewhere, all "I'm an empty folder" markers up the tree get cleared.
procedure AddAncestorKeepMarkers(var L: TStringArray; const StartDir: AnsiString);
var P: AnsiString;
begin
  P := StartDir;
  while P <> '' do
  begin
    AddReplace(L, P + '\.p3a_keep');
    P := ParentDir(P);
  end;
end;

function PackFiles(PackedFile, SubPath, SrcPath, AddList: PAnsiChar; Flags: Integer): Integer; stdcall;
var
  Arc, Src, ArchivePath: AnsiString;
  Files: TStringArray;
  ReplaceList: TStringArray;
  EmptyDirs: TStringArray;
  i: Integer;
  AddItem, ArchEntry, DiskFile, EntryName, FolderPath: AnsiString;
  W: TPACWriter;
  Buf: TBytes;
  Aborted: Boolean;
  IsFolder: Boolean;
begin
  ArchivePath := AnsiString(PackedFile);
  if SrcPath <> nil then Src := AnsiString(SrcPath) else Src := '';
  Arc := AnsiString(SubPath); // SubPath is folder INSIDE archive; usually empty

  Files := ParseDoubleNullList(AddList);
  if Length(Files) = 0 then begin Result := 0; Exit; end;

  // Load sidecar (list of empty folders explicitly created via F7).
  EmptyDirs := LoadSidecar(ArchivePath);

  // === Pass 1: figure out which existing entries the new content REPLACES,
  // and update sidecar for F7 / file-add operations.
  ReplaceList := nil;
  for i := 0 to High(Files) do
  begin
    AddItem := Files[i];
    if AddItem = '' then Continue;

    // Compose full archive path = SubPath + AddItem
    if (Arc <> '') and (Arc[Length(Arc)] <> '\') then
      ArchEntry := Arc + '\' + AddItem
    else
      ArchEntry := Arc + AddItem;

    IsFolder := (ArchEntry[Length(ArchEntry)] = '\');

    if IsFolder then
    begin
      // F7 (Make Folder): record in sidecar so it's visible in TC,
      // but we don't write anything to the archive itself (P3A format
      // can't store empty folders, and we don't want to leak markers
      // to external extractors).
      FolderPath := Copy(ArchEntry, 1, Length(ArchEntry) - 1);
      SidecarAdd(EmptyDirs, FolderPath);
      // Cleanup any legacy .p3a_keep markers from older plugin versions.
      AddAncestorKeepMarkers(ReplaceList, FolderPath);
    end
    else
    begin
      AddReplace(ReplaceList, ArchEntry);
      // Adding a real file means its parent (and ancestors) is no longer
      // empty -- prune from sidecar AND clean any legacy .p3a_keep markers.
      SidecarRemoveAncestors(EmptyDirs, ArchEntry);
      AddAncestorKeepMarkers(ReplaceList, ParentDir(ArchEntry));
    end;
  end;

  // === Carry over existing entries (minus the replaced ones).
  W := CarryOverExisting(ArchivePath, ReplaceList, FileExists(ArchivePath));
  if W = nil then begin Result := E_BAD_ARCHIVE; Exit; end;

  try
    // === Pass 2: actually pack the new content.
    for i := 0 to High(Files) do
    begin
      AddItem := Files[i];
      if AddItem = '' then Continue;

      if (Arc <> '') and (Arc[Length(Arc)] <> '\') then
        ArchEntry := Arc + '\' + AddItem
      else
        ArchEntry := Arc + AddItem;

      IsFolder := (ArchEntry[Length(ArchEntry)] = '\');

      if IsFolder then Continue;  // F7 only updates sidecar, no archive entry

      // Disk path = SrcPath + AddItem (NOT SubPath -- SubPath is for
      // archive side only)
      if Src <> '' then DiskFile := Src + AddItem
      else              DiskFile := AddItem;

      if not ReadWholeFile(DiskFile, Buf) then begin Result := E_EREAD; Exit; end;

      EntryName := ToUnixPath(ArchEntry);

      Aborted := False;
      if Assigned(GProcessDataProcW) then
        Aborted := (GProcessDataProcW(PWideChar(UTF8Decode(AddItem)), Length(Buf)) = 0)
      else if Assigned(GProcessDataProc) then
        Aborted := (GProcessDataProc(PAnsiChar(AddItem), Length(Buf)) = 0);
      if Aborted then begin Result := E_EWRITE; Exit; end;

      if Length(Buf) > 0 then
        W.AddFromBuffer(EntryName, @Buf[0], Length(Buf))
      else
        W.AddFromBuffer(EntryName, nil, 0);
    end;

    Result := FinalizeWrite(W, ArchivePath);

    // After successful archive write, persist updated sidecar.
    if Result = 0 then SaveSidecar(ArchivePath, EmptyDirs);

    // Move-files mode: delete on-disk sources after successful pack.
    if (Result = 0) and ((Flags and PK_PACK_MOVE_FILES) <> 0) then
    begin
      for i := 0 to High(Files) do
      begin
        AddItem := Files[i];
        if (AddItem = '') or (AddItem[Length(AddItem)] = '\') then Continue;
        if Src <> '' then DiskFile := Src + AddItem else DiskFile := AddItem;
        DeleteFile(DiskFile);
      end;
    end;
  finally
    W.Free;
  end;
end;

function PackFilesW(PackedFile, SubPath, SrcPath, AddList: PWideChar; Flags: Integer): Integer; stdcall;
var
  AArc, ASub, ASrc: AnsiString;
  WFiles: TStringArray;
  AAdd: AnsiString;
  i, TotalLen: Integer;
  P: PAnsiChar;
begin
  AArc := UTF8Encode(WideString(PackedFile));
  if SubPath <> nil then ASub := UTF8Encode(WideString(SubPath)) else ASub := '';
  if SrcPath <> nil then ASrc := UTF8Encode(WideString(SrcPath)) else ASrc := '';

  // Convert wide double-null list to ansi double-null list
  WFiles := ParseDoubleNullListW(AddList);
  TotalLen := 1;  // trailing extra null
  for i := 0 to High(WFiles) do Inc(TotalLen, Length(WFiles[i]) + 1);
  SetLength(AAdd, TotalLen);
  P := PAnsiChar(AAdd);
  for i := 0 to High(WFiles) do
  begin
    if Length(WFiles[i]) > 0 then
      Move(WFiles[i][1], P^, Length(WFiles[i]));
    Inc(P, Length(WFiles[i]));
    P^ := #0; Inc(P);
  end;
  P^ := #0;

  Result := PackFiles(PAnsiChar(AArc),
                      PAnsiChar(ASub),
                      PAnsiChar(ASrc),
                      PAnsiChar(AAdd),
                      Flags);
end;

function DeleteFiles(PackedFile, DeleteList: PAnsiChar): Integer; stdcall;
var
  ArchivePath: AnsiString;
  Patterns: TStringArray;
  EmptyDirs, KeptDirs: TStringArray;
  W: TPACWriter;
  i, j: Integer;
  DirPath: AnsiString;
  Match: Boolean;
  StripPat: AnsiString;
begin
  ArchivePath := AnsiString(PackedFile);
  if not FileExists(ArchivePath) then begin Result := E_BAD_ARCHIVE; Exit; end;

  Patterns := ParseDoubleNullList(DeleteList);
  if Length(Patterns) = 0 then begin Result := 0; Exit; end;

  // Prune sidecar entries that match any delete pattern.
  EmptyDirs := LoadSidecar(ArchivePath);
  KeptDirs := nil;
  for i := 0 to High(EmptyDirs) do
  begin
    DirPath := ToWinPath(EmptyDirs[i]);
    Match := MatchAnyPattern(DirPath, Patterns);
    if not Match then Match := MatchAnyPattern(DirPath + '\', Patterns);
    if not Match then
      for j := 0 to High(Patterns) do
      begin
        StripPat := Patterns[j];
        if (Length(StripPat) >= 4) and (Copy(StripPat, Length(StripPat)-3, 4) = '\*.*') then
          StripPat := Copy(StripPat, 1, Length(StripPat) - 4)
        else if (Length(StripPat) >= 2) and (Copy(StripPat, Length(StripPat)-1, 2) = '\*') then
          StripPat := Copy(StripPat, 1, Length(StripPat) - 2);
        if (StripPat <> '') and (AnsiUpperCase(DirPath) = AnsiUpperCase(StripPat)) then
        begin Match := True; Break; end;
      end;
    if not Match then
    begin
      SetLength(KeptDirs, Length(KeptDirs) + 1);
      KeptDirs[High(KeptDirs)] := EmptyDirs[i];
    end;
  end;

  W := CarryOverExisting(ArchivePath, Patterns, True);
  if W = nil then begin Result := E_BAD_ARCHIVE; Exit; end;

  try
    Result := FinalizeWrite(W, ArchivePath);
    if Result = 0 then SaveSidecar(ArchivePath, KeptDirs);
  finally
    W.Free;
  end;
end;

function DeleteFilesW(PackedFile, DeleteList: PWideChar): Integer; stdcall;
var
  AArc, ADel: AnsiString;
  WPats: TStringArray;
  i, TotalLen: Integer;
  P: PAnsiChar;
begin
  AArc := UTF8Encode(WideString(PackedFile));
  WPats := ParseDoubleNullListW(DeleteList);

  TotalLen := 1;
  for i := 0 to High(WPats) do Inc(TotalLen, Length(WPats[i]) + 1);
  SetLength(ADel, TotalLen);
  P := PAnsiChar(ADel);
  for i := 0 to High(WPats) do
  begin
    if Length(WPats[i]) > 0 then Move(WPats[i][1], P^, Length(WPats[i]));
    Inc(P, Length(WPats[i]));
    P^ := #0; Inc(P);
  end;
  P^ := #0;

  Result := DeleteFiles(PAnsiChar(AArc), PAnsiChar(ADel));
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
  CanYouHandleThisFileW,
  PackFiles,
  PackFilesW,
  DeleteFiles,
  DeleteFilesW;

begin
end.
