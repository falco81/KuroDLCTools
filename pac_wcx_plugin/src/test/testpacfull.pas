program testpacfull;
{$mode objfpc}{$H+}

uses SysUtils, paclib;

procedure ExtractToMap(const Path: AnsiString;
                       out Names: array of AnsiString;
                       out Sizes: array of Int64;
                       out Hashes: array of LongWord);
var
  A: TPACArchive;
  i: Integer;
begin
  A := TPACArchive.Create(Path);
  try
    for i := 0 to High(A.Entries) do
    begin
      Names[i]  := A.Entries[i].Name;
      Sizes[i]  := A.Entries[i].Size;
      Hashes[i] := A.Entries[i].Hash;
    end;
  finally
    A.Free;
  end;
end;

function FNV1a(P: PByte; Len: Int64): QWord;
var i: Int64;
begin
  Result := QWord($cbf29ce484222325);
  for i := 0 to Len - 1 do
  begin
    Result := Result xor P[i];
    Result := Result * QWord($00000100000001B3);
  end;
end;

procedure CompareContents(const PathA, PathB: AnsiString);
var
  A, B: TPACArchive;
  i, j, k: Integer;
  Buf: TBytes;
  HA, HB: QWord;
  Mismatched: Integer;
begin
  A := TPACArchive.Create(PathA);
  B := TPACArchive.Create(PathB);
  try
    if Length(A.Entries) <> Length(B.Entries) then
    begin
      WriteLn('FAIL: entry count differs (', Length(A.Entries), ' vs ', Length(B.Entries), ')');
      Halt(2);
    end;
    Mismatched := 0;
    for i := 0 to High(A.Entries) do
    begin
      // Find the same name in B
      j := -1;
      for k := 0 to High(B.Entries) do
        if B.Entries[k].Name = A.Entries[i].Name then
        begin j := k; Break; end;
      if j < 0 then
      begin
        WriteLn('FAIL: ', A.Entries[i].Name, ' missing in B');
        Inc(Mismatched);
        Continue;
      end;

      // Sizes must match
      if A.Entries[i].Size <> B.Entries[j].Size then
      begin
        WriteLn('FAIL: ', A.Entries[i].Name, ' size differs (',
                A.Entries[i].Size, ' vs ', B.Entries[j].Size, ')');
        Inc(Mismatched);
        Continue;
      end;

      if A.Entries[i].Size = 0 then Continue;

      // Compare actual bytes via hash
      SetLength(Buf, A.Entries[i].Size);
      A.ExtractEntry(i, @Buf[0], A.Entries[i].Size);
      HA := FNV1a(@Buf[0], Length(Buf));
      B.ExtractEntry(j, @Buf[0], B.Entries[j].Size);
      HB := FNV1a(@Buf[0], Length(Buf));
      if HA <> HB then
      begin
        WriteLn('FAIL: ', A.Entries[i].Name, ' content differs');
        Inc(Mismatched);
      end;
    end;
    WriteLn('Compared ', Length(A.Entries), ' entries; mismatches: ', Mismatched);
    if Mismatched > 0 then Halt(2);
    WriteLn('CONTENT IDENTICAL');
  finally
    A.Free; B.Free;
  end;
end;

begin
  if ParamCount < 2 then
  begin
    WriteLn('usage: testpacfull <a.pac> <b.pac>');
    Halt(1);
  end;
  CompareContents(ParamStr(1), ParamStr(2));
end.
