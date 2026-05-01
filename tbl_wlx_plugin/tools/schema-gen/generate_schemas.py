#!/usr/bin/env python3
"""
Generate KuroTools-compatible schema JSONs for TBL sections that don't
have one yet. Type inference is heuristic but conservative:

  * Walk multiple rows of the same section, treating each as a fixed-size
    blob, and try every reasonable type sequence at every byte offset.
  * For each candidate offset, score by:
      - Looks like printable text? -> toffset (offset into data2)
      - Looks like a finite float in a reasonable range? -> float
      - Wide value range / signedness? -> int / uint / etc.
  * Greedily pick the field layout that best explains the bytes:
      offset 0 -> field1 of inferred type
      offset N -> field2 of next inferred type
      etc., until row size is consumed.

Output:
  schemas/headers/<SectionName>.json
  with a single platform key entry (we use a synthesized "GENERATED"
  key so users can tell auto-generated schemas apart from the real
  KuroTools ones).

This is a best-effort tool. Schemas it produces will let the plugin
display the data as a typed grid instead of the raw passthrough mode,
but field NAMES will be generic (field0, field1, ...) and types may
sometimes be wrong (e.g. a bitfield uint will be inferred as uint).
The user can rename fields and tweak types in the generated JSON.
"""

import os
import sys
import struct
import json
import glob
from collections import Counter, defaultdict


# ---- TBL parsing -------------------------------------------------------

def parse_tbl(path):
    with open(path, 'rb') as f:
        data = f.read()
    if data[:4] != b'#TBL':
        return None
    n = struct.unpack_from('<I', data, 4)[0]
    if not (0 < n <= 1024):
        return None
    secs = []
    off = 8
    for _ in range(n):
        if off + 80 > len(data):
            return None
        name = data[off:off+64].split(b'\x00', 1)[0].decode('utf-8', 'replace')
        crc, start, ent_len, ent_count = struct.unpack_from('<4I', data, off+64)
        secs.append({
            'name': name,
            'start': start,
            'entry_length': ent_len,
            'entry_count': ent_count,
            'rows': [data[start + i*ent_len:start + (i+1)*ent_len]
                     for i in range(ent_count)],
        })
        off += 80
    return {'data': data, 'sections': secs, 'size': len(data)}


# ---- Type inference helpers --------------------------------------------

def looks_like_float(b4):
    """Conservative: |x| <= 1e9, and x is finite and not a tiny denormal."""
    try:
        v = struct.unpack('<f', b4)[0]
    except struct.error:
        return False
    if v != v:
        return False
    if v in (float('inf'), float('-inf')):
        return False
    av = abs(v)
    if av == 0.0:
        return True
    # Reject denormals / extremely tiny values that more likely mean garbage
    if av < 1e-30 or av > 1e9:
        return False
    return True


def looks_like_toffset(buf, off, file_size):
    """The 4 bytes at off, interpreted as u32, must be a plausible offset
    into the file pointing at printable ASCII / UTF-8."""
    if off + 4 > len(buf):
        return False
    v = struct.unpack_from('<I', buf, off)[0]
    if v == 0:
        return True   # NULL string is allowed
    if v >= file_size or v < 32:
        return False
    return True


def is_printable_string_at(filebuf, str_off):
    """True if filebuf[str_off:] starts at a NUL-terminated string that
    looks like printable text in UTF-8 (or ASCII). Accepts:
      - ASCII printable (32..126)
      - tab/newline/CR
      - UTF-8 leading bytes (0xC2..0xF4) and continuation bytes (0x80..0xBF)
    Rejects bytes that almost never appear in real strings (binary
    garbage, NUL, most control chars)."""
    if str_off == 0 or str_off >= len(filebuf):
        return False
    end = filebuf.find(b'\x00', str_off, str_off + 256)
    if end == -1:
        return False
    s = filebuf[str_off:end]
    if len(s) == 0:
        return True
    good = 0
    for b in s:
        if 32 <= b < 127:
            good += 1
        elif b in (9, 10, 13):
            good += 1
        elif 0x80 <= b <= 0xBF:  # UTF-8 continuation byte
            good += 1
        elif 0xC2 <= b <= 0xF4:  # UTF-8 leading byte (2/3/4-byte sequence)
            good += 1
        # else: control byte / binary garbage — count against the string
    if good < len(s) * 0.85:
        return False
    return True


