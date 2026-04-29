unit lz4comp;
{$mode objfpc}{$H+}

// LZ4 compression: thin Pascal wrapper that statically links the
// official LZ4 reference C implementation (lib/lz4.c from the lz4
// project). Build the C side first into a COFF (Win) / ELF (Linux)
// object file named "lz4obj.o" sitting next to this file, then fpc
// will pick it up via the {$L} directive at the bottom.

interface

// Compresses Src..Src+SrcSize-1 into Dst (capacity DstCapacity bytes).
// Returns compressed size on success, 0 on failure.
function LZ4_compress_default(Src, Dst: PByte; SrcSize, DstCapacity: LongInt): LongInt; cdecl; external;

// Recommended worst-case output size for a given input.
function LZ4_compressBound(InputSize: LongInt): LongInt; cdecl; external;

implementation

// libc replacements that the linked lz4.o references. The C code uses
// memcpy/memmove/memset/calloc/free; we route them to FPC's own
// runtime so we don't need to drag in libc.
function memcpy(Dst, Src: Pointer; N: PtrUInt): Pointer; cdecl; public name 'memcpy';
begin
  Move(Src^, Dst^, N);
  Result := Dst;
end;

function memmove(Dst, Src: Pointer; N: PtrUInt): Pointer; cdecl; public name 'memmove';
begin
  Move(Src^, Dst^, N);
  Result := Dst;
end;

function memset(Dst: Pointer; C: LongInt; N: PtrUInt): Pointer; cdecl; public name 'memset';
begin
  FillChar(Dst^, N, Byte(C));
  Result := Dst;
end;

function calloc(Num, Size: PtrUInt): Pointer; cdecl; public name 'calloc';
begin
  GetMem(Result, Num * Size);
  FillChar(Result^, Num * Size, 0);
end;

procedure free_(P: Pointer); cdecl; public name 'free';
begin
  if P <> nil then FreeMem(P);
end;

// __chkstk_ms is mingw's stack-probe helper. For small allocations
// it's effectively a no-op. The COFF symbol on Win64 has 3 leading
// underscores; ELF on Linux has 2.
procedure chkstk_ms; cdecl;
  {$IFDEF MSWINDOWS}
  public name '___chkstk_ms';
  {$ELSE}
  public name '__chkstk_ms';
  {$ENDIF}
begin
end;

{$L lz4obj.o}

end.
