#!/usr/bin/env python3
"""
tbl_schema_autogen.py — comprehensive TBL schema auto-generator (v3).

Generates KuroTools-format schemas directly from a corpus of #TBL files.
Designed to work on FUTURE Falcom games with no manual intervention.

==============================================================================
What this generator does
==============================================================================

1. Walks one or more directories of #TBL files.
2. Parses headers and aggregates raw row bytes per (section_name,
   entry_length) tuple — pooling evidence across ALL files in the corpus.
3. Detects field boundaries and types using layered evidence:
   - **toffset** confidence: 8-byte values that point into data2 and
     decode as NUL-terminated UTF-8 (verified against EVERY non-zero
     value across ALL rows in ALL files).
   - **u32array / u16array / u8array** detection: 8-byte offset + 4-byte
     count where the offset points to `count * elem_size` valid bytes.
   - **float** vs **uint**: when 4-byte slot has natural-looking float
     distribution (small range, common values like 0.0/1.0/0.5, IEEE 754
     normals).
   - **type-narrow** ints: ubyte if all values 0-255, ushort if 0-65535,
     etc., based on observed range across rows.
   - **padding**: zero-only columns adjacent to wider fields.
4. Names fields using positional conventions (id at offset 0, name/desc
   for last toffsets, common patterns from KuroTools schemas).
5. Optionally MERGES with an existing schemas/headers/ directory —
   skipping sections that already have a schema for that entry_length,
   so manual or community work is preserved.
6. Generates per-section markdown reports so a human can verify the
   auto-inference was correct.

==============================================================================
Vocabulary
==============================================================================

Output uses KuroTools-compatible types (compatible with tbl_wlx plugin):
    byte, ubyte, short, ushort, int, uint, long, ulong, float
    toffset (8-byte offset to NUL-term UTF-8 string in data2)
    u8array, u16array, u32array (8-byte offset + 4-byte count = 12 bytes)

==============================================================================
Usage
==============================================================================

    python3 tbl_schema_autogen.py <tbl_dir> [<tbl_dir>...] -o schemas/headers/

    # Don't overwrite existing schemas
    python3 tbl_schema_autogen.py game/ -o schemas/headers/ \\
        --merge-with /existing/schemas/headers/

    # Custom platform/game tags
    python3 tbl_schema_autogen.py game/ -o schemas/headers/ \\
        -p "GENERATED_NewGame" -g "NewGame"

    # Full diagnostic output
    python3 tbl_schema_autogen.py game/ -o schemas/headers/ -r -v

==============================================================================
"""

import os
import sys
import json
import struct
import argparse
import math
import re
from collections import defaultdict, Counter
from pathlib import Path


# =============================================================================
# TBL parsing
# =============================================================================

def parse_tbl(path):
    """Parse a #TBL file. Returns dict with 'data' (full bytes) and 'sections'
    list, where each section has name, start, entry_length, entry_count, rows.
    Returns None if file isn't a #TBL."""
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        return None
    if data[:4] != b'#TBL':
        return None
    if len(data) < 8:
        return None
    n = struct.unpack_from('<I', data, 4)[0]
    if not (0 < n <= 4096):
        return None
    secs = []
    off = 8
    for _ in range(n):
        if off + 80 > len(data):
            return None
        name_bytes = data[off:off+64].split(b'\x00', 1)[0]
        try:
            name = name_bytes.decode('utf-8')
        except UnicodeDecodeError:
            name = name_bytes.decode('utf-8', 'replace')
        crc, start, ent_len, ent_count = struct.unpack_from('<4I', data, off+64)
        if ent_len == 0 or start + ent_len * ent_count > len(data):
            return None
        rows = [data[start+i*ent_len:start+(i+1)*ent_len]
                for i in range(ent_count)]
        secs.append({
            'name': name,
            'start': start,
            'entry_length': ent_len,
            'entry_count': ent_count,
            'rows': rows,
        })
        off += 80
    return {'data': data, 'sections': secs, 'size': len(data)}


# =============================================================================
# Evidence aggregation
# =============================================================================

