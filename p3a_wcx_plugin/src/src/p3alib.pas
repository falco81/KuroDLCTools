unit p3alib;
{$mode objfpc}{$H+}

// P3A archive format reader AND writer. Supports versions 1100 and 1200.
//
// Read side: extraction supports cmp_type 0 (none), 1 (lz4),
// 2 (zstd), 3 (zstd with dictionary). For type 3 the per-archive
// P3ADICT block is parsed automatically when flags & 1 = 1.
//
// Write side: new entries are produced as cmp_type 1 (lz4). Existing
// compressed entries (any cmp_type, including zstd) can be carried
// over verbatim when modifying an archive, so a delete or partial-
// update doesn't decompress + recompress every untouched file.
// When the source archive was v1200 with a dictionary, the writer
// preserves both the version and the dict block.

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
    FDict: TBytes;          // P3ADICT contents when flags & 1 = 1, else empty
    procedure CaptureFileTime;
  public
    constructor Create(const FileName: AnsiString);
    destructor Destroy; override;
    function ExtractEntry(Index: Integer; OutBuf: PByte; OutSize: Int64): Boolean;
    function ReadCompressedBytes(Index: Integer; OutBuf: PByte): Boolean;
    property Entries: TP3AEntryArray read FEntries;
    property Version: LongWord read FVersion;
    property Flags: LongWord read FFlags;
    property Dict: TBytes read FDict;
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
    FDict: TBytes;
    FDictPresent: Boolean;
    FSourceVersion: LongWord;
  public
    constructor Create;
    procedure AddFromCompressed(const Name: AnsiString;
                                CmpType: Int64;
                                const CmpData: TBytes;
                                UncSize: Int64;
                                CmpHash, UncHash: QWord;
                                HasUncHash: Boolean);
    procedure AddFromBuffer(const Name: AnsiString; UncBuf: PByte; UncSize: Int64);
    procedure SetDict(const ADict: TBytes);
    function Count: Integer;
    procedure WriteToFile(const FileName: AnsiString; Version: LongWord = 0);
    // Source archive version, captured by CarryOverExisting so we can
    // round-trip v1200 archives (header layout, per-entry unc_hash,
    // optional dict block) when the user makes modifications.
    property SourceVersion: LongWord read FSourceVersion write FSourceVersion;
  end;

  EP3A = class(Exception);

implementation

