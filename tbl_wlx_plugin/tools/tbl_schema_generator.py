#!/usr/bin/env python3
"""
Generate KuroTools-compatible schema JSONs for TBL sections that don't
yet have a schema in the plugin's schemas/headers/ folder.

Usage
-----
  python tbl_schema_generator.py <input_dir> <output_dir>
                                 [--schemas-dir <plugin_schemas_dir>]

  <input_dir>           folder with .tbl files (recursive scan; can mix
                        multiple games, the tool groups by section name)
  <output_dir>          where to write generated <SectionName>.json files
  --schemas-dir DIR     existing schemas/headers folder; sections that
                        already have a schema there will NOT be
                        regenerated. Optional. If you want to regenerate
                        everything, omit this flag.

How it works
------------
For every TBL it can parse, it gathers sections by (name, entry_length).
For each missing section it:
  1. Pools rows from all sample files
  2. Infers a field layout via greedy left-to-right type detection
     - 8-byte aligned slot whose u64 (mostly) dereferences to a printable
       UTF-8 string in its file's data2 region -> toffset
     - 4-byte slot with all values looking like floats -> float
     - 4-byte slot with mostly small varying bytes -> 4 ubytes (packed)
     - otherwise int/uint/short/ushort/byte/ubyte by alignment + range
  3. Writes <SectionName>.json with placeholder field names
     (field0, field1, ...) and the inferred types

Limitations
-----------
* Field names are always generic. You'll want to rename them.
* The tool deliberately avoids inferring 'long'/'ulong' (8-byte int).
  At binary level you can't tell a true 8-byte int from two adjacent
  4-byte ints. We pick 2x uint as the conservative default; if you
  KNOW a column is ulong (rare), edit the generated JSON.
* Same for 4xubyte vs 1xuint: we try a heuristic ('packed bytes' if
  bytes vary independently with small max value) but won't always be
  right. Mis-detection round-trips fine; just types displayed in the
  grid will be slightly off.
* Nested array fields (arrays-of-structs) are NOT inferred. If a
  schema you generate doesn't quite fit the data when you try to load
  it, the section likely has a nested array — write that part of the
  schema by hand.

Drop the generated JSONs into the plugin's
schemas/headers/<SectionName>.json and restart Total Commander.
"""

import os
import sys
import struct
import json
import argparse
from collections import defaultdict


# ---- TBL parsing -------------------------------------------------------

def parse_tbl(path):
    """Parse a .tbl. Returns dict with .data (full file bytes), .size,
    and .sections (list of dicts: name, entry_length, entry_count, rows).
    Returns None if the file isn't a recognizable plain #TBL."""
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        return None
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
        if not name:
            return None
        crc, start, ent_len, ent_count = struct.unpack_from('<4I', data, off+64)
        if start + ent_len * ent_count > len(data):
            return None
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

def is_printable_string_at(filebuf, str_off):
    """True if filebuf[str_off:] is a NUL-terminated string of mostly
    printable bytes (ASCII + UTF-8 multi-byte sequences)."""
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
        elif 0x80 <= b <= 0xBF:
            good += 1
        elif 0xC2 <= b <= 0xF4:
            good += 1
    return good >= len(s) * 0.85


def confirm_toffset_field(samples, off):
    """An 8-byte slot is a toffset if every row's u64 either is 0 or
    points to a printable string in that row's home file_buf, AND at
    least 50% of rows have a non-zero value.

    The 50% threshold separates real toffset columns (mostly populated)
    from 64-bit integer columns whose values happen to fall into
    printable-byte ranges by accident."""
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
    return nonzero_total * 2 > total_rows


def looks_like_float(b4):
    """Conservative: x finite and |x| in (1e-30, 1e9), or exactly 0."""
    try:
        v = struct.unpack('<f', b4)[0]
    except struct.error:
        return False
    if v != v or v in (float('inf'), float('-inf')):
        return False
    av = abs(v)
    if av == 0.0:
        return True
    return 1e-30 < av < 1e9


def looks_like_packed_bytes(all_rows, off):
    """True if 4 bytes at off are more naturally explained as 4
    independent 1-byte fields than as a single u32. Each byte position
    must vary across rows (>= 2 distinct values) AND the largest byte
    seen anywhere must be <= 64 (small flag/id values, not part of a
    large-range integer)."""
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
    varying = sum(1 for s in seen_per_byte if len(s) >= 2)
    return varying >= 3 and max_val <= 64


def infer_int_range(rows, off, size):
    """Walk rows, return (smin, smax, has_high_bit, has_negative) or None."""
    if size == 1:
        sfmt, ufmt = '<b', '<B'
    elif size == 2:
        sfmt, ufmt = '<h', '<H'
    elif size == 4:
        sfmt, ufmt = '<i', '<I'
    else:
        return None
    smin = smax = None
    has_high = has_neg = False
    for r in rows:
        if off + size > len(r):
            return None
        sv = struct.unpack_from(sfmt, r, off)[0]
        uv = struct.unpack_from(ufmt, r, off)[0]
        if sv < 0:
            has_neg = True
        if (size == 1 and uv >= 128) or \
           (size == 2 and uv >= 32768) or \
           (size == 4 and uv >= 0x80000000):
            has_high = True
        if smin is None or sv < smin: smin = sv
        if smax is None or sv > smax: smax = sv
    return (smin, smax, has_high, has_neg)


