#!/usr/bin/env python3
"""
sky2_fix_shaders.py - find and repair materials whose shader does not exist in
Trails in the Sky 2nd Chapter.

The symptom
-----------
A costume converted from another game looks perfect in an MDL viewer, but in
the game the character wears nothing: the meshes are simply not drawn.  The
game log says

    [LOG] file not found: asset/dx11/shader/chr_cloth#6192628a.fxo

Shaders are not compiled at run time.  Every material names a shader
(chr_cloth, chr_skin, ...) plus a set of switches, and the engine turns that
combination into one file name, <shader>#<hash>.fxo.  Sky 2nd Chapter ships
only the combinations its own models use.  A material carried over from Sky 1st
Chapter or from Kuro can ask for a combination this game never compiled, and
then the mesh is dropped.  A viewer does not care, because it renders with its
own shaders - which is why the model looks fine there.

What this script does
---------------------
It reads a set of untouched 2nd Chapter models (--ref) and collects every
shader configuration that game actually has.  Then it checks each material in
your models against that set and reports the ones that cannot work.  With --fix
it rebuilds those materials from the closest configuration the game does have,
keeping your material names and your textures.

That is the manual fix described in kuro_mdl_tool's readme ("copy the entire
section from the model you want, give it a unique material_name, update the
textures"), done automatically.

Usage
-----
A whole folder of models at once, when you do not know which ones are broken:

  # 1. build the reference from the game itself, once. Point it at pac/steam
  #    and it reads every .pac in there. The result is cached, so this is a
  #    one-off.
  python sky2_fix_shaders.py mymod --ref "F:\\Games\\...\\Trails in the Sky 2nd Chapter\\pac\\steam"

  # 2. read the report, then apply it. A .bak of every model is kept.
  python sky2_fix_shaders.py mymod --fix

The reference may also be a folder of extracted stock models, a single .mdl, or
one .pac. A model you know renders correctly in game is the strongest reference
there is:

  python sky2_fix_shaders.py mymod --ref stock_models --fix

Options
  --ref PATH        Untouched 2nd Chapter models. A folder (searched for both
                    .mdl files and .pac archives - the game's pac/steam folder
                    is the obvious choice), a single .mdl, or one .pac. May be
                    given several times. Required unless --cache already holds
                    a reference.
  --cache FILE      Store/reuse the collected configurations (default:
                    sky2_shader_ref.json). Reading a .pac is slow; the cache
                    makes later runs instant. --ref refreshes it.
  --fix             Rebuild broken materials from the reference.
  --max-diff N      Refuse to use a donor differing in more than N switches
                    (default 6). Raise it if nothing close enough is found.
  --no-recursive    Do not descend into subfolders.
  --no-backup       Do not keep a .bak of the models that are rewritten.
  -q, --quiet       Only print problems and the summary.

Exit code is 1 while unrepaired problems remain.

Requires the xxhash module (python -m pip install xxhash). blowfish and
zstandard are only needed for Kuro-format (CLE) models; sky_pac_lib.py, from
this toolkit, is only needed to read a .pac reference.

Part of the KuroDLCTools toolkit. The MDL format work is eArmada8's
(kuro_mdl_tool), as is the advice this script automates.
"""

import argparse
import base64
import glob
import io
import json
import os
import struct
import sys

try:
    import xxhash
    HAS_XXHASH = True
except ImportError:
    HAS_XXHASH = False

try:
    import operator
    import blowfish
    HAS_BLOWFISH = True
except ImportError:
    HAS_BLOWFISH = False

try:
    import zstandard
    HAS_ZSTD = True
except ImportError:
    HAS_ZSTD = False

try:
    from sky_pac_lib import sky_pac_class, is_pac_file
    HAS_PAC = True
except ImportError:
    HAS_PAC = False

    def is_pac_file(path):
        try:
            with open(path, 'rb') as f:
                return f.read(4) == b'FPAC'
        except (OSError, IOError):
            return False


