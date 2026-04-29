unit crc32pac;
{$mode objfpc}{$H+}

// CRC32 used by Trails-in-the-Sky FPAC archives for entry hashing.
//
// The hash stored in each file entry is "zlib CRC32 with final XOR
// undone" — i.e., the running 32-bit register state after processing
// the bytes of the lowercase entry name (UTF-8). Equivalent to:
//     zlib.crc32(name.encode('utf-8')) ^ 0xFFFFFFFF
// in Python.
//
// Sky tooling sorts the entry table by this hash so the game can do
// a binary search at runtime.

interface

function CRC32_PAC(const Buf; Len: PtrUInt): LongWord;
function CRC32_PAC_Str(const S: AnsiString): LongWord;

implementation

var
  Tab: array[0..255] of LongWord;
  TabReady: Boolean = False;

procedure InitTable;
const POLY = $EDB88320;
var i, j: Integer; C: LongWord;
begin
  for i := 0 to 255 do
  begin
    C := LongWord(i);
    for j := 0 to 7 do
      if (C and 1) = 1 then C := (C shr 1) xor POLY
      else                  C := C shr 1;
    Tab[i] := C;
  end;
  TabReady := True;
end;

function CRC32_PAC(const Buf; Len: PtrUInt): LongWord;
var
  P: PByte;
  i: PtrUInt;
  C: LongWord;
begin
  if not TabReady then InitTable;
  C := $FFFFFFFF;
  P := @Buf;
  for i := 0 to Len - 1 do
    C := (C shr 8) xor Tab[(C xor P[i]) and $FF];
  // For FPAC: return the register state directly, NOT XORed with FFFFFFFF
  // (matches Python's `zlib.crc32(x) ^ 0xFFFFFFFF`).
  Result := C;
end;

function CRC32_PAC_Str(const S: AnsiString): LongWord;
begin
  if S = '' then
    Result := $FFFFFFFF
  else
    Result := CRC32_PAC(S[1], Length(S));
end;

end.
