#!/usr/bin/env python3
"""Convert FalcomSchema-main JSON files into KuroTools schema format
used by the TBL Lister plugin.

Usage:
    python3 convert_falcomschema.py <falcomschema_dir> <output_dir>

Example:
    python3 convert_falcomschema.py . converted/

Output: one JSON file per section in <output_dir>/, with platform keys
FALCOMSCHEMA_Daybreak1, FALCOMSCHEMA_Daybreak2, FALCOMSCHEMA_Ys_X.
Each variant is a fully flattened KuroTools schema with all nested
dicts and ref_<Name> types expanded.

Type vocabulary handled:
  Primitives:  u8/s8, u16/s16, u32/s32, u64/s64, f32
  Pointers:    ptr_str_utf8, ptr_str_latin1  -> toffset (8 bytes)
  Arrays:      arr_u8/arr_u16/arr_u32        -> u8array/u16array/u32array (12)
  Raw:         dN  (N raw bytes)              -> N x ubyte
  Refs:        ref_<CommonName>               -> common schema fields inlined
  Nested:      {"repeat": N, "type": ...}     -> N copies
               {"type": "ref_<Name>"}         -> single instance of common
"""
import json, os, sys, glob

PRIMITIVES = {
    'u8':  'ubyte',  's8':  'byte',
    'u16': 'ushort', 's16': 'short',
    'u32': 'uint',   's32': 'int',
    'u64': 'ulong',  's64': 'long',
    'f32': 'float',
}
SIZES = {
    'byte':1,'ubyte':1,'short':2,'ushort':2,'int':4,'uint':4,
    'long':8,'ulong':8,'float':4,'toffset':8,
    'u32array':12,'u16array':12,'u8array':12,
}
GAME_DIR_TO_PLATFORM = {
    'ed9_Daybreak1': ('FALCOMSCHEMA_Daybreak1', 'Kuro1'),
    'ed9_Daybreak2': ('FALCOMSCHEMA_Daybreak2', 'Kuro2'),
    'ys_X':          ('FALCOMSCHEMA_Ys_X',     'Ys_X'),
}


def load_common(falcomschema_dir):
    common = {}
    for f in glob.glob(os.path.join(falcomschema_dir, 'common', '*.json')):
        name = os.path.basename(f)[:-5]
        common[name] = json.load(open(f))['schema']
    return common


def expand(field_name, ftype, output, common, prefix=''):
    """Expand a single FalcomSchema field into flat KuroTools fields."""
    full_name = prefix + field_name

    if isinstance(ftype, str):
        if ftype in PRIMITIVES:
            output[full_name] = PRIMITIVES[ftype]; return
        if ftype.startswith('ptr_str'):
            output[full_name] = 'toffset'; return
        if ftype == 'arr_u8':
            output[full_name] = 'u8array'; return
        if ftype == 'arr_u16':
            output[full_name] = 'u16array'; return
        if ftype == 'arr_u32':
            output[full_name] = 'u32array'; return
        if ftype.startswith('d') and ftype[1:].isdigit():
            n = int(ftype[1:])
            for i in range(n):
                output[f'{full_name}_b{i}'] = 'ubyte'
            return
        if ftype.startswith('ref_'):
            ref_name = ftype[4:]
            if ref_name in common:
                for sk, sv in common[ref_name].items():
                    expand(sk, sv, output, common, prefix=f'{full_name}_')
                return
        # Unknown — keep marker so we notice
        output[full_name] = f'unknown({ftype})'
        return

    if isinstance(ftype, dict):
        if 'repeat' in ftype:
            n = ftype['repeat']
            inner = ftype['type']
            for i in range(n):
                if isinstance(inner, str):
                    expand(f'{field_name}_{i}', inner, output, common, prefix=prefix)
                elif isinstance(inner, dict):
                    for sk, sv in inner.items():
                        expand(f'{field_name}_{i}_{sk}', sv, output, common, prefix=prefix)
            return
        elif 'type' in ftype:
            # single inline / single ref (no repeat)
            expand(field_name, ftype['type'], output, common, prefix=prefix)
            return
        else:
            # Inline struct dict (rare — not seen in current FalcomSchema)
            for sk, sv in ftype.items():
                expand(sk, sv, output, common, prefix=f'{full_name}_')
            return

    output[full_name] = '?'


def schema_size(sch):
    total = 0
    for ft in sch.values():
        if not isinstance(ft, str): return None
        if ft in SIZES:
            total += SIZES[ft]
        elif ft.startswith('toffset'):
            total += 8
        else:
            return None
    return total


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    os.makedirs(dst, exist_ok=True)
    common = load_common(src)
    print(f"Loaded {len(common)} common schemas: {list(common)}")

    per_section = {}
    n_files = 0
    for game_dir, (plat, game) in GAME_DIR_TO_PLATFORM.items():
        for f in glob.glob(os.path.join(src, game_dir, '*.json')):
            n_files += 1
            name = os.path.basename(f)[:-5]
            d = json.load(open(f))
            flat = {}
            for fname, ftype in d['schema'].items():
                expand(fname, ftype, flat, common)
            sz = schema_size(flat)
            per_section.setdefault(name, {})[plat] = {
                'game': game,
                'schema': flat,
                'source': 'FalcomSchema (Trails-Research-Group)',
                'size_bytes': sz if sz is not None else 'complex',
            }

    for name, variants in per_section.items():
        with open(os.path.join(dst, f'{name}.json'), 'w') as f:
            json.dump(variants, f, indent='\t', ensure_ascii=False)

    print(f"Read {n_files} input files")
    print(f"Wrote {len(per_section)} output sections to {dst}/")


if __name__ == '__main__':
    main()