DEFAULT_CACHE = 'sky2_shader_ref.json'
CLE_MAGICS = (b'F9BA', b'C9BA', b'D9BA')
MDL_MAGIC = 0x204c444d          # 'MDL '


def out(text=''):
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or 'ascii'
        print(text.encode(enc, 'replace').decode(enc, 'replace'))


# ---------------------------------------------------------------------------
# Reading models
# ---------------------------------------------------------------------------

def decrypt_cle(file_content):
    """Unwrap a Kuro / Daybreak asset (F9BA, C9BA, D9BA).

    Thank you to the authors of KuroTools for this function.
    """
    key = b"\x16\x4B\x7D\x0F\x4F\xA7\x4C\xAC\xD3\x7A\x06\xD9\xF8\x6D\x20\x94"
    IV = b"\x9D\x8F\x9D\xA1\x49\x60\xCC\x4C"
    result = file_content
    magic = file_content[0:4]
    while magic in CLE_MAGICS:
        if magic in (b'F9BA', b'C9BA'):
            if not HAS_BLOWFISH:
                raise RuntimeError("the blowfish module is needed for {} files"
                                   .format(magic.decode()))
            cipher = blowfish.Cipher(key, byte_order="big")
            iv = struct.unpack(">Q", IV)
            counter = blowfish.ctr_counter(iv[0], f=operator.add)
            result = b"".join(cipher.decrypt_ctr(file_content[8:], counter))
        else:
            if not HAS_ZSTD:
                raise RuntimeError("the zstandard module is needed for D9BA files")
            result = zstandard.ZstdDecompressor().decompress(file_content[8:])
        file_content = result
        magic = file_content[0:4]
    return result


def read_mdl_bytes(path):
    with open(path, 'rb') as f:
        data = f.read()
    return decrypt_cle(data) if data[:4] in CLE_MAGICS else data


def read_pascal_string(f):
    size = int.from_bytes(f.read(1), byteorder='little')
    return f.read(size)


def make_pascal_string(text):
    encoded = text.encode('ASCII')
    return struct.pack("<B", len(encoded)) + encoded


def mdl_sections(mdl_data):
    """[(type, size, start_offset)] for every section in the model."""
    sections = []
    with io.BytesIO(mdl_data) as f:
        header = struct.unpack("<III", f.read(12))
        if header[0] != MDL_MAGIC:
            raise ValueError("not an MDL file")
        while True:
            try:
                stype, size = struct.unpack("<II", f.read(8))
            except struct.error:
                break
            sections.append((stype, size, f.tell()))
            f.seek(size, 1)
    return sections


def get_kuro_ver(mdl_data):
    return struct.unpack("<I", mdl_data[4:8])[0]


# ---------------------------------------------------------------------------
# Material section: parse and serialise. Both follow kuro_mdl_tool exactly, so
# a parse/serialise round trip reproduces the original bytes.
# ---------------------------------------------------------------------------

# Parameter payload sizes by type. Types 0/1/4/5/6 are decoded into values, the
# rest are kept as raw bytes so they survive a round trip untouched.
DECODED_TYPES = {0: "<I", 1: "<I", 4: "<f", 5: "<2f", 6: "<3f"}
RAW_SIZES = {2: 8, 3: 12, 7: 16, 8: 64, 0xFFFFFFFF: 0}