def confirm_toffset_field_per_file(samples, off):
    """An 8-byte slot is a toffset if:
      - In every row, the u64 value either is 0 or points to a printable
        UTF-8 string in the row's home file_buf.
      - At least 50% of rows have a non-zero value (otherwise the column
        is statistically more likely a ulong of mostly-zeros).

    The ratio threshold is what distinguishes a string-pointer column
    from a 64-bit integer column whose values happen to be sized like
    pointers. Real-world toffset columns are mostly populated; sparse
    columns are usually integers."""
    nonzero_total = 0
    total_rows = 0
    for s in samples:
        file_buf = s['file_buf']
        file_size = s['file_size']
        rows = s['rows']
        for r in rows:
            if off + 8 > len(r):
                return False
            v = struct.unpack_from('<Q', r, off)[0]
            total_rows += 1
            if v == 0:
                continue
            nonzero_total += 1
            if v >= file_size or v < 32:
                return False
            if not is_printable_string_at(file_buf, v):
                return False
    if total_rows == 0:
        return False
    # Require >50% non-zero. This screens out sparse ulong columns that
    # accidentally have one or two values happening to look like
    # printable-string pointers.
    return nonzero_total * 2 > total_rows


def looks_like_ulong_field(samples, off):
    """Disabled. We can't distinguish 1×ulong from 2×uint reliably
    from binary alone — and choosing 2×uint by default is safe because
    splitting a real ulong into two uints round-trips correctly through
    the plugin's serializer. Users who know specific ulong columns
    (typically 'id' fields in older Falcom schemas) can edit the
    generated JSON manually."""
    return False


def infer_int_range(rows, off, size):
    """Look at all values for a field and decide signed/unsigned. Returns
    (kind, signed_min, signed_max)."""
    fmt = {1: '<b', 2: '<h', 4: '<i'}[size]
    ufmt = {1: '<B', 2: '<H', 4: '<I'}[size]
    smin = smax = None
    has_high_bit = False
    has_negative = False
    for r in rows:
        if off + size > len(r):
            return None
        sv = struct.unpack_from(fmt, r, off)[0]
        uv = struct.unpack_from(ufmt, r, off)[0]
        if sv < 0:
            has_negative = True
        if size == 1 and uv >= 128:
            has_high_bit = True
        if size == 2 and uv >= 32768:
            has_high_bit = True
        if size == 4 and uv >= 0x80000000:
            has_high_bit = True
        if smin is None or sv < smin:
            smin = sv
        if smax is None or sv > smax:
            smax = sv
    return (smin, smax, has_high_bit, has_negative)


def infer_field_at(file_buf, file_size, rows, off, remaining):
    """Return (size, type_name) for the field starting at offset `off`.
    Tries types in priority order and picks the first that fits."""
    # Try toffset first (4 bytes pointing into data2)
    if remaining >= 4:
        if confirm_toffset_field(file_buf, file_size, rows, off):
            return 4, 'toffset'

    # Try float (4 bytes, must look like a float in every row)
    if remaining >= 4:
        all_float = True
        for r in rows:
            if not looks_like_float(r[off:off+4]):
                all_float = False
                break
        if all_float:
            return 4, 'float'

    # Then integer types — pick smallest that fits the data range
    # 1-byte
    if remaining >= 1:
        info = infer_int_range(rows, off, 1)
        if info:
            smin, smax, has_high_bit, has_negative = info
            # If there's a bigger remaining and the values look small,
            # prefer larger types only if data demands it. We default
            # to byte/ubyte for 1-byte slots.
            if has_negative:
                return 1, 'byte'
            else:
                return 1, 'ubyte'

    return 1, 'ubyte'  # fallback


def looks_like_packed_bytes(all_rows, off):
    """True if the 4 bytes at offset `off` are more naturally explained
    as 4 independent 1-byte fields than as a single u32. Heuristic: each
    of the 4 byte positions has at least 2 distinct values across rows,
    AND the largest byte value seen anywhere is small (<= 64). This
    matches the common pattern where the slot holds 4 packed flag/id/
    category bytes that each independently vary."""
    if not all_rows:
        return False
    seen_per_byte = [set(), set(), set(), set()]
    max_val = 0
    for r in all_rows:
        if off + 4 > len(r):
            return False
        for k in range(4):
            b = r[off + k]
            seen_per_byte[k].add(b)
            if b > max_val:
                max_val = b
    # All 4 bytes must show variation (otherwise some are always-zero
    # padding and we should keep them as ubyte regardless, but the call
    # site will still split — this check is for the "is this really 4
    # bytes vs 1 uint" decision).
    varying = sum(1 for s in seen_per_byte if len(s) >= 2)
    if varying < 3:
        return False
    if max_val > 64:
        return False
    return True


