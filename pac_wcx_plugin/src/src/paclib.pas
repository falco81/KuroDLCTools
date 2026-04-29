unit paclib;
{$mode objfpc}{$H+}

// FPAC archive format reader AND writer.
//
// Format (Trails in the Sky FC; same in subsequent Sky games):
//   16 bytes  | header: 'FPAC' magic + count + header_size + unk(=1)
//   N * 32 B  | entry table, sorted by hash
//   M bytes   | name pool (null-terminated UTF-8 strings)
//   ...       | data block (raw file contents, uncompressed)
//
// Per-entry layout (32 bytes):
//   uint32  hash         CRC32(name) with the final XOR undone
//   uint32  reserved     always 0
//   uint64  name_offset  absolute offset of NUL-terminated name
//   uint64  size         file size (no compression in this format)
//   uint64  data_offset  absolute offset of file data

interface

uses Classes, SysUtils
  {$IFDEF MSWINDOWS}, Windows{$ENDIF}
  ;

type
  TPACEntry = record
    Name: AnsiString;
    Size: Int64;
    DataOffset: Int64;
    Hash: LongWord;
  end;
  TPACEntryArray = array of TPACEntry;

  {$IFDEF MSWINDOWS}
  TPACTimeStamp = TFileTime;
  {$ELSE}
  TPACTimeStamp = QWord;
  {$ENDIF}

  TPACArchive = class
  private
    FStream: TFileStream;
    FFileName: AnsiString;
    FMTime: TPACTimeStamp;
    FEntries: TPACEntryArray;
    procedure CaptureFileTime;
  public
    constructor Create(const FileName: AnsiString);
    destructor Destroy; override;
    function ExtractEntry(Index: Integer; OutBuf: PByte; OutSize: Int64): Boolean;
    function ReadRawBytes(Index: Integer; OutBuf: PByte): Boolean;
    property Entries: TPACEntryArray read FEntries;
    property MTime: TPACTimeStamp read FMTime;
    property FileName: AnsiString read FFileName;
  end;

  TPACPending = record
    Entry: TPACEntry;
    Data: TBytes;
  end;

  TPACWriter = class
  private
    FPending: array of TPACPending;
  public
    procedure AddFromBuffer(const Name: AnsiString; Buf: PByte; Size: Int64);
    procedure AddRaw(const Name: AnsiString; const Data: TBytes);
    function Count: Integer;
    procedure WriteToFile(const FileName: AnsiString);
  end;

  EPAC = class(Exception);

implementation

uses crc32pac;

procedure TPACArchive.CaptureFileTime;
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

// Read a NUL-terminated string starting at AbsOffset in FStream.
function ReadAnsiZ(S: TStream; AbsOffset: Int64): AnsiString;
var
  Save: Int64;
  B: Byte;
  Buf: array of Byte;
  N: Integer;
begin
  Result := '';
  Save := S.Position;
  S.Seek(AbsOffset, soBeginning);
  try
    N := 0;
    SetLength(Buf, 64);
    while True do
    begin
      if S.Read(B, 1) <> 1 then Break;
      if B = 0 then Break;
      if N >= Length(Buf) then SetLength(Buf, Length(Buf) * 2);
      Buf[N] := B;
      Inc(N);
      // Sanity cap so a malformed archive can't hang us forever.
      if N > 4096 then Break;
    end;
    SetString(Result, PAnsiChar(@Buf[0]), N);
  finally
    S.Seek(Save, soBeginning);
  end;
end;

constructor TPACArchive.Create(const FileName: AnsiString);
var
  Magic: array[0..3] of AnsiChar;
  Count, HeaderSize, Unk: LongWord;
  i: Integer;
  Hash, Reserved: LongWord;
  NameOff, Sz, DataOff: QWord;
