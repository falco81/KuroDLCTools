program testxxh;
{$mode objfpc}{$H+}
uses xxhash64, SysUtils;

procedure Check(const Name: AnsiString; const Buf; Len: PtrUInt; Seed, Expected: QWord);
var
  H: QWord;
begin
  H := XXH64(@Buf, Len, Seed);
  if H = Expected then
    WriteLn(Name, ': OK (0x', IntToHex(H, 16), ')')
  else
    WriteLn(Name, ': FAIL  got 0x', IntToHex(H, 16), '  want 0x', IntToHex(Expected, 16));
end;

var
  Empty: array[0..0] of Byte = (0);
  HelloBuf: array[0..4] of Byte = ($68, $65, $6C, $6C, $6F); // "hello"
  Long32: array[0..31] of Byte = (0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,
                                  16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31);
  Long40: array[0..39] of Byte = (0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,
                                  16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,
                                  32,33,34,35,36,37,38,39);
begin
  // Reference values computed with Python xxhash module:
  //   xxhash.xxh64(b'').intdigest()       == 0xef46db3751d8e999
  //   xxhash.xxh64(b'hello').intdigest()  == 0x26c7827d889f6da3
  //   xxhash.xxh64(buf32, seed=0)         == ...
  //   xxhash.xxh64(buf40, seed=0xdeadbeef) == ...
  Check('empty(seed=0)',       Empty, 0, 0,             QWord($EF46DB3751D8E999));
  Check('hello(seed=0)',       HelloBuf, 5, 0,           QWord($26C7827D889F6DA3));
  Check('hello(seed=0xCAFE)',  HelloBuf, 5, $CAFE,       QWord($09EF7D048031FAB4));
  Check('32B(seed=0)',         Long32, 32, 0,            QWord($CBF59C5116FF32B4));
  Check('40B(seed=0xDEADBEEF)', Long40, 40, $DEADBEEF,   QWord($F615B15718412F1A));
end.