uses lz4dec, lz4comp, zstddec, xxhash64;

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
  DictSize: QWord;
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

  // P3ADICT block: when flags & 1 = 1 the archive carries a ZSTD
  // training dictionary right after the entry table. cmp_type=3
  // entries reference it during decompression.
  FDict := nil;
  if (FFlags and 1) = 1 then
  begin
    FStream.ReadBuffer(Magic, 8);
    if (Magic[0] = 'P') and (Magic[1] = '3') and (Magic[2] = 'A')
       and (Magic[3] = 'D') and (Magic[4] = 'I') and (Magic[5] = 'C')
       and (Magic[6] = 'T') and (Magic[7] = #0) then
    begin
      FStream.ReadBuffer(DictSize, 8);
      if (DictSize > 0) and (DictSize < 64 * 1024 * 1024) then
      begin
        SetLength(FDict, DictSize);
        FStream.ReadBuffer(FDict[0], DictSize);
      end;
    end;
    // If magic doesn't match P3ADICT, leave FDict empty -- entries
    // with cmp_type=3 will fail at extract time.
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
  Dctx: Pointer;
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
      2: begin
           // ZSTD without dictionary
           Got := PtrInt(ZSTD_decompress(OutBuf, E.UncSize, CmpBuf, E.CmpSize));
           Result := (ZSTD_isError(PtrUInt(Got)) = 0) and (Got = E.UncSize);
         end;
      3: begin
           // ZSTD with the archive's training dictionary. Needs a
           // decompression context to thread the dict through.
           if Length(FDict) = 0 then
             Result := False
           else
           begin
             Dctx := ZSTD_createDCtx;
             if Dctx = nil then
               Result := False
             else
             try
               Got := PtrInt(ZSTD_decompress_usingDict(
                              Dctx,
                              OutBuf, E.UncSize,
                              CmpBuf, E.CmpSize,
                              @FDict[0], Length(FDict)));
               Result := (ZSTD_isError(PtrUInt(Got)) = 0) and (Got = E.UncSize);
             finally
               ZSTD_freeDCtx(Dctx);
             end;
           end;
         end;
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

constructor TP3AWriter.Create;
begin
  inherited;
  FSourceVersion := 1100;
  FDictPresent := False;
end;

procedure TP3AWriter.SetDict(const ADict: TBytes);
begin
  FDict := Copy(ADict);
  FDictPresent := Length(FDict) > 0;
end;

procedure TP3AWriter.WriteToFile(const FileName: AnsiString; Version: LongWord);
var
  F: TFileStream;
  Magic: array[0..7] of AnsiChar;
  DictMagic: array[0..7] of AnsiChar;
  Flags: LongWord;
  NumFiles: QWord;
  HeaderHashBuf: array[0..23] of Byte;
  ExtHdrBuf: array[0..7] of Byte;
  ExtHdrSize, EntrySize: LongWord;
  P3AHash, ExtHdrHash: QWord;
  EntrySizeOnDisk, HeaderLen, CurOffset, DictBlockLen: Int64;
  DictSizeQ: QWord;
  Pad: array[0..63] of Byte;
  i: Integer;
  NameBuf: array[0..255] of AnsiChar;
  Vals: array[0..3] of Int64;
  PadByte: Byte;
begin
  // Version=0 means "use SourceVersion" (default after CarryOverExisting).
  if Version = 0 then Version := FSourceVersion;
  if (Version <> 1100) and (Version <> 1200) then Version := 1100;
  // A dictionary is a v1200 feature: if a caller passes a dict but
  // requests v1100, upgrade the version automatically.
  if FDictPresent and (Version < 1200) then Version := 1200;

  Flags := 0;
  if FDictPresent then Flags := Flags or 1;

  NumFiles := Count;

  // Per-entry size on disk:
  //   v1100: 256 name + 5*8 (cmp_type, cmp_size, unc_size, offset, cmp_hash)
  //   v1200: above + 8 (unc_hash)
  if Version >= 1200 then EntrySizeOnDisk := 304
  else                    EntrySizeOnDisk := 296;

  // Fixed-header size (magic + flags + version + num_files + hash):
  //   v1100: 32 bytes
  //   v1200: 32 + 16 (ext header hash + ExtHdrSize + EntrySize) = 48
  if Version >= 1200 then HeaderLen := 48
  else                    HeaderLen := 32;

  Inc(HeaderLen, EntrySizeOnDisk * NumFiles);

  // Optional P3ADICT block, sandwiched between entries and data:
  //   8 magic + 8 size + dict bytes
  if FDictPresent then
    DictBlockLen := 16 + Length(FDict)
  else
    DictBlockLen := 0;
  Inc(HeaderLen, DictBlockLen);

  // 64-byte alignment for the start of the data block.
  if HeaderLen mod 64 <> 0 then
    HeaderLen := ((HeaderLen + 63) div 64) * 64;

  // Compute per-entry data offsets (each entry block also 64-aligned
  // except for the last one).
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
    PadByte := 0;

    // ---- Main header ----
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

    // ---- v1200 extension header ----
    if Version >= 1200 then
    begin
      ExtHdrSize := 16;
      EntrySize  := EntrySizeOnDisk;
      Move(ExtHdrSize, ExtHdrBuf[0], 4);
      Move(EntrySize,  ExtHdrBuf[4], 4);
      ExtHdrHash := XXH64(@ExtHdrBuf[0], 8, 0);
      F.WriteBuffer(ExtHdrHash, 8);
      F.WriteBuffer(ExtHdrBuf, 8);
    end;

    // ---- Entry table ----
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

      if Version >= 1200 then
        F.WriteBuffer(FPending[i].Entry.UncHash, 8);
    end;

    // ---- Optional P3ADICT block ----
    if FDictPresent then
    begin
      DictMagic := 'P3ADICT'#0;
      F.WriteBuffer(DictMagic, 8);
      DictSizeQ := Length(FDict);
      F.WriteBuffer(DictSizeQ, 8);
      if DictSizeQ > 0 then
        F.WriteBuffer(FDict[0], Length(FDict));
    end;

    // ---- Pad to 64-byte alignment before data ----
    FillChar(Pad, SizeOf(Pad), 0);
    while F.Position < HeaderLen do
      F.WriteBuffer(PadByte, 1);

    // ---- File data ----
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
