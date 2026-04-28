unit p3alib;
{$mode objfpc}{$H+}

// P3A archive format reader. Supports versions 1100 and 1200.
// Compression types supported: 0 (none), 1 (lz4). Types 2/3 (zstd) are
// reported but extraction returns "unsupported".

interface

uses Classes, SysUtils;

type
  TP3AEntry = record
    Name: AnsiString;       // file path inside archive (forward slashes)
    CmpType: Int64;         // 0=none, 1=lz4, 2=zstd, 3=zstd-dict
    CmpSize: Int64;
    UncSize: Int64;
    Offset: Int64;
    CmpHash: QWord;
    UncHash: QWord;
    HasUncHash: Boolean;
  end;
  TP3AEntryArray = array of TP3AEntry;

  TP3AArchive = class
  private
    FStream: TFileStream;
    FVersion: LongWord;
    FFlags: LongWord;
    FEntries: TP3AEntryArray;
  public
    constructor Create(const FileName: AnsiString);
    destructor Destroy; override;
    function ExtractEntry(Index: Integer; OutBuf: PByte; OutSize: Int64): Boolean;
    property Entries: TP3AEntryArray read FEntries;
    property Version: LongWord read FVersion;
    property Flags: LongWord read FFlags;
  end;

  EP3A = class(Exception);

implementation

uses lz4dec;

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
  FStream := TFileStream.Create(FileName, fmOpenRead or fmShareDenyWrite);

  // ---- magic ----
  FStream.ReadBuffer(Magic, 8);
  if (Magic[0] <> 'P') or (Magic[1] <> 'H') or (Magic[2] <> '3')
     or (Magic[3] <> 'A') or (Magic[4] <> 'R') or (Magic[5] <> 'C')
     or (Magic[6] <> 'V') or (Magic[7] <> #0) then
    raise EP3A.Create('not a P3A archive (bad magic)');

  // ---- header ----
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

  // ---- TOC entries ----
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
    // No compression -- read directly into output.
    FStream.ReadBuffer(OutBuf^, E.UncSize);
    Result := True;
    Exit;
  end;

  // Compressed: read into temp buffer, decompress.
  GetMem(CmpBuf, E.CmpSize);
  try
    FStream.ReadBuffer(CmpBuf^, E.CmpSize);
    case E.CmpType of
      1:
        begin
          Got := LZ4_Decompress_Block(CmpBuf, E.CmpSize, OutBuf, E.UncSize);
          Result := (Got = E.UncSize);
        end;
      2, 3:
        begin
          // ZSTD not supported in this build.
          Result := False;
        end;
    else
      Result := False;
    end;
  finally
    FreeMem(CmpBuf);
  end;
end;

end.