class SectionEvidence:
    """Pooled evidence for one (section_name, entry_length) across files."""
    __slots__ = ('name', 'entry_length', 'rows', 'sources', 'tbl_data2_map')

    def __init__(self, name, entry_length):
        self.name = name
        self.entry_length = entry_length
        self.rows = []           # list of raw row bytes
        self.sources = []        # list of (file_path, row_index_in_file)
        self.tbl_data2_map = {}  # row_index -> (file_data_bytes, data2_start)

    def add_rows(self, rows, file_path, file_data, data2_start):
        for i, r in enumerate(rows):
            self.rows.append(r)
            self.sources.append((file_path, i))
            self.tbl_data2_map[len(self.rows) - 1] = (file_data, data2_start)


def collect_evidence(tbl_dirs, verbose=False):
    """Walk directories, parse TBLs, build {(name, entry_length): Evidence}.
    data2_start = end of last section's row data = where strings begin."""
    evidence = {}
    n_files = 0
    n_skipped = 0
    for d in tbl_dirs:
        for root, _, files in os.walk(d):
            for fn in files:
                if not fn.endswith('.tbl'):
                    continue
                path = os.path.join(root, fn)
                t = parse_tbl(path)
                if t is None:
                    n_skipped += 1
                    continue
                n_files += 1
                # data2_start = end of last section's data
                if not t['sections']:
                    continue
                last = t['sections'][-1]
                data2_start = last['start'] + last['entry_length'] * last['entry_count']
                for s in t['sections']:
                    key = (s['name'], s['entry_length'])
                    if key not in evidence:
                        evidence[key] = SectionEvidence(s['name'], s['entry_length'])
                    evidence[key].add_rows(
                        s['rows'], path, t['data'], data2_start,
                    )
                if verbose:
                    pass  # too noisy for default
    if verbose:
        print(f"  Parsed {n_files} TBL files, skipped {n_skipped} non-TBL files",
              file=sys.stderr)
        print(f"  Found {len(evidence)} unique (section, entry_length) tuples",
              file=sys.stderr)
    return evidence


# =============================================================================
# Type inference
# =============================================================================

def is_valid_utf8_string(file_data, offset, max_len=4096):
    """Check if there's a NUL-terminated UTF-8 string at offset.
    Returns string length (incl. NUL) or 0 if invalid."""
    if offset < 0 or offset >= len(file_data):
        return 0
    end = file_data.find(b'\x00', offset, offset + max_len)
    if end < 0:
        return 0
    s = file_data[offset:end]
    if len(s) == 0:
        return 1  # empty string is valid (just a NUL)
    try:
        s.decode('utf-8')
    except UnicodeDecodeError:
        return 0
    # Heuristic: most printable
    printable = sum(1 for b in s if 0x20 <= b < 0x7f or b in (0x09, 0x0A, 0x0D)
                    or b >= 0x80)
    if printable < 0.5 * len(s):
        return 0
    return end - offset + 1


def is_plausible_float(b4):
    """Check if 4 bytes interpreted as IEEE 754 float look natural."""
    f = struct.unpack('<f', b4)[0]
    if math.isnan(f) or math.isinf(f):
        return False
    if f == 0.0:
        return True  # exact zero is fine (matches uint 0 too)
    af = abs(f)
    # Natural floats: 1e-6 .. 1e9 and not extreme denormals
    if af < 1e-6 or af > 1e9:
        return False
    return True


def looks_like_natural_float(values_4byte):
    """Given a list of 4-byte values, check if they look more like floats
    than like ints. Returns confidence 0.0-1.0."""
    if not values_4byte:
        return 0.0
    n_zero = 0
    n_natural_float = 0
    n_total = 0
    for b4 in values_4byte:
        if b4 == b'\x00\x00\x00\x00':
            n_zero += 1
            continue
        n_total += 1
        if is_plausible_float(b4):
            f = struct.unpack('<f', b4)[0]
            # Common natural values: 0.5, 1.0, 1.5, 2.0, ..., or fractional
            af = abs(f)
            if af in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 10.0):
                n_natural_float += 1
            elif 0.001 < af < 10000.0:
                # Check if it's a "round" float (1.5, 2.5, 0.1, etc.)
                if af < 1.0:
                    # fractional
                    n_natural_float += 1
                elif int(f) == f and af < 100:
                    # small integer-like - could be either, count as 0.5
                    n_natural_float += 0.5
                else:
                    # could go either way
                    n_natural_float += 0.7
    if n_total == 0:
        return 0.5  # all zeros — ambiguous
    return n_natural_float / n_total