def parse_materials(mdl_data):
    """Parse the material section into fully round-trippable dicts."""
    kuro_ver = get_kuro_ver(mdl_data)
    material_data = None
    for stype, size, start in mdl_sections(mdl_data):
        if stype == 0:
            # Refuse a truncated section outright, so a caller that handed us
            # only the front of a file knows to read the whole thing.
            if start + size > len(mdl_data):
                raise ValueError("material section is truncated")
            material_data = mdl_data[start:start + size]
            break
    if material_data is None:
        return [], kuro_ver

    materials = []
    with io.BytesIO(material_data) as f:
        blocks, = struct.unpack("<I", f.read(4))
        for index in range(blocks):
            material = {'id_referenceonly': index}
            material['material_name'] = read_pascal_string(f).decode('ASCII')
            material['shader_name'] = read_pascal_string(f).decode('ASCII')
            material['str3'] = read_pascal_string(f).decode('ASCII')

            texture_count, = struct.unpack("<I", f.read(4))
            material['textures'] = []
            for _ in range(texture_count):
                texture = {}
                texture['texture_image_name'] = read_pascal_string(f).decode('ASCII')
                texture['texture_slot'], = struct.unpack("<i", f.read(4))
                if kuro_ver > 1:
                    texture['unk_00'], = struct.unpack("<i", f.read(4))
                texture['wrapS'], texture['wrapT'] = struct.unpack("<2i", f.read(8))
                if kuro_ver > 1:
                    texture['unk_03'], = struct.unpack("<i", f.read(4))
                material['textures'].append(texture)

            parameter_count, = struct.unpack("<I", f.read(4))
            material['shaders'] = []
            for _ in range(parameter_count):
                parameter = {}
                parameter['shader_name'] = read_pascal_string(f).decode('ASCII')
                parameter['type_int'], = struct.unpack("<I", f.read(4))
                type_int = parameter['type_int']
                if type_int in DECODED_TYPES:
                    fmt = DECODED_TYPES[type_int]
                    values = struct.unpack(fmt, f.read(struct.calcsize(fmt)))
                    parameter['data'] = list(values) if len(values) > 1 else values[0]
                else:
                    parameter['data_base64'] = base64.b64encode(
                        f.read(RAW_SIZES.get(type_int, 0))).decode()
                material['shaders'].append(parameter)

            switch_count, = struct.unpack("<I", f.read(4))
            switch_start = f.tell()
            material['material_switches'] = []
            for _ in range(switch_count):
                switch = {}
                switch['material_switch_name'] = read_pascal_string(f).decode('ASCII')
                switch['int2'], = struct.unpack("<i", f.read(4))
                material['material_switches'].append(switch)
            switch_end = f.tell()
            f.seek(switch_start, 0)
            switch_bytes = f.read(switch_end - switch_start)
            material['switches_hash'] = (xxhash.xxh64_hexdigest(switch_bytes)
                                         if HAS_XXHASH else '')

            uv_count, = struct.unpack("<I", f.read(4))
            material['uv_map_indices'] = list(struct.unpack(
                "{}B".format(uv_count), f.read(uv_count)))
            unknown1_count, = struct.unpack("<I", f.read(4))
            material['unknown1'] = list(struct.unpack(
                "{}B".format(unknown1_count), f.read(unknown1_count)))
            material['unknown2'] = list(struct.unpack("<3IfI", f.read(20)))

            materials.append(material)
    return materials, kuro_ver


def build_material_section(materials, kuro_ver):
    """Serialise materials back into a complete section (header included)."""
    body = struct.pack("<I", len(materials))
    for material in materials:
        block = make_pascal_string(material['material_name']) \
            + make_pascal_string(material['shader_name']) \
            + make_pascal_string(material['str3'])

        textures = b''
        for texture in material['textures']:
            textures += make_pascal_string(texture['texture_image_name']) \
                + struct.pack("<i", texture['texture_slot'])
            if kuro_ver > 1:
                textures += struct.pack("<i", texture['unk_00'])
            textures += struct.pack("<2i", texture['wrapS'], texture['wrapT'])
            if kuro_ver > 1:
                textures += struct.pack("<i", texture['unk_03'])
        block += struct.pack("<I", len(material['textures'])) + textures

        parameters = b''
        for parameter in material['shaders']:
            parameters += make_pascal_string(parameter['shader_name']) \
                + struct.pack("<I", parameter['type_int'])
            if parameter['type_int'] in DECODED_TYPES:
                fmt = DECODED_TYPES[parameter['type_int']]
                data = parameter['data']
                if isinstance(data, list):
                    parameters += struct.pack(fmt, *data)
                else:
                    parameters += struct.pack(fmt, data)
            else:
                parameters += base64.b64decode(parameter['data_base64'])
        block += struct.pack("<I", len(material['shaders'])) + parameters

        switches = b''
        for switch in material['material_switches']:
            switches += make_pascal_string(switch['material_switch_name']) \
                + struct.pack("<i", switch['int2'])
        block += struct.pack("<I", len(material['material_switches'])) + switches

        block += struct.pack("<I{}B".format(len(material['uv_map_indices'])),
                             len(material['uv_map_indices']),
                             *material['uv_map_indices'])
        block += struct.pack("<I{}B".format(len(material['unknown1'])),
                             len(material['unknown1']), *material['unknown1'])
        block += struct.pack("<3IfI", *material['unknown2'])
        body += block
    return struct.pack("<2I", 0, len(body)) + body


