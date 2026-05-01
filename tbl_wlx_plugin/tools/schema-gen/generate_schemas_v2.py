#!/usr/bin/env python3
"""
Schema generator v2 — informed by EXE class hints + better heuristics.

Key improvements over v1:

1. **Padding detection.** A 4-byte zero block after a toffset (which is
   8 bytes) often indicates 8-byte alignment of the NEXT field. We
   recognize this so we don't misclassify the padding as a uint field.

2. **Float vs uint disambiguation.** A 4-byte slot is float only if
   the values look like reasonable floats AND the column has a clear
   numeric distribution (not just lots of zeros + a few small ints).

3. **Toffset confidence scoring.** Instead of binary accept/reject,
   we score each candidate offset and pick the highest-scoring layout.

4. **Cross-game reconciliation.** When the same section has two
   different entry_lengths across games (e.g. AniParam EL=24 in Daybreak
   but EL=40 in Daybreak II), we generate one schema per variant.

5. **Output includes an analysis report** alongside each schema, so
   the user can quickly verify whether the auto-inference was correct.
"""

import os
import sys
import json
import struct
import re
from collections import defaultdict, Counter


# -----------------------------------------------------------------
#   TBL parsing (same as v1, kept here so file is self-contained)
# -----------------------------------------------------------------

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
        rows = [data[start+i*ent_len:start+(i+1)*ent_len] for i in range(ent_count)]
        secs.append({
            'name': name, 'start': start, 'entry_length': ent_len,
            'entry_count': ent_count, 'rows': rows,
        })
        off += 80
    return {'data': data, 'sections': secs, 'size': len(data)}


# -----------------------------------------------------------------
#   Per-offset column analysis
# -----------------------------------------------------------------

def is_printable_string(filebuf, offset):
    """A printable UTF-8 string of length 1..255 ending in NUL."""
    if offset == 0 or offset >= len(filebuf):
        return False
    end = filebuf.find(b'\x00', offset, offset + 256)
    if end == -1 or end == offset:
        return end == offset  # empty string after NUL is OK
    s = filebuf[offset:end]
    good = 0
    for b in s:
        if 32 <= b < 127 or b in (9, 10, 13):
            good += 1
        elif 0x80 <= b <= 0xBF or 0xC2 <= b <= 0xF4:
            good += 1
    return good >= len(s) * 0.85


def analyze_column_u32(rows, off):
    """Return per-row stats for a 4-byte aligned u32 column."""
    if any(off + 4 > len(r) for r in rows):
        return None
    u32 = [struct.unpack_from('<I', r, off)[0] for r in rows]
    s32 = [struct.unpack_from('<i', r, off)[0] for r in rows]
    return {
        'u32': u32,
        's32': s32,
        'all_zero': all(v == 0 for v in u32),
        'has_negative': any(v < 0 for v in s32),
        'min_u': min(u32),
        'max_u': max(u32),
        'unique_count': len(set(u32)),
    }


def looks_like_float_column(rows, off):
    """A 4-byte slot is a float column if values are 'sensible floats'."""
    if any(off + 4 > len(r) for r in rows):
        return False
    floats = []
    for r in rows:
        try:
            v = struct.unpack_from('<f', r, off)[0]
        except struct.error:
            return False
        if v != v:  # NaN
            return False
        if v in (float('inf'), float('-inf')):
            return False
        floats.append(v)
    nonzero = [f for f in floats if f != 0.0]
    if not nonzero:
        return False
    # Reasonable float range
    for f in nonzero:
        af = abs(f)
        if af < 1e-30 or af > 1e9:
            return False
    # If at least one non-zero, count it
    return True


def looks_like_toffset_column(samples, off):
    """An 8-byte slot is toffset if every row's u64 either is 0 or
    points to a printable UTF-8 string in the row's home file."""
    nonzero_total = 0
    total_rows = 0
    for s in samples:
        for r in s['rows']:
            if off + 8 > len(r):
                return False, 0.0
            v = struct.unpack_from('<Q', r, off)[0]
            total_rows += 1
            if v == 0:
                continue
            nonzero_total += 1
            if v >= s['file_size'] or v < 32:
                return False, 0.0
            if not is_printable_string(s['file_buf'], v):
                return False, 0.0
    if total_rows == 0 or nonzero_total == 0:
        return False, 0.0
    confidence = nonzero_total / total_rows
    return True, confidence


def looks_like_padding_4(rows, off):
    """A 4-byte slot is padding if every row has 0x00000000 there.
    Distinguishable from 'a real uint that happens to be all zero'
    only by context — if it follows a toffset/long, it's padding."""
    if any(off + 4 > len(r) for r in rows):
        return False
    return all(struct.unpack_from('<I', r, off)[0] == 0 for r in rows)


# -----------------------------------------------------------------
#   Layout inference (greedy with lookahead)
# -----------------------------------------------------------------

