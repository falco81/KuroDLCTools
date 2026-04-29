program testlz4c;
{$mode objfpc}{$H+}
uses lz4comp, lz4dec, SysUtils;

var
  src, cmp, rt: array of Byte;
  n, csz, rsz: PtrInt;
  i: Integer;
  ok: Boolean;
begin
  // Build a test buffer with some repetition
  n := 4096;
  SetLength(src, n);
  for i := 0 to n - 1 do
    src[i] := Byte((i * 7 + 3) mod 251);
  // Add a repetitive segment to give LZ4 something to match
  for i := 1000 to 1999 do
    src[i] := src[i mod 1000];

  SetLength(cmp, LZ4_compressBound(n));
  csz := LZ4_compress_default(@src[0], @cmp[0], n, Length(cmp));
  WriteLn('compress: ', n, ' -> ', csz, ' bytes (ratio ', (csz * 100) div n, '%)');

  if csz <= 0 then
  begin
    WriteLn('compression FAILED');
    Halt(1);
  end;

  // Round-trip via our pure-Pascal decompressor
  SetLength(rt, n);
  rsz := LZ4_Decompress_Block(@cmp[0], csz, @rt[0], n);
  WriteLn('decompress -> ', rsz, ' bytes');

  if rsz <> n then
  begin
    WriteLn('decompress size mismatch');
    Halt(1);
  end;

  ok := True;
  for i := 0 to n - 1 do
    if rt[i] <> src[i] then begin ok := False; Break; end;

  if ok then
    WriteLn('round-trip: OK')
  else
    WriteLn('round-trip: FAIL at index ', i);
end.