def replace_material_section(mdl_data, new_section):
    """Return the model with its material section swapped for new_section."""
    rebuilt = mdl_data[:12]
    with io.BytesIO(mdl_data) as f:
        f.seek(12)
        while True:
            offset = f.tell()
            header = f.read(8)
            try:
                stype, size = struct.unpack("<II", header)
            except struct.error:
                f.seek(offset, 0)
                break
            payload = f.read(size)
            rebuilt += new_section if stype == 0 else header + payload
        rebuilt += f.read()      # trailing bytes, if any
    return rebuilt


# ---------------------------------------------------------------------------
# Shader configurations
# ---------------------------------------------------------------------------

def switch_map(material):
    """{switch name: value} for the material's switch block."""
    return {s['material_switch_name']: s['int2']
            for s in material['material_switches']}


def switch_list(material):
    """The switch block in file order - the engine hashes the raw bytes."""
    return [(s['material_switch_name'], s['int2'])
            for s in material['material_switches']]


def parameter_list(material):
    """The shader parameter block in file order, names and types only."""
    return [(p['shader_name'], p['type_int']) for p in material['shaders']]


def config_key(material):
    """Identity of a shader configuration.

    Everything the engine can fold into the compiled shader it asks for: the
    shader, str3, the switch block and the parameter block in file order, the
    UV mapping and the two trailing unknown fields.  Only the material name and
    the textures are left out, because those are what a mod legitimately
    changes.

    The switch block alone is not enough.  In a real case two materials had
    byte-identical switches and parameters and still asked for a shader the
    game does not have; the only difference was unknown2[2] (6 instead of 14),
    which evidently takes part in choosing the compiled permutation.
    """
    return json.dumps({
        'shader': material['shader_name'],
        'str3': material['str3'],
        'switches': switch_list(material),
        'parameters': parameter_list(material),
        'uv_map_indices': material['uv_map_indices'],
        'unknown1': material['unknown1'],
        'unknown2': material['unknown2'],
    }, sort_keys=True)


def switch_difference(a, b):
    """Switch names whose presence or value differs between two materials."""
    differing = []
    for name in sorted(set(a) | set(b)):
        if a.get(name) != b.get(name):
            differing.append(name)
    return differing


def describe_difference(material, donor):
    """Human-readable list of what differs between a material and a donor."""
    notes = []
    switches = switch_difference(switch_map(material), switch_map(donor))
    if switches:
        notes.append("switches: " + ", ".join(switches))
    elif switch_list(material) != switch_list(donor):
        notes.append("switches in a different order")
    if parameter_list(material) != parameter_list(donor):
        own = [p[0] for p in parameter_list(material)]
        theirs = [p[0] for p in parameter_list(donor)]
        added = [p for p in theirs if p not in own]
        removed = [p for p in own if p not in theirs]
        if added or removed:
            detail = []
            if removed:
                detail.append("drops " + ", ".join(removed[:4])
                              + ("..." if len(removed) > 4 else ""))
            if added:
                detail.append("gains " + ", ".join(added[:4])
                              + ("..." if len(added) > 4 else ""))
            notes.append("parameters: " + "; ".join(detail))
        else:
            notes.append("parameters in a different order")
    for field in ('str3', 'uv_map_indices', 'unknown1', 'unknown2'):
        if material[field] != donor[field]:
            notes.append("{0}: {1} -> {2}".format(field, material[field],
                                                  donor[field]))
    return notes