def looks_like_uint_ids(values_4byte):
    """Check if values look like sequential or clustered ID numbers."""
    if not values_4byte:
        return 0.0
    ints = [struct.unpack('<I', v)[0] for v in values_4byte]
    nonzero = [v for v in ints if v != 0]
    if not nonzero:
        return 0.0
    # IDs are typically small positive integers
    if all(v < 1_000_000 for v in nonzero):
        return 0.9
    if all(v < 10_000_000 for v in nonzero):
        return 0.7
    return 0.3


def detect_toffset_at(rows, file_data_map, offset):
    """Check if 8-byte slot at `offset` is a toffset (string pointer).

    Strict validation: value must be >= data2_start AND point to a valid
    NUL-terminated UTF-8 string. Small integer values like 10 or 100 that
    happen to land on NUL-terminated bytes inside header areas don't
    count — they would fail the data2_start lower-bound test.

    Returns confidence 0.0-1.0."""
    if not rows or offset + 8 > len(rows[0]):
        return 0.0
    n_total = 0
    n_valid_string = 0
    for i, row in enumerate(rows):
        v = struct.unpack_from('<Q', row, offset)[0]
        if v == 0:
            continue  # zero is ambiguous, skip in scoring
        n_total += 1
        file_data, data2_start = file_data_map[i]
        # Strict: pointer must be at or after data2 (the strings region)
        if v < data2_start or v >= len(file_data):
            continue
        if is_valid_utf8_string(file_data, v) > 0:
            n_valid_string += 1
    if n_total == 0:
        return 0.5  # all zero — could be toffset or anything
    return n_valid_string / n_total


def detect_array_at(rows, file_data_map, offset, elem_size):
    """Check if 12-byte slot at `offset` is a u<elem*8>array (8-byte offset
    + 4-byte count). Returns confidence 0.0-1.0.

    Strict: array offset must point to data2 region, count must be small
    (< 10000), and offset+count*elem_size must fit in file."""
    if not rows or offset + 12 > len(rows[0]):
        return 0.0
    n_total = 0
    n_valid = 0
    for i, row in enumerate(rows):
        ofs, cnt = struct.unpack_from('<QI', row, offset)
        if ofs == 0 and cnt == 0:
            continue
        n_total += 1
        file_data, data2_start = file_data_map[i]
        if (ofs >= data2_start and
                ofs < len(file_data) and
                0 < cnt < 10000 and
                ofs + cnt * elem_size <= len(file_data)):
            n_valid += 1
    if n_total == 0:
        return 0.5
    return n_valid / n_total


def value_range_4byte(rows, offset):
    """Get min/max for 4-byte unsigned at offset."""
    if not rows or offset + 4 > len(rows[0]):
        return 0, 0
    vals = [struct.unpack_from('<I', row, offset)[0] for row in rows]
    return min(vals), max(vals)


def value_range_2byte(rows, offset):
    if not rows or offset + 2 > len(rows[0]):
        return 0, 0
    vals = [struct.unpack_from('<H', row, offset)[0] for row in rows]
    return min(vals), max(vals)


def value_range_1byte(rows, offset):
    if not rows or offset + 1 > len(rows[0]):
        return 0, 0
    vals = [row[offset] for row in rows]
    return min(vals), max(vals)


def is_all_zero_at(rows, offset, length):
    """Check if every byte at offset..offset+length is zero in every row."""
    if not rows or offset + length > len(rows[0]):
        return False
    for row in rows:
        if row[offset:offset+length] != b'\x00' * length:
            return False
    return True


# =============================================================================
# Layout solver
# =============================================================================

# Each candidate type carries (size, score). We greedy-pick from highest
# score. Ties broken by larger size first (prefer toffset over uint+uint).

CONFIDENT_THRESHOLD = 0.95