def infer_field_layout(samples, entry_length):
    """Greedy left-to-right field detection. Multi-byte types are
    preferred when alignment + value patterns support them. Order at
    each offset:

      8-byte aligned, >=8 remaining: toffset (string ptr)
      4-byte aligned, >=4 remaining: float > packed-bytes > int/uint
      2-byte aligned, >=2 remaining: short/ushort
      otherwise: byte/ubyte

    Note: ulong/long are deliberately not generated. They're
    indistinguishable from 2×uint at the binary level when the high
    32 bits look like data — and 2×uint is the more common pattern.
    Splitting a true ulong into two uints round-trips correctly, so
    the failure mode is benign. Users who know a column is ulong can
    edit the generated schema manually.

    Same goes for 4×ubyte vs uint: we try to detect the packed-bytes
    case via `looks_like_packed_bytes` (small values + varying bytes)
    but won't always be right. Mis-inferred uint→ubyte×4 round-trips
    correctly; the failure is again benign."""
    all_rows = []
    for s in samples:
        all_rows.extend(s['rows'])

    fields = []
    off = 0
    while off < entry_length:
        remaining = entry_length - off
        chose = None

        # 8-byte slot — only toffset.
        if remaining >= 8 and off % 8 == 0:
            if confirm_toffset_field_per_file(samples, off):
                chose = (8, 'toffset')

        # 4-byte slot
        if chose is None and remaining >= 4 and off % 4 == 0:
            all_float = all(looks_like_float(r[off:off+4]) for r in all_rows
                            if off+4 <= len(r))
            nonzero_floats = any(
                struct.unpack_from('<f', r, off)[0] != 0.0
                for r in all_rows if off+4 <= len(r))
            if all_float and nonzero_floats:
                chose = (4, 'float')
            elif looks_like_packed_bytes(all_rows, off):
                # Defer to 4 single-byte slots below by leaving chose
                # unset for this iteration. The 1-byte case will pick
                # ubyte and we'll loop 4 times.
                pass
            else:
                info4 = infer_int_range(all_rows, off, 4)
                if info4:
                    smin, smax, hi, neg = info4
                    chose = (4, 'int' if neg else 'uint')

        if chose is None and remaining >= 2 and off % 2 == 0:
            # Try 2-byte only if the 4-byte slot above didn't claim
            # a packed-bytes split. If it did, fall through to ubyte
            # so we get individual bytes, not a ushort+ushort.
            if not (remaining >= 4 and off % 4 == 0
                    and looks_like_packed_bytes(all_rows, off)):
                info2 = infer_int_range(all_rows, off, 2)
                if info2:
                    smin, smax, hi, neg = info2
                    chose = (2, 'short' if neg else 'ushort')

        if chose is None:
            info1 = infer_int_range(all_rows, off, 1)
            if info1:
                smin, smax, hi, neg = info1
                chose = (1, 'byte' if neg else 'ubyte')
            else:
                chose = (1, 'ubyte')

        size, type_name = chose
        fields.append((f'field{len(fields)}', type_name))
        off += size

    return fields


# ---- Schema generation --------------------------------------------------