def distance(material, donor):
    """How far a donor is from a material; smaller is safer.

    Donors whose switch and parameter blocks already match are preferred, since
    replacing such a material only changes the trailing fields and cannot alter
    the texture or parameter set the mesh relies on.
    """
    switches = switch_difference(switch_map(material), switch_map(donor))
    params_differ = parameter_list(material) != parameter_list(donor)
    others = sum(1 for field in ('str3', 'uv_map_indices', 'unknown1', 'unknown2')
                 if material[field] != donor[field])
    return (len(switches), 1 if params_differ else 0, others)


# ---------------------------------------------------------------------------
# Reference set
# ---------------------------------------------------------------------------

# The material section is the first one in a model and only a few tens of KB,
# while the mesh section that follows can be many megabytes.  Reading just the
# front of each model turns scanning a whole game archive from minutes into
# seconds.  If the prefix turns out to be too short, the full file is read.
PREFIX_BYTES = 512 * 1024


def iter_reference_models(paths, recursive=True):
    """Yield (label, read) for every reference model.

    `read(limit)` returns the model bytes, at most `limit` of them when the
    source allows a partial read.
    """
    def loose_reader(mdl_path):
        def read(limit=None):
            with open(mdl_path, 'rb') as f:
                data = f.read() if limit is None else f.read(limit)
            # A CLE wrapper has to be unwrapped whole.
            if data[:4] in CLE_MAGICS:
                with open(mdl_path, 'rb') as f:
                    data = decrypt_cle(f.read())
            return data
        return read

    def pac_reader(pac_path, entry):
        def read(limit=None):
            size = entry['cmp_size'] if limit is None else min(entry['cmp_size'], limit)
            with open(pac_path, 'rb') as f:
                f.seek(entry['offset'])
                data = f.read(size)
            if data[:4] in CLE_MAGICS:
                with open(pac_path, 'rb') as f:
                    f.seek(entry['offset'])
                    data = decrypt_cle(f.read(entry['cmp_size']))
            return data
        return read

    def from_pac(pac_path):
        if not HAS_PAC:
            out("  sky_pac_lib.py is missing - cannot read {}".format(
                os.path.basename(pac_path)))
            return
        try:
            pac = sky_pac_class()
            with open(pac_path, 'rb') as pac.f:
                _header, entries, _ = pac.read_toc()
        except Exception as e:
            out("  {0}: {1}".format(os.path.basename(pac_path), e))
            return
        for entry in entries:
            if entry['name'].lower().endswith('.mdl'):
                yield os.path.basename(entry['name']), pac_reader(pac_path, entry)

    for path in paths:
        if os.path.isdir(path):
            # A folder may hold loose models, .pac archives, or both - the
            # game's pac/steam folder is the usual reference.
            mdl_pattern = os.path.join(path, '**', '*.mdl') if recursive \
                else os.path.join(path, '*.mdl')
            for mdl in sorted(glob.glob(mdl_pattern, recursive=recursive)):
                yield os.path.basename(mdl), loose_reader(mdl)
            pac_pattern = os.path.join(path, '**', '*.pac') if recursive \
                else os.path.join(path, '*.pac')
            for pac_path in sorted(glob.glob(pac_pattern, recursive=recursive)):
                if is_pac_file(pac_path):
                    for item in from_pac(pac_path):
                        yield item
        elif os.path.isfile(path) and is_pac_file(path):
            for item in from_pac(path):
                yield item
        elif os.path.isfile(path):
            yield os.path.basename(path), loose_reader(path)


