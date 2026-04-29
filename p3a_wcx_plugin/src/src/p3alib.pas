unit p3alib;
{$mode objfpc}{$H+}

// P3A archive format reader AND writer. Supports versions 1100 and 1200.
//
// Read side: extraction supports cmp_type 0 (none) and 1 (lz4).
// Write side: emits cmp_type 1 (lz4) by default. Existing compressed
// entries can be carried over verbatim when modifying an archive
// (so a delete or partial-update doesn't decompress + recompress
// every untouched file).

interface

uses Classes, SysUtils, Math
  {$IFDEF MSWINDOWS}, Windows{$ENDIF}
  ;

type
  TP3AEntry = record
    Name: AnsiString;
    CmpType: Int64;
    CmpSize: Int64;
    UncSize: Int64;
    Offset: Int64;
    CmpHash: QWord;
    UncHash: QWord;
    HasUncHash: Boolean;
  end;
  TP3AEntryArray = array of TP3AEntry;

  {$IFDEF MSWINDOWS}
  TP3ATimeStamp = TFileTime;
  {$ELSE}
  TP3ATimeStamp = QWord;
  {$ENDIF}

  TP3AArchive = class
  private
    FStream: TFileStream;
    FFileName: AnsiString;
    FMTime: TP3ATimeStamp;
    FVersion: LongWord;
    FFlags: LongWord;
    FEntries: TP3AEntryArray;
    procedure CaptureFileTime;
  public
    constructor Create(const FileName: AnsiString);
    destructor Destroy; override;
    function ExtractEntry(Index: Integer; OutBuf: PByte; OutSize: Int64): Boolean;
    function ReadCompressedBytes(Index: Integer; OutBuf: PByte): Boolean;
    property Entries: TP3AEntryArray read FEntries;
    property Version: LongWord read FVersion;
    property Flags: LongWord read FFlags;
    property MTime: TP3ATimeStamp read FMTime;
    property FileName: AnsiString read FFileName;
  end;

  TP3APending = record
    Entry: TP3AEntry;
    Data: TBytes;
  end;

  TP3AWriter = class
  private
    FPending: array of TP3APending;
  public
    procedure AddFromCompressed(const Name: AnsiString;
                                CmpType: Int64;
                                const CmpData: TBytes;
                                UncSize: Int64;
                                CmpHash, UncHash: QWord;
                                HasUncHash: Boolean);
    procedure AddFromBuffer(const Name: AnsiString; UncBuf: PByte; UncSize: Int64);
    function Count: Integer;
    procedure WriteToFile(const FileName: AnsiString; Version: LongWord = 1100);
  end;

  EP3A = class(Exception);

implementation

uses lz4dec, lz4comp, xxhash64;

