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

Just one model from the folder:

  python sky2_fix_shaders.py mymod --mdl mod_chr5000_c72qw --fix

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
  --mdl NAME        Only process this model (file name, .mdl optional, or a
                    path). May be given several times. Without it every model
                    in the folder is processed, as before.
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
import re
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


def build_reference(paths, recursive=True, quiet=False, exclude=()):
    """Collect every shader configuration the reference models use.

    Returns {config_key: donor}, where a donor carries the whole material block
    so a broken material can be rebuilt from it.  Models named in `exclude`
    (lower-case file names) are skipped - with an auto-detected game folder
    those are the very models being checked, possibly installed there already.
    """
    reference = {}
    models, skipped, seen = 0, 0, 0
    for label, read in iter_reference_models(paths, recursive):
        if label.lower() in exclude:
            continue
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


def save_reference(reference, models, path, sources=None):
    payload = {'version': 1, 'models': models, 'configurations': reference}
    if sources:
        payload['sources'] = [os.path.abspath(p) for p in sources]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=1)


def load_reference(path):
    with open(path, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    return (payload.get('configurations', {}), payload.get('models', 0),
            payload.get('sources') or [])


# ---------------------------------------------------------------------------
# Finding the game
# ---------------------------------------------------------------------------

# Steam's name for the game and the folder it installs to. Matched loosely so
# that a renamed or localised install is still found; 1st Chapter never matches.
GAME_NAME_RE = re.compile(r'sky.*(2nd|second|\bsc\b)', re.IGNORECASE)
REFERENCE_MIN_CONFIGS = 50


def pac_folder(game_dir):
    """The folder with the game's .pac archives, or None."""
    for candidate in (os.path.join(game_dir, 'pac', 'steam'),
                      os.path.join(game_dir, 'pac'), game_dir):
        try:
            names = os.listdir(candidate)
        except OSError:
            continue
        for name in names:
            if name.lower().endswith('.pac') and \
                    is_pac_file(os.path.join(candidate, name)):
                return candidate
    return None


def steam_roots():
    """Where Steam itself is installed, on Windows, Linux and SteamOS."""
    roots = []
    if os.name == 'nt':
        try:
            import winreg
            for hive, key, value in (
                    (winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                    (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam',
                     'InstallPath'),
                    (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath')):
                try:
                    with winreg.OpenKey(hive, key) as handle:
                        roots.append(winreg.QueryValueEx(handle, value)[0])
                except OSError:
                    pass
        except ImportError:
            pass
        for env in ('ProgramFiles(x86)', 'ProgramFiles'):
            if os.environ.get(env):
                roots.append(os.path.join(os.environ[env], 'Steam'))
    else:
        home = os.path.expanduser('~')
        roots += [os.path.join(home, '.steam', 'steam'),
                  os.path.join(home, '.steam', 'root'),
                  os.path.join(home, '.local', 'share', 'Steam'),
                  os.path.join(home, '.var', 'app', 'com.valvesoftware.Steam',
                               '.local', 'share', 'Steam')]
    seen, unique = set(), []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        real = os.path.normcase(os.path.realpath(root))
        if real not in seen:
            seen.add(real)
            unique.append(root)
    return unique


def steam_libraries(root):
    """Every library folder Steam knows about (extra drives, SD cards...)."""
    libraries = [root]
    vdf = os.path.join(root, 'steamapps', 'libraryfolders.vdf')
    try:
        with open(vdf, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return libraries
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        libraries.append(match.group(1).replace('\\\\', '\\'))
    return libraries


def steam_game_dirs():
    """Installed copies of the game, found through Steam's app manifests."""
    found, seen = [], set()
    for root in steam_roots():
        for library in steam_libraries(root):
            apps = os.path.join(library, 'steamapps')
            candidates = []
            for manifest in glob.glob(os.path.join(apps, 'appmanifest_*.acf')):
                try:
                    with open(manifest, 'r', encoding='utf-8', errors='replace') as f:
                        text = f.read()
                except OSError:
                    continue
                name = re.search(r'"name"\s+"([^"]*)"', text)
                folder = re.search(r'"installdir"\s+"([^"]*)"', text)
                if name and folder and GAME_NAME_RE.search(name.group(1)):
                    candidates.append(os.path.join(apps, 'common', folder.group(1)))
            # Manifests missing (a copied install): go by the folder name.
            for folder in glob.glob(os.path.join(apps, 'common', '*')):
                if GAME_NAME_RE.search(os.path.basename(folder)):
                    candidates.append(folder)
            for folder in candidates:
                real = os.path.normcase(os.path.realpath(folder))
                if real not in seen and os.path.isdir(folder):
                    seen.add(real)
                    found.append(folder)
    return found


def detect_reference(start_dirs):
    """The game's pac folder, found without being told. (path, how) or (None, None).

    First the folders above the models and the script - the toolkit is often
    kept inside the game folder - then every Steam library on the machine.
    """
    seen = set()
    for start in start_dirs:
        folder = os.path.abspath(start)
        while True:
            if folder not in seen:
                seen.add(folder)
                pacs = pac_folder(folder)
                # A folder of loose .pac files above the models counts only
                # when it looks like the game's own pac/steam layout.
                if pacs and (pacs != folder or
                             os.path.basename(os.path.dirname(folder)).lower() == 'pac'):
                    return pacs, "game folder above {}".format(start)
            parent = os.path.dirname(folder)
            if parent == folder:
                break
            folder = parent
    for game_dir in steam_game_dirs():
        pacs = pac_folder(game_dir)
        if pacs:
            return pacs, "Steam library"
    return None, None


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


# The reference only lists what the game's own models use, and the game has
# more shaders than that: a working port of a Kuro costume kept a fur material
# and several chr_cloth parameter sets no game model has. So a configuration
# missing from the reference is at most a suspect.
#
# unknown2[2] is a set of flags. What was learnt on real models:
#  - a Kuro chr_cloth material with the value 6 did not render in 2nd Chapter;
#    with 14 (the same plus 8), exactly as the game's own copy of that
#    configuration has it, it did;
#  - chr_hair and chr_cloth materials with 14 render fine even where every model
#    of the game uses 6 for the same configuration.
# So adding the 8 flag is a proven repair and removing it is never needed.
RENDER_FLAG = 8


def only_unknown2_differs(material, donor):
    if switch_list(material) != switch_list(donor):
        return False
    if parameter_list(material) != parameter_list(donor):
        return False
    for field in ('str3', 'uv_map_indices', 'unknown1'):
        if material[field] != donor[field]:
            return False
    ours, theirs = material['unknown2'], donor['unknown2']
    return ours[:2] == theirs[:2] and ours[3:] == theirs[3:] and ours[2] != theirs[2]


def classify(material, donor, differing):
    """How sure we are that a material missing from the reference is broken.

    missing_shader  no game model uses the shader at all
    certain         only the render flag is missing - the proven failure
    known_ok        the flag is set where the game's models leave it out -
                    proven to render, so not touched
    unverified      switches or parameters differ; may well work, since the game
                    ships more shaders than its models use
    too_far         nothing comparable in the reference
    """
    if donor is None:
        return 'missing_shader' if differing is None else 'too_far'
    if only_unknown2_differs(material, donor):
        ours, theirs = material['unknown2'][2], donor['unknown2'][2]
        if theirs == ours | RENDER_FLAG:
            return 'certain'
        if ours == theirs | RENDER_FLAG:
            return 'known_ok'
    return 'unverified'


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


# ---------------------------------------------------------------------------
# Shaders the game does not have at all
# ---------------------------------------------------------------------------

# A shader no 2nd Chapter model uses was never compiled for the game, so no
# configuration of it can work.  Such a material is moved to a shader the game
# does have.  Only character shaders are handled; the fur shell effect, for
# example, has no counterpart and is simply lost - the mesh renders as cloth.
SUBSTITUTE_SHADERS = {'fur': 'chr_cloth'}


def substitute_shader(shader):
    if shader in SUBSTITUTE_SHADERS:
        return SUBSTITUTE_SHADERS[shader]
    if shader.startswith('chr_'):
        return 'chr_cloth'
    return None


def texture_role(name):
    """What a texture is for, judged by the usual naming."""
    lowered = name.lower()
    if 'toon' in lowered:
        return 'toon'
    if lowered.endswith('_n'):
        return 'normal'
    if lowered.endswith(('_q', '_p', '_m')):
        return 'mask'
    return 'diffuse'


def textures_by_role(material):
    """{role: texture name}.  The diffuse is the one in the lowest slot, so a
    shader-specific extra (a fur pattern, say) is not mistaken for it."""
    roles = {}
    for texture in sorted(material['textures'], key=lambda t: t['texture_slot']):
        role = texture_role(texture['texture_image_name'])
        roles.setdefault(role, texture['texture_image_name'])
    return roles


def find_substitute(material, siblings, reference):
    """A working material on another shader to rebuild `material` from.

    First choice is a material of the same model that already works and uses
    the same textures - it is known to suit this mesh and these images. Failing
    that, the closest configuration of the substitute shader in the reference.
    Returns (donor, where it came from) or (None, None).
    """
    target = substitute_shader(material['shader_name'])
    if target is None:
        return None, None
    own = set(t['texture_image_name'] for t in material['textures'])

    best = None
    for sibling in siblings:
        if sibling is material or sibling['shader_name'] != target:
            continue
        key = config_key(sibling)
        if key not in reference:
            continue
        shared = len(own & set(t['texture_image_name'] for t in sibling['textures']))
        if shared == 0:
            continue
        rank = (-shared, len(switch_difference(switch_map(material),
                                               switch_map(sibling))),
                sibling['material_name'])
        if best is None or rank < best[0]:
            # The sibling itself, not the reference copy of its configuration:
            # its textures belong to this costume, so a mask or toon map the
            # broken material lacks comes from the same set.
            best = (rank, sibling, sibling['material_name'])
    if best is not None:
        return best[1], "this model / {}".format(best[2])

    candidates = []
    for donor in reference.values():
        if donor['shader_name'] != target or not donor['textures']:
            continue
        candidates.append((len(switch_difference(switch_map(material),
                                                 switch_map(donor))),
                           donor.get('_source_model', ''),
                           donor['material_name'], donor))
    if not candidates:
        return None, None
    candidates.sort(key=lambda c: (c[0], c[1], c[2]))
    donor = candidates[0][3]
    return donor, "{0} / {1}".format(donor.get('_source_model', ''),
                                     donor['material_name'])


def rebuild_material_by_role(material, donor, kuro_ver):
    """Like rebuild_material, for a donor on a different shader: slot numbers
    mean different things there, so textures are matched by what they are."""
    rebuilt = json.loads(json.dumps(donor))
    rebuilt.pop('_source_model', None)
    rebuilt.pop('_source_kuro_ver', None)
    rebuilt['material_name'] = material['material_name']
    rebuilt['id_referenceonly'] = material['id_referenceonly']

    own = textures_by_role(material)
    used, kept, borrowed = set(), [], []
    for texture in rebuilt['textures']:
        role = texture_role(texture['texture_image_name'])
        if role in own:
            texture['texture_image_name'] = own[role]
            used.add(own[role])
            kept.append(own[role])
        else:
            borrowed.append("{0} (slot {1}) -> {2}".format(
                role, texture['texture_slot'], texture['texture_image_name']))
    dropped = [t['texture_image_name'] for t in material['textures']
               if t['texture_image_name'] not in used]
    if kuro_ver > 1:
        for texture in rebuilt['textures']:
            texture.setdefault('unk_00', 0)
            texture.setdefault('unk_03', 0)
    return rebuilt, kept, borrowed, dropped


def restore_backups(mdl_files, scan_dir):
    """Undo every earlier --fix: each model gets its first backup back.

    The first backup (<model>.bak) is the file as it was before this script
    touched it at all; later runs made .bak1, .bak2... The backups are kept.
    """
    restored = 0
    for mdl in mdl_files:
        first = mdl + '.bak'
        if not os.path.isfile(first):
            continue
        with open(first, 'rb') as f:
            original = f.read()
        with open(mdl, 'rb') as f:
            current = f.read()
        rel = rel_name(mdl, scan_dir)
        if original == current:
            out("{}   already the original".format(rel))
            continue
        with open(mdl, 'wb') as f:
            f.write(original)
        restored += 1
        out("{0}   restored from {1}".format(rel, os.path.basename(first)))
    out("")
    out("{} model(s) restored. Run with --fix again to repair them the careful way."
        .format(restored) if restored else "Nothing to restore.")
    return 0


def select_models(names, mdl_files, scan_dir):
    """Narrow mdl_files to the models asked for with --mdl.

    A name may be a path to an existing .mdl (used as is, even outside the
    folder), a path relative to the folder, or a bare file name with or
    without .mdl, matched case-insensitively anywhere under the folder.
    Returns (selected, missing) where missing is [(name, close_matches)].
    """
    import difflib
    by_base = {}
    for m in mdl_files:
        by_base.setdefault(os.path.basename(m).lower(), []).append(m)
    selected, missing = [], []
    for name in names:
        hits = []
        for candidate in (name, os.path.join(scan_dir, name)):
            if not candidate.lower().endswith('.mdl'):
                candidate += '.mdl'
            if os.path.isfile(candidate):
                hits = [os.path.abspath(candidate)]
                break
        if not hits:
            base = os.path.basename(name).lower()
            if not base.endswith('.mdl'):
                base += '.mdl'
            hits = by_base.get(base, [])
        if not hits:
            close = difflib.get_close_matches(
                os.path.basename(name).lower(), list(by_base), n=3, cutoff=0.6)
            missing.append((name, close))
            continue
        for hit in hits:
            # Match the spelling glob produced, so later relpath output is the same.
            same = [m for m in mdl_files
                    if os.path.normcase(os.path.abspath(m)) == os.path.normcase(hit)]
            hit = same[0] if same else hit
            if hit not in selected:
                selected.append(hit)
    return selected, missing


def rel_name(path, base):
    """relpath that also works for a file on another drive (Windows)."""
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return path


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
               "the log says 'file not found: asset/dx11/shader/<name>#<hash>.fxo'.\n\n"
               "Reference (what the game has), in this order:\n"
               "  --ref PATH      always used when given\n"
               "  the cache       sky2_shader_ref.json from an earlier run\n"
               "  auto-detected   the game's pac/steam in a folder above the models\n"
               "                  or the script, or in any Steam library (Windows,\n"
               "                  Linux, SteamOS, Flatpak Steam)\n\n"
               "Examples:\n"
               "  python sky2_fix_shaders.py mymod            report, game found automatically\n"
               "  python sky2_fix_shaders.py mymod --fix      repair (a .bak is kept)\n"
               "  python sky2_fix_shaders.py mymod --mdl mod_chr5000_c72qw --fix   only that model\n"
               "  python sky2_fix_shaders.py mymod --rebuild  read the game again (after an update)\n"
               '  python sky2_fix_shaders.py mymod --ref "D:\\Games\\Sky2nd\\pac\\steam"')
    parser.add_argument('directory', nargs='?', default='.',
                        help="folder with the .mdl files to check (default: current)")
    parser.add_argument('--ref', action='append', default=[], metavar='PATH',
                        help="untouched 2nd Chapter models: a folder (both "
                             ".mdl files and .pac archives inside it are used), "
                             "an .mdl or a .pac (may be repeated). Without it "
                             "the cache is used, or the game is found "
                             "automatically (folders above, Steam libraries)")
    parser.add_argument('--rebuild', action='store_true',
                        help="ignore the cache and read the game again (found "
                             "automatically unless --ref is given)")
    parser.add_argument('--cache', default=DEFAULT_CACHE, metavar='FILE',
                        help="where to keep the collected configurations "
                             "(default: {})".format(DEFAULT_CACHE))
    parser.add_argument('--fix', action='store_true',
                        help="rebuild broken materials from the reference")
    parser.add_argument('--max-diff', type=int, default=6, metavar='N',
                        help="largest acceptable number of differing switches "
                             "(default: 6)")
    parser.add_argument('--restore', action='store_true',
                        help="put back the original of every model this script "
                             "ever rewrote (from its first .bak), then stop")
    parser.add_argument('--aggressive', action='store_true',
                        help="with --fix, also rewrite materials that are only "
                             "unverified (switches or parameters differ from "
                             "every game model). Not recommended: the game "
                             "usually has these shaders too")
    parser.add_argument('--substitute', action='store_true',
                        help="with --fix, move materials whose shader no game "
                             "model uses (e.g. fur) to chr_cloth. Off by default: "
                             "the game does have such shaders - a working port "
                             "kept its fur material as it was")
    parser.add_argument('--mdl', action='append', default=[], metavar='NAME',
                        help="only process this model: a file name (.mdl "
                             "optional, looked up in the folder) or a path. "
                             "May be repeated. Without it every model in the "
                             "folder is processed")
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
    # Every model in the folder, kept for excluding the mod from an
    # auto-detected game reference even when --mdl narrows the work.
    all_mdl_files = list(mdl_files)
    if args.mdl:
        selected, missing = select_models(args.mdl, mdl_files, scan_dir)
        if missing:
            for name, close in missing:
                out("--mdl {}: no such model in {}".format(name, scan_dir))
                if close:
                    out("  did you mean: {}".format(", ".join(close)))
            return 2
        mdl_files = selected
        all_mdl_files = sorted(set(all_mdl_files) | set(selected))
    if not mdl_files:
        out("No .mdl files found in {}".format(scan_dir))
        return 0

    if args.restore:
        return restore_backups(mdl_files, scan_dir)

    # ---- reference -------------------------------------------------------
    # 1. --ref, when given, always wins.
    # 2. Otherwise the cache from an earlier run - unless it is thin (built from
    #    a model or two) and the game itself can be found.
    # 3. Otherwise the game is looked for: above the models and the script,
    #    then in every Steam library. The result is cached.
    reference, ref_models, ref_sources = {}, 0, list(args.ref)
    cache_path = args.cache
    if not os.path.exists(cache_path) and args.cache == DEFAULT_CACHE:
        beside_script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     DEFAULT_CACHE)
        if os.path.exists(beside_script):
            cache_path = beside_script

    build_from, exclude = None, ()
    if args.ref:
        build_from = args.ref
        if not args.quiet:
            out("Reference: --ref {}".format(", ".join(args.ref)))
    else:
        if os.path.exists(cache_path) and not args.rebuild:
            try:
                reference, ref_models, ref_sources = load_reference(cache_path)
                if not args.quiet:
                    out("Reference loaded from {}".format(cache_path))
            except (OSError, ValueError) as e:
                out("Could not read {0}: {1}".format(cache_path, e))
        if len(reference) < REFERENCE_MIN_CONFIGS:
            found, how = detect_reference(
                [scan_dir, os.getcwd(), os.path.dirname(os.path.abspath(__file__))])
            if found:
                if reference and not args.quiet:
                    out("The cached reference is small ({} configuration(s)); "
                        "rebuilding it from the game.".format(len(reference)))
                if not args.quiet:
                    out("Game found ({0}): {1}".format(how, found))
                build_from = [found]
                # The game folder may already hold the mod being checked.
                exclude = {os.path.basename(m).lower() for m in all_mdl_files}
            elif args.rebuild and not args.quiet:
                out("--rebuild: the game could not be found; point --ref at it.")

    if build_from:
        if not args.quiet:
            out("Reading reference models (a one-off, the result is cached)...")
        built, built_models = build_reference(build_from, recursive, args.quiet,
                                              exclude)
        if built:
            reference, ref_models, ref_sources = built, built_models, build_from
            try:
                save_reference(reference, ref_models, cache_path, build_from)
                if not args.quiet:
                    out("Cached to {}".format(cache_path))
            except OSError as e:
                out("Could not write the cache: {}".format(e))

    if not reference:
        out("No reference configurations available, and the game was not found.")
        out("")
        out("Looked above {0}, above this script, and in the Steam libraries."
            .format(scan_dir))
        out("Point --ref at the game's pac/steam folder (every .pac in it is "
            "read, and the")
        out("result is cached, so this is a one-off):")
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
    known_ok_total, unverified_total, certain_total = 0, 0, 0
    models_with_problems = []
    unreadable = []

    for mdl in mdl_files:
        rel = rel_name(mdl, scan_dir)
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

        before = broken_total
        out(rel)

        changed = False
        for material in broken:
            donor, differing = find_donor(material, reference, args.max_diff)
            verdict = classify(material, donor, differing)
            name = material['material_name']

            # ---- known to work although no game model uses it -------------
            if verdict == 'known_ok':
                known_ok_total += 1
                if not args.quiet:
                    out("    [ok]     {0}   unknown2[2] = {1}; the game's own models "
                        "use {2},".format(name, material['unknown2'][2],
                                          donor['unknown2'][2]))
                    out("             but this variant is known to render - "
                        "left alone")
                continue

            broken_total += 1

            # ---- the game has no such shader at all -------------------------
            if verdict == 'missing_shader':
                out("    [?]      {0}   shader {1}: no model of the game uses it"
                    .format(name, material['shader_name']))
                out("             The game still has shaders its models do not use "
                    "(a working port")
                out("             kept a fur material unchanged), so this is not "
                    "proof of a problem.")
                if not args.substitute:
                    if args.fix:
                        unverified_total += 1
                        out("             not changed (--substitute moves it to "
                            "chr_cloth)")
                    continue
                substitute, origin = find_substitute(material, materials, reference)
                if substitute is None:
                    unfixable_total += 1
                    out("             no working shader to move it to - reassign "
                        "it in Blender")
                    continue
                out("             replace with shader {0}, donor: {1}".format(
                    substitute['shader_name'], origin))
                out("             [!] the {} look is lost; the mesh renders as "
                    "{}".format(material['shader_name'], substitute['shader_name']))
                if not args.fix:
                    continue
                rebuilt, kept, borrowed, dropped = rebuild_material_by_role(
                    material, substitute, kuro_ver)
                materials[material['id_referenceonly']] = rebuilt
                changed = True
                fixed_total += 1
                out("             rebuilt, textures kept: {}".format(
                    ", ".join(kept) or "none"))
                for note in borrowed:
                    out("             [!] no texture of yours for {} - kept from "
                        "the donor".format(note))
                for note in dropped:
                    out("             [!] {} is not used by the new "
                        "shader".format(note))
                continue

            if verdict == 'too_far':
                unfixable_total += 1
                out("    [?]      {0}   shader {1}: nothing close enough in the game"
                    .format(name, material['shader_name']))
                for note in differing or []:
                    out("               {}".format(note))
                continue

            # ---- certain: only the render flag is missing ---------------------
            # ---- unverified: switches or parameters differ --------------------
            if verdict == 'certain':
                certain_total += 1
                out("    [broken] {0}   shader {1}".format(name, material['shader_name']))
            else:
                out("    [?]      {0}   shader {1}: this exact configuration is not "
                    "in any game model".format(name, material['shader_name']))
                out("             That alone does not prove it is broken - the game "
                    "has more shaders")
                out("             than its models use. Check in game first; the log "
                    "says 'file not found:")
                out("             asset/dx11/shader/{}#....fxo' when it is."
                    .format(material['shader_name']))
            out("             donor: {0} / {1}".format(
                donor['_source_model'], donor['material_name']))
            for note in differing:
                out("             changes -> {}".format(note))

            if not args.fix:
                continue
            if verdict == 'unverified' and not args.aggressive:
                unverified_total += 1
                out("             not changed (--aggressive rewrites it anyway)")
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
            for note in dropped:
                out("             [!] your texture {} has no slot in the new "
                    "material".format(note))

        if broken_total > before:
            models_with_problems.append(rel)
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
    out("Flagged materials:    {}  ([broken] and [?] above)".format(broken_total))
    if known_ok_total:
        out("Known-good variants:  {}  (not in the game's models, but render)"
            .format(known_ok_total))
    if unverified_total:
        out("Left unchanged:       {}  (unverified - see above; --aggressive)"
            .format(unverified_total))
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
        out("Every material uses a shader configuration this game has, or one known "
            "to work.")
    elif not args.fix:
        if certain_total:
            out("Run again with --fix to repair the {} [broken] material(s); the [?] "
                "ones are".format(certain_total))
            out("left alone unless you ask (--aggressive, --substitute). A .bak of "
                "every model that")
            out("changes is kept.")
        else:
            out("Nothing proven broken. The [?] materials are only suspects - check "
                "the game's")
            out("console.log for 'file not found: asset/dx11/shader/...' before "
                "changing anything.")
    elif fixed_total:
        out("Check the models in game.  A donor whose switches differ can change "
            "how a surface")
        out("looks - alpha, face culling, rim light.  If something comes out "
            "wrong, restore the")
        out(".bak and pick a donor by hand: kuro_mdl_tool's "
            "kuro_find_similar_shaders.py lists the")
        out("alternatives, and its readme explains copying a material across "
            "by hand.")

    remaining = unfixable_total + (certain_total if not args.fix else 0)
    return 1 if remaining or unreadable else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        out("\nCancelled.")
        sys.exit(130)