begin
  inherited Create;
  FFileName := FileName;
  FStream := TFileStream.Create(FileName, fmOpenRead or fmShareDenyWrite);
  CaptureFileTime;

  FStream.ReadBuffer(Magic, 4);
  if (Magic[0] <> 'F') or (Magic[1] <> 'P') or (Magic[2] <> 'A') or (Magic[3] <> 'C') then
    raise EPAC.Create('not an FPAC archive (bad magic)');

  FStream.ReadBuffer(Count, 4);
  FStream.ReadBuffer(HeaderSize, 4);
  FStream.ReadBuffer(Unk, 4);

  if Count > 1000000 then
    raise EPAC.Create('absurd file count');

  SetLength(FEntries, Count);
  for i := 0 to Integer(Count) - 1 do
  begin
    FStream.ReadBuffer(Hash, 4);
    FStream.ReadBuffer(Reserved, 4);
    FStream.ReadBuffer(NameOff, 8);
    FStream.ReadBuffer(Sz, 8);
    FStream.ReadBuffer(DataOff, 8);
    FEntries[i].Hash       := Hash;
    FEntries[i].Size       := Sz;
    FEntries[i].DataOffset := DataOff;
    FEntries[i].Name       := ReadAnsiZ(FStream, NameOff);
  end;
end;

destructor TPACArchive.Destroy;
begin
  FreeAndNil(FStream);
  inherited;
end;

function TPACArchive.ExtractEntry(Index: Integer; OutBuf: PByte; OutSize: Int64): Boolean;
var E: TPACEntry;
begin
  Result := False;
  if (Index < 0) or (Index >= Length(FEntries)) then Exit;
  E := FEntries[Index];
  if OutSize < E.Size then Exit;
  if E.Size > 0 then
  begin
    FStream.Seek(E.DataOffset, soBeginning);
    FStream.ReadBuffer(OutBuf^, E.Size);
  end;
  Result := True;
end;

function TPACArchive.ReadRawBytes(Index: Integer; OutBuf: PByte): Boolean;
var E: TPACEntry;
begin
  Result := False;
  if (Index < 0) or (Index >= Length(FEntries)) then Exit;
  E := FEntries[Index];
  if E.Size > 0 then
  begin
    FStream.Seek(E.DataOffset, soBeginning);
    FStream.ReadBuffer(OutBuf^, E.Size);
  end;
  Result := True;
end;

procedure TPACWriter.AddFromBuffer(const Name: AnsiString; Buf: PByte; Size: Int64);
var L: Integer;
begin
  L := Length(FPending);
  SetLength(FPending, L + 1);
  FPending[L].Entry.Name       := Name;
  FPending[L].Entry.Size       := Size;
  FPending[L].Entry.DataOffset := 0;
  FPending[L].Entry.Hash       := CRC32_PAC_Str(Name);
  if Size > 0 then
  begin
    SetLength(FPending[L].Data, Size);
    Move(Buf^, FPending[L].Data[0], Size);
  end;
end;

procedure TPACWriter.AddRaw(const Name: AnsiString; const Data: TBytes);
var L: Integer;
begin
  L := Length(FPending);
  SetLength(FPending, L + 1);
  FPending[L].Entry.Name       := Name;
  FPending[L].Entry.Size       := Length(Data);
  FPending[L].Entry.DataOffset := 0;
  FPending[L].Entry.Hash       := CRC32_PAC_Str(Name);
  FPending[L].Data             := Copy(Data);
end;

function TPACWriter.Count: Integer;
begin
  Result := Length(FPending);
end;

// Sort indices by hash for the on-disk entry table (the Sky engine
// expects entries in ascending hash order so it can binary-search).
procedure SortByHash(var Order: array of Integer; const Pending: array of TPACPending);
var
  i, j, T: Integer;
begin
  // Insertion sort — fine for thousands of entries.
  for i := 1 to High(Order) do
  begin
    T := Order[i];
    j := i - 1;
    while (j >= 0) and (Pending[Order[j]].Entry.Hash > Pending[T].Entry.Hash) do
    begin
      Order[j + 1] := Order[j];
      Dec(j);
    end;
    Order[j + 1] := T;
  end;