def infer_field_layout(samples, entry_length):
    """Greedy left-to-right inference. Picks the largest type that
    fits the data and the alignment at each offset."""
    all_rows = []
    for s in samples:
        all_rows.extend(s['rows'])

    fields = []
    off = 0
    while off < entry_length:
        remaining = entry_length - off
        chose = None

        if remaining >= 8 and off % 8 == 0:
            if confirm_toffset_field(samples, off):
                chose = (8, 'toffset')

        if chose is None and remaining >= 4 and off % 4 == 0:
            all_float = all(looks_like_float(r[off:off+4]) for r in all_rows
                            if off+4 <= len(r))
            nonzero_floats = any(
                struct.unpack_from('<f', r, off)[0] != 0.0
                for r in all_rows if off+4 <= len(r))
            if all_float and nonzero_floats:
                chose = (4, 'float')
            elif looks_like_packed_bytes(all_rows, off):
                pass  # fall through to 4 ubytes
            else:
                info = infer_int_range(all_rows, off, 4)
                if info:
                    smin, smax, hi, neg = info
                    chose = (4, 'int' if neg else 'uint')

        if chose is None and remaining >= 2 and off % 2 == 0:
            packed4 = (remaining >= 4 and off % 4 == 0
                       and looks_like_packed_bytes(all_rows, off))
            if not packed4:
                info = infer_int_range(all_rows, off, 2)
                if info:
                    smin, smax, hi, neg = info
                    chose = (2, 'short' if neg else 'ushort')

        if chose is None:
            info = infer_int_range(all_rows, off, 1)
            if info:
                smin, smax, hi, neg = info
                chose = (1, 'byte' if neg else 'ubyte')
            else:
                chose = (1, 'ubyte')

        size, type_name = chose
        fields.append((f'field{len(fields)}', type_name))
        off += size

    return fields


# ---- Main --------------------------------------------------------------

def collect_section_data(input_dir):
    """Walk input_dir for .tbl files, group rows by (section_name, EL)."""
    grouped = defaultdict(lambda: {'rows': [], 'samples': []})
    n_files = n_parsed = 0
    for root, _, files in os.walk(input_dir):
        for fn in files:
            if not fn.endswith('.tbl'):
                continue
            n_files += 1
            tbl = parse_tbl(os.path.join(root, fn))
            if not tbl:
                continue
            n_parsed += 1
            for sec in tbl['sections']:
                key = (sec['name'], sec['entry_length'])
                if len(grouped[key]['samples']) < 5:
                    grouped[key]['samples'].append({
                        'file_buf': tbl['data'],
                        'file_size': tbl['size'],
                        'rows': sec['rows'],
                    })
                grouped[key]['rows'].extend(sec['rows'])
    return grouped, n_files, n_parsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input_dir', help='folder with .tbl files')
    ap.add_argument('output_dir', help='destination for generated JSONs')
    ap.add_argument('--schemas-dir', default=None,
                    help='existing schemas/headers folder (sections already '
                         'present here will be skipped)')
    args = ap.parse_args()

    if not os.path.isdir(args.input_dir):
        print(f"ERROR: input_dir not found: {args.input_dir}", file=sys.stderr)
        sys.exit(1)
    os.makedirs(args.output_dir, exist_ok=True)

    existing = set()
    if args.schemas_dir and os.path.isdir(args.schemas_dir):
        for f in os.listdir(args.schemas_dir):
            if f.endswith('.json'):
                existing.add(f[:-5])

    print(f"Scanning {args.input_dir}...")
    grouped, n_files, n_parsed = collect_section_data(args.input_dir)
    print(f"  scanned {n_files} .tbl files ({n_parsed} parsed cleanly)")
    print(f"  found {len(grouped)} unique (section, entry_length) tuples")
    if existing:
        print(f"  existing schemas in --schemas-dir: {len(existing)}")

    by_name = defaultdict(list)
    for (name, el), info in grouped.items():
        by_name[name].append((el, info))

    candidates = sorted(set(by_name.keys()) - existing)
    print(f"  missing schemas to generate: {len(candidates)}")

    n_written = n_skipped = 0
    for name in candidates:
        variants = sorted(by_name[name], key=lambda x: -len(x[1]['rows']))
        ent_len, info = variants[0]
        if len(info['rows']) == 0:
            n_skipped += 1
            continue
        layout = infer_field_layout(info['samples'], ent_len)
        schema = {
            'GENERATED': {
                'game': 'Unknown',
                'note': (
                    f'Auto-generated from {len(info["rows"])} rows across '
                    f'{len(info["samples"])} TBL files. Field names are '
                    f'placeholders; types are heuristic. Verify before '
                    f'relying on saves.'
                ),
                'schema': {fn: ft for fn, ft in layout},
            }
        }
        out_path = os.path.join(args.output_dir, f'{name}.json')
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(schema, f, indent='\t', ensure_ascii=False)
        n_written += 1

    print(f"\nGenerated {n_written} schemas in {args.output_dir}")
    if n_skipped:
        print(f"Skipped {n_skipped} sections (empty in all sampled files)")


if __name__ == '__main__':
    main()