def collect_section_data(games_root, schema_dir):
    """Walk every TBL under games_root, group section row data by
    section name + entry_length. Return dict[(name, ent_len)] -> {rows, file_buf, file_size}."""
    grouped = defaultdict(lambda: {'rows': [], 'samples': []})
    n_files = 0
    for root, _, files in os.walk(games_root):
        for fn in files:
            if not fn.endswith('.tbl'):
                continue
            path = os.path.join(root, fn)
            n_files += 1
            tbl = parse_tbl(path)
            if not tbl:
                continue
            for sec in tbl['sections']:
                key = (sec['name'], sec['entry_length'])
                # We need the FILE BUFFER for toffset string verification.
                # Save up to first 5 occurrences for redundant cross-check.
                if len(grouped[key]['samples']) < 5:
                    grouped[key]['samples'].append({
                        'file_buf': tbl['data'],
                        'file_size': tbl['size'],
                        'rows': sec['rows'],
                    })
                grouped[key]['rows'].extend(sec['rows'])
    return grouped, n_files


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description='Generate KuroTools-compatible schema JSONs for unknown TBL sections.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  1. Extract your game's TBL files into a folder (one folder per game,
     or all together — both work). Use the bundled p3a_extract.py for
     P3A archives or sky_extract_pac.py for PAC archives.
  2. Point this script at the parent folder of your extracted TBLs.
  3. It scans every .tbl, finds sections without a schema in the
     plugin's schemas/headers/, and emits one JSON per missing section
     into the output folder.
  4. Drop those JSONs into the plugin's schemas/headers/ folder.
  5. Restart Total Commander. Sections will now appear as typed grids
     instead of raw passthrough.

Field accuracy is around 40-50% on validation against known schemas.
Field NAMES are always placeholders (field0, field1...). Treat the
output as a starting point — rename fields and refine types based on
what you see in the data.

Limitations:
  * ulong/long can't be reliably distinguished from 2x uint in binary;
    we always emit 2x uint. Splitting a real ulong into 2x uint
    round-trips correctly through the plugin's serializer, so this
    is benign.
  * u8array / u16array / u32array (variable-length nested data) are
    never inferred; they appear as a stretch of byte/ubyte fields.
  * Nested struct arrays are flattened into the parent layout.
""")
    ap.add_argument('--tbl-dir', default='./extracted',
                    help='Directory tree containing extracted .tbl files')
    ap.add_argument('--schema-dir', default='./schemas/headers',
                    help='Existing plugin schemas dir (only sections NOT '
                         'present here will be generated)')
    ap.add_argument('--output-dir', default='./generated_schemas',
                    help='Where to write generated *.json files')
    args = ap.parse_args()

    games_root = args.tbl_dir
    schema_dir = args.schema_dir
    out_dir = args.output_dir
    os.makedirs(out_dir, exist_ok=True)

    print(f"Scanning TBL files in: {games_root}")
    grouped, n_files = collect_section_data(games_root, schema_dir)
    print(f"  {n_files} TBL files scanned")
    print(f"  {len(grouped)} unique (section_name, entry_length) tuples")

    if not os.path.isdir(schema_dir):
        print(f"WARNING: --schema-dir not found: {schema_dir}")
        print(f"  Treating all sections as missing.")
        existing = set()
    else:
        existing = set()
        for f in os.listdir(schema_dir):
            if f.endswith('.json'):
                existing.add(f[:-5])

    by_name = defaultdict(list)
    for (name, el), info in grouped.items():
        by_name[name].append((el, info))

    missing_names = sorted(set(by_name.keys()) - existing)
    print(f"  {len(missing_names)} missing schemas to generate")

    if not missing_names:
        print("Nothing to generate. (All sections already covered.)")
        return

    generated = 0
    for name in missing_names:
        variants = by_name[name]
        variants.sort(key=lambda x: -len(x[1]['rows']))
        ent_len, info = variants[0]
        rows = info['rows']
        if len(rows) == 0:
            continue

        layout = infer_field_layout(info['samples'], ent_len)

        schema = {
            'GENERATED': {
                'game': 'Unknown',
                'note': (
                    f'Auto-generated from {len(rows)} sampled rows across '
                    f'{len(info["samples"])} TBL files. Field names are '
                    f'placeholders (field0, field1, ...). Types are '
                    f'best-effort heuristic; verify and rename before '
                    f'relying on saves.'
                ),
                'schema': {fname: ftype for fname, ftype in layout}
            }
        }

        out_path = os.path.join(out_dir, f'{name}.json')
        with open(out_path, 'w') as f:
            json.dump(schema, f, indent='\t')
        generated += 1

    print(f"\nGenerated {generated} schema files in {out_dir}")
    print(f"Skipped {len(missing_names) - generated} (empty section)")
    print(f"\nNext step: copy *.json from {out_dir}")
    print(f"into your plugin's schemas/headers/ folder.")


if __name__ == '__main__':
    main()