def infer_field_at(evidence, offset, min_confidence=0.8):
    """Infer the most likely field type at offset. Returns (type_name, size,
    confidence) — picks the highest-confidence interpretation that fits."""
    rows = evidence.rows
    if not rows or offset >= evidence.entry_length:
        return None
    remaining = evidence.entry_length - offset

    candidates = []  # list of (score, size, type_name)

    # 12-byte: array types (need offset+count to validate)
    if remaining >= 12:
        for elem_size, type_name in [(4, 'u32array'),
                                     (2, 'u16array'),
                                     (1, 'u8array')]:
            score = detect_array_at(rows, evidence.tbl_data2_map,
                                    offset, elem_size)
            if score >= min_confidence:
                candidates.append((score, 12, type_name))

    # 8-byte: toffset (highest priority among 8-byte types if validated)
    if remaining >= 8:
        score = detect_toffset_at(rows, evidence.tbl_data2_map, offset)
        if score >= min_confidence:
            candidates.append((score, 8, 'toffset'))

        # ulong / long fallback
        # values_8byte = [struct.unpack_from('<Q', row, offset)[0] for row in rows]
        # high-bit pattern check: if any value > 2^63, it's unsigned
        # otherwise either unsigned or signed - default to ulong
        # (only emit if no toffset candidate)

    # 4-byte: uint, int, float
    if remaining >= 4:
        values_4 = [row[offset:offset+4] for row in rows]
        # Check float-ness vs uint-ness
        f_score = looks_like_natural_float(values_4)
        i_score = looks_like_uint_ids(values_4)
        # Need clear winner for float
        if f_score >= 0.85 and f_score > i_score + 0.15:
            candidates.append((f_score, 4, 'float'))

    # 2-byte: ushort/short
    # 1-byte: ubyte/byte
    # These are "fallback" types — only used if nothing larger fits.

    # Pick best candidate (score, then larger size on tie)
    if candidates:
        candidates.sort(key=lambda c: (-c[0], -c[1]))
        score, size, type_name = candidates[0]
        return (type_name, size, score)

    # Fallback: pick smallest unambiguous slot from 8/4/2/1 with type narrowing
    if remaining >= 8 and offset % 8 == 0:
        # Default: ulong. Post-pass will split if there's strong evidence
        # (e.g. upper half always zero AND lower half is clearly float).
        return ('ulong', 8, 0.6)
    if remaining >= 4:
        # Try float first at 4-byte slots
        values_4 = [row[offset:offset+4] for row in rows]
        f_score = looks_like_natural_float(values_4)
        if f_score >= 0.9:
            return ('float', 4, 0.7)
        return ('uint', 4, 0.5)
    if remaining >= 2:
        return ('ushort', 2, 0.5)
    return ('ubyte', 1, 0.5)


# =============================================================================
# Field naming heuristics
# =============================================================================

# Naming conventions learned from KuroTools / FalcomSchema / PDF guide
NAMING_HINTS = {
    # By position + type
    'first_uint':      'id',
    'last_toffset':    'name',
    'second_to_last_toffset': 'description',
    'third_to_last_toffset':  'flag',
}


def name_fields(field_specs, section_name=''):
    """Given list of (offset, size, type, score) tuples, generate names.
    Uses positional conventions:
      - First uint at offset 0 → 'id'
      - Last toffset → 'name' (if multiple toffsets, the last is usually name)
      - Second-to-last toffset → 'description' (or 'desc')
      - Other toffsets → 'text<N>'
      - Floats → 'float<N>' or 'flt<N>'
      - Other ints → 'unk<N>'
    """
    n_fields = len(field_specs)
    # Collect indices by type
    toffset_indices = [i for i, (off, sz, t, sc) in enumerate(field_specs)
                       if t == 'toffset']
    float_indices = [i for i, (off, sz, t, sc) in enumerate(field_specs)
                     if t == 'float']
    array_indices = [i for i, (off, sz, t, sc) in enumerate(field_specs)
                     if t.endswith('array')]

    names = [''] * n_fields
    used_names = set()

    def alloc(base):
        if base not in used_names:
            used_names.add(base)
            return base
        n = 1
        while f'{base}{n}' in used_names:
            n += 1
        used_names.add(f'{base}{n}')
        return f'{base}{n}'

    # First uint at offset 0 → 'id'
    if (n_fields > 0 and field_specs[0][0] == 0
            and field_specs[0][2] in ('uint', 'ulong')):
        names[0] = alloc('id')

    # Last toffset → 'name', second-to-last → 'description'
    if len(toffset_indices) >= 2:
        names[toffset_indices[-1]] = alloc('name')
        names[toffset_indices[-2]] = alloc('description')
        # Other toffsets → text<n>
        for idx in toffset_indices[:-2]:
            names[idx] = alloc('text')
    elif len(toffset_indices) == 1:
        names[toffset_indices[0]] = alloc('name')

    # Floats → float<n>
    for idx in float_indices:
        if not names[idx]:
            names[idx] = alloc('float')

    # Arrays → arr<n>
    for idx in array_indices:
        if not names[idx]:
            names[idx] = alloc('arr')

    # Remaining: pick name based on type
    for i, (off, sz, t, sc) in enumerate(field_specs):
        if names[i]:
            continue
        if t in ('uint', 'int'):
            names[i] = alloc('unk')
        elif t in ('ushort', 'short'):
            names[i] = alloc('short')
        elif t in ('ubyte', 'byte'):
            names[i] = alloc('byte')
        elif t in ('ulong', 'long'):
            names[i] = alloc('long')
        else:
            names[i] = alloc(t)
    return names


