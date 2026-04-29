unit zstddec;
{$mode objfpc}{$H+}

// ZSTD decompression: thin Pascal wrapper around the official ZSTD
// reference C implementation (single-file decoder from
// github.com/facebook/zstd, contrib/single_file_libs/zstddeclib.c).
// Build the C side first into a COFF (Win) / ELF (Linux) object file
// named "zstdobj.o" sitting next to this file, then fpc will pick it
// up via the {$L} directive at the bottom.
//
// Only decompression is provided. Most P3A archives use ZSTD only for
// reading; new entries produced by this plugin go via LZ4. ZSTD
// entries already present in an archive are preserved verbatim during
// modifications (see TP3AWriter.AddFromCompressed).

interface

// ZSTD's size_t-shaped return values: success returns the byte count,
// errors return values >= -ZSTD_error_maxCode (very large unsigned).
// Use ZSTD_isError to distinguish.

function ZSTD_decompress(Dst: PByte; DstCapacity: PtrUInt;
                         Src: PByte; SrcSize: PtrUInt): PtrUInt; cdecl; external;

function ZSTD_decompress_usingDict(Dctx: Pointer;
                                   Dst: PByte; DstCapacity: PtrUInt;
                                   Src: PByte; SrcSize: PtrUInt;
                                   Dict: PByte; DictSize: PtrUInt): PtrUInt; cdecl; external;

function ZSTD_createDCtx: Pointer; cdecl; external;
function ZSTD_freeDCtx(Dctx: Pointer): PtrUInt; cdecl; external;
function ZSTD_isError(Code: PtrUInt): LongInt; cdecl; external;

implementation

// libc replacement that the linked zstdobj.o references in addition
// to the ones already provided by lz4comp (memcpy/memmove/memset/
// calloc/free/__chkstk_ms). ZSTD allocates working buffers via
// malloc, LZ4 doesn't, so this stub lives here.
function malloc_(N: PtrUInt): Pointer; cdecl; public name 'malloc';
begin
  GetMem(Result, N);
end;

{$L zstdobj.o}

end.