def build_reference(paths, recursive=True, quiet=False):
    """Collect every shader configuration the reference models use.

    Returns {config_key: donor}, where a donor carries the whole material block
    so a broken material can be rebuilt from it.
    """
    reference = {}
    models, skipped, seen = 0, 0, 0
    for label, read in iter_reference_models(paths, recursive):
        seen += 1
        materials = None
        for limit in (PREFIX_BYTES, None):
            try:
                materials, kuro_ver = parse_materials(read(limit))
                if materials:
                    break
            except Exception:
                materials = None
        if not materials:
            skipped += 1
            continue
        models += 1
        for material in materials:
            key = config_key(material)
            if key in reference:
                continue
            donor = dict(material)
            donor['_source_model'] = label
            donor['_source_kuro_ver'] = kuro_ver
            reference[key] = donor
        if not quiet and seen % 250 == 0:
            out("  ... {0} models read, {1} configuration(s)".format(
                models, len(reference)))
    if not quiet and skipped:
        out("  ({} file(s) held no material section - animations and the like)"
            .format(skipped))
    return reference, models


def save_reference(reference, models, path):
    payload = {'version': 1, 'models': models, 'configurations': reference}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=1)


def load_reference(path):
    with open(path, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    return payload.get('configurations', {}), payload.get('models', 0)


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------

def find_donor(material, reference, max_diff):
    """Closest usable configuration for a broken material.

    Only donors using the same shader are considered - a different shader would
    need different textures and parameters.  Among those, the one differing in
    the fewest switches wins.
    """
    candidates = []
    for donor in reference.values():
        if donor['shader_name'] != material['shader_name']:
            continue
        candidates.append((distance(material, donor),
                           donor.get('_source_model', ''),
                           donor['material_name'], donor))
    if not candidates:
        return None, None
    # Closest wins; the model and material name break ties so the same donor is
    # picked on every run.
    candidates.sort(key=lambda c: (c[0], c[1], c[2]))
    best_distance, _model, _name, best = candidates[0]
    if best_distance[0] > max_diff:
        return None, describe_difference(material, best)
    return best, describe_difference(material, best)


def rebuild_material(material, donor, kuro_ver):
    """A working material: the donor's shader setup, your name and textures.

    The mesh section refers to materials by name, so the name has to stay.  The
    textures are carried over slot by slot; a slot the donor has and the broken
    material does not keeps the donor's texture, which is reported.
    """
    rebuilt = json.loads(json.dumps(donor))     # deep copy, plain data only
    rebuilt.pop('_source_model', None)
    rebuilt.pop('_source_kuro_ver', None)
    rebuilt['material_name'] = material['material_name']
    rebuilt['id_referenceonly'] = material['id_referenceonly']

    own_by_slot = {t['texture_slot']: t for t in material['textures']}
    kept, borrowed = [], []
    for texture in rebuilt['textures']:
        slot = texture['texture_slot']
        if slot in own_by_slot:
            texture['texture_image_name'] = own_by_slot[slot]['texture_image_name']
            kept.append(texture['texture_image_name'])
        else:
            borrowed.append("slot {0} -> {1}".format(
                slot, texture['texture_image_name']))

    dropped = [t['texture_image_name'] for t in material['textures']
               if t['texture_slot'] not in
               {x['texture_slot'] for x in rebuilt['textures']}]

    # Fields the parser only fills for kuro_ver > 1 must exist for the writer.
    if kuro_ver > 1:
        for texture in rebuilt['textures']:
            texture.setdefault('unk_00', 0)
            texture.setdefault('unk_03', 0)

    return rebuilt, kept, borrowed, dropped


def backup_path(path, suffix='.bak'):
    candidate = path + suffix
    if not os.path.exists(candidate):
        return candidate
    n = 1
    while os.path.exists("{0}{1}".format(candidate, n)):
        n += 1
    return "{0}{1}".format(candidate, n)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Find and repair materials whose shader configuration does "
                    "not exist in Trails in the Sky 2nd Chapter.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="The game only ships the shader combinations its own models use.\n"
               "A material asking for any other one makes the mesh disappear -\n"
               "the log says 'file not found: asset/dx11/shader/<name>#<hash>.fxo'.")
    parser.add_argument('directory', nargs='?', default='.',
                        help="folder with the .mdl files to check (default: current)")
    parser.add_argument('--ref', action='append', default=[], metavar='PATH',
                        help="untouched 2nd Chapter models: a folder (both "
                             ".mdl files and .pac archives inside it are used), "
                             "an .mdl or a .pac (may be repeated)")
    parser.add_argument('--cache', default=DEFAULT_CACHE, metavar='FILE',
                        help="where to keep the collected configurations "
                             "(default: {})".format(DEFAULT_CACHE))
    parser.add_argument('--fix', action='store_true',
                        help="rebuild broken materials from the reference")
    parser.add_argument('--max-diff', type=int, default=6, metavar='N',
                        help="largest acceptable number of differing switches "
                             "(default: 6)")
    parser.add_argument('--no-recursive', action='store_true',
                        help="do not descend into subfolders")
    parser.add_argument('--no-backup', action='store_true',
                        help="do not keep a .bak of rewritten models")
    parser.add_argument('-q', '--quiet', action='store_true',
                        help="only print problems and the summary")
    args = parser.parse_args()

    if not HAS_XXHASH:
        out("The xxhash module is missing.  Install it with:")
        out("  python -m pip install xxhash")
        return 2

    recursive = not args.no_recursive
    scan_dir = os.path.abspath(args.directory)
    if not os.path.isdir(scan_dir):
        out("Not a folder: {}".format(scan_dir))
        return 2

    pattern = os.path.join(scan_dir, '**', '*.mdl') if recursive \
        else os.path.join(scan_dir, '*.mdl')
    mdl_files = sorted(glob.glob(pattern, recursive=recursive))
    # Never treat the reference itself as something to check.
    ref_abs = {os.path.abspath(p) for p in args.ref}
    mdl_files = [m for m in mdl_files
                 if not any(os.path.abspath(m).startswith(r) for r in ref_abs)]
    if not mdl_files:
        out("No .mdl files found in {}".format(scan_dir))
        return 0

    # ---- reference -------------------------------------------------------
    reference, ref_models = {}, 0
    if args.ref:
        if not args.quiet:
            out("Reading reference models...")
        reference, ref_models = build_reference(args.ref, recursive, args.quiet)
        if reference:
            try:
                save_reference(reference, ref_models, args.cache)
                if not args.quiet:
                    out("Cached to {}".format(args.cache))
            except OSError as e:
                out("Could not write the cache: {}".format(e))
    elif os.path.exists(args.cache):
        try:
            reference, ref_models = load_reference(args.cache)
            if not args.quiet:
                out("Reference loaded from {}".format(args.cache))
        except (OSError, ValueError) as e:
            out("Could not read {0}: {1}".format(args.cache, e))

    if not reference:
        out("No reference configurations available.")
        out("")
        out("Point --ref at untouched Trails in the Sky 2nd Chapter models. "
            "The game's own")
        out("pac/steam folder is the easiest choice - every .pac in it is read, "
            "and the result")
        out("is cached so this is a one-off:")
        out('  python sky2_fix_shaders.py mymod --ref "<game>/pac/steam"')
        return 2

    if not args.quiet:
        out("Reference: {0} shader configuration(s) from {1} model(s)".format(
            len(reference), ref_models))
        out("Checking:  {0} model(s) in {1}".format(len(mdl_files), scan_dir))
        out("")

    # A thin reference is the one real hazard of fixing a whole folder at once:
    # a configuration the game does have but the reference happens to miss looks
    # broken, and --fix would rewrite a material that was fine.
    if len(reference) < 50:
        out("[!] This reference is small ({0} configuration(s) from {1} model(s))."
            .format(len(reference), ref_models))
        out("    Anything it does not happen to contain will look broken. For a "
            "whole folder of")
        out("    models, build it from the game itself:")
        out('      python sky2_fix_shaders.py {0} --ref "<game>/pac/steam"'.format(
            args.directory))
        out("")

    # ---- check -----------------------------------------------------------
    broken_total, fixed_total, unfixable_total = 0, 0, 0
    models_with_problems = []
    unreadable = []

    for mdl in mdl_files:
        rel = os.path.relpath(mdl, scan_dir)
        try:
            with open(mdl, 'rb') as f:
                original_bytes = f.read()
            data = read_mdl_bytes(mdl)
            materials, kuro_ver = parse_materials(data)
        except Exception as e:
            unreadable.append((rel, str(e)))
            continue
        if not materials:
            unreadable.append((rel, "no material section"))
            continue

        broken = [m for m in materials if config_key(m) not in reference]
        if not broken:
            if not args.quiet:
                out("{0}   ({1} material(s), all ok)".format(rel, len(materials)))
            continue

        models_with_problems.append(rel)
        broken_total += len(broken)
        out(rel)

        changed = False
        for material in broken:
            out("    [broken] {0}   shader {1}, {2} switch(es)".format(
                material['material_name'], material['shader_name'],
                len(material['material_switches'])))

            donor, differing = find_donor(material, reference, args.max_diff)
            if donor is None:
                unfixable_total += 1
                if differing is None:
                    out("             no material in the reference uses shader "
                        "{}".format(material['shader_name']))
                else:
                    out("             the closest configuration differs too "
                        "much (--max-diff is {})".format(args.max_diff))
                    for note in differing:
                        out("               {}".format(note))
                continue

            out("             donor: {0} / {1}".format(
                donor['_source_model'], donor['material_name']))
            for note in differing:
                out("             changes -> {}".format(note))
            if not differing:
                out("             identical configuration (nothing to change)")

            if not args.fix:
                continue

            rebuilt, kept, borrowed, dropped = rebuild_material(
                material, donor, kuro_ver)
            materials[material['id_referenceonly']] = rebuilt
            changed = True
            fixed_total += 1
            out("             rebuilt, {} texture(s) carried over".format(len(kept)))
            for note in borrowed:
                out("             [!] no texture of yours for {} - the donor's "
                    "is kept".format(note))
            for name in dropped:
                out("             [!] your texture {} has no slot in the new "
                    "material".format(name))

        if args.fix and changed:
            try:
                new_section = build_material_section(materials, kuro_ver)
                new_data = replace_material_section(data, new_section)
                if not args.no_backup:
                    target = backup_path(mdl)
                    with open(target, 'wb') as f:
                        f.write(original_bytes)
                    out("    backup: {}".format(os.path.basename(target)))
                with open(mdl, 'wb') as f:
                    f.write(new_data)
                out("    written: {}".format(rel))
            except Exception as e:
                out("    [FAILED] could not rewrite: {}".format(e))
                unfixable_total += 1
                fixed_total = max(0, fixed_total - 1)

    # ---- summary ---------------------------------------------------------
    out("")
    out("=" * 62)
    out("Models checked:       {}".format(len(mdl_files)))
    out("Models with problems: {}".format(len(models_with_problems)))
    out("Broken materials:     {}".format(broken_total))
    if args.fix:
        out("Materials rebuilt:    {}".format(fixed_total))
    if unfixable_total:
        out("Not repairable:       {}".format(unfixable_total))
    if unreadable:
        out("Models unreadable:    {}".format(len(unreadable)))
        for rel, reason in unreadable:
            out("    {0}: {1}".format(rel, reason))
    out("=" * 62)

    if broken_total == 0:
        out("Every material uses a shader configuration this game has.")
    elif not args.fix:
        out("Run again with --fix to rebuild {} material(s).".format(broken_total))
        out("A .bak of every model that changes is kept.")
    elif fixed_total:
        out("Check the models in game.  A donor whose switches differ can change "
            "how a surface")
        out("looks - alpha, face culling, rim light.  If something comes out "
            "wrong, restore the")
        out(".bak and pick a donor by hand: kuro_mdl_tool's "
            "kuro_find_similar_shaders.py lists the")
        out("alternatives, and its readme explains copying a material across "
            "by hand.")

    remaining = unfixable_total + (broken_total if not args.fix else 0)
    return 1 if remaining or unreadable else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        out("\nCancelled.")
        sys.exit(130)
