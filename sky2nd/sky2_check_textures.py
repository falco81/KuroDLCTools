#!/usr/bin/env python3
"""
sky2_check_textures.py - check the .dds textures of a Trails in the Sky 2nd
Chapter mod and convert them to the format the game will actually load.

Two formats matter, and which one is right depends on how the mod is installed:

  loose files   (asset/dx11/image/*.dds next to the game, served by the mod
                loader - the log says "PAC bypass" and "LZ4 bypassed: vtable
                swapped for raw DDS")
                -> PLAIN .dds.  The loader switches the game to reading raw
                DDS, so an LZ4-wrapped file is not loaded.  This is the
                default target.

  inside a .pac (the game's own archives)
                -> LZ4-wrapped DDS (magic 04 22 4D 18).  --target pac.

Textures carried over from Kuro / Daybreak are Blowfish-encrypted or
zstd-compressed (F9BA / C9BA / D9BA); Sky 2nd reads neither, and they are
converted like the rest.

Every texture is also checked for a sane DDS header and complete image data
(a truncated export fails to load just the same).

Which textures are checked:
  - the ones the .mdl models in the folder use (missing files are reported), or
  - every .dds under the folder with --all, or when the folder has no models.

Usage:
  python sky2_check_textures.py                     check the current folder
  python sky2_check_textures.py mymod               check another folder
  python sky2_check_textures.py mymod --fix         convert to plain .dds
  python sky2_check_textures.py mymod --all --fix   every .dds, not only used ones
  python sky2_check_textures.py mymod --fix --target pac    LZ4, for a .pac

Options:
  --fix                Convert every texture to the target format. A backup of
                       each converted file is kept (<name>.dds.lz4_original,
                       .raw_original or .kuro_original) unless --no-backup.
  --target loose|pac   The format to aim for (default: loose = plain .dds).
  --decompress         Same as --fix --target loose (kept for old scripts).
  --all                Check every .dds under the folder, not only the ones the
                       models use.
  --image-dir DIR      Where the .dds files live. Default: asset/dx11/image
                       above the models, each model's own folder and the scan
                       folder, recursively.
  --shader-ref PATH    Untouched 2nd Chapter .mdl files; report materials whose
                       shader configuration none of them uses (see also
                       sky2_fix_shaders.py, which does this better).
  --no-recursive       Only the folder itself, no subfolders.
  --no-backup          Do not keep backups of converted textures.
  --list-ok            Also list the textures that are fine.
  -q, --quiet          Only the problems and the summary.

Exit code is 1 when problems remain, so it can be used in a build step.

Requires the lz4 module (python -m pip install lz4). blowfish and zstandard
are only needed for Kuro-format textures.

Part of the KuroDLCTools toolkit. The LZ4 texture format of Sky 2nd Chapter was
documented by eArmada8 (kuro_mdl_tool); the MDL material parser follows the
same project's format work.
"""

import argparse
import glob
import io
import os
import struct
import sys

# ---------------------------------------------------------------------------
# Optional modules. Only lz4 is needed for the common case.
# ---------------------------------------------------------------------------
try:
    import lz4.frame
    HAS_LZ4 = True
except ImportError:
    HAS_LZ4 = False

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


# ---------------------------------------------------------------------------
# Console output. Texture and material names can contain characters the Windows
# console cannot encode, so every print goes through here.
# ---------------------------------------------------------------------------

def out(text=''):
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or 'ascii'
        print(text.encode(enc, 'replace').decode(enc, 'replace'))


# ---------------------------------------------------------------------------
# File format detection
# ---------------------------------------------------------------------------

LZ4_MAGIC = b'\x04\x22\x4D\x18'
DDS_MAGIC = b'DDS '
CLE_MAGICS = (b'F9BA', b'C9BA', b'D9BA')