procedure TP3AArchive.CaptureFileTime;
{$IFDEF MSWINDOWS}
var H: THandle;
{$ENDIF}
begin
  FillChar(FMTime, SizeOf(FMTime), 0);
  {$IFDEF MSWINDOWS}
  H := CreateFileA(PAnsiChar(FFileName), 0, FILE_SHARE_READ or FILE_SHARE_WRITE,
                   nil, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
  if H <> INVALID_HANDLE_VALUE then
  begin
    GetFileTime(H, nil, nil, @FMTime);
    CloseHandle(H);
  end;
  {$ENDIF}
end;

constructor TP3AArchive.Create(const FileName: AnsiString);
var
  Magic: array[0..7] of AnsiChar;
  NumFiles, P3AHash, P3AHash2: QWord;
  ExtHdrSize, EntrySize: LongWord;
  i: Integer;
  NameBuf: array[0..255] of AnsiChar;
  NameLen: Integer;
  Vals: array[0..3] of Int64;
  CmpHash, UncHash: QWord;
begin
  inherited Create;
  FFileName := FileName;
  FStream := TFileStream.Create(FileName, fmOpenRead or fmShareDenyWrite);
  CaptureFileTime;

  FStream.ReadBuffer(Magic, 8);
  if (Magic[0] <> 'P') or (Magic[1] <> 'H') or (Magic[2] <> '3')
     or (Magic[3] <> 'A') or (Magic[4] <> 'R') or (Magic[5] <> 'C')
     or (Magic[6] <> 'V') or (Magic[7] <> #0) then
    raise EP3A.Create('not a P3A archive (bad magic)');

  FStream.ReadBuffer(FFlags, 4);
  FStream.ReadBuffer(FVersion, 4);
  FStream.ReadBuffer(NumFiles, 8);
  FStream.ReadBuffer(P3AHash, 8);
  if FVersion >= 1200 then
  begin
    FStream.ReadBuffer(P3AHash2, 8);
    FStream.ReadBuffer(ExtHdrSize, 4);
    FStream.ReadBuffer(EntrySize, 4);
  end;

  if NumFiles > 1000000 then
    raise EP3A.Create('absurd file count');
  SetLength(FEntries, NumFiles);
  for i := 0 to Integer(NumFiles) - 1 do
  begin
    FStream.ReadBuffer(NameBuf, 256);
    NameLen := 0;
    while (NameLen < 256) and (NameBuf[NameLen] <> #0) do Inc(NameLen);
    SetString(FEntries[i].Name, PAnsiChar(@NameBuf[0]), NameLen);

    FStream.ReadBuffer(Vals, 32);
    FEntries[i].CmpType := Vals[0];
    FEntries[i].CmpSize := Vals[1];
    FEntries[i].UncSize := Vals[2];
    FEntries[i].Offset  := Vals[3];

    FStream.ReadBuffer(CmpHash, 8);
    FEntries[i].CmpHash := CmpHash;

    if FVersion >= 1200 then
    begin
      FStream.ReadBuffer(UncHash, 8);
      FEntries[i].UncHash := UncHash;
      FEntries[i].HasUncHash := True;
    end
    else
      FEntries[i].HasUncHash := False;
  end;
end;

destructor TP3AArchive.Destroy;
begin
  FreeAndNil(FStream);
  inherited;
end;

function TP3AArchive.ExtractEntry(Index: Integer; OutBuf: PByte; OutSize: Int64): Boolean;
var
  E: TP3AEntry;
  CmpBuf: PByte;
  Got: PtrInt;
begin
  Result := False;
  if (Index < 0) or (Index >= Length(FEntries)) then Exit;
  E := FEntries[Index];
  if OutSize < E.UncSize then Exit;

  FStream.Seek(E.Offset, soBeginning);

  if E.CmpType = 0 then
  begin
    if E.UncSize > 0 then FStream.ReadBuffer(OutBuf^, E.UncSize);
    Result := True;
    Exit;
  end;

  GetMem(CmpBuf, E.CmpSize);
  try
    FStream.ReadBuffer(CmpBuf^, E.CmpSize);
    case E.CmpType of
      1: begin
           Got := LZ4_Decompress_Block(CmpBuf, E.CmpSize, OutBuf, E.UncSize);
           Result := (Got = E.UncSize);
         end;
      2, 3: Result := False;
    else
      Result := False;
    end;
  finally
    FreeMem(CmpBuf);
  end;
end;

function TP3AArchive.ReadCompressedBytes(Index: Integer; OutBuf: PByte): Boolean;
var E: TP3AEntry;
begin
  Result := False;
  if (Index < 0) or (Index >= Length(FEntries)) then Exit;
  E := FEntries[Index];
  FStream.Seek(E.Offset, soBeginning);
  if E.CmpSize > 0 then FStream.ReadBuffer(OutBuf^, E.CmpSize);
  Result := True;
end;

procedure TP3AWriter.AddFromCompressed(const Name: AnsiString; CmpType: Int64;
                                       const CmpData: TBytes; UncSize: Int64;
                                       CmpHash, UncHash: QWord; HasUncHash: Boolean);
var L: Integer;
begin
  L := Length(FPending);
  SetLength(FPending, L + 1);
  FPending[L].Entry.Name        := AnsiLowerCase(Name);
  FPending[L].Entry.CmpType     := CmpType;
  FPending[L].Entry.CmpSize     := Length(CmpData);
  FPending[L].Entry.UncSize     := UncSize;
  FPending[L].Entry.Offset      := 0;
  FPending[L].Entry.CmpHash     := CmpHash;
  FPending[L].Entry.UncHash     := UncHash;
  FPending[L].Entry.HasUncHash  := HasUncHash;
  FPending[L].Data              := Copy(CmpData);
end;

procedure TP3AWriter.AddFromBuffer(const Name: AnsiString; UncBuf: PByte; UncSize: Int64);
var
  Bound, CmpSz: LongInt;
  CmpBuf: TBytes;
  UH, CH: QWord;
  L: Integer;
  CmpType: Int64;
  Dummy: QWord;
begin
  Dummy := 0;
  if UncSize > 0 then
    UH := XXH64(UncBuf, UncSize, 0)
  else
    UH := XXH64(@Dummy, 0, 0);

  CmpType := 1;
  Bound := LZ4_compressBound(UncSize);
  if Bound < 16 then Bound := 16;
  SetLength(CmpBuf, Bound);
  if UncSize > 0 then
    CmpSz := LZ4_compress_default(UncBuf, @CmpBuf[0], UncSize, Bound)
  else
    CmpSz := 0;

  if (CmpSz <= 0) or (CmpSz >= UncSize) then
  begin
    CmpType := 0;
    SetLength(CmpBuf, UncSize);
    if UncSize > 0 then Move(UncBuf^, CmpBuf[0], UncSize);
    CmpSz := UncSize;
  end
  else
    SetLength(CmpBuf, CmpSz);

  if Length(CmpBuf) > 0 then
    CH := XXH64(@CmpBuf[0], Length(CmpBuf), 0)
  else
    CH := XXH64(@Dummy, 0, 0);

  L := Length(FPending);
  SetLength(FPending, L + 1);
  FPending[L].Entry.Name       := AnsiLowerCase(Name);
  FPending[L].Entry.CmpType    := CmpType;
  FPending[L].Entry.CmpSize    := Length(CmpBuf);
  FPending[L].Entry.UncSize    := UncSize;
  FPending[L].Entry.Offset     := 0;
  FPending[L].Entry.CmpHash    := CH;
  FPending[L].Entry.UncHash    := UH;
  FPending[L].Entry.HasUncHash := True;
  FPending[L].Data             := CmpBuf;
end;

function TP3AWriter.Count: Integer;
begin
  Result := Length(FPending);
end;

procedure TP3AWriter.WriteToFile(const FileName: AnsiString; Version: LongWord);
var
  F: TFileStream;
  Magic: array[0..7] of AnsiChar;
  Flags: LongWord;
  NumFiles: QWord;
  HeaderHashBuf: array[0..23] of Byte;
  P3AHash: QWord;
  EntrySizeOnDisk, HeaderLen, CurOffset: Int64;
  Pad: array[0..63] of Byte;
  i: Integer;
  NameBuf: array[0..255] of AnsiChar;
  Vals: array[0..3] of Int64;
  PadByte: Byte;
begin
  if Version <> 1100 then Version := 1100;

  Flags := 0;
  NumFiles := Count;

  EntrySizeOnDisk := 296;  // 256 name + 5*8 (cmp_type, cmp_size, unc_size, offset, cmp_hash)
  HeaderLen := 8 + 4 + 4 + 8 + 8 + EntrySizeOnDisk * NumFiles;
  if HeaderLen mod 64 <> 0 then
    HeaderLen := ((HeaderLen + 63) div 64) * 64;

  CurOffset := HeaderLen;
  for i := 0 to Integer(NumFiles) - 1 do
  begin
    FPending[i].Entry.Offset := CurOffset;
    Inc(CurOffset, FPending[i].Entry.CmpSize);
    if i < Integer(NumFiles) - 1 then
      if CurOffset mod 64 <> 0 then
        Inc(CurOffset, 64 - (CurOffset mod 64));
  end;

  F := TFileStream.Create(FileName, fmCreate);
  try
    Magic := 'PH3ARCV'#0;
    F.WriteBuffer(Magic, 8);

    FillChar(HeaderHashBuf, SizeOf(HeaderHashBuf), 0);
    Move(Magic[0], HeaderHashBuf[0], 8);
    F.WriteBuffer(Flags, 4);
    Move(Flags, HeaderHashBuf[8], 4);
    F.WriteBuffer(Version, 4);
    Move(Version, HeaderHashBuf[12], 4);
    F.WriteBuffer(NumFiles, 8);
    Move(NumFiles, HeaderHashBuf[16], 8);

    P3AHash := XXH64(@HeaderHashBuf[0], 24, 0);
    F.WriteBuffer(P3AHash, 8);

    for i := 0 to Integer(NumFiles) - 1 do
    begin
      FillChar(NameBuf, 256, 0);
      if Length(FPending[i].Entry.Name) > 0 then
        Move(FPending[i].Entry.Name[1], NameBuf[0],
             Min(Length(FPending[i].Entry.Name), 256));
      F.WriteBuffer(NameBuf, 256);

      Vals[0] := FPending[i].Entry.CmpType;
      Vals[1] := FPending[i].Entry.CmpSize;
      Vals[2] := FPending[i].Entry.UncSize;
      Vals[3] := FPending[i].Entry.Offset;
      F.WriteBuffer(Vals, 32);

      F.WriteBuffer(FPending[i].Entry.CmpHash, 8);
    end;

    FillChar(Pad, SizeOf(Pad), 0);
    PadByte := 0;
    while F.Position < HeaderLen do
      F.WriteBuffer(PadByte, 1);

    for i := 0 to Integer(NumFiles) - 1 do
    begin
      if Length(FPending[i].Data) > 0 then
        F.WriteBuffer(FPending[i].Data[0], Length(FPending[i].Data));
      if i < Integer(NumFiles) - 1 then
        while F.Position mod 64 <> 0 do
          F.WriteBuffer(PadByte, 1);
    end;
  finally
    F.Free;
  end;
end;

end.