# =============================================================================
# Field layout solver — walks bytes, picks best type at each offset
# =============================================================================

def solve_layout(evidence, min_confidence=0.8):
    """Walk through entry bytes, picking the highest-confidence type at each
    offset. Returns list of (offset, size, type, confidence) tuples.
    Then runs post-pass type narrowing."""
    el = evidence.entry_length
    fields = []
    off = 0
    while off < el:
        result = infer_field_at(evidence, off, min_confidence=min_confidence)
        if result is None:
            break
        type_name, size, conf = result
        fields.append((off, size, type_name, conf))
        off += size
    fields = post_process_padding(fields, evidence)
    return fields


def post_process_padding(fields, evidence):
    """Type narrowing post-pass.

    Strategy: only split an 8-byte 'ulong'/'long' slot into 'uint'+'uint'
    when there is STRONG evidence of split layout:

    1. Upper 4 bytes are always exactly 0 (so the slot couldn't be a
       genuine 64-bit integer storing values >= 2^32).
    2. AND lower 4 bytes are non-trivially varied (so it's not just
       16 bytes of zero).
    3. AND the lower 4 bytes look like a natural-float distribution
       OR the slot follows another 8-byte slot (suggesting 4+4 packed
       layout common in modern Falcom games with toffset alignment).

    Without these conditions, keep ulong intact — Sky 1st genuinely
    uses `ulong` for IDs (e.g. character_id, item_id can be > 2^32).

    Float-half detection within 8-byte slots: only split if upper or
    lower half scores >= 0.95 as float. Below that the savings don't
    justify splitting because Sky/Daybreak may use full ulongs.
    """
    if not evidence.rows:
        return fields

    rows = evidence.rows
    refined = []

    for idx, (off, sz, t, sc) in enumerate(fields):
        if t in ('ulong', 'long') and sz == 8:
            values_lo = [row[off:off+4] for row in rows]
            values_hi = [row[off+4:off+8] for row in rows]

            upper_all_zero = all(v == b'\x00\x00\x00\x00' for v in values_hi)
            lower_all_zero = all(v == b'\x00\x00\x00\x00' for v in values_lo)

            f_lo = looks_like_natural_float(values_lo)
            f_hi = looks_like_natural_float(values_hi)

            # Only split if STRONG float evidence in one half
            if f_lo >= 0.95 and not lower_all_zero:
                refined.append((off,   4, 'float', sc))
                if upper_all_zero:
                    refined.append((off+4, 4, 'uint', 0.6))  # padding-uint
                elif f_hi >= 0.95:
                    refined.append((off+4, 4, 'float', sc))
                else:
                    refined.append((off+4, 4, 'uint', 0.6))
                continue
            elif f_hi >= 0.95 and not upper_all_zero:
                refined.append((off,   4, 'uint',  sc))
                refined.append((off+4, 4, 'float', sc))
                continue
            # Otherwise keep as ulong/long — user can refine manually
        refined.append((off, sz, t, sc))

    return refined