# What a texture file turned out to be.
OK      = 'lz4'          # LZ4 frame holding a DDS - what a .pac holds
RAW     = 'plain'        # plain .dds - what loose files through the loader need
CLE     = 'kuro'         # Kuro encrypted / zstd compressed - wrong game
BAD_LZ4 = 'bad_lz4'      # LZ4 frame that does not hold a valid DDS
DAMAGED = 'damaged'      # a DDS whose header or image data is broken
UNKNOWN = 'unknown'      # something else entirely
MISSING = 'missing'      # no such file

STATE_TEXT = {
    OK:      'LZ4-wrapped DDS',
    RAW:     'plain DDS',
    CLE:     'Kuro format (encrypted / zstd), unreadable in Sky 2nd',
    BAD_LZ4: 'LZ4 container, but the contents are not a DDS',
    DAMAGED: 'broken DDS',
    UNKNOWN: 'unrecognised file format',
    MISSING: 'file not found',
}

# The format each target wants, and what can be converted into it.
GOOD = {'loose': RAW, 'pac': OK}
CONVERTIBLE = {'loose': (OK, CLE), 'pac': (RAW, CLE)}


def classify(path):
    """Return (state, detail) for one texture file."""
    try:
        with open(path, 'rb') as f:
            head = f.read(4)
    except (OSError, IOError) as e:
        return UNKNOWN, str(e)

    if head == DDS_MAGIC:
        return RAW, ''
    if head in CLE_MAGICS:
        return CLE, head.decode('ascii', 'replace')
    if head == LZ4_MAGIC:
        if not HAS_LZ4:
            # Without the module the contents cannot be verified. The magic is
            # right, so take the file at face value.
            return OK, 'contents not verified (lz4 module missing)'
        try:
            with open(path, 'rb') as f:
                data = lz4.frame.decompress(f.read())
        except Exception as e:
            return BAD_LZ4, 'does not decompress: {}'.format(e)
        if data[:4] != DDS_MAGIC:
            return BAD_LZ4, 'decompresses to something that is not a DDS'
        return OK, ''
    return UNKNOWN, 'starts with {!r}'.format(head)


# DXGI formats worth naming; anything else is shown as its number.
DXGI_NAMES = {
    28: 'R8G8B8A8', 29: 'R8G8B8A8_SRGB', 71: 'BC1', 72: 'BC1_SRGB',
    74: 'BC2', 77: 'BC3', 78: 'BC3_SRGB', 80: 'BC4', 83: 'BC5',
    87: 'B8G8R8A8', 95: 'BC6H', 98: 'BC7', 99: 'BC7_SRGB',
}


def dds_info(data):
    """(width, height, mipmaps, format) of a DDS held in memory, or None."""
    if len(data) < 128 or data[:4] != DDS_MAGIC:
        return None
    try:
        size, _flags, height, width, _pitch, _depth, mips = \
            struct.unpack_from('<7I', data, 4)
        # A real DDS header is 124 bytes and the rest has to be plausible;
        # without this a file that merely starts with "DDS " reports nonsense.
        if size != 124 or not (0 < width <= 65536) or not (0 < height <= 65536) \
                or mips > 32:
            return None
        four_cc = struct.unpack_from('<4s', data, 4 + 80)[0]
        name = four_cc.decode('ascii', 'replace').strip('\x00')
        if name == 'DX10' and len(data) >= 148:
            dxgi, = struct.unpack_from('<I', data, 4 + 124)
            name = DXGI_NAMES.get(dxgi, 'DXGI{}'.format(dxgi))
        elif not name:
            name = 'uncompressed'
        return width, height, max(mips, 1), name
    except struct.error:
        return None


BLOCK_BYTES = {  # bytes per 4x4 block for block-compressed formats
    'DXT1': 8, 'DXT2': 16, 'DXT3': 16, 'DXT4': 16, 'DXT5': 16,
    'ATI1': 8, 'BC4U': 8, 'BC4S': 8, 'ATI2': 16, 'BC5U': 16, 'BC5S': 16,
    'BC1': 8, 'BC1_SRGB': 8, 'BC4': 8, 'BC2': 16, 'BC3': 16, 'BC3_SRGB': 16,
    'BC5': 16, 'BC6H': 16, 'BC7': 16, 'BC7_SRGB': 16,
}
PIXEL_BYTES = {'R8G8B8A8': 4, 'R8G8B8A8_SRGB': 4, 'B8G8R8A8': 4}