end;

procedure TPACWriter.WriteToFile(const FileName: AnsiString);
var
  F: TFileStream;
  Magic: array[0..3] of AnsiChar;
  CountW, HeaderSize, Unk: LongWord;
  i, n: Integer;
  Order: array of Integer;
  NameOffsets: array of Int64;
  NamePool: TBytes;
  EntryTableSize, NamePoolSize, HeaderTotal: Int64;
  CurDataOffset: Int64;
  Reserved: LongWord;
  NameOff, Sz, DataOff: QWord;
  ZeroByte: Byte;
begin
  n := Count;
  CountW := n;
  Unk := 1;

  // Resolve final layout.
  EntryTableSize := n * 32;
  // Build the name pool and capture each name's offset relative to
  // the start of the pool. The pool sits right after the entry table
  // in the file, so absolute offset = 16 + EntryTableSize + relative.
  SetLength(NameOffsets, n);
  NamePool := nil;
  for i := 0 to n - 1 do
  begin
    NameOffsets[i] := Length(NamePool);
    SetLength(NamePool, Length(NamePool) + Length(FPending[i].Entry.Name) + 1);
    if Length(FPending[i].Entry.Name) > 0 then
      Move(FPending[i].Entry.Name[1],
           NamePool[NameOffsets[i]],
           Length(FPending[i].Entry.Name));
    NamePool[NameOffsets[i] + Length(FPending[i].Entry.Name)] := 0; // NUL term
  end;
  NamePoolSize := Length(NamePool);

  // header_size in the FPAC field = bytes from start of file to start
  // of data, i.e. 16 + entry table + name pool.
  HeaderSize := 16 + EntryTableSize + NamePoolSize;
  HeaderTotal := HeaderSize;

  // Resolve data offsets. Files are placed back-to-back, no padding.
  CurDataOffset := HeaderTotal;
  for i := 0 to n - 1 do
  begin
    FPending[i].Entry.DataOffset := CurDataOffset;
    Inc(CurDataOffset, FPending[i].Entry.Size);
  end;

  // Sort entries by hash — required for binary search at runtime.
  SetLength(Order, n);
  for i := 0 to n - 1 do Order[i] := i;
  SortByHash(Order, FPending);

  F := TFileStream.Create(FileName, fmCreate);
  try
    Magic := 'FPAC';
    F.WriteBuffer(Magic, 4);
    F.WriteBuffer(CountW, 4);
    F.WriteBuffer(HeaderSize, 4);
    F.WriteBuffer(Unk, 4);

    Reserved := 0;
    for i := 0 to n - 1 do
    begin
      F.WriteBuffer(FPending[Order[i]].Entry.Hash, 4);
      F.WriteBuffer(Reserved, 4);
      NameOff := QWord(16 + EntryTableSize + NameOffsets[Order[i]]);
      Sz      := QWord(FPending[Order[i]].Entry.Size);
      DataOff := QWord(FPending[Order[i]].Entry.DataOffset);
      F.WriteBuffer(NameOff, 8);
      F.WriteBuffer(Sz, 8);
      F.WriteBuffer(DataOff, 8);
    end;

    if NamePoolSize > 0 then
      F.WriteBuffer(NamePool[0], NamePoolSize);

    // Data section, in original (insertion) order so file offsets line
    // up with the offsets we computed above.
    ZeroByte := 0;
    for i := 0 to n - 1 do
      if Length(FPending[i].Data) > 0 then
        F.WriteBuffer(FPending[i].Data[0], Length(FPending[i].Data))
      else
        // shouldn't happen — Size = 0 entries simply have no payload
        ZeroByte := ZeroByte;  // keep compiler happy, no-op
  finally
    F.Free;
  end;
end;

end.
