unit xxhash64;
{$mode objfpc}{$H+}

// Pure Pascal implementation of XXH64.
// Reference: https://github.com/Cyan4973/xxHash/blob/dev/doc/xxhash_spec.md

interface

function XXH64(Buf: Pointer; Len: PtrUInt; Seed: QWord): QWord;

implementation

const
  P1: QWord = QWord($9E3779B185EBCA87);
  P2: QWord = QWord($C2B2AE3D27D4EB4F);
  P3: QWord = QWord($165667B19E3779F9);
  P4: QWord = QWord($85EBCA77C2B2AE63);
  P5: QWord = QWord($27D4EB2F165667C5);

function Rotl64(X: QWord; N: Integer): QWord; inline;
begin
  Result := (X shl N) or (X shr (64 - N));
end;

function Read64LE(P: PByte): QWord; inline;
begin
  // x86/x64 is little-endian, so we can just read directly.
  Result := PQWord(P)^;
end;

function Read32LE(P: PByte): LongWord; inline;
begin
  Result := PLongWord(P)^;
end;

function Round64(Acc, Input: QWord): QWord; inline;
begin
  Acc := Acc + Input * P2;
  Acc := Rotl64(Acc, 31);
  Result := Acc * P1;
end;

function MergeRound(Acc, Val: QWord): QWord; inline;
begin
  Val := Round64(0, Val);
  Acc := Acc xor Val;
  Result := Acc * P1 + P4;
end;

function XXH64(Buf: Pointer; Len: PtrUInt; Seed: QWord): QWord;
var
  P, BEnd, Limit: PByte;
  V1, V2, V3, V4, H64, K1: QWord;
begin
  P := PByte(Buf);
  BEnd := P + Len;

  if Len >= 32 then
  begin
    Limit := BEnd - 32;
    V1 := Seed + P1 + P2;
    V2 := Seed + P2;
    V3 := Seed + 0;
    V4 := Seed - P1;

    repeat
      V1 := Round64(V1, Read64LE(P)); Inc(P, 8);
      V2 := Round64(V2, Read64LE(P)); Inc(P, 8);
      V3 := Round64(V3, Read64LE(P)); Inc(P, 8);
      V4 := Round64(V4, Read64LE(P)); Inc(P, 8);
    until P > Limit;

    H64 := Rotl64(V1, 1) + Rotl64(V2, 7) + Rotl64(V3, 12) + Rotl64(V4, 18);
    H64 := MergeRound(H64, V1);
    H64 := MergeRound(H64, V2);
    H64 := MergeRound(H64, V3);
    H64 := MergeRound(H64, V4);
  end
  else
    H64 := Seed + P5;

  H64 := H64 + QWord(Len);

  while P + 8 <= BEnd do
  begin
    K1 := Round64(0, Read64LE(P));
    H64 := H64 xor K1;
    H64 := Rotl64(H64, 27) * P1 + P4;
    Inc(P, 8);
  end;

  if P + 4 <= BEnd then
  begin
    H64 := H64 xor (QWord(Read32LE(P)) * P1);
    H64 := Rotl64(H64, 23) * P2 + P3;
    Inc(P, 4);
  end;

  while P < BEnd do
  begin
    H64 := H64 xor (QWord(P^) * P5);
    H64 := Rotl64(H64, 11) * P1;
    Inc(P);
  end;

  H64 := H64 xor (H64 shr 33);
  H64 := H64 * P2;
  H64 := H64 xor (H64 shr 29);
  H64 := H64 * P3;
  H64 := H64 xor (H64 shr 32);

  Result := H64;
end;

end.