def dds_problem(data):
    """Why a DDS held in memory cannot load, or None if it looks sound."""
    info = dds_info(data)
    if info is None:
        return "header is not a valid DDS header"
    width, height, mips, fmt = info
    header = 128 + (20 if data[84:88] == b'DX10' else 0)
    if fmt in BLOCK_BYTES:
        per_block, pixel = BLOCK_BYTES[fmt], None
    elif fmt in PIXEL_BYTES:
        per_block, pixel = None, PIXEL_BYTES[fmt]
    elif fmt == 'uncompressed':
        bits, = struct.unpack_from('<I', data, 88)
        per_block, pixel = None, bits // 8 if bits else None
        if not pixel:
            return None
    else:
        return None                      # a format we do not size - no verdict
    layers = 1
    caps2, = struct.unpack_from('<I', data, 112)
    if caps2 & 0x200:                    # cube map
        layers = 6
    if data[84:88] == b'DX10':
        array_size, = struct.unpack_from('<I', data, 140)
        layers *= max(array_size, 1)
    expected, w, h = 0, width, height
    for _ in range(mips):
        if per_block:
            expected += max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * per_block
        else:
            expected += w * h * pixel
        w, h = max(1, w // 2), max(1, h // 2)
    expected *= layers
    have = len(data) - header
    if have < expected:
        return "image data cut short: {0} of {1} bytes".format(have, expected)
    return None


def load_dds_bytes(path, state):
    """The plain DDS inside a texture file, whatever its wrapper, or None."""
    try:
        with open(path, 'rb') as f:
            data = f.read()
        if state == OK:
            return lz4.frame.decompress(data) if HAS_LZ4 else None
        if state == CLE:
            return decrypt_cle(data)
        if state == RAW:
            return data
    except Exception:
        return None
    return None


def read_dds_info(path, state):
    """Inspect a texture file whatever wrapper it is in."""
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except (OSError, IOError):
        return None
    if state == OK and HAS_LZ4:
        try:
            data = lz4.frame.decompress(data)
        except Exception:
            return None
    elif state == CLE:
        try:
            data = decrypt_cle(data)
        except Exception:
            return None
    return dds_info(data)


def decrypt_cle(file_content):
    """Unwrap a Kuro / Daybreak asset (F9BA, C9BA, D9BA).

    Thank you to the authors of KuroTools for this function.
    https://github.com/nnguyen259/KuroTools
    """
    key = b"\x16\x4B\x7D\x0F\x4F\xA7\x4C\xAC\xD3\x7A\x06\xD9\xF8\x6D\x20\x94"
    IV = b"\x9D\x8F\x9D\xA1\x49\x60\xCC\x4C"

    result = file_content
    magic = file_content[0:4]
    while magic in CLE_MAGICS:
        if magic in (b'F9BA', b'C9BA'):
            if not HAS_BLOWFISH:
                raise RuntimeError("the blowfish module is needed to decrypt "
                                   "{} files".format(magic.decode()))
            cipher = blowfish.Cipher(key, byte_order="big")
            iv = struct.unpack(">Q", IV)
            dec_counter = blowfish.ctr_counter(iv[0], f=operator.add)
            result = b"".join(cipher.decrypt_ctr(file_content[8:], dec_counter))
        else:
            if not HAS_ZSTD:
                raise RuntimeError("the zstandard module is needed to "
                                   "decompress D9BA files")
            result = zstandard.ZstdDecompressor().decompress(file_content[8:])
        file_content = result
        magic = file_content[0:4]
    return result


# ---------------------------------------------------------------------------
# MDL parsing. Only the material section is needed, so this is a trimmed copy
# of the parser in kuro_mdl_rename.py / kuro_mdl_tool - that keeps the script
# usable on its own, dropped into a folder of models.
# ---------------------------------------------------------------------------

MDL_MAGIC = 0x204c444d          # 'MDL '


def read_pascal_string(f):
    size = int.from_bytes(f.read(1), byteorder='little')
    return f.read(size)


def read_mdl(path):
    """Return the model bytes, unwrapped if the file is a Kuro CLE asset."""
    with open(path, 'rb') as f:
        data = f.read()
    if data[:4] in CLE_MAGICS:
        data = decrypt_cle(data)
    return data


def isolate_material_data(mdl_data):
    """Return the raw bytes of the material section, or None."""
    with io.BytesIO(mdl_data) as f:
        header = struct.unpack("<III", f.read(12))
        if header[0] != MDL_MAGIC:
            return None
        sections = []
        while True:
            info = {}
            try:
                info['type'], info['size'] = struct.unpack("<II", f.read(8))
            except struct.error:
                break
            info['start'] = f.tell()
            sections.append(info)
            f.seek(info['size'], 1)
        # Kuro-engine models have a single material section, type 0.
        for section in sections:
            if section['type'] == 0:
                f.seek(section['start'], 0)
                return f.read(section['size'])
    return None


def obtain_material_data(mdl_data):
    """Parse the material section into a list of material dicts."""
    kuro_ver, = struct.unpack("<I", mdl_data[4:8])
    material_data = isolate_material_data(mdl_data)
    if material_data is None:
        return []

    materials = []
    with io.BytesIO(material_data) as f:
        blocks, = struct.unpack("<I", f.read(4))
        for _ in range(blocks):
            material = {}
            material['material_name'] = read_pascal_string(f).decode('ASCII', 'replace')
            material['shader_name'] = read_pascal_string(f).decode('ASCII', 'replace')
            read_pascal_string(f)                    # str3, not needed here

            texture_count, = struct.unpack("<I", f.read(4))
            material['textures'] = []
            for _t in range(texture_count):
                name = read_pascal_string(f).decode('ASCII', 'replace')
                f.read(4)                            # texture_slot
                if kuro_ver > 1:
                    f.read(4)                        # unk_00
                f.read(8)                            # wrapS, wrapT
                if kuro_ver > 1:
                    f.read(4)                        # unk_03
                material['textures'].append(name)

            # Shader parameters. The payload size depends on the type.
            shader_count, = struct.unpack("<I", f.read(4))
            payload = {0: 4, 1: 4, 2: 8, 3: 12, 4: 4, 5: 8, 6: 12,
                       7: 16, 8: 64, 0xFFFFFFFF: 0}
            for _s in range(shader_count):
                read_pascal_string(f)                # parameter name
                type_int, = struct.unpack("<I", f.read(4))
                f.read(payload.get(type_int, 0))

            # The switch block identifies the compiled shader configuration.
            switch_count, = struct.unpack("<I", f.read(4))
            switch_start = f.tell()
            for _w in range(switch_count):
                read_pascal_string(f)                # switch name
                f.read(4)                            # value
            switch_end = f.tell()
            f.seek(switch_start, 0)
            switch_bytes = f.read(switch_end - switch_start)
            material['switches_hash'] = (xxhash.xxh64_hexdigest(switch_bytes)
                                         if HAS_XXHASH else '')

            uv_count, = struct.unpack("<I", f.read(4))
            f.read(uv_count)
            unknown1_count, = struct.unpack("<I", f.read(4))
            f.read(unknown1_count)
            f.read(20)                               # unknown2

            materials.append(material)
    return materials


def shader_id(material):
    """'chr_cloth#<switch hash>' - the compiled configuration a material needs."""
    return "{0}#{1}".format(material['shader_name'], material['switches_hash'])


# ---------------------------------------------------------------------------
# Locating texture files
# ---------------------------------------------------------------------------

def find_game_image_dirs(start_dir):
    """Walk up from start_dir collecting asset/dx11/image folders."""
    found = []
    current = os.path.abspath(start_dir)
    while True:
        candidate = os.path.join(current, 'asset', 'dx11', 'image')
        if os.path.isdir(candidate):
            found.append(candidate)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return found


def build_texture_index(roots, recursive=True):
    """Map lowercase texture basename (no extension) -> full path.

    Earlier roots win, so an explicit --image-dir beats a stray copy picked up
    by the recursive search.
    """
    index = {}
    for root in roots:
        if not os.path.isdir(root):
            continue
        pattern = os.path.join(root, '**', '*.dds') if recursive \
            else os.path.join(root, '*.dds')
        for path in glob.glob(pattern, recursive=recursive):
            key = os.path.splitext(os.path.basename(path))[0].lower()
            index.setdefault(key, path)
    return index


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def backup_path(path, suffix):
    """First free '<path><suffix>' name; an existing backup is never replaced."""
    candidate = path + suffix
    if not os.path.exists(candidate):
        return candidate
    n = 1
    while os.path.exists("{0}{1}".format(candidate, n)):
        n += 1
    return "{0}{1}".format(candidate, n)


BACKUP_SUFFIX = {OK: '.lz4_original', RAW: '.raw_original', CLE: '.kuro_original'}


def convert(path, state, target, keep_backup=True):
    """Rewrite one texture in the target format. (True, note) or (False, why)."""
    if not HAS_LZ4 and (state == OK or target == 'pac'):
        return False, "the lz4 module is missing (python -m pip install lz4)"
    data = load_dds_bytes(path, state)
    if data is None or data[:4] != DDS_MAGIC:
        return False, "could not be unwrapped to a DDS"
    problem = dds_problem(data)
    if problem:
        return False, "the DDS inside is broken: " + problem
    payload = lz4.frame.compress(data) if target == 'pac' else data

    if keep_backup:
        backup = backup_path(path, BACKUP_SUFFIX.get(state, '.original'))
        os.replace(path, backup)
        note = "backup: " + os.path.basename(backup)
    else:
        note = "no backup"
    with open(path, 'wb') as f:
        f.write(payload)
    return True, note


# ---------------------------------------------------------------------------
# Shader reference set
# ---------------------------------------------------------------------------

def collect_shader_ids(paths, recursive=True):
    """Every 'name#hash' configuration used by the reference models."""
    ids = set()
    files = []
    for path in paths:
        if os.path.isfile(path):
            files.append(path)
        elif os.path.isdir(path):
            pattern = os.path.join(path, '**', '*.mdl') if recursive \
                else os.path.join(path, '*.mdl')
            files.extend(glob.glob(pattern, recursive=recursive))
    for mdl in files:
        try:
            for material in obtain_material_data(read_mdl(mdl)):
                ids.add(shader_id(material))
        except Exception:
            continue
    return ids, len(files)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Check the .dds textures of a Trails in the Sky 2nd Chapter "
                    "mod and convert them to the format the game loads.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Loose files served by the mod loader (the usual way to install a "
               "mod) must be\nPLAIN .dds - the loader switches the game to raw "
               "DDS, so an LZ4-wrapped file\nis not loaded. Only textures packed "
               "into a .pac need LZ4 (--target pac).\n\n"
               "Examples:\n"
               "  python sky2_check_textures.py mymod                check\n"
               "  python sky2_check_textures.py mymod --fix          convert to plain .dds\n"
               "  python sky2_check_textures.py mymod --all --fix    every .dds in the folder\n"
               "  python sky2_check_textures.py mymod --fix --target pac")
    parser.add_argument('directory', nargs='?', default='.',
                        help="folder with the mod (default: current)")
    parser.add_argument('--fix', action='store_true',
                        help="convert the textures to the target format")
    parser.add_argument('--target', choices=('loose', 'pac'), default='loose',
                        help="loose = plain .dds for the mod loader (default); "
                             "pac = LZ4-wrapped, for packing into a .pac")
    parser.add_argument('--decompress', action='store_true',
                        help="same as --fix --target loose")
    parser.add_argument('--all', action='store_true',
                        help="every .dds under the folder, not only the ones "
                             "the models use")
    parser.add_argument('--image-dir', action='append', default=[],
                        metavar='DIR', help="where the .dds files are")
    parser.add_argument('--shader-ref', action='append', default=[],
                        metavar='PATH',
                        help="untouched 2nd Chapter .mdl files to check the "
                             "shader configurations against")
    parser.add_argument('--no-recursive', action='store_true',
                        help="do not descend into subfolders")
    parser.add_argument('--no-backup', action='store_true',
                        help="do not keep a backup of converted textures")
    parser.add_argument('--list-ok', action='store_true',
                        help="also list textures that are already fine")
    parser.add_argument('-q', '--quiet', action='store_true',
                        help="only print the problems and the summary")
    args = parser.parse_args()

    if args.decompress:
        if args.target == 'pac':
            out("--decompress means --target loose; it cannot go with --target pac.")
            return 2
        args.fix = True
    target, good = args.target, GOOD[args.target]

    recursive = not args.no_recursive
    scan_dir = os.path.abspath(args.directory)
    if not os.path.isdir(scan_dir):
        out("Not a folder: {}".format(scan_dir))
        return 2

    pattern = os.path.join(scan_dir, '**', '*.mdl') if recursive \
        else os.path.join(scan_dir, '*.mdl')
    mdl_files = sorted(glob.glob(pattern, recursive=recursive))
    by_models = bool(mdl_files) and not args.all

    # Where the textures are.
    roots = [os.path.abspath(d) for d in args.image_dir]
    auto_dirs = find_game_image_dirs(scan_dir)
    for mdl in mdl_files:
        for candidate in find_game_image_dirs(os.path.dirname(mdl)):
            if candidate not in auto_dirs:
                auto_dirs.append(candidate)
    if by_models:
        roots.extend(auto_dirs)
        roots.extend(sorted({os.path.dirname(m) for m in mdl_files}))
    roots.append(scan_dir)
    seen, search_roots = set(), []
    for root in roots:
        key = os.path.normcase(os.path.abspath(root))
        if key not in seen:
            seen.add(key)
            search_roots.append(root)
    index = build_texture_index(search_roots, recursive=recursive)

    # ---- which textures, and who uses them --------------------------------
    wanted = []                   # (name, path or None, [models])
    unreadable, shader_problems = [], []
    if by_models:
        users = {}
        shader_ref_ids = set()
        if args.shader_ref and HAS_XXHASH:
            shader_ref_ids, _ = collect_shader_ids(args.shader_ref, recursive=recursive)
        for mdl in mdl_files:
            rel = os.path.relpath(mdl, scan_dir)
            try:
                materials = obtain_material_data(read_mdl(mdl))
            except Exception as e:
                unreadable.append((rel, str(e)))
                continue
            for material in materials or []:
                for name in material['textures']:
                    if name:
                        users.setdefault(name.lower(), (name, []))[1].append(rel)
                if shader_ref_ids:
                    sid = shader_id(material)
                    if sid not in shader_ref_ids:
                        shader_problems.append((rel, material['material_name'], sid))
        for key in sorted(users):
            name, models = users[key]
            wanted.append((name, index.get(key), sorted(set(models))))
    else:
        for key in sorted(index):
            path = index[key]
            wanted.append((os.path.splitext(os.path.basename(path))[0], path, []))

    if not args.quiet:
        if by_models:
            out("Models:    {0} .mdl file(s) in {1}".format(len(mdl_files), scan_dir))
            out("Textures:  {} used by them".format(len(wanted)))
        else:
            out("Textures:  every .dds under {0} ({1})".format(scan_dir, len(wanted)))
        out("Target:    {}".format(
            "plain .dds - loose files through the mod loader" if target == 'loose'
            else "LZ4-wrapped .dds - for a .pac"))
        out("")

    if not wanted:
        out("No textures found.")
        return 0

    counts = {state: 0 for state in STATE_TEXT}
    converted, failed, damaged = 0, 0, []
    formats, no_mipmaps = {}, []

    for name, path, models in wanted:
        where = "   (used by {})".format(", ".join(models[:3]) + (
            ", ..." if len(models) > 3 else "")) if models else ""
        if path is None:
            counts[MISSING] += 1
            out("  [missing]   {0}.dds{1}".format(name, where))
            continue
        state, detail = classify(path)
        rel = os.path.relpath(path, scan_dir)

        data = load_dds_bytes(path, state) if state in (OK, RAW, CLE) else None
        info = dds_info(data) if data else None
        problem = dds_problem(data) if data else None
        if state in (OK, RAW, CLE) and data is not None and problem:
            state, detail = DAMAGED, problem
        if info:
            formats[info[3]] = formats.get(info[3], 0) + 1
            if info[2] <= 1:
                no_mipmaps.append((name, info))
        described = "  ({0}x{1} {2}, {3})".format(
            info[0], info[1], info[3],
            "no mipmaps" if info[2] <= 1 else "{} mipmaps".format(info[2])) if info else ""

        counts[state] += 1
        if state == good:
            if args.list_ok:
                out("  [ok]        {0}{1}".format(rel, described))
            continue

        label = STATE_TEXT[state] + (": " + detail if detail else "")
        if state in CONVERTIBLE[target] and args.fix:
            ok, note = convert(path, state, target, keep_backup=not args.no_backup)
            if ok:
                converted += 1
                out("  [converted] {0}  {1} -> {2}  ({3}){4}".format(
                    rel, STATE_TEXT[state], STATE_TEXT[good], note, described))
            else:
                failed += 1
                out("  [FAILED]    {0}  {1}".format(rel, note))
            continue
        if state in (DAMAGED, BAD_LZ4, UNKNOWN):
            damaged.append(rel)
        tag = {OK: 'lz4', RAW: 'plain', CLE: 'kuro'}.get(state, state)
        out("  [{0:<9}] {1}  {2}{3}{4}".format(tag, rel, label, described, where))

    # ---- summary ---------------------------------------------------------
    wrong = sum(counts[s] for s in CONVERTIBLE[target])
    out("")
    out("=" * 62)
    out("Textures checked:     {}".format(len(wanted)))
    out("Already right:        {0}  ({1})".format(counts[good], STATE_TEXT[good]))
    for state in CONVERTIBLE[target]:
        if counts[state]:
            out("{0:<22}{1}".format(
                {OK: "LZ4-wrapped:", RAW: "Plain DDS:", CLE: "Kuro format:"}[state],
                counts[state]))
    for state, label in ((DAMAGED, "Broken DDS:"), (BAD_LZ4, "Damaged LZ4:"),
                         (UNKNOWN, "Unrecognised:"), (MISSING, "Missing files:")):
        if counts[state]:
            out("{0:<22}{1}".format(label, counts[state]))
    if formats:
        out("Formats:              {}".format(", ".join(
            "{0} x{1}".format(fmt, n) for fmt, n in
            sorted(formats.items(), key=lambda kv: -kv[1]))))
    if args.fix:
        out("Converted:            {}".format(converted))
        if failed:
            out("Conversions failed:   {}".format(failed))
    if unreadable:
        out("Models unreadable:    {}".format(len(unreadable)))
        for rel, reason in unreadable:
            out("    {0}: {1}".format(rel, reason))
    if shader_problems:
        out("Shader problems:      {}  (see sky2_fix_shaders.py)".format(
            len(shader_problems)))
    out("=" * 62)

    if wrong and not args.fix:
        out("Run again with --fix to convert {0} texture(s) to {1}.".format(
            wrong, STATE_TEXT[good]))
    if damaged:
        out("Broken files cannot be converted - export them again from the "
            "image editor.")
    if counts[MISSING]:
        out("Missing textures are fine when they are stock ones the game "
            "supplies itself;")
        out("otherwise add them to the mod. --image-dir if they live elsewhere.")
    if wrong == 0 and not damaged and not counts[MISSING] and not failed:
        out("Every texture is in the right format.")

    remaining = len(damaged) + counts[MISSING] + failed + (0 if args.fix else wrong)
    return 1 if remaining or unreadable else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        out("\nCancelled.")
        sys.exit(130)