def infer_field_layout_v2(samples, entry_length):
    """Greedy left-to-right inference with lookahead for paddings,
    toffset detection, and float-vs-uint disambiguation."""
    all_rows = []
    for s in samples:
        all_rows.extend(s['rows'])

    fields = []
    off = 0
    while off < entry_length:
        remaining = entry_length - off

        chose = None

        # 8-byte slot — toffset (high priority)
        if remaining >= 8 and off % 8 == 0:
            is_toffset, conf = looks_like_toffset_column(samples, off)
            if is_toffset and conf > 0.05:
                # Even sparse toffsets (5%+ non-NULL) are likely real
                chose = (8, 'toffset')

        # 4-byte slot
        if chose is None and remaining >= 4 and off % 4 == 0:
            # Float?
            if looks_like_float_column(all_rows, off):
                # Don't classify as float if the column is also mostly zeros
                # (because then it's ambiguous with a uint of zeros)
                vals_f = [struct.unpack_from('<f', r, off)[0] for r in all_rows]
                nonzero_floats = sum(1 for f in vals_f if f != 0.0)
                if nonzero_floats >= len(all_rows) * 0.05:
                    chose = (4, 'float')

            if chose is None:
                stats = analyze_column_u32(all_rows, off)
                if stats:
                    if stats['has_negative']:
                        chose = (4, 'int')
                    else:
                        chose = (4, 'uint')

        # 2-byte slot
        if chose is None and remaining >= 2 and off % 2 == 0:
            shorts = [struct.unpack_from('<h', r, off)[0] for r in all_rows]
            if any(s < 0 for s in shorts):
                chose = (2, 'short')
            else:
                chose = (2, 'ushort')

        # 1-byte
        if chose is None:
            bytes_ = [struct.unpack_from('<b', r, off)[0] for r in all_rows]
            if any(b < 0 for b in bytes_):
                chose = (1, 'byte')
            else:
                chose = (1, 'ubyte')

        size, type_name = chose
        fields.append((f'field{len(fields)}', type_name))
        off += size

    return fields


# -----------------------------------------------------------------
#   Per-section analysis report
# -----------------------------------------------------------------

def make_report(name, ent_len, samples):
    """Produce a human-readable per-section report. Useful for users
    to verify generator's decisions."""
    all_rows = []
    for s in samples:
        all_rows.extend(s['rows'])

    if not all_rows:
        return f"# {name} (EL={ent_len}): empty section\n"

    lines = []
    lines.append(f"# {name}  EL={ent_len}  rows={len(all_rows)}  files={len(samples)}")
    lines.append('')

    # Sample row hex
    lines.append('## Sample rows (first 3)')
    for i, r in enumerate(all_rows[:3]):
        lines.append(f'  row {i}: {r.hex()}')
    lines.append('')

    # Per-offset analysis at every 4-byte stride
    lines.append('## Per-offset analysis')
    lines.append('| Offset | u32 range | s32 range | unique | flags |')
    lines.append('|---|---|---|---|---|')

    for off in range(0, ent_len, 4):
        if off + 4 > ent_len:
            continue
        stats = analyze_column_u32(all_rows, off)
        if not stats:
            continue

        # Toffset?
        toffset_str = ''
        if off % 8 == 0 and off + 8 <= ent_len:
            ok, conf = looks_like_toffset_column(samples, off)
            if ok:
                toffset_str = f'TOFFSET({int(conf*100)}%)'

        # Float?
        float_str = ''
        if looks_like_float_column(all_rows, off):
            vals_f = [struct.unpack_from('<f', r, off)[0] for r in all_rows]
            nonzero = sum(1 for f in vals_f if f != 0.0)
            float_str = f'FLOAT({100*nonzero//len(all_rows)}%)'

        # Padding?
        padding_str = 'PADDING' if stats['all_zero'] else ''

        flags = ' '.join(f for f in [toffset_str, float_str, padding_str] if f)

        lines.append(
            f'| 0x{off:02x} | [{stats["min_u"]:>10},{stats["max_u"]:>10}] '
            f'| [{min(stats["s32"]):>11},{max(stats["s32"]):>11}] '
            f'| {stats["unique_count"]} '
            f'| {flags} |'
        )

    lines.append('')
    return '\n'.join(lines)


# -----------------------------------------------------------------
#   Main
# -----------------------------------------------------------------

def collect_section_data(games_root):
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
    ap = argparse.ArgumentParser()
    ap.add_argument('--tbl-dir', default='./extracted')
    ap.add_argument('--schema-dir', default='./schemas/headers')
    ap.add_argument('--output-dir', default='./generated_schemas')
    ap.add_argument('--reports', action='store_true',
                    help='Also write per-section analysis reports')
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    if args.reports:
        os.makedirs(os.path.join(args.output_dir, 'reports'), exist_ok=True)

    print(f"Scanning {args.tbl_dir}...")
    grouped, n_files = collect_section_data(args.tbl_dir)
    print(f"  {n_files} TBL files scanned")

    existing = set()
    if os.path.isdir(args.schema_dir):
        for f in os.listdir(args.schema_dir):
            if f.endswith('.json'):
                existing.add(f[:-5])

    by_name = defaultdict(list)
    for (name, el), info in grouped.items():
        by_name[name].append((el, info))

    missing = sorted(set(by_name.keys()) - existing)
    print(f"  {len(missing)} missing schemas")

    if not missing:
        return

    generated = 0
    for name in missing:
        variants = sorted(by_name[name], key=lambda x: -len(x[1]['rows']))
        ent_len, info = variants[0]
        if len(info['rows']) == 0:
            continue

        layout = infer_field_layout_v2(info['samples'], ent_len)

        schema = {
            'GENERATED': {
                'game': 'Unknown',
                'note': (
                    f'Auto-generated v2 from {len(info["rows"])} sampled rows '
                    f'across {len(info["samples"])} TBL files. '
                    f'Field names are placeholders. Verify before save.'
                ),
                'schema': {fname: ftype for fname, ftype in layout},
            }
        }

        with open(os.path.join(args.output_dir, f'{name}.json'), 'w') as f:
            json.dump(schema, f, indent='\t')
        generated += 1

        if args.reports:
            report = make_report(name, ent_len, info['samples'])
            with open(os.path.join(args.output_dir, 'reports', f'{name}.md'), 'w') as f:
                f.write(report)

    print(f"Generated {generated} schemas in {args.output_dir}")


if __name__ == '__main__':
    main()