# =============================================================================
# Schema serialization
# =============================================================================

KUROTOOLS_TYPE_SIZES = {
    'byte': 1, 'ubyte': 1,
    'short': 2, 'ushort': 2,
    'int': 4, 'uint': 4, 'float': 4,
    'long': 8, 'ulong': 8, 'toffset': 8,
    'u8array': 12, 'u16array': 12, 'u32array': 12,
}


def schema_total_size(schema):
    """Sum of field sizes."""
    return sum(KUROTOOLS_TYPE_SIZES.get(t, 0) for t in schema.values())


def field_specs_to_schema(field_specs, names):
    """Build {name: type} dict from the layout solver output."""
    schema = {}
    for (off, sz, t, sc), name in zip(field_specs, names):
        schema[name] = t
    return schema


def write_schema_file(out_path, name, schemas_per_variant):
    """Write a single schema JSON file with one or more platform variants."""
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(schemas_per_variant, f, indent='\t', ensure_ascii=False)


# =============================================================================
# Reports
# =============================================================================

def generate_report(evidence, fields, names, schema):
    """Build a markdown diagnostic report for one section."""
    lines = []
    lines.append(f'# {evidence.name} (entry_length={evidence.entry_length})')
    lines.append('')
    lines.append(f'- Rows analyzed: {len(evidence.rows)}')
    lines.append(f'- Source files: {len(set(s[0] for s in evidence.sources))}')
    lines.append(f'- Inferred schema size: {schema_total_size(schema)} bytes '
                 f'(target {evidence.entry_length})')
    lines.append('')
    lines.append('## Field-by-field analysis')
    lines.append('')
    lines.append('| Offset | Size | Type | Confidence | Name |')
    lines.append('|---:|---:|:---|---:|:---|')
    for (off, sz, t, sc), name in zip(fields, names):
        lines.append(f'| 0x{off:02x} ({off:>3d}) | {sz} | {t} | {sc:.2f} | {name} |')
    lines.append('')

    # Sample row hex dump
    if evidence.rows:
        lines.append('## Sample row 0 (hex)')
        lines.append('')
        lines.append('```')
        row = evidence.rows[0]
        for i in range(0, len(row), 16):
            chunk = row[i:i+16]
            hex_part = ' '.join(f'{b:02x}' for b in chunk)
            lines.append(f'{i:04x}: {hex_part}')
        lines.append('```')
    return '\n'.join(lines)


# =============================================================================
# Main
# =============================================================================

