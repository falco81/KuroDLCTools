unit lz4dec;
{$mode objfpc}{$H+}

// Pure Pascal implementation of LZ4 block decompression.
// Format reference: https://github.com/lz4/lz4/blob/dev/doc/lz4_Block_format.md

interface

// Decompress an LZ4 block. SrcLen is the size of the compressed data; the
// decompressor returns when it has produced exactly DstLen bytes (which
// must match the original uncompressed size). Returns the number of bytes
// produced on success, or -1 on bad data.
function LZ4_Decompress_Block(Src: PByte; SrcLen: PtrUInt;
                              Dst: PByte; DstLen: PtrUInt): PtrInt;

implementation

function LZ4_Decompress_Block(Src: PByte; SrcLen: PtrUInt;
                              Dst: PByte; DstLen: PtrUInt): PtrInt;
var
  S, SEnd, D, DEnd, DStart, MatchPos: PByte;
  Token, B: Byte;
  LitLen, MatLen: PtrUInt;
  Offset: Word;
  i: PtrUInt;
begin
  Result := -1;
  S := Src;
  SEnd := Src + SrcLen;
  DStart := Dst;
  D := Dst;
  DEnd := Dst + DstLen;

  while True do
  begin
    if S >= SEnd then Exit;
    Token := S^; Inc(S);

    // ---- literal length ----
    LitLen := Token shr 4;
    if LitLen = 15 then
      repeat
        if S >= SEnd then Exit;
        B := S^; Inc(S);
        Inc(LitLen, B);
      until B <> 255;

    // ---- copy literals ----
    if LitLen > 0 then
    begin
      if (S + LitLen > SEnd) or (D + LitLen > DEnd) then Exit;
      Move(S^, D^, LitLen);
      Inc(S, LitLen);
      Inc(D, LitLen);
    end;

    // End of block: last sequence is literals only, no match.
    if S >= SEnd then
    begin
      if D = DEnd then
        Result := PtrInt(D - DStart);
      Exit;
    end;

    // ---- match offset (2 bytes, little-endian) ----
    if S + 2 > SEnd then Exit;
    Offset := PWord(S)^;
    Inc(S, 2);
    if Offset = 0 then Exit;

    // ---- match length (minimum match is 4 bytes) ----
    MatLen := Token and $0F;
    if MatLen = 15 then
      repeat
        if S >= SEnd then Exit;
        B := S^; Inc(S);
        Inc(MatLen, B);
      until B <> 255;
    Inc(MatLen, 4);

    // ---- copy match ----
    MatchPos := D - Offset;
    if MatchPos < DStart then Exit;
    if D + MatLen > DEnd then Exit;

    // Byte-by-byte copy in case of overlap (offset < match_length).
    // This is the safe, format-correct way; perf is fine for archive-extract use.
    for i := 1 to MatLen do
    begin
      D^ := MatchPos^;
      Inc(D);
      Inc(MatchPos);
    end;
  end;
end;

end.
