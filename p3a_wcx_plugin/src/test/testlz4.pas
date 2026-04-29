program testlz4;
{$mode objfpc}{$H+}
uses lz4dec, SysUtils;

var
  // The compressed and decompressed test vectors are filled in from external
  // hex strings produced by Python's lz4.block module. This program reads
  // pairs of hex strings from stdin: line 1 = compressed, line 2 = expected.
  CmpHex, DecHex: AnsiString;
  CmpBuf, DecBuf, OutBuf: array of Byte;
  i: Integer;
  Got: PtrInt;

function HexToBytes(const S: AnsiString): TBytes;
var
  i, n: Integer;
begin
  n := Length(S) div 2;
  SetLength(Result, n);
  for i := 0 to n - 1 do
    Result[i] := StrToInt('$' + Copy(S, i * 2 + 1, 2));
end;

procedure RunCase(N: Integer; const CmpHex, DecHex: AnsiString);
var
  Cmp, Dec, Out_: TBytes;
  Got: PtrInt;
  i: Integer;
  Match: Boolean;
begin
  Cmp := HexToBytes(CmpHex);
  Dec := HexToBytes(DecHex);
  SetLength(Out_, Length(Dec));

  if Length(Out_) > 0 then
    Got := LZ4_Decompress_Block(@Cmp[0], Length(Cmp), @Out_[0], Length(Out_))
  else
    Got := LZ4_Decompress_Block(@Cmp[0], Length(Cmp), nil, 0);

  Match := (Got = Length(Dec));
  if Match then
    for i := 0 to Length(Dec) - 1 do
      if Out_[i] <> Dec[i] then begin Match := False; Break; end;

  if Match then
    WriteLn('case ', N, ': OK  (', Length(Cmp), ' -> ', Length(Dec), ' bytes)')
  else
  begin
    WriteLn('case ', N, ': FAIL  expected ', Length(Dec), ', got ', Got);
    Write('  out_first16  =');
    for i := 0 to 15 do
      if i < Length(Out_) then Write(' ', IntToHex(Out_[i], 2));
    WriteLn;
    Write('  want_first16 =');
    for i := 0 to 15 do
      if i < Length(Dec) then Write(' ', IntToHex(Dec[i], 2));
    WriteLn;
  end;
end;

var
  N: Integer = 0;
begin
  while not EOF do
  begin
    ReadLn(CmpHex);
    if EOF then Break;
    ReadLn(DecHex);
    Inc(N);
    RunCase(N, CmpHex, DecHex);
  end;
end.