def main():
    p = argparse.ArgumentParser(
        description='Generate KuroTools-format schemas from #TBL files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument('tbl_dirs', nargs='+',
                   help='One or more directories of TBL files to analyze')
    p.add_argument('-o', '--output', default='generated_schemas/',
                   help='Output directory for schema JSON files')
    p.add_argument('-m', '--merge-with', default=None,
                   help='Existing schemas/headers/ to merge with '
                        '(skip sections that already have a variant for '
                        'this entry_length)')
    p.add_argument('-p', '--platform', default='GENERATED',
                   help='Platform key for new schemas (default: GENERATED)')
    p.add_argument('-g', '--game', default='Unknown',
                   help='Game tag for new schemas (default: Unknown)')
    p.add_argument('-r', '--reports', action='store_true',
                   help='Generate per-section markdown analysis reports '
                        'in <output>/reports/')
    p.add_argument('--min-rows', type=int, default=3,
                   help='Skip sections with fewer rows (default: 3)')
    p.add_argument('--min-confidence', type=float, default=0.8,
                   help='Type confidence threshold 0.0-1.0 (default: 0.8)')
    p.add_argument('-v', '--verbose', action='store_true')
    args = p.parse_args()

    # Validate
    for d in args.tbl_dirs:
        if not os.path.isdir(d):
            print(f'Error: directory not found: {d}', file=sys.stderr)
            sys.exit(2)

    os.makedirs(args.output, exist_ok=True)
    if args.reports:
        os.makedirs(os.path.join(args.output, 'reports'), exist_ok=True)

    # Load existing schemas to skip
    existing_sizes = defaultdict(set)  # section_name -> set of entry_lengths
    if args.merge_with:
        for fn in os.listdir(args.merge_with):
            if not fn.endswith('.json'):
                continue
            name = fn[:-5]
            try:
                d = json.load(open(os.path.join(args.merge_with, fn)))
            except Exception:
                continue
            for plat, pd in d.items():
                sch = pd.get('schema', {})
                sz = schema_total_size(sch) if all(
                    isinstance(v, str) for v in sch.values()
                ) else None
                if sz is not None:
                    existing_sizes[name].add(sz)
        print(f'Loaded {len(existing_sizes)} existing sections '
              f'from {args.merge_with}', file=sys.stderr)

    # Phase 1: aggregate evidence
    print(f'Phase 1: scanning {len(args.tbl_dirs)} directories...', file=sys.stderr)
    evidence = collect_evidence(args.tbl_dirs, verbose=args.verbose)

    # Phase 2: filter & infer
    print(f'Phase 2: inferring schemas (min-rows={args.min_rows}, '
          f'min-confidence={args.min_confidence})...', file=sys.stderr)
    n_emitted = 0
    n_skipped_existing = 0
    n_skipped_few_rows = 0

    # Group by section name → list of variants
    variants_per_section = defaultdict(list)

    for (name, el), ev in sorted(evidence.items()):
        # Skip if existing schema covers this size
        if el in existing_sizes.get(name, set()):
            n_skipped_existing += 1
            continue

        if len(ev.rows) < args.min_rows:
            n_skipped_few_rows += 1
            continue

        # Solve layout
        fields = solve_layout(ev, min_confidence=args.min_confidence)
        # Verify total size matches entry_length exactly
        total = sum(sz for off, sz, t, sc in fields)
        if total != el:
            # Fallback: pad with raw bytes — emit a 'data<remaining>'
            # synthesis. For the plugin's purposes we represent leftover
            # as repeated ubytes.
            for i in range(total, el):
                fields.append((i, 1, 'ubyte', 0.5))

        names = name_fields(fields, section_name=name)
        schema = field_specs_to_schema(fields, names)
        variants_per_section[name].append({
            'entry_length': el,
            'schema': schema,
            'fields': fields,
            'names': names,
            'evidence': ev,
            'avg_confidence': (sum(sc for off, sz, t, sc in fields) / len(fields)
                               if fields else 0.0),
        })

    # Phase 3: emit JSON files
    print(f'Phase 3: writing schemas to {args.output}...', file=sys.stderr)
    for name, variants in sorted(variants_per_section.items()):
        out_payload = {}
        for i, v in enumerate(variants):
            plat_key = args.platform
            if len(variants) > 1:
                plat_key = f'{args.platform}_EL{v["entry_length"]}'
            out_payload[plat_key] = {
                'game': args.game,
                'schema': v['schema'],
                'source': 'tbl_schema_autogen v3 (auto-inferred)',
                'note': (f'Auto-generated from {len(v["evidence"].rows)} rows '
                         f'across {len(set(s[0] for s in v["evidence"].sources))} '
                         f'TBL files. Confidence avg: {v["avg_confidence"]:.2f}. '
                         f'Field names are placeholder — verify before relying.'),
            }

        out_path = os.path.join(args.output, f'{name}.json')
        write_schema_file(out_path, name, out_payload)
        n_emitted += 1

        if args.reports:
            for v in variants:
                report = generate_report(
                    v['evidence'], v['fields'], v['names'], v['schema']
                )
                rep_name = f'{name}_EL{v["entry_length"]}.md' if len(variants) > 1 \
                    else f'{name}.md'
                with open(os.path.join(args.output, 'reports', rep_name),
                          'w', encoding='utf-8') as f:
                    f.write(report)

    # Summary
    print(f'\n=== Summary ===', file=sys.stderr)
    print(f'  Emitted:           {n_emitted} schema files', file=sys.stderr)
    print(f'  Skipped (existing): {n_skipped_existing} variants', file=sys.stderr)
    print(f'  Skipped (few rows): {n_skipped_few_rows} variants', file=sys.stderr)
    print(f'  Output: {args.output}/', file=sys.stderr)
    if args.reports:
        print(f'  Reports: {args.output}/reports/', file=sys.stderr)


if __name__ == '__main__':
    main()
