#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kuro_mdl_rename.py
==================

Self-contained tool that produces renamed mod .p3a archives for Kuro no
Kiseki / ED9 games. The renaming is per-mdl and isolates each model's
texture set into a private namespace so that two mods which touch
overlapping vanilla assets never overwrite each other.

PRIMARY WORKFLOW
----------------
Point the script at the game's install directory, interactively pick
the .mdl files you want to mod, and let it produce a single mod .p3a
archive in the directory you ran the script from:

    py kuro_mdl_rename.py --game "D:\\Steam\\...\\TrailsXYZ" --select --apply

If the script lives inside the game folder itself, --game alone (no
path) is enough:

    py kuro_mdl_rename.py --game --select --apply

In this mode the script reads every .p3a's table of contents at the
game-folder top level, presents the discovered mdls in an interactive
picker (with display filter, paging and glob-add) and extracts ONLY
the files the selected models actually need into a transient scratch
directory before packaging them. The game's own data is never modified.

WHAT THE SCRIPT DOES PER .mdl
-----------------------------
  1. Computes a new mdl basename (prefix+original+suffix; or a name
     you enter under --rename; or the original name unchanged).
  2. Reads the .mdl's material data and figures out which images it
     references.
  3. Compares those references against the project's image catalogue
     and produces a unique renamed copy for every image actually
     available. The image rename is anchored on the *new* mdl basename
     so two .mdl files that share the same source image still end up
     referencing their own private copy in the output.
  4. Patches image_list.json (extension preserved) and material_info.json
     (texture_image_name has no extension in this file).
  5. Repacks the .mdl using the embedded import logic, writes it under
     the new name, then cleans up scratch files.
  6. Renames the matching .mi side-car (if present).

References to images that are NOT present in the source are left
untouched in the JSONs (the engine is expected to find them elsewhere
in the game). Source data is never modified.

ALTERNATIVE INPUT MODES
-----------------------
The script also handles legacy project layouts as the source:
  * a project directory tree (asset/common/model/, asset/dx11/image/, ...)
  * a single .p3a archive (extracted on the fly to a transient scratch)

For these the output defaults to a directory tree; pass --p3a to
package as a .p3a archive.

SUBSET SELECTION (default = all discovered .mdls)
-------------------------------------------------
  * --select          interactive picker with display filter, paging,
                      glob-add, and a 'help' command (recommended for
                      game-directory mode -- see PRIMARY WORKFLOW)
  * --only NAMES      comma-separated names or globs (chr*_c01, etc.)
  * --only-from FILE  one name/glob per line; '#' is a line comment

Default mode is dry-run; pass --apply (or answer 'yes' to the apply
prompt in interactive mode) to actually write files.

More usage examples:
    py kuro_mdl_rename.py --game --only "chr*_c01" --apply
    py kuro_mdl_rename.py C:\\mods\\proj --apply
    py kuro_mdl_rename.py C:\\mods\\proj.p3a --p3a --apply
    py kuro_mdl_rename.py C:\\mods\\proj --select

Run with --help for the full reference.

Requires: blowfish, zstandard, xxhash, numpy, lz4   (and optionally colorama)
    py -m pip install blowfish zstandard xxhash numpy lz4 colorama
"""

# ---------------------------------------------------------------------------
# Unified imports for both the embedded library code and the wrapper code.
# ---------------------------------------------------------------------------
import argparse
import glob
import io
import json
import logging
import math
import os
import re
import shutil
import struct
import sys
from datetime import datetime
from itertools import chain

# Hard dependencies of the embedded library code.
try:
    import blowfish
    import lz4.block
    import numpy
    import operator
    import xxhash
    import zstandard
except ImportError as e:
    sys.stderr.write(
        "ERROR: missing required Python module: {}\n"
        "Install with:  py -m pip install blowfish zstandard xxhash numpy lz4\n".format(e)
    )
    sys.exit(2)

# Optional: colorama for nice colored output on Windows cmd.
try:
    from colorama import Fore, Style, init as _colorama_init
    _colorama_init(autoreset=True)
    _COLORAMA_OK = True
except ImportError:  # graceful fallback
    class _NoColor:
        def __getattr__(self, _):
            return ""
    Fore = _NoColor()
    Style = _NoColor()
    _COLORAMA_OK = False


# Match any ANSI SGR escape so the file handler (and --no-color console)
# can strip them out.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


# Colors-as-runtime-flag: set to False for --no-color so _c() returns plain
# strings everywhere. Defaults to whether colorama is available.
_COLOR_ENABLED = _COLORAMA_OK


def _c(text, *codes):
    """Wrap `text` with ANSI codes when color is enabled; otherwise pass
    through unchanged. The codes are simply concatenated, so you can pass
    e.g. _c('hi', Style.BRIGHT, Fore.GREEN)."""
    if not _COLOR_ENABLED or not codes:
        return str(text)
    return "".join(codes) + str(text) + Style.RESET_ALL


def _bold(t):    return _c(t, Style.BRIGHT)
def _dim(t):     return _c(t, Style.DIM)
def _cyan(t):    return _c(t, Fore.CYAN)
def _green(t):   return _c(t, Fore.GREEN)
def _yellow(t):  return _c(t, Fore.YELLOW)
def _red(t):     return _c(t, Fore.RED)
def _magenta(t): return _c(t, Fore.MAGENTA)


# ---------------------------------------------------------------------------
# Override the builtin `input` so the embedded code never blocks on prompts.
# The export's "folder exists, overwrite?" prompt is bypassed by passing
# overwrite=True; this safety net catches any other interactive prompt
# (e.g. the vgmap-incompatible warning in the import code).
# ---------------------------------------------------------------------------
_real_input = input
def input(prompt=""):  # noqa: A001 - intentional shadowing of builtin
    msg = "[suppressed interactive prompt] " + str(prompt).rstrip()
    try:
        logging.getLogger("kuro_mdl_rename").warning(msg)
    except Exception:
        sys.stderr.write(msg + "\n")
    return ""


# ---------------------------------------------------------------------------
# Interactive-prompt helpers
# ---------------------------------------------------------------------------
# These use _real_input (the original builtin we saved above), NOT the
# no-op `input` we installed for the embedded code's safety net.
def _is_interactive():
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _windows_prefill_input(prompt, default):
    """Inject `default` into the Windows console input buffer so the user
    sees it as if typed and can edit it normally with Backspace, Delete,
    arrow keys, etc. before pressing Enter. Raises OSError on failure so
    the caller can fall back."""
    import ctypes
    from ctypes import wintypes
    if not default:
        return _real_input(prompt)

    STD_INPUT_HANDLE = -10
    KEY_EVENT = 0x0001

    kernel32 = ctypes.windll.kernel32
    h_stdin = kernel32.GetStdHandle(STD_INPUT_HANDLE)
    if h_stdin in (0, ctypes.c_void_p(-1).value):
        raise OSError("could not get stdin handle")

    class _UCHAR(ctypes.Union):
        _fields_ = [
            ("UnicodeChar", wintypes.WCHAR),
            ("AsciiChar", ctypes.c_char),
        ]

    class KEY_EVENT_RECORD(ctypes.Structure):
        _fields_ = [
            ("bKeyDown", wintypes.BOOL),
            ("wRepeatCount", wintypes.WORD),
            ("wVirtualKeyCode", wintypes.WORD),
            ("wVirtualScanCode", wintypes.WORD),
            ("uChar", _UCHAR),
            ("dwControlKeyState", wintypes.DWORD),
        ]

    class _Event(ctypes.Union):
        _fields_ = [("KeyEvent", KEY_EVENT_RECORD)]

    class INPUT_RECORD(ctypes.Structure):
        _fields_ = [
            ("EventType", wintypes.WORD),
            ("Event", _Event),
        ]

    n = len(default) * 2  # one key-down + one key-up per character
    arr = (INPUT_RECORD * n)()
    for i, ch in enumerate(default):
        for k, down in enumerate((True, False)):
            r = arr[i * 2 + k]
            r.EventType = KEY_EVENT
            kev = r.Event.KeyEvent
            kev.bKeyDown = 1 if down else 0
            kev.wRepeatCount = 1
            kev.wVirtualKeyCode = 0
            kev.wVirtualScanCode = 0
            kev.uChar.UnicodeChar = ch
            kev.dwControlKeyState = 0

    written = wintypes.DWORD(0)
    ok = kernel32.WriteConsoleInputW(h_stdin, arr, n, ctypes.byref(written))
    if not ok or written.value != n:
        raise OSError("WriteConsoleInputW failed")
    return _real_input(prompt)


def _unix_prefill_input(prompt, default):
    """readline-based pre-fill for Linux/macOS terminals."""
    import readline  # stdlib on POSIX
    if not default:
        return _real_input(prompt)
    readline.set_startup_hook(lambda: readline.insert_text(default))
    try:
        return _real_input(prompt)
    finally:
        readline.set_startup_hook(None)


def prompt_with_default(prompt, default, allow_empty=True):
    """Prompt the user with `default` pre-filled and editable when possible.

    - On a real interactive console the default appears as if typed and the
      user edits it (Backspace, Delete, arrows) before pressing Enter.
    - On non-interactive stdin (pipes/redirects) or if the platform-specific
      pre-fill machinery is unavailable, a bracket-style prompt is shown
      where empty input means "use the default".
    - If `allow_empty` is False, an empty result re-prompts.
    """
    default = "" if default is None else str(default)
    while True:
        used_prefill = False
        if _is_interactive():
            try:
                if sys.platform == "win32":
                    val = _windows_prefill_input(prompt, default)
                else:
                    val = _unix_prefill_input(prompt, default)
                used_prefill = True
            except Exception:
                used_prefill = False

        if not used_prefill:
            # Bracket-style fallback. Empty input -> default.
            base = prompt.rstrip().rstrip(":")
            shown = " " + _dim("[{}]".format(default)) if default else ""
            try:
                raw = _real_input("{}{}: ".format(base, shown))
            except EOFError:
                raw = ""
            val = raw if raw != "" else default

        if val == "" and not allow_empty:
            sys.stdout.write("  " + _red("Value cannot be empty.") + " Try again.\n")
            continue
        return val


def prompt_yes_no(prompt, default=False):
    """Yes/no prompt. `default` is the value used on empty input."""
    default_label = "yes" if default else "no"
    while True:
        ans = prompt_with_default(prompt, default_label).strip().lower()
        if ans in ("y", "yes", "true", "1"):
            return True
        if ans in ("n", "no", "false", "0", ""):
            return False
        sys.stdout.write("  Please answer yes or no.\n")


def _is_safe_name(name):
    """Allow filename-safe characters only: no \\ / : * ? \" < > | and no
    whitespace. Empty is rejected by the caller."""
    bad = '\\/:*?"<>|'
    for ch in name:
        if ch in bad or ch.isspace():
            return False
    return True


# ===========================================================================
# BEGIN EMBEDDED LIBRARY CODE (lib_fmtibvb + kuro_mdl_export_meshes +
#                              kuro_mdl_import_meshes, with imports and
#                              __main__ blocks stripped).
#
# Source: https://github.com/eArmada8/kuro_mdl_tool
# ===========================================================================
# === /mnt/user-data/uploads/lib_fmtibvb.py ===
# A small library of functions to read and write .fmt / .ib / .vb files into and out of
# python structures that are JSON serializable.
#
# GitHub eArmada8/gust_stuff


# Currently only simple formats (8-, 16-, and 32-bit) are supported.  Floats must be 32-bit.
# Attempting to read an unsupported format will return a raw bytes object.


def unpack_dxgi_vector(f, stride, dxgi_format, e = '<'):
    dxgi_format = dxgi_format.split('DXGI_FORMAT_')[-1]
    dxgi_format_split = dxgi_format.split('_')
    if len(dxgi_format_split) == 2:
        numtype = dxgi_format_split[1]
        vec_format = re.findall("[0-9]+",dxgi_format_split[0])
        if len(vec_format) > 0:
            vec_bits = int(vec_format[0])
            vec_elements = len(vec_format)
        else:
            vec_bits = 0
            vec_elements = 0
    else:
        numtype = 'UNSUPPORTED'

    if numtype == 'FLOAT' and (vec_elements * vec_bits / 8 == stride):
        if vec_bits == 32:
            read = list(struct.unpack(e+str(vec_elements)+"f", f.read(stride)))
        elif vec_bits == 16:
            read = list(struct.unpack(e+str(vec_elements)+"e", f.read(stride)))
    elif numtype == 'UINT' and (vec_elements * vec_bits / 8 == stride):
        if vec_bits == 32:
            read = list(struct.unpack(e+str(vec_elements)+"I", f.read(stride)))
        elif vec_bits == 16:
            read = list(struct.unpack(e+str(vec_elements)+"H", f.read(stride)))
        elif vec_bits == 8:
            read = list(struct.unpack(e+str(vec_elements)+"B", f.read(stride)))
    elif numtype == "SINT" and (vec_elements * vec_bits / 8 == stride):
        if vec_bits == 32:
            read = list(struct.unpack(e+str(vec_elements)+"i", f.read(stride)))
        elif vec_bits == 16:
            read = list(struct.unpack(e+str(vec_elements)+"h", f.read(stride)))
        elif vec_bits == 8:
            read = list(struct.unpack(e+str(vec_elements)+"b", f.read(stride)))
    elif numtype == "UNORM" and (vec_elements * vec_bits / 8 == stride):
        # First read as integers
        if vec_bits == 32:
            read = list(struct.unpack(e+str(vec_elements)+"I", f.read(stride)))
        elif vec_bits == 16:
            read = list(struct.unpack(e+str(vec_elements)+"H", f.read(stride)))
        elif vec_bits == 8:
            read = list(struct.unpack(e+str(vec_elements)+"B", f.read(stride)))
        # Convert to normalized floats
        float_max = ((2**vec_bits)-1)
        for i in range(len(read)):
            read[i] = read[i] / float_max
    elif numtype == "SNORM" and (vec_elements * vec_bits / 8 == stride):
        # First read as integers
        if vec_bits == 32:
            read = list(struct.unpack(e+str(vec_elements)+"i", f.read(stride)))
        elif vec_bits == 16:
            read = list(struct.unpack(e+str(vec_elements)+"h", f.read(stride)))
        elif vec_bits == 8:
            read = list(struct.unpack(e+str(vec_elements)+"b", f.read(stride)))
        # Convert to normalized floats
        float_max = ((2**(vec_bits-1))-1)
        for i in range(len(read)):
            read[i] = read[i] / float_max
    else:
        read = f.read(stride)
    return (read)

def pack_dxgi_vector(f, data, stride, dxgi_format, e = '<'):
    dxgi_format = dxgi_format.split('DXGI_FORMAT_')[-1]
    dxgi_format_split = dxgi_format.split('_')
    if len(dxgi_format_split) == 2:
        numtype = dxgi_format_split[1]
        vec_format = re.findall("[0-9]+",dxgi_format_split[0])
        if len(vec_format) > 0:
            vec_bits = int(vec_format[0])
            vec_elements = len(vec_format)
        else:
            vec_bits = 0
            vec_elements = 0
    else:
        numtype = 'UNSUPPORTED'

    if numtype == 'FLOAT' and (vec_elements * vec_bits / 8 == stride):
        for i in range(vec_elements):
            if vec_bits == 32:
                f.write(struct.pack(e+"f", data[i]))
            elif vec_bits == 16:
                f.write(struct.pack(e+"e", data[i]))
    elif numtype == 'UINT' and (vec_elements * vec_bits / 8 == stride):
        for i in range(vec_elements):
            if vec_bits == 32:
                f.write(struct.pack(e+"I", data[i]))
            elif vec_bits == 16:
                f.write(struct.pack(e+"H", data[i]))
            elif vec_bits == 8:
                f.write(struct.pack(e+"B", data[i]))
    elif numtype == "SINT" and (vec_elements * vec_bits / 8 == stride):
        for i in range(vec_elements):
            if vec_bits == 32:
                f.write(struct.pack(e+"i", data[i]))
            elif vec_bits == 16:
                f.write(struct.pack(e+"h", data[i]))
            elif vec_bits == 8:
                f.write(struct.pack(e+"b", data[i]))
    elif numtype == 'UNORM' and (vec_elements * vec_bits / 8 == stride):
        converted_data = []
        for i in range(vec_elements):
            #First convert back to unsigned integers, then pack
            float_max = ((2**vec_bits)-1)
            converted_data.append(int(round(min(max(data[i],0), 1) * float_max)))
            if vec_bits == 32:
                f.write(struct.pack(e+"I", converted_data[i]))
            elif vec_bits == 16:
                f.write(struct.pack(e+"H", converted_data[i]))
            elif vec_bits == 8:
                f.write(struct.pack(e+"B", converted_data[i]))
    elif numtype == 'SNORM' and (vec_elements * vec_bits / 8 == stride):
        converted_data = []
        for i in range(vec_elements):
            #First convert back to unsigned integers, then pack
            float_max = ((2**(vec_bits-1))-1)
            converted_data.append(int(round(min(max(data[i],-1), 1) * float_max)))
            if vec_bits == 32:
                f.write(struct.pack(e+"i", converted_data[i]))
            elif vec_bits == 16:
                f.write(struct.pack(e+"h", converted_data[i]))
            elif vec_bits == 8:
                f.write(struct.pack(e+"b", converted_data[i]))
    else:
        write = f.write(data)
    return

def get_stride_from_dxgi_format(dxgi_format):
    dxgi_format = dxgi_format.split('DXGI_FORMAT_')[-1]
    dxgi_format_split = dxgi_format.split('_')
    if len(dxgi_format_split) == 2:
        numtype = dxgi_format_split[1]
        vec_format = re.findall("[0-9]+",dxgi_format_split[0])
        if len(vec_format) > 0:
            return(int(len(vec_format) * int(vec_format[0]) / 8))
        else:
            return False
    else:
        return False

def read_fmt(fmt_filename):
    fmt_struct = {}
    with open(fmt_filename, 'r') as f:
        elements = []
        while True:
            line = f.readline().strip()
            if line[0:7] == 'element':
                element = {}
                element['id'] = line.split('[')[-1][:-2]
                while True:
                    line_offset = f.tell()
                    line = f.readline().strip()
                    if line[0:7] == 'element' or line == "":
                        f.seek(line_offset)
                        elements.append(element)
                        break
                    else:
                        element[line.split(': ')[0]] = line.split(': ')[1]
            else:
                if line == "":
                    break
                fmt_struct[line.split(': ')[0]] = line.split(': ')[1]
        fmt_struct['elements'] = elements
    return(fmt_struct)

def write_fmt(fmt_struct, fmt_filename):
    output = bytearray()
    for key in fmt_struct:
        if key == "elements":
            for i in range(len(fmt_struct["elements"])):
                for key in fmt_struct["elements"][i]:
                    if key == "id":
                        output.extend(("element[" + fmt_struct["elements"][i][key] + "]:\r\n").encode())
                    else:
                        output.extend(("  " + key + ": " + fmt_struct["elements"][i][key] + "\r\n").encode())
        else:
            output.extend((key + ": " + fmt_struct[key] + "\r\n").encode())
    with open(fmt_filename, "wb") as f:
        f.write(output)
    return

def read_ib_stream(ib_stream, fmt_struct, e = '<'):
    ib_data = []
    # Cheating a bit here, since all index buffers I've seen are single numbers, but fmt doesn't have a stride for IB
    ib_stride = int(int(re.findall("[0-9]+", fmt_struct["format"])[0])/8)
    with io.BytesIO(ib_stream) as f:
        length = f.seek(0,2)
        f.seek(0)
        vertex_num = 0
        triangle = []
        while f.tell() < length:
            triangle.extend(unpack_dxgi_vector(f, ib_stride, fmt_struct["format"], e))
            vertex_num += 1
            if vertex_num % 3 == 0 or f.tell() == length:
                ib_data.append(triangle)
                triangle = []
    return(ib_data)

def read_ib(ib_filename, fmt_struct, e = '<'):
    with open(ib_filename, 'rb') as f:
        ib_stream = f.read()
    return(read_ib_stream(ib_stream, fmt_struct, e))

def write_ib_stream(ib_data, ib_stream, fmt_struct, e = '<'):
    # See above about cheating
    ib_stride = int(int(re.findall("[0-9]+", fmt_struct["format"])[0])/8)
    if len(ib_data) > 0:
        if type(ib_data[0]) == list: # Flatten list for legacy code
            new_ib_data = [x for y in ib_data for x in y]
        else:
            new_ib_data = ib_data
    else:
        new_ib_data = ib_data
    for i in range(len(new_ib_data)):
        pack_dxgi_vector(ib_stream, [new_ib_data[i]], ib_stride, fmt_struct["format"], e)
    return

def write_ib(ib_data, ib_filename, fmt_struct, e = '<'):
    with open(ib_filename, 'wb') as f:
        write_ib_stream(ib_data, f, fmt_struct, e)
    return

def read_vb_stream(vb_stream, fmt_struct, e = '<'):
    vb_data = []
    with io.BytesIO(vb_stream) as f:
        length = f.seek(0,2)
        f.seek(0)
        num_vertex = int(length / int(fmt_struct["stride"]))
        buffer_strides = []
        # Calculate individual buffer strides
        for i in range(len(fmt_struct["elements"])):
            if i == len(fmt_struct["elements"]) - 1:
                buffer_strides.append(int(fmt_struct["stride"]) - int(fmt_struct["elements"][i]["AlignedByteOffset"]))
            else:
                buffer_strides.append(int(fmt_struct["elements"][i+1]["AlignedByteOffset"]) \
                    - int(fmt_struct["elements"][i]["AlignedByteOffset"]))
        # Read in the buffers
        for i in range(len(fmt_struct["elements"])):
            element = {}
            element["SemanticName"] = fmt_struct["elements"][i]["SemanticName"]
            element["SemanticIndex"] = fmt_struct["elements"][i]["SemanticIndex"]
            element_buffer = []
            for j in range(num_vertex):
                f.seek(j * int(fmt_struct["stride"]) + int(fmt_struct["elements"][i]["AlignedByteOffset"]),0)
                element_buffer.append(unpack_dxgi_vector(f, buffer_strides[i], fmt_struct["elements"][i]["Format"], e))
            element["Buffer"] = element_buffer
            vb_data.append(element)
    return(vb_data)

def read_seg_vb_stream(vb_stream, fmt_struct, input_slot, e = '<'):
    seg_stride = "vb{} stride".format(input_slot)
    seg_elements = [x for x in fmt_struct['elements'] if x['InputSlot'] == input_slot]
    vb_data = []
    with io.BytesIO(vb_stream) as f:
        length = f.seek(0,2)
        f.seek(0)
        num_vertex = int(length / int(fmt_struct[seg_stride]))
        buffer_strides = []
        # Calculate individual buffer strides
        for i in range(len(seg_elements)):
            if i == len(seg_elements) - 1:
                buffer_strides.append(int(fmt_struct[seg_stride]) - int(seg_elements[i]["AlignedByteOffset"]))
            else:
                buffer_strides.append(int(seg_elements[i+1]["AlignedByteOffset"]) \
                    - int(seg_elements[i]["AlignedByteOffset"]))
        # Read in the buffers
        for i in range(len(seg_elements)):
            element = {}
            element["SemanticName"] = seg_elements[i]["SemanticName"]
            element["SemanticIndex"] = seg_elements[i]["SemanticIndex"]
            element["InputSlot"] = seg_elements[i]["InputSlot"]
            element_buffer = []
            for j in range(num_vertex):
                f.seek(j * int(fmt_struct[seg_stride]) + int(seg_elements[i]["AlignedByteOffset"]),0)
                element_buffer.append(unpack_dxgi_vector(f, buffer_strides[i], seg_elements[i]["Format"], e))
            element["Buffer"] = element_buffer
            vb_data.append(element)
    return(vb_data)

def read_vb(vb_filename, fmt_struct, e = '<'):
    if 'stride' in fmt_struct:
        with open(vb_filename, 'rb') as f:
            vb_stream = f.read()
        return(read_vb_stream(vb_stream, fmt_struct, e))
    elif 'vb0 stride' in fmt_struct:
        vb = []
        for input_slot in [x[2:-7] for x in fmt_struct if len(x.split('stride')) > 1]:
            with open(vb_filename + input_slot, 'rb') as f:
                vb_stream = f.read()
            vb.extend(read_seg_vb_stream(vb_stream, fmt_struct, input_slot, e))
        return(vb)
    else:
        print("Decoding error when trying to interpret fmt file for {0}!\r\n".format(vb_filename))
        input("Press Enter to abort.")
        raise

def write_vb_stream(vb_data, vb_stream, fmt_struct, e = '<', interleave = True):
    buffer_strides = []
    # Calculate individual buffer strides
    for i in range(len(fmt_struct["elements"])):
        if i == len(fmt_struct["elements"]) - 1:
            buffer_strides.append(int(fmt_struct["stride"]) - int(fmt_struct["elements"][i]["AlignedByteOffset"]))
        else:
            buffer_strides.append(int(fmt_struct["elements"][i+1]["AlignedByteOffset"]) \
                - int(fmt_struct["elements"][i]["AlignedByteOffset"]))
    if interleave == True:
        # Write out the buffers, vertex by vertex.
        for j in range(len(vb_data[0]["Buffer"])):
            for i in range(len(fmt_struct["elements"])):
                pack_dxgi_vector(vb_stream, vb_data[i]["Buffer"][j], buffer_strides[i], fmt_struct["elements"][i]["Format"], e)
    else:
        # Write out the buffers, element by element.
        for i in range(len(fmt_struct["elements"])):
            for j in range(len(vb_data[0]["Buffer"])):
                pack_dxgi_vector(vb_stream, vb_data[i]["Buffer"][j], buffer_strides[i], fmt_struct["elements"][i]["Format"], e)
    return

def write_seg_vb_stream(vb_data, vb_stream, fmt_struct, input_slot, e = '<', interleave = True):
    buffer_strides = []
    seg_stride = fmt_struct["vb{} stride".format(input_slot)]
    seg_vb_data = [x for x in vb_data if x['InputSlot'] == input_slot]
    seg_elements = [x for x in fmt_struct['elements'] if x['InputSlot'] == input_slot]
    # Calculate individual buffer strides
    for i in range(len(seg_elements)):
        if i == len(seg_elements) - 1:
            buffer_strides.append(int(seg_stride) - int(seg_elements[i]["AlignedByteOffset"]))
        else:
            buffer_strides.append(int(seg_elements[i+1]["AlignedByteOffset"]) \
                - int(seg_elements[i]["AlignedByteOffset"]))
    if interleave == True:
        # Write out the buffers, vertex by vertex.
        for j in range(len(seg_vb_data[0]["Buffer"])):
            for i in range(len(seg_elements)):
                pack_dxgi_vector(vb_stream, seg_vb_data[i]["Buffer"][j], buffer_strides[i], seg_elements[i]["Format"], e)
    else:
        # Write out the buffers, element by element.
        for i in range(len(seg_elements)):
            for j in range(len(seg_vb_data[0]["Buffer"])):
                pack_dxgi_vector(vb_stream, seg_vb_data[i]["Buffer"][j], buffer_strides[i], seg_elements[i]["Format"], e)
    return

def write_vb(vb_data, vb_filename, fmt_struct, e = '<', interleave = True):
    if 'stride' in fmt_struct:
        with open(vb_filename, 'wb') as f:
            write_vb_stream(vb_data, f, fmt_struct, e=e, interleave=interleave)
    elif 'vb0 stride' in fmt_struct:
        for input_slot in [x[2:-7] for x in fmt_struct if len(x.split('stride')) > 1]:
            with open(vb_filename + input_slot, 'wb') as f:
                write_seg_vb_stream(vb_data, f, fmt_struct, input_slot, e=e, interleave=interleave)
    else:
        print("Decoding error when trying to interpret fmt file for {0}!\r\n".format(vb_filename))
        input("Press Enter to abort.")
        raise
    return

# The following two functions are purely for convenience
def read_struct_from_json(filename, raise_on_fail = True):
    with open(filename, 'r') as f:
        try:
            return(json.loads(f.read()))
        except json.JSONDecodeError as e:
            print("Decoding error when trying to read JSON file {0}!\r\n".format(filename))
            print("{0} at line {1} column {2} (character {3})\r\n".format(e.msg, e.lineno, e.colno, e.pos))
            if raise_on_fail == True:
                input("Press Enter to abort.")
                raise
            else:
                return(False)

def write_struct_to_json(struct, filename):
    if not filename[:-5] == '.json':
        filename += '.json'
    with open(filename, "wb") as f:
        f.write(json.dumps(struct, indent=4).encode("utf-8"))
    return


# === /mnt/user-data/uploads/kuro_mdl_export_meshes.py ===
# Tool to manipulate  ED9 / Kuro no Kiseki models in mdl format.  Dumps meshes for
# import into Blender.  Based on Uyjulian's script.
# Usage:  Run by itself without commandline arguments and it will read only the mesh section of
# every model it finds in the folder and output fmt / ib / vb files.
#
# For command line options (including option to dump vertices), run:
# /path/to/python3 kuro_mdl_export_meshes.py --help
#
# Requires both blowfish and zstandard for CLE assets.
# These can be installed by:
# /path/to/python3 -m pip install blowfish zstandard
#
# GitHub eArmada8/kuro_mdl_tool


# This script outputs complete vgmaps by default, change the following line to False to change
complete_vgmaps_default = True

# Thank you to authors of Kuro Tools for this decrypt function
# https://github.com/nnguyen259/KuroTools


def decryptCLE(file_content):
    key = b"\x16\x4B\x7D\x0F\x4F\xA7\x4C\xAC\xD3\x7A\x06\xD9\xF8\x6D\x20\x94"
    IV = b"\x9D\x8F\x9D\xA1\x49\x60\xCC\x4C"
    cipher = blowfish.Cipher(key, byte_order = "big")
    iv = struct.unpack(">Q", IV)
    dec_counter = blowfish.ctr_counter(iv[0], f = operator.add)

    magic = file_content[0:4]
    to_decrypt = [b"F9BA", b"C9BA"]
    to_decompress = [b"D9BA"]
    result = file_content
    while (magic in to_decrypt) or (magic in to_decompress):
        if (magic in to_decrypt):
            result = b"".join(cipher.decrypt_ctr(file_content[8:], dec_counter))
        elif(magic in to_decompress):
            decompressor = zstandard.ZstdDecompressor()
            result = decompressor.decompress(file_content[8:])
        file_content = result
        magic = file_content[0:4]

    return result

def get_kuro_ver (mdl_data):
    kuro_ver, = struct.unpack("<I",mdl_data[4:8])
    return(kuro_ver)

# From Julian Uy's ED9 MDL parser, thank you
def read_pascal_string(f):
    sz = int.from_bytes(f.read(1), byteorder="little")
    return f.read(sz)

def mdl_contents (mdl_data):
    with io.BytesIO(mdl_data) as f:
        mdl_header = struct.unpack("<III",f.read(12))
        if not mdl_header[0] == 0x204c444d:
            sys.exit()
        contents = []
        while True:
            current_offset = f.tell()
            section_info = {}
            try:
                section_info["type"], section_info["size"] = struct.unpack("<II",f.read(8))
            except:
                break
            section_info["section_start_offset"] = f.tell()
            contents.append(section_info)
            f.seek(section_info["size"],1) # Move forward to the next section
        return([x['type'] for x in contents])

def isolate_skeleton_data (mdl_data):
    with io.BytesIO(mdl_data) as f:
        mdl_header = struct.unpack("<III",f.read(12))
        if not mdl_header[0] == 0x204c444d:
            sys.exit()
        contents = []
        while True:
            current_offset = f.tell()
            section_info = {}
            try:
                section_info["type"], section_info["size"] = struct.unpack("<II",f.read(8))
            except:
                break
            section_info["section_start_offset"] = f.tell()
            contents.append(section_info)
            f.seek(section_info["size"],1) # Move forward to the next section
        # Kuro models seem to only have one skeleton section
        if len([x for x in contents if x["type"] == 2]) > 0:
            skeleton_section = [x for x in contents if x["type"] == 2][0]
            f.seek(skeleton_section["section_start_offset"],0)
            skeleton_section_data = f.read(skeleton_section["size"])
            return(skeleton_section_data)
        else:
            return False

def obtain_skeleton_data (mdl_data):
    skel_data = isolate_skeleton_data(mdl_data)
    if skel_data == False:
        return False
    with io.BytesIO(skel_data) as f:
        blocks, = struct.unpack("<I",f.read(4))
        skel_struct = []
        for i in range(blocks):
            node_block = {}
            node_block['id_referenceonly'] = i # Not used at all for repacking, purely for convenience
            node_block['name'] = read_pascal_string(f).decode("ASCII")
            # node_block['type']: 0 = transform only, 1 = skin child, 2 = mesh
            node_block['type'], node_block['mesh_index'] = struct.unpack("<Ii",f.read(8))
            node_block['pos_xyz'] = struct.unpack("<3f",f.read(12))
            node_block['unknown_quat'] = struct.unpack("<4f",f.read(16))
            node_block['skin_mesh'], = struct.unpack("<I",f.read(4))
            node_block['rotation_euler_rpy'] = struct.unpack("<3f",f.read(12))
            node_block['scale'] = struct.unpack("<3f",f.read(12))
            node_block['unknown'] = struct.unpack("<3f",f.read(12))
            child_count, = struct.unpack("<I",f.read(4))
            node_block['children'] = []
            for j in range(child_count):
                child, = struct.unpack("<I",f.read(4))
                node_block['children'].append(child)
            skel_struct.append(node_block)
    return(skel_struct)

def isolate_mesh_data (mdl_data):
    with io.BytesIO(mdl_data) as f:
        mdl_header = struct.unpack("<III",f.read(12))
        if not mdl_header[0] == 0x204c444d:
            sys.exit()
        contents = []
        while True:
            current_offset = f.tell()
            section_info = {}
            try:
                section_info["type"], section_info["size"] = struct.unpack("<II",f.read(8))
            except:
                break
            section_info["section_start_offset"] = f.tell()
            contents.append(section_info)
            f.seek(section_info["size"],1) # Move forward to the next section
        # Kuro models seem to only have one mesh section
        if len([x for x in contents if x["type"] == 1]) > 0:
            mesh_section = [x for x in contents if x["type"] == 1][0]
            f.seek(mesh_section["section_start_offset"],0)
            mesh_section_data = f.read(mesh_section["size"])
            return(mesh_section_data)
        else:
            return False

# Kuro 2 has separate primitive section
def isolate_primitive_data (mdl_data):
    with io.BytesIO(mdl_data) as f:
        mdl_header = struct.unpack("<III",f.read(12))
        if not mdl_header[0] == 0x204c444d:
            sys.exit()
        contents = []
        while True:
            current_offset = f.tell()
            section_info = {}
            try:
                section_info["type"], section_info["size"] = struct.unpack("<II",f.read(8))
            except:
                break
            section_info["section_start_offset"] = f.tell()
            contents.append(section_info)
            f.seek(section_info["size"],1) # Move forward to the next section
        # Kuro models seem to only have one primitive section?
        primitive_section = [x for x in contents if x["type"] == 4][0]
        f.seek(primitive_section["section_start_offset"],0)
        primitive_section_data = f.read(primitive_section["size"])
        return(primitive_section_data)

def parse_primitive_header (primitive_data):
    with io.BytesIO(primitive_data) as f:
        blocks, = struct.unpack("<I",f.read(4))
        data_offset = blocks * 20 + 4
        primitive_info = []
        for i in range(blocks):
            element = {}
            element["type_int"], element["size"], element["stride"], element["mesh"],\
                element["submesh"] = struct.unpack("<5I",f.read(20))
            element["offset"] = data_offset
            data_offset += element["size"]
            primitive_info.append(element)
    return(primitive_info)
            
def obtain_mesh_data (mdl_data, material_struct, trim_for_gpu = False):
    kuro_ver = get_kuro_ver(mdl_data)
    mesh_data = isolate_mesh_data(mdl_data)
    if mesh_data == False:
        return False
    material_dict = {i:material_struct[i]['material_name'] for i in range(len(material_struct))}
    if kuro_ver > 1:
        primitive_data = isolate_primitive_data(mdl_data)
        primitive_info = parse_primitive_header(primitive_data)
        prim = io.BytesIO(primitive_data)
    with io.BytesIO(mesh_data) as f:
        blocks, = struct.unpack("<I",f.read(4))
        mesh_blocks = []
        mesh_block_buffers = []
        mesh_collision_data = []
        # Meshes are separated into groups (hair, body, shadow)
        for i in range(blocks):
            mesh_block = {}
            mesh_block["name"] = read_pascal_string(f).decode("ASCII")
            mesh_block["size"], = struct.unpack("<I",f.read(4))
            mesh_block["offset"] = f.tell()
            mesh_block["primitive_count"], = struct.unpack("<I",f.read(4))
            primitives = []
            mesh_buffers = []
            for j in range(mesh_block["primitive_count"]):
                primitive = {}
                primitive["id_referenceonly"] = j # Not used at all for repacking, purely for convenience
                primitive["material"] = material_dict[struct.unpack("<I",f.read(4))[0]]
                if kuro_ver == 1:
                    primitive["num_of_elements"], = struct.unpack("<I",f.read(4))
                elif kuro_ver > 1:
                    primitive["num_of_elements"] = len([x for x in primitive_info if x['mesh'] == i and x['submesh'] == j])
                    primitive["triangle_count"], primitive["unk"] = struct.unpack("<2I",f.read(8))
                elements = []
                ibvb = {}
                buffers = []
                semantic_index = [0,0,0,0,0,0,0,0] # Counters for multiple indicies (e.g. TEXCOORD1, 2, etc)
                aligned_byte_offset = 0
                element_num = 0 # Needed for accurate count in fmt when skipping elements
                for k in range(primitive["num_of_elements"]):
                    element = {}
                    if kuro_ver == 1:
                        element["type_int"], element["size"], element["stride"] = struct.unpack("<3I",f.read(12))
                        element["offset"] = f.tell()
                    elif kuro_ver > 1:
                        prim_element = [x for x in primitive_info if x['mesh'] == i and x['submesh'] == j][k]
                        element["type_int"], element["size"], element["stride"], element["offset"] =\
                            prim_element["type_int"], prim_element["size"], prim_element["stride"], prim_element["offset"]
                        prim.seek(prim_element["offset"])
                    element["count"] = int(element["size"]/element["stride"])
                    # Vertex reading here!!
                    match element["type_int"]:
                        case 0:
                            element["Semantic"] = "POSITION"
                            element_type = 'f'
                        case 1:
                            element["Semantic"] = "NORMAL"
                            if element["stride"] == 4:
                                element_type = 'S'
                            else:
                                element_type = 'f'
                        case 2:
                            element["Semantic"] = "TANGENT"
                            if element["stride"] == 4:
                                element_type = 'S'
                            else:
                                element_type = 'f'
                        case 3:
                            element["Semantic"] = "COLOR"
                            if element["stride"] == 4:
                                element_type = 'U'
                            else:
                                element_type = 'f'
                        case 4:
                            element["Semantic"] = "TEXCOORD"
                            element_type = 'f'
                        case 5:
                            element["Semantic"] = "BLENDWEIGHT"
                            element_type = 'f'
                        case 6:
                            element["Semantic"] = "BLENDINDICES"
                            element_type = 'I'
                        case 7:
                            element["Semantic"] = "TRIANGLES"
                            element_type = 'I'
                    element_index = semantic_index[element["type_int"]]
                    semantic_index[element["type_int"]] += 1
                    buffer = {}
                    buffer["stride"] = element["stride"] # Purely for convenience, used later to make fmt
                    buffer_data = []
                    match element_type:
                        case 'f': #32-bit FLOAT
                            format_colors = ['R32','G32','B32','A32','D32']
                            for l in range(element["count"]):
                                if kuro_ver == 1:
                                    buffer_data.append(struct.unpack("<{0}f".format(int(element["stride"]/4)), f.read(element["stride"])))
                                elif kuro_ver > 1:
                                    buffer_data.append(struct.unpack("<{0}f".format(int(element["stride"]/4)), prim.read(element["stride"])))
                                format_string = "".join(format_colors[0:int(element["stride"]/4)]) + "_FLOAT"
                        case 'I': #32-bit UINT
                            format_colors = ['R32','G32','B32','A32','D32']
                            for l in range(element["count"]):
                                if kuro_ver == 1:
                                    buffer_data.append(struct.unpack("<{0}I".format(int(element["stride"]/4)), f.read(element["stride"])))
                                elif kuro_ver > 1:
                                    buffer_data.append(struct.unpack("<{0}I".format(int(element["stride"]/4)), prim.read(element["stride"])))
                                format_string = "".join(format_colors[0:int(element["stride"]/4)]) + "_UINT"
                        case 'H': #16-bit UINT, not sure this is used by Kuro at all
                            format_colors = ['R16','G16','B16','A16','D16']
                            for l in range(element["count"]):
                                if kuro_ver == 1:
                                    buffer_data.append(struct.unpack("<{0}H".format(int(element["stride"]/2)), f.read(element["stride"])))
                                elif kuro_ver > 1:
                                    buffer_data.append(struct.unpack("<{0}H".format(int(element["stride"]/2)), prim.read(element["stride"])))
                                format_string = "".join(format_colors[0:int(element["stride"]/2)]) + "_UINT"
                        case 'U': #8-bit UNORM
                            if kuro_ver == 2:
                                format_colors = ['B8','G8','R8','A8'] # Dunno why Kuro 2 has this reversed
                            else:
                                format_colors = ['R8','G8','B8','A8']
                            float_max = ((2**8)-1) #Assuming all UNORM is 8-bit
                            for l in range(element["count"]):
                                if kuro_ver == 1:
                                    buffer_data.append([x / float_max for x in struct.unpack("<{0}B".format(int(element["stride"])), f.read(element["stride"]))])
                                elif kuro_ver > 1:
                                    buffer_data.append([x / float_max for x in struct.unpack("<{0}B".format(int(element["stride"])), prim.read(element["stride"]))])
                                format_string = "".join(format_colors[0:int(element["stride"])]) + "_UNORM"
                        case 'S': #8-bit SNORM
                            format_colors = ['R8','G8','B8','A8']
                            float_max = ((2**(8-1))-1) #Assuming all SNORM is 8-bit
                            for l in range(element["count"]):
                                if kuro_ver == 1:
                                    buffer_data.append([x / float_max for x in struct.unpack("<{0}b".format(int(element["stride"])), f.read(element["stride"]))])
                                elif kuro_ver > 1:
                                    buffer_data.append([x / float_max for x in struct.unpack("<{0}b".format(int(element["stride"])), prim.read(element["stride"]))])
                                format_string = "".join(format_colors[0:int(element["stride"])]) + "_SNORM"
                    buffer["fmt"] = {"id": str(element_num),
                        "SemanticName": element["Semantic"],\
                        "SemanticIndex": str(element_index),\
                        "Format": format_string,\
                        "InputSlot": "0",\
                        "AlignedByteOffset": str(aligned_byte_offset),\
                        "InputSlotClass": "per-vertex",\
                        "InstanceDataStepRate": "0"}
                    if element["type_int"] == 7:
                        ib = {}
                        ib["format"] = "DXGI_FORMAT_" + format_string
                        ib["Buffer"] = []
                        indices = list(chain.from_iterable(buffer_data))
                        triangle = []
                        vertex_num = 0
                        for l in range(len(indices)):
                            triangle.append(indices[l])
                            vertex_num += 1
                            if vertex_num % 3 == 0:
                                ib["Buffer"].append(triangle)
                                triangle = []
                    else:
                        # The next two lines makes the buffer fully compatible with lib_fmtibvb
                        buffer["SemanticName"] = buffer["fmt"]["SemanticName"]
                        buffer["SemanticIndex"] = buffer["fmt"]["SemanticIndex"]
                        # If Trim for GPU is on, discard texcoords above the 3rd, and the unknown buffers
                        if (trim_for_gpu == False) or (element_index < 3 and not element["type_int"] == 3):
                            aligned_byte_offset += element["stride"]
                            buffer["Buffer"] = buffer_data
                            buffers.append(buffer)
                            element_num += 1
                    elements.append(element)
                ibvb["ib"] = ib
                ibvb["vb"] = buffers
                mesh_buffers.append(ibvb)                    
                primitive["Elements"] = elements
                primitives.append(primitive)
            mesh_block["primitives"] = primitives
            mesh_block["node_count"], = struct.unpack("<I",f.read(4))
            if mesh_block["node_count"] > 0:
                nodes = []
                for j in range(mesh_block["node_count"]):
                    node = {}
                    node["name"] = read_pascal_string(f).decode("ASCII")
                    node["matrix"] = [struct.unpack("<4f",f.read(16)), struct.unpack("<4f",f.read(16)),\
                        struct.unpack("<4f",f.read(16)), struct.unpack("<4f",f.read(16))]
                    nodes.append(node)
                mesh_block["nodes"] = nodes
            mesh_block_collision_data = {}
            section2 = {} # Collision metadata, thank you to Kyuuhachi for unwinding this data!
            section2["size"], = struct.unpack("<I", f.read(4))
            section2["minbound"] = list(struct.unpack("<3f", f.read(12)))
            section2["unk0"], = struct.unpack("<I", f.read(4))
            section2["maxbound"] = list(struct.unpack("<3f", f.read(12)))
            section2["unk1"], = struct.unpack("<I", f.read(4))
            section2["num_triangles"], = struct.unpack("<I", f.read(4))
            if section2["num_triangles"] > 0:
                vert_buffer = []
                idx_buffer = []
                for j in range(section2["num_triangles"]):
                    pos = numpy.array([list(struct.unpack("<3f", f.read(12))) for _ in range(3)])
                    nrm = numpy.array(struct.unpack("<3f", f.read(12)))
                    midpoint = list(struct.unpack("<3f", f.read(12)))
                    radius, = struct.unpack("<f", f.read(4))
                    # Determine triangle winding order by comparing the calculated normal to the provided one
                    calc_nrm = numpy.cross(pos[1] - pos[0], pos[2] - pos[0])
                    calc_nrm = calc_nrm / numpy.linalg.norm(calc_nrm)
                    wind_order = numpy.dot(calc_nrm, nrm)
                    vert_buffer.extend(pos.tolist())
                    if wind_order >= 0:
                        idx_buffer.append([j*3, j*3+1, j*3+2])
                    else:
                        idx_buffer.append([j*3, j*3+2, j*3+1])
                fmt = {'stride': '12', 'topology': 'trianglelist', 'format': 'DXGI_FORMAT_R32_UINT',\
                    'elements': [{'id': '0', 'SemanticName': 'POSITION', 'SemanticIndex': '0',\
                    'Format': 'R32G32B32_FLOAT', 'InputSlot': '0', 'AlignedByteOffset': '0',\
                    'InputSlotClass': 'per-vertex', 'InstanceDataStepRate': '0'}]}
                mesh_block_collision_data["collision_mesh"] = {'fmt': fmt,
                    'ib': idx_buffer, 'vb': [{'Buffer': vert_buffer}]}
            section2["num_nodes"], = struct.unpack("<I", f.read(4))
            if section2["num_nodes"] > 0:
                node_buffer = []
                for j in range(section2["num_nodes"]):
                    node = {}
                    node['min'], node['max'] = [list(struct.unpack("<3f", f.read(12))) for _ in range(2)]
                    node['start'], node['end'] = struct.unpack("<2i", f.read(8))
                    node['num_triangles'], = struct.unpack("<I", f.read(4))
                    if node['num_triangles'] > 0:
                        node['triangles'] = struct.unpack("<{}I".format(node['num_triangles']), f.read(node['num_triangles']*4))
                    node_buffer.append(node)
                mesh_block_collision_data["collision_map"] = node_buffer
            section2["flags"], = struct.unpack("<I", f.read(4))
            mesh_block["section2"] = section2
            mesh_blocks.append(mesh_block)
            mesh_block_buffers.append(mesh_buffers)
            mesh_collision_data.append(mesh_block_collision_data)
        mesh_data = {}
        mesh_data["mesh_blocks"] = mesh_blocks
        mesh_data["mesh_buffers"] = mesh_block_buffers
        mesh_data["mesh_collision_data"] = mesh_collision_data
    if kuro_ver > 1:
        prim.close()
    return(mesh_data)

def isolate_material_data (mdl_data):
    with io.BytesIO(mdl_data) as f:
        mdl_header = struct.unpack("<III",f.read(12))
        if not mdl_header[0] == 0x204c444d:
            sys.exit()
        contents = []
        while True:
            current_offset = f.tell()
            section_info = {}
            try:
                section_info["type"], section_info["size"] = struct.unpack("<II",f.read(8))
            except:
                break
            section_info["section_start_offset"] = f.tell()
            contents.append(section_info)
            f.seek(section_info["size"],1) # Move forward to the next section
        if len([x for x in contents if x["type"] == 0]) > 0:
            # Kuro models seem to only have one material section
            material_section = [x for x in contents if x["type"] == 0][0]
            f.seek(material_section["section_start_offset"],0)
            material_section_data = f.read(material_section["size"])
            return(material_section_data)
        else:
            return False

def obtain_material_data (mdl_data):
    kuro_ver = get_kuro_ver(mdl_data)
    material_data = isolate_material_data(mdl_data)
    if material_data == False:
        return False
    with io.BytesIO(material_data) as f:
        blocks, = struct.unpack("<I",f.read(4))
        material_blocks = []
        # Materials are not grouped like meshes, but roughly follow the same order
        for i in range(blocks):
            material_block = {}
            material_block['id_referenceonly'] = i # Not used at all for repacking, purely for convenience
            material_block['material_name'] = read_pascal_string(f).decode("ASCII")
            material_block['shader_name'] = read_pascal_string(f).decode("ASCII")
            material_block['str3'] = read_pascal_string(f).decode("ASCII")
            material_block['shader_switches_hash_referenceonly'] = ''
            texture_element_count, = struct.unpack("<I",f.read(4))
            material_block['textures'] = []
            for j in range(texture_element_count):
                texture_block = {}
                texture_block['texture_image_name'] = read_pascal_string(f).decode("ASCII")
                texture_block['texture_slot'], = struct.unpack("<i",f.read(4))
                if kuro_ver > 1:
                    texture_block['unk_00'], = struct.unpack("<i",f.read(4))
                texture_block['wrapS'], texture_block['wrapT'] = struct.unpack("<2i",f.read(8))
                if kuro_ver > 1:
                    texture_block['unk_03'], = struct.unpack("<i",f.read(4))
                material_block['textures'].append(texture_block)
            shader_element_count, = struct.unpack("<I",f.read(4))
            material_block['shaders'] = []
            for j in range(shader_element_count):
                shader_block = {}
                shader_block['shader_name'] = read_pascal_string(f).decode("ASCII")
                shader_block['type_int'], = struct.unpack("<I",f.read(4))
                match shader_block['type_int']:
                    case 0 | 1:
                        shader_block['data'], = struct.unpack("<I",f.read(4))
                    case 2:
                        shader_block['data_base64'] = base64.b64encode(f.read(8)).decode()
                    case 3:
                        shader_block['data_base64'] = base64.b64encode(f.read(12)).decode()
                    case 4:
                        shader_block['data'], = struct.unpack("<f",f.read(4))
                    case 5:
                        shader_block['data'] = list(struct.unpack("<2f",f.read(8)))
                    case 6:
                        shader_block['data'] = list(struct.unpack("<3f",f.read(12)))
                    case 7:
                        shader_block['data_base64'] = base64.b64encode(f.read(16)).decode()
                    case 8:
                        shader_block['data_base64'] = base64.b64encode(f.read(64)).decode()
                    case 0xFFFFFFFF:
                        shader_block['data_base64'] = ''
                material_block['shaders'].append(shader_block)
            material_switch_count, = struct.unpack("<I",f.read(4))
            material_block['material_switches'] = []
            switch_start = f.tell()
            for j in range(material_switch_count):
                material_switch_block = {}
                material_switch_block['material_switch_name'] = read_pascal_string(f).decode("ASCII")
                material_switch_block['int2'], = struct.unpack("<i",f.read(4))
                material_block['material_switches'].append(material_switch_block)
            switch_end = f.tell()
            f.seek(switch_start,0)
            material_block['shader_switches_hash_referenceonly'] = xxhash.xxh64_hexdigest(f.read(switch_end - switch_start))
            uv_map_index_count, = struct.unpack("<I",f.read(4))
            material_block['uv_map_indices'] = list(struct.unpack("{0}B".format(uv_map_index_count),f.read(uv_map_index_count)))
            unknown1_count, = struct.unpack("<I",f.read(4))
            material_block['unknown1'] = list(struct.unpack("{0}B".format(unknown1_count),f.read(unknown1_count)))
            material_block['unknown2'] = list(struct.unpack("<3IfI",f.read(20)))
            material_blocks.append(material_block)
        return(material_blocks)

def make_fmt_struct (mesh_buffers):
    fmt_struct = {}
    fmt_struct["stride"] = 0
    for i in range(len(mesh_buffers['vb'])):
        fmt_struct["stride"] += mesh_buffers['vb'][i]['stride']
    fmt_struct["stride"] = str(fmt_struct["stride"])
    fmt_struct["topology"] = "trianglelist"
    fmt_struct["format"] = mesh_buffers["ib"]["format"]
    fmt_struct["elements"] = [x["fmt"] for x in mesh_buffers["vb"]]
    return(fmt_struct)

def write_fmt_ib_vb (mesh_buffers, filename, node_list = False, complete_maps = False, write_empty_buffers = False):
    print("Processing submesh {0}...".format(filename))
    fmt_struct = make_fmt_struct(mesh_buffers)
    write_fmt(fmt_struct, filename + '.fmt')
    if len(mesh_buffers['ib']['Buffer']) > 0 or write_empty_buffers == True:
        write_ib(mesh_buffers['ib']['Buffer'], filename +  '.ib', fmt_struct)
        write_vb(mesh_buffers['vb'], filename +  '.vb', fmt_struct)
    if not node_list == False:
        # Find vertex groups referenced by vertices so that we can cull the empty ones
        active_nodes = list(set(list(chain.from_iterable([x["Buffer"] for x in mesh_buffers["vb"] \
            if x["fmt"]["SemanticName"] == 'BLENDINDICES'][0]))))
        vgmap_json = {}
        for i in range(len(node_list)):
            if (i in active_nodes) or (complete_maps == True):
                vgmap_json[node_list[i]["name"]] = i
        with open(filename + '.vgmap', 'wb') as f:
            f.write(json.dumps(vgmap_json, indent=4).encode("utf-8"))
    return

def process_mdl (mdl_file, complete_maps = complete_vgmaps_default, trim_for_gpu = False, dump_collision_nodes = False, overwrite = False):
    with open(mdl_file, "rb") as f:
        mdl_data = f.read()
    print("Processing {0}...".format(mdl_file))
    mdl_data = decryptCLE(mdl_data)
    material_struct = obtain_material_data(mdl_data)
    material_json_filename = mdl_file[:-4] + '/material_info.json'
    mesh_struct = obtain_mesh_data(mdl_data, material_struct = material_struct, trim_for_gpu = trim_for_gpu)
    mesh_json_filename = mdl_file[:-4] + '/mesh_info.json'
    skel_struct = obtain_skeleton_data(mdl_data)
    skel_json_filename = mdl_file[:-4] + '/skeleton.json'
    mdl_version_json_filename = mdl_file[:-4] + '/mdl_version.json'
    if mesh_struct == False and material_struct == False:
        print ("Skipping {0} as it lacks mesh and material data.".format(mdl_file))
        return False
    image_list = sorted(list(set([x['texture_image_name']+'.dds' for y in material_struct for x in y['textures']])))
    image_json_filename = mdl_file[:-4] + '/image_list.json'
    if os.path.exists(mdl_file[:-4]) and (os.path.isdir(mdl_file[:-4])) and (overwrite == False):
        if str(input(mdl_file[:-4] + " folder exists! Overwrite? (y/N) ")).lower()[0:1] == 'y':
            overwrite = True
    if (overwrite == True) or not os.path.exists(mdl_file[:-4]):
        if not os.path.exists(mdl_file[:-4]):
            os.mkdir(mdl_file[:-4])
        with open(mdl_version_json_filename, 'wb') as f:
            f.write(json.dumps({'mdl_version': get_kuro_ver(mdl_data)}, indent=4).encode("utf-8"))
        with open(mesh_json_filename, 'wb') as f:
            f.write(json.dumps(mesh_struct["mesh_blocks"], indent=4).encode("utf-8"))
        with open(material_json_filename, 'wb') as f:
            f.write(json.dumps(material_struct, indent=4).encode("utf-8"))
        with open(image_json_filename, 'wb') as f:
            f.write(json.dumps(image_list, indent=4).encode("utf-8"))
        with open(skel_json_filename, 'wb') as f:
            f.write(json.dumps(skel_struct, indent=4).encode("utf-8"))
        for i in range(len(mesh_struct["mesh_buffers"])):
            safe_filename = "".join([x if x not in "\\/:*?<>|" else "_" for x in mesh_struct["mesh_blocks"][i]["name"]])
            if mesh_struct["mesh_blocks"][i]["node_count"] > 0:
                node_list = mesh_struct["mesh_blocks"][i]["nodes"]
            else:
                node_list = False
            for j in range(len(mesh_struct["mesh_buffers"][i])):
                write_fmt_ib_vb(mesh_struct["mesh_buffers"][i][j], mdl_file[:-4] +\
                    '/{0}_{1}_{2:02d}'.format(i, safe_filename, j),\
                    node_list = node_list, complete_maps = complete_maps)
            if "collision_mesh" in mesh_struct["mesh_collision_data"][i]:
                fmt = mesh_struct["mesh_collision_data"][i]["collision_mesh"]['fmt']
                write_fmt(fmt, mdl_file[:-4] + '/{0}_{1}_collision.fmt'.format(i, safe_filename))
                write_ib(mesh_struct["mesh_collision_data"][i]["collision_mesh"]['ib'],
                    mdl_file[:-4] + '/{0}_{1}_collision.ib'.format(i, safe_filename), fmt)
                write_vb(mesh_struct["mesh_collision_data"][i]["collision_mesh"]['vb'],
                    mdl_file[:-4] + '/{0}_{1}_collision.vb'.format(i, safe_filename), fmt)
            if "collision_map" in mesh_struct["mesh_collision_data"][i] and dump_collision_nodes == True:
                with open(mdl_file[:-4] + '/{0}_{1}_collision_nodes.json'.format(i, safe_filename), 'wb') as f:
                    f.write(json.dumps(mesh_struct["mesh_collision_data"][i]["collision_map"], indent=4).encode("utf-8"))


# === /mnt/user-data/uploads/kuro_mdl_import_meshes.py ===
# Tool to manipulate ED9 / Kuro no Kiseki models in mdl format.  Replace mesh section of
# Kuro no Kiseki mdl file with individual buffers previously exported.  Based on Uyjulian's script.
# Usage:  Run by itself without commandline arguments and it will read only the mesh section of
# every model it finds in the folder and replace them with fmt / ib / vb files in the same named
# directory.
#
# For command line options, run:
# /path/to/python3 kuro_mdl_import_meshes.py --help
#
# Requires both blowfish and zstandard for CLE assets.
# These can be installed by:
# /path/to/python3 -m pip install blowfish zstandard
#
# GitHub eArmada8/kuro_mdl_tool


def compressCLE(file_content):
    magic = file_content[0:4]
    compressed_magic = b"D9BA"
    result = file_content
    if not magic == compressed_magic: # Don't compress files that are already compressed:
        compressor = zstandard.ZstdCompressor(level = 12, write_checksum = True)
        result = compressor.compress(file_content)
        while (len(result) % 8) > 0:
            result += b'\x00'
        result = compressed_magic + struct.pack("<I", len(result)) + result
    return result

def make_pascal_string(string):
    return struct.pack("<B", len(string)) + string.encode("utf8")

# Primitive data is in Kuro 2.  In Kuro 1, it will be an empty buffer.
# force_kuro_version should be either set to False, or to an integer.
def insert_model_data (mdl_data, skeleton_section_data, material_section_data, mesh_section_data, primitive_section_data, kuro_ver):
    with io.BytesIO(mdl_data) as f:
        new_mdl_data = f.read(4) #Header
        orig_kuro_ver, = struct.unpack("<I", f.read(4))
        kuro_ver = min(kuro_ver, orig_kuro_ver)
        new_mdl_data += struct.pack("<I", kuro_ver)
        new_mdl_data += f.read(4) #Not sure what this is in the header
        while True:
            current_offset = f.tell()
            section = f.read(8)
            section_info = {}
            try:
                section_info["type"], section_info["size"] = struct.unpack("<II",section)
                section += f.read(section_info["size"])
            except:
                break
            if section_info["type"] == 0: # Material section to replace
                section = material_section_data
            if section_info["type"] == 1: # Mesh section to replace
                section = mesh_section_data
            if section_info["type"] == 2: # Skeleton section to replace
                section = skeleton_section_data
            if section_info["type"] == 4: # Primitive section to replace
                if kuro_ver > 1:
                    section = primitive_section_data
                else: # Needed if we are forcing downgrade to version 1
                    section = b''
            new_mdl_data += section
        # Catch the null bytes at the end of the stream
        f.seek(current_offset,0)
        new_mdl_data += f.read()
        return(new_mdl_data)

def build_skeleton_struct_from_mdl (mdl_filename):
    # Will read data from JSON file, or load original data from the mdl file if JSON is missing
    try:
        skel_struct = read_struct_from_json(mdl_filename + "/skeleton.json")
    except:
        print("{0}/skeleton.json missing or unreadable, reading data from {0}.mdl instead...".format(mdl_filename))
        with open(mdl_filename + '.mdl', "rb") as f:
            mdl_data = f.read()
        mdl_data = decryptCLE(mdl_data)
        skel_struct = obtain_skeleton_data(mdl_data)
    return(skel_struct)

def build_skeleton_section (skel_struct):
    output_buffer = struct.pack("<I", len(skel_struct))
    for i in range(len(skel_struct)):
        output_buffer += make_pascal_string(skel_struct[i]['name'])
        output_buffer += struct.pack("<Ii", skel_struct[i]['type'], skel_struct[i]['mesh_index'])
        output_buffer += struct.pack("<3f", *skel_struct[i]['pos_xyz'])
        output_buffer += struct.pack("<4f", *skel_struct[i]['unknown_quat'])
        output_buffer += struct.pack("<I", skel_struct[i]['skin_mesh'])
        output_buffer += struct.pack("<3f", *skel_struct[i]['rotation_euler_rpy'])
        output_buffer += struct.pack("<3f", *skel_struct[i]['scale'])
        output_buffer += struct.pack("<3f", *skel_struct[i]['unknown'])
        output_buffer += struct.pack("<I", len(skel_struct[i]['children']))
        output_buffer += struct.pack("<{}I".format(len(skel_struct[i]['children'])), *skel_struct[i]['children'])
    return(struct.pack("<2I", 2, len(output_buffer)) + output_buffer)

def build_material_section (mdl_filename, material_list = [], kuro_ver = 1):
    # Will read data from JSON file, or load original data from the mdl file if JSON is missing
    try:
        raw_material_struct = read_struct_from_json(mdl_filename + "/material_info.json")
    except:
        print("{0}/material_info.json missing or unreadable, reading data from {0}.mdl instead...".format(mdl_filename))
        with open(mdl_filename + '.mdl', "rb") as f:
            mdl_data = f.read()
        mdl_data = decryptCLE(mdl_data)
        raw_material_struct = obtain_material_data(mdl_data)
    material_struct = []
    try:
        materials = [x['material_name'] for x in raw_material_struct]
        for material in material_list:
            material_struct.append(raw_material_struct[materials.index(material)])
    except ValueError:
        print("ValueError: Attempted to add material {0} it does not exist in material_info.json!".format(material))
        input("Press Enter to abort.")
        raise
    output_buffer = struct.pack("<I", len(material_struct))
    for i in range(len(material_struct)):
        material_block = make_pascal_string(material_struct[i]['material_name']) \
            + make_pascal_string(material_struct[i]['shader_name']) \
            + make_pascal_string(material_struct[i]['str3'])
        texture_blocks = bytes()
        texture_block_count = 0
        for j in range(len(material_struct[i]['textures'])):
            texture_blocks += make_pascal_string(material_struct[i]['textures'][j]['texture_image_name']) \
                + struct.pack("<i", material_struct[i]['textures'][j]['texture_slot'])
            if kuro_ver > 1:
                texture_blocks += struct.pack("<i", material_struct[i]['textures'][j]['unk_00'])
            texture_blocks += struct.pack("<2i", material_struct[i]['textures'][j]['wrapS'], material_struct[i]['textures'][j]['wrapT'])
            if kuro_ver > 1:
                texture_blocks += struct.pack("<i", material_struct[i]['textures'][j]['unk_03'])
            texture_block_count += 1
        material_block += struct.pack("<I", texture_block_count) + texture_blocks
        shader_elements = bytes()
        shader_element_count = 0
        for j in range(len(material_struct[i]['shaders'])):
            if material_struct[i]['shaders'][j]['type_int'] in [0,1,4,5,6]: # These are decoded, so need to be encoded
                struct_dict = {0: "<I", 1: "<I", 4: "<f", 5: "<2f", 6: "<3f"}
                shader_elements += make_pascal_string(material_struct[i]['shaders'][j]['shader_name']) \
                    + struct.pack("<I", material_struct[i]['shaders'][j]['type_int'])
                if type(material_struct[i]['shaders'][j]['data']) == list:
                    shader_elements += struct.pack(struct_dict[material_struct[i]['shaders'][j]['type_int']], *material_struct[i]['shaders'][j]['data'])
                else:
                    shader_elements += struct.pack(struct_dict[material_struct[i]['shaders'][j]['type_int']], material_struct[i]['shaders'][j]['data'])
            else:
                shader_elements += make_pascal_string(material_struct[i]['shaders'][j]['shader_name']) \
                    + struct.pack("<I", material_struct[i]['shaders'][j]['type_int']) \
                    + base64.b64decode(material_struct[i]['shaders'][j]['data_base64'])
            shader_element_count += 1
        material_block += struct.pack("<I", shader_element_count) + shader_elements
        material_switches = bytes()
        material_switch_count = 0
        for j in range(len(material_struct[i]['material_switches'])):
            material_switches += make_pascal_string(material_struct[i]['material_switches'][j]['material_switch_name']) \
                + struct.pack("<i", material_struct[i]['material_switches'][j]['int2'])
            material_switch_count += 1
        material_block += struct.pack("<I", material_switch_count) + material_switches
        material_block += struct.pack("<I{0}B".format(len(material_struct[i]['uv_map_indices'])), len(material_struct[i]['uv_map_indices']), *material_struct[i]['uv_map_indices'])
        material_block += struct.pack("<I{0}B".format(len(material_struct[i]['unknown1'])), len(material_struct[i]['unknown1']), *material_struct[i]['unknown1'])
        material_block += struct.pack("<3IfI", *material_struct[i]['unknown2'])
        output_buffer += material_block
    return(struct.pack("<2I", 0, len(output_buffer)) + output_buffer)

# Calculate the normal vector for a collision mesh triangle.
def triangle_normal(pos_vector):
    pos = numpy.array(pos_vector)
    calc_nrm = numpy.cross(pos[1] - pos[0], pos[2] - pos[0])
    calc_nrm = calc_nrm / numpy.linalg.norm(calc_nrm)
    return calc_nrm

# Calculate the circumsphere for a collision mesh triangle.  This function is written by chatgpt.
# Gratitude and credit to chatgpt and all the code that went into its training and their authors.
def circumsphere(pos_vector):
    pos = numpy.array(pos_vector)

    if numpy.dot(pos[1] - pos[0], pos[2] - pos[0]) <= 0: return (pos[1] + pos[2]) / 2, numpy.linalg.norm(pos[1] - pos[2]) / 2
    if numpy.dot(pos[0] - pos[1], pos[2] - pos[1]) <= 0: return (pos[0] + pos[2]) / 2, numpy.linalg.norm(pos[0] - pos[2]) / 2
    if numpy.dot(pos[0] - pos[2], pos[1] - pos[2]) <= 0: return (pos[0] + pos[1]) / 2, numpy.linalg.norm(pos[0] - pos[1]) / 2

    # For an acute triangle, we must compute the circumcenter.
    # First, construct an orthonormal basis (u, v) for the plane of the triangle.
    u = pos[1] - pos[0]
    u = u / numpy.linalg.norm(u)
    # The normal to the plane
    normal = numpy.cross(pos[1] - pos[0], pos[2] - pos[0])
    normal = normal / numpy.linalg.norm(normal)
    # The in-plane vector perpendicular to u
    v = numpy.cross(normal, u)

    # Project points pos[1] and pos[2] onto the (u,v) coordinate system with pos[0] as the origin.
    pB = numpy.array([numpy.linalg.norm(pos[1] - pos[0]), 0])
    pC = numpy.array([numpy.dot(pos[2] - pos[0], u), numpy.dot(pos[2] - pos[0], v)])

    # Solve for the circumcenter in 2D.
    # The perpendicular bisector of the segment from (0,0) to pB has the equation:
    #   pB[0]*x + pB[1]*y = 0.5 * (||pB||^2)
    # Similarly for the segment from (0,0) to pC.
    M = numpy.array([[pB[0], pB[1]], [pC[0], pC[1]]])
    b_vec = numpy.array([0.5 * numpy.dot(pB, pB), 0.5 * numpy.dot(pC, pC)])

    # Solve the linear system to get the 2D circumcenter coordinates (x, y)
    circumcenter_2d = numpy.linalg.solve(M, b_vec)

    # Map the 2D circumcenter back to 3D
    center = pos[0] + circumcenter_2d[0] * u + circumcenter_2d[1] * v
    radius = numpy.linalg.norm(center - pos[0])

    return (center, radius)

# Takes a collision mesh struct with raw buffers and outputs the triangles in the format the Kuro engine expects
def generate_triangle_struct(mesh_struct):
    triangle_struct = []
    posidx = [x['SemanticName'] for x in mesh_struct['vb']].index('POSITION')
    for i in range(len(mesh_struct['ib'])):
        pos_vector = [mesh_struct['vb'][posidx]['Buffer'][j] for j in mesh_struct['ib'][i]]
        nrm_vector = triangle_normal(pos_vector)
        midpoint, radius = circumsphere(pos_vector)
        triangle = {'pos': pos_vector, 'nrm': nrm_vector.tolist(), 'midpoint': midpoint.tolist(), 'radius': radius.tolist()}
        triangle_struct.append(triangle)
    return triangle_struct

# This is specifically for constructing the BVH tree, and takes a triangle struct in the collision mesh format
def bounding_box (triangles):
    x = [x[0] for y in triangles for x in y[1]['pos']]
    y = [x[1] for y in triangles for x in y[1]['pos']]
    z = [x[2] for y in triangles for x in y[1]['pos']]
    return([[min(x), min(y), min(z)], [max(x), max(y), max(z)]])

class BVHNode:  # Self-running recursive class to build a bounding volume hierarchy node tree
    def __init__(self, triangles, max_per_node = 2):
        self.bounds = bounding_box(triangles)
        self.children = []  # Always 0 or 2 elements
        self.tri_indices = []  # Stores indices of triangles
        if len(triangles) > max_per_node:
            axis_len = list(enumerate([max([x[1]['midpoint'][0] for x in triangles]) - min([x[1]['midpoint'][0] for x in triangles]),
                max([x[1]['midpoint'][1] for x in triangles]) - min([x[1]['midpoint'][1] for x in triangles]),
                max([x[1]['midpoint'][2] for x in triangles]) - min([x[1]['midpoint'][2] for x in triangles])]))
            a = [x[0] for x in sorted(axis_len, key = lambda e: e[1], reverse = True)] # Axes longest to shortest
            sorted_triangles = sorted(triangles, key = lambda x: (x[1]['midpoint'][a[0]], x[1]['midpoint'][a[1]], x[1]['midpoint'][a[2]]))
            set1 = sorted_triangles[:len(sorted_triangles)//2]
            set2 = sorted_triangles[len(sorted_triangles)//2:]
            self.children = [BVHNode(set1, max_per_node), BVHNode(set2, max_per_node)]
        else:
            self.tri_indices = [x[0] for x in triangles]

# node is of type BVHNode class, run with root node
def add_node_to_BVH_list (node, node_list = [{}], i = 0): # i is current node
    node_list[i]['min'] = node.bounds[0]
    node_list[i]['max'] = node.bounds[1]
    if len(node.children) > 0:
        node_list[i]['start'] = len(node_list)
        node_list[i]['end'] = len(node_list) + len(node.children) - 1
        node_list[i]['triangles'] = []
        new_children_indices = []
        for j in range(len(node.children)):
            new_children_indices.append(len(node_list))
            node_list.append({})
        for j in range(len(node.children)):
            node_list = add_node_to_BVH_list(node.children[j], node_list, new_children_indices[j])
    else:
        node_list[i]['start'] = -1
        node_list[i]['end'] = -1
        node_list[i]['triangles'] = node.tri_indices
    return(node_list)

def triangle_struct_to_bvh_node_list (triangle_struct):
    return (add_node_to_BVH_list(BVHNode(list(enumerate(triangle_struct))), [{}], 0))

def build_mesh_section (mdl_filename, kuro_ver = 1):
    # Ordinarily we do not need to parse the original file, but in case we do, we only want to do it once
    has_parsed_original_file = False
    try:
        mesh_struct_metadata = read_struct_from_json(mdl_filename + "/mesh_info.json")
    except:
        print("{0}/mesh_info.json missing or unreadable, reading data from {0}.mdl instead...".format(mdl_filename))
        with open(mdl_filename + '.mdl', "rb") as f:
            mdl_data = f.read()
        mdl_data = decryptCLE(mdl_data)
        mesh_struct = obtain_mesh_data(mdl_data, obtain_material_data(mdl_data))
        has_parsed_original_file = True
        mesh_struct_metadata = mesh_struct["mesh_blocks"]
    output_buffer = struct.pack("<I", len(mesh_struct_metadata))
    material_list = []
    if kuro_ver > 1:
        prim_output_header = bytes()
        prim_output_data = bytes()
        prim_buffer_count = 0
    for i in range(len(mesh_struct_metadata)):
        mesh_block = bytes()
        meshes = 0 # Keep count of actual meshes imported, in case some have been deleted
        safe_filename = "".join([x if x not in "\\/:*?<>|" else "_" for x in mesh_struct_metadata[i]["name"]])
        if "nodes" in mesh_struct_metadata[i].keys():
            expected_vgmap = {mesh_struct_metadata[i]['nodes'][j]['name']:j for j in range(len(mesh_struct_metadata[i]['nodes']))}
        else:
            expected_vgmap = {}
        # Initialize bounding box - I have no idea why this works, but it does.
        bbox = {'min_x': True, 'min_y': True, 'min_z': True, 'max_x': False, 'max_y': False, 'max_z': False}
        for j in range(len(mesh_struct_metadata[i]["primitives"])):
            try:
                mesh_filename = mdl_filename + '/{0}_{1}_{2:02d}'.format(i, safe_filename, j)
                fmt = read_fmt(mesh_filename + '.fmt')
                ib = list(chain.from_iterable(read_ib(mesh_filename + '.ib', fmt)))
                vb = read_vb(mesh_filename + '.vb', fmt)
            except FileNotFoundError:
                if kuro_ver > 1:
                    print("Submesh {0} not found, generating an empty submesh...".format(mesh_filename))
                    if has_parsed_original_file == False:
                        with open(mdl_filename + '.mdl', "rb") as f:
                            mdl_data = f.read()
                        mdl_data = decryptCLE(mdl_data)
                        mesh_struct = obtain_mesh_data(mdl_data, obtain_material_data(mdl_data))
                        has_parsed_original_file = True
                    # Generate an empty submesh
                    fmt = make_fmt_struct(mesh_struct["mesh_buffers"][i][j])
                    ib = []
                    vb = mesh_struct["mesh_buffers"][i][j]['vb']
                else:
                    print("Submesh {0} not found, skipping...".format(mesh_filename))
                    continue
            print("Processing submesh {0}...".format(mesh_filename))
            # VGMap sanity check - Make sure the .vgmap file matches the actual skin node tree
            try:
                vgmap = read_struct_from_json(mesh_filename + '.vgmap')
                if not (all([True if x in expected_vgmap else False for x in vgmap])\
                    and all([expected_vgmap[x] == vgmap[x] for x in vgmap])):
                    print("Warning! {}.vgmap does not match the internal skin node tree!".format(mesh_filename))
                    rev_vgmap = {vgmap[k]:k for k in vgmap}
                    semantics = [x['SemanticName'] for x in vb]
                    if 'BLENDINDICES' in semantics and ('BLENDWEIGHT' in semantics or 'BLENDWEIGHTS' in semantics):
                        vg_index = semantics.index('BLENDINDICES')
                        if 'BLENDWEIGHT' in semantics:
                            wt_index = semantics.index('BLENDWEIGHT')
                        else:
                            wt_index = semantics.index('BLENDWEIGHTS')
                        indices = [x for y in vb[vg_index]['Buffer'] for x in y]
                        weights = [x for y in vb[wt_index]['Buffer'] for x in y]
                        true_indices = sorted(list(set([indices[k] for k in range(len(indices)) if weights[k] > 0.0])))
                        used_vg = [rev_vgmap[z] for z in true_indices]
                        if all([x in expected_vgmap.keys() for x in used_vg]):
                            print("VGMap appears compatible, attempting automatic remap...")
                            new_buffer = []
                            for k in range(len(vb[vg_index]['Buffer'])):
                                new_buffer.append([expected_vgmap[y] if y in expected_vgmap else 0 for y \
                                    in [rev_vgmap[z] for z in vb[vg_index]['Buffer'][k]]])
                            vb[vg_index]['Buffer'] = new_buffer
                        else:
                            print("VGMap incompatible with this mesh, automatic remap not possible.")
                            print("This model will likely have major animation distortions and may crash the game.")
                            input("Press Enter to continue.")
                    else:
                        pass # No weights, sanity check unnecessary
            except FileNotFoundError:
                if len(expected_vgmap) > 1:
                    print("{}.vgmap not found, vertex group sanity check skipped.".format(mesh_filename))
            if mesh_struct_metadata[i]["primitives"][j]["material"] in material_list:
                primitive_buffer = struct.pack("<I", material_list.index(mesh_struct_metadata[i]["primitives"][j]["material"]))
            else:
                primitive_buffer = struct.pack("<I", len(material_list))
                material_list.append(mesh_struct_metadata[i]["primitives"][j]["material"])
            num_texcoord = len([x for x in fmt["elements"] if x["SemanticName"] == "TEXCOORD"])
            primitive_buffer_elements = len(vb)+1 # vb+ib
            if kuro_ver <= 2 and num_texcoord in [1,2]: # Increase texcoord to 3, required by Kuro 1 (&2?)
                primitive_buffer_elements += 3 - num_texcoord
            if kuro_ver == 1:
                primitive_buffer += struct.pack("<I", primitive_buffer_elements)
            elif kuro_ver > 1:
                primitive_buffer += struct.pack("<2I", len(ib), mesh_struct_metadata[i]["primitives"][j]["unk"])
            texcoord_counter = 0
            for k in range(len(vb)):
                dxgi_format = fmt["elements"][k]["Format"].split('DXGI_FORMAT_')[-1]
                dxgi_format_split = dxgi_format.split('_')
                vec_type = dxgi_format_split[1]
                vec_format = re.findall("[0-9]+",dxgi_format_split[0])
                vec_first_color = dxgi_format_split[0][0] # Should be R in most cases, but will be B if format is B8G8R8A8_UNORM
                vec_elements = len(vec_format)
                vec_stride = int(int(vec_format[0]) * vec_elements / 8)
                reverse_colors = False # COLOR is BGR in Kuro 2
                eval_buffer_len = False # Normal and Tangent may need buffer length change
                match vb[k]["SemanticName"]:
                    case "POSITION":
                        type_int = 0
                        #Bounding box
                        bbox_min = [min(x[0] for x in vb[k]["Buffer"]),
                            min(x[1] for x in vb[k]["Buffer"]),
                            min(x[2] for x in vb[k]["Buffer"])]
                        bbox_max = [max(x[0] for x in vb[k]["Buffer"]),
                            max(x[1] for x in vb[k]["Buffer"]),
                            max(x[2] for x in vb[k]["Buffer"])]
                        bbox['min_x'] = min(bbox['min_x'], bbox_min[0])
                        bbox['min_y'] = min(bbox['min_y'], bbox_min[1])
                        bbox['min_z'] = min(bbox['min_z'], bbox_min[2])
                        bbox['max_x'] = max(bbox['max_x'], bbox_max[0])
                        bbox['max_y'] = max(bbox['max_y'], bbox_max[1])
                        bbox['max_z'] = max(bbox['max_z'], bbox_max[2])
                    case "NORMAL":
                        type_int = 1
                        eval_buffer_len = True
                    case "TANGENT":
                        type_int = 2
                        eval_buffer_len = True
                    case "COLOR":
                        type_int = 3
                        if kuro_ver == 1: # Forcing 32-bit float since Kuro 1 uses float
                            if vec_first_color == 'B':
                                reverse_colors = True
                            vec_type = 'FLOAT'
                            vec_stride = 4 * vec_elements
                        elif kuro_ver > 1: # Forcing 8-bit unorm since MDL v2 and up use 8-bit UNORM
                            if vec_first_color == 'R' and kuro_ver == 2: # Kuro 2 uses BGRA instead of RGBA
                                reverse_colors = True
                            elif vec_first_color == 'B' and not kuro_ver == 2:
                                reverse_colors = True
                            vec_type = 'UNORM'
                            vec_stride = vec_elements
                    case "TEXCOORD":
                        type_int = 4
                        texcoord_counter += 1 # This will be 1 for TEXCOORD0, 2 for TEXCOORD1, etc
                    case "BLENDWEIGHT" | "BLENDWEIGHTS":
                        type_int = 5
                    case "BLENDINDICES":
                        type_int = 6
                if reverse_colors == True and vec_elements == 4: # vec_elements should ALWAYS be 4 with COLOR, but just in case
                    current_buffer = [[x[2],x[1],x[0],x[3]] for x in vb[k]["Buffer"]]
                else:
                    current_buffer = vb[k]["Buffer"]
                if eval_buffer_len == True and type_int in [1,2]: # Only eval for Normal, Tangent
                    if kuro_ver <= 2 : # Forcing 32-bit float since Kuro 1 uses float
                        vec_type, vec_elements, vec_stride = 'FLOAT', 3, 12
                        current_buffer = [x[0:3] for x in vb[k]["Buffer"]]
                    elif kuro_ver > 2: # Forcing 8-bit VEC4
                        vec_type, vec_elements, vec_stride = 'SNORM', 4, 4
                        if len(vb[k]["Buffer"][0]) < 4:
                            current_buffer = [x[0:3]+[0.0]*(4-len(vb[k]["Buffer"][0])) for x in vb[k]["Buffer"]]
                        else:
                            current_buffer = vb[k]["Buffer"]
                match vec_type:
                    case "FLOAT":
                        element_type = 'f'
                        data_list = list(chain.from_iterable(current_buffer))
                    case "UINT":
                        element_type = 'I' # Assuming 32-bit since Kuro models all use 32-bit
                        data_list = list(chain.from_iterable(current_buffer))
                    case "UNORM":
                        element_type = 'B'
                        float_max = ((2**8)-1)
                        data_list = [int(round(min(max(x,0), 1) * float_max)) for x in list(chain.from_iterable(current_buffer))]
                    case "SNORM":
                        element_type = 'b'
                        float_max = ((2**(8-1))-1)
                        data_list = [int(round(min(max(x,-1), 1) * float_max)) for x in list(chain.from_iterable(current_buffer))]
                raw_buffer = struct.pack("<{0}{1}".format(len(data_list), element_type), *data_list)
                if kuro_ver == 1:
                    primitive_buffer += struct.pack("<3I", type_int, len(raw_buffer), vec_stride) + raw_buffer
                elif kuro_ver > 1:
                    prim_output_header += struct.pack("<5I", type_int, len(raw_buffer), vec_stride, i, j)
                    prim_output_data += raw_buffer
                    prim_buffer_count += 1
                # Minimum 3 texcoord, required by Kuro 1 (&2?)
                if kuro_ver <= 2 and type_int == 4 and num_texcoord in [1,2] and texcoord_counter == num_texcoord:
                    for l in range(3 - num_texcoord):
                        if kuro_ver == 1:
                            primitive_buffer += struct.pack("<3I", type_int, len(raw_buffer), vec_stride) + raw_buffer
                        elif kuro_ver > 1:
                            prim_output_header += struct.pack("<5I", type_int, len(raw_buffer), vec_stride, i, j)
                            prim_output_data += raw_buffer
                            prim_buffer_count += 1
            # After VB, need to add IB
            # Making assumptions here that it will always be in Rxx_UINT format, saves a bunch of code
            vec_stride = int(int(re.findall("[0-9]+",fmt["format"].split('DXGI_FORMAT_')[-1].split('_')[0])[0]) / 8)
            raw_ibuffer = struct.pack("<{0}I".format(len(ib), element_type), *ib)
            if kuro_ver == 1:
                primitive_buffer += struct.pack("<3I", 7, len(raw_ibuffer), vec_stride) + raw_ibuffer
            elif kuro_ver > 1:
                prim_output_header += struct.pack("<5I", 7, len(raw_ibuffer), vec_stride, i, j)
                prim_output_data += raw_ibuffer
                prim_buffer_count += 1
            mesh_block += primitive_buffer
            meshes += 1
        mesh_block = struct.pack("<I", meshes) + mesh_block
        if "nodes" in mesh_struct_metadata[i].keys():
            node_count = len(mesh_struct_metadata[i]["nodes"])
        else:
            node_count = 0
        node_block = struct.pack("<I", node_count)
        if node_count > 0:
            for j in range(node_count):
                node_block += make_pascal_string(mesh_struct_metadata[i]["nodes"][j]["name"])
                node_block += struct.pack("<16f", *list(chain.from_iterable(mesh_struct_metadata[i]["nodes"][j]["matrix"])))
        mesh_block += node_block
        if "data" in mesh_struct_metadata[i]["section2"]: # Legacy mode
            raw_section2 = struct.pack("<3fI3f4I", *mesh_struct_metadata[i]["section2"]["data"])
        else: # Decoded data
            collision_present = True
            try:
                mesh_filename = mdl_filename + '/{0}_{1}_collision'.format(i, safe_filename)
                fmt = read_fmt(mesh_filename + '.fmt')
                ib = read_ib(mesh_filename + '.ib', fmt)
                vb = read_vb(mesh_filename + '.vb', fmt)
            except FileNotFoundError:
                collision_present = False
            if collision_present:
                triangle_struct = generate_triangle_struct({'fmt': fmt, 'ib': ib, 'vb': vb})
                node_list = triangle_struct_to_bvh_node_list(triangle_struct)
                # I think I could just read the root node for the bounding box
                # because collision and visible meshes are separated, but just in case...
                bbox['min_x'] = min(bbox['min_x'], node_list[0]['min'][0])
                bbox['min_y'] = min(bbox['min_y'], node_list[0]['min'][1])
                bbox['min_z'] = min(bbox['min_z'], node_list[0]['min'][2])
                bbox['max_x'] = max(bbox['max_x'], node_list[0]['max'][0])
                bbox['max_y'] = max(bbox['max_y'], node_list[0]['max'][1])
                bbox['max_z'] = max(bbox['max_z'], node_list[0]['max'][2])
            raw_section2 = bytearray(struct.pack("<3fI3fI", bbox['min_x'], bbox['min_y'], bbox['min_z'],
                mesh_struct_metadata[i]["section2"]["unk0"],
                bbox['max_x'], bbox['max_y'],bbox['max_z'],
                mesh_struct_metadata[i]["section2"]["unk1"]))
            if collision_present:
                raw_section2.extend(struct.pack("<I", len(triangle_struct)))
                for j in range(len(triangle_struct)):
                    raw_section2.extend(struct.pack("<16f",
                        *[x for y in triangle_struct[j]['pos'] for x in y],
                        *triangle_struct[j]['nrm'],
                        *triangle_struct[j]['midpoint'],
                        triangle_struct[j]['radius']))
                raw_section2.extend(struct.pack("<I", len(node_list)))
                for j in range(len(node_list)):
                    raw_section2.extend(struct.pack("<6f2iI{}I".format(len(node_list[j]['triangles'])),
                        *node_list[j]['min'],
                        *node_list[j]['max'],
                        node_list[j]['start'],
                        node_list[j]['end'],
                        len(node_list[j]['triangles']),
                        *node_list[j]['triangles']))
            else:
                raw_section2.extend(struct.pack("<2I", 0, 0))
            raw_section2.extend(struct.pack("<I", mesh_struct_metadata[i]["section2"]["flags"]))
        section2_block = struct.pack("<I", len(raw_section2)) + bytes(raw_section2)
        mesh_block = make_pascal_string(mesh_struct_metadata[i]["name"]) + struct.pack("<I", len(mesh_block)) + mesh_block + section2_block
        output_buffer += mesh_block
        mesh_section_buffer = struct.pack("<2I", 1, len(output_buffer)) + output_buffer
        primitive_section_buffer = bytes()
        if kuro_ver > 1: # Primitives in a separate section #4
            primitive_output_buffer = struct.pack("<I", prim_buffer_count) + prim_output_header + prim_output_data
            primitive_section_buffer += struct.pack("<2I", 4, len(primitive_output_buffer)) + primitive_output_buffer
    return(mesh_section_buffer, primitive_section_buffer, material_list)

def process_mdl_import (mdl_file, change_compression = False, force_kuro_version = False):
    with open(mdl_file, "rb") as f:
        mdl_data = f.read()
    print("Processing {0}...".format(mdl_file))
    if mdl_data[0:4] in [b"F9BA", b"C9BA", b"D9BA"]:
        compressed = True
        mdl_data = decryptCLE(mdl_data)
    else:
        compressed = False
    if obtain_material_data(mdl_data) == False:
        print("Skipping {0} as it is not a model file.".format(mdl_file))
        return False
    kuro_ver = get_kuro_ver(mdl_data)
    try: # Attempt to get MDL version from JSON file, if this fails just use version number embedded in MDL
        json_kuro_ver = read_struct_from_json(mdl_file[:-4] + '/mdl_version.json')['mdl_version']
        if json_kuro_ver > 0 and json_kuro_ver <= kuro_ver:
            kuro_ver = json_kuro_ver
    except:
        print("{0}/mdl_version.json missing or unreadable, reading data from {0}.mdl instead...".format(mdl_file[:-4]))
    # Command line option overrides JSON file
    if force_kuro_version != False and force_kuro_version < kuro_ver:
        kuro_ver = force_kuro_version
    skeleton_data = build_skeleton_section(build_skeleton_struct_from_mdl(mdl_file[:-4]))
    mesh_data, primitive_data, material_list = build_mesh_section(mdl_file[:-4], kuro_ver = kuro_ver)
    material_data = build_material_section(mdl_file[:-4], material_list, kuro_ver)
    new_mdl_data = insert_model_data(mdl_data, skeleton_data, material_data, mesh_data, primitive_data, kuro_ver)
    # Instead of overwriting backups, it will just tag a number onto the end
    backup_suffix = ''
    if os.path.exists(mdl_file + '.bak' + backup_suffix):
        backup_suffix = '1'
        if os.path.exists(mdl_file + '.bak' + backup_suffix):
            while os.path.exists(mdl_file + '.bak' + backup_suffix):
                backup_suffix = str(int(backup_suffix) + 1)
        shutil.copy2(mdl_file, mdl_file + '.bak' + backup_suffix)
    else:
        shutil.copy2(mdl_file, mdl_file + '.bak')
    if (compressed == True and change_compression == False) or (compressed == False and change_compression == True):
        new_mdl_data = compressCLE(new_mdl_data)
    with open(mdl_file,'wb') as f:
        f.write(new_mdl_data)


# === /mnt/user-data/uploads/p3a_lib.py ===
# Script with functions to manipulate a P3A archive.
#
# GitHub eArmada8/kuro_dlc_tool


class p3a_class:
    def __init__ (self):
        self.f = None

    def read_entry (self, version):
        entry = {}
        entry['name'] = self.f.read(0x100).split(b'\x00')[0].decode('utf-8')
        entry['cmp_type'], entry['cmp_size'], entry['unc_size'], entry['offset']\
            = struct.unpack("<4Q", self.f.read(32))
        entry['cmp_hash'], = list(struct.unpack("Q", self.f.read(8)))
        if version >= 1200:
            entry['unc_hash'], = list(struct.unpack("Q", self.f.read(8)))
        return(entry)

    def read_dict (self):
        magic = self.f.read(8)
        if magic == b'P3ADICT\x00':
            dict_size, = struct.unpack("<Q", self.f.read(8))
            return(self.f.read(dict_size))
        else:
            return b''

    def read_p3a_toc (self):
        self.f.seek(0)
        magic = self.f.read(8)
        if magic == b'PH3ARCV\x00':
            header = {}
            header['flags'], header['version'], header['num_files'], header['p3a_hash']\
                = struct.unpack("<2I2Q", self.f.read(24))
            if header['version'] >= 1200:
                header['p3a_hash_2'], header['ext_header_size'], header['entry_size']\
                    = struct.unpack("<Q2I", self.f.read(16))
            entries = [self.read_entry(header['version']) for i in range(header['num_files'])]
            if header['flags'] & 1 == 1:
                p3a_dict = zstandard.ZstdCompressionDict(self.read_dict())
            else:
                p3a_dict = None
            return(header, entries, p3a_dict)
        else:
            input("Not P3A! Press Enter to continue")
            return []

    def read_file (self, entry, p3a_dict):
        self.f.seek(entry['offset'])
        cmp_data = self.f.read(entry['cmp_size'])
        if not xxhash.xxh64_intdigest(cmp_data) == entry['cmp_hash']:
            input("{} is corrupt, skipping.  Press Enter to continue.".format(entry['name']))
            return(b'')
        if entry['cmp_type'] == 0:
            unc_data = cmp_data
        elif entry['cmp_type'] == 1:
            unc_data = lz4.block.decompress(cmp_data, entry['unc_size'])
        elif entry['cmp_type'] == 2:
            decompressor = zstandard.ZstdDecompressor()
            unc_data = decompressor.decompress(cmp_data)
        elif entry['cmp_type'] == 3:
            decompressor = zstandard.ZstdDecompressor(dict_data = p3a_dict)
            unc_data = decompressor.decompress(cmp_data)
        else:
            input("{0} is unknown compression (type {1}), skipping.  Press Enter to continue.".format(entry['name'],
                entry['cmp_type']))
            unc_data = b''
        if len(unc_data) > 0 and 'unc_hash' in entry:
            if not xxhash.xxh64_intdigest(unc_data) == entry['unc_hash']:
                input("{} is corrupt, skipping.  Press Enter to continue.".format(entry['name']))
                return(b'')
        return(unc_data)

    # assigned_paths are specific names for each file, and are optional.
    # The key should match the file in file_list, and the value is the new name.
    # For example, if '/path/to/file1' is in file_list, then assigned_path could have
    # a key:value of '/path/to/file1':'/different/path/to/file2', and '/path/to/file1'
    # will be stored in the p3a as '/different/path/to/file2'.
    def p3a_pack_files (self, file_list, assigned_paths = {}, cmp_type = 1, p3a_ver = 1100):
        def return_256_len_str(string):
            assert len(string) <= 256
            return(string.encode('utf-8') + b'\x00'*(256-len(string)))
        p3a_flags = 0
        header_length = ({1100: 32, 1200: 48}[p3a_ver]
            + {1100: 296, 1200: 304}[p3a_ver] * len(file_list))
        file_data = []
        if cmp_type == 2:
            zstd_compressor = zstandard.ZstdCompressor(level = 12, write_checksum = True)
        if cmp_type == 3:
            p3a_flags = p3a_flags | 1
            dict_size = 112640
            print("Generating dictionary...")
            samples = [open(file, 'rb').read() for file in file_list]
            zdict = zstandard.train_dictionary(dict_size, samples)
            header_length += len(zdict.as_bytes()) + 16
            zstd_compressor = zstandard.ZstdCompressor(level = 12, dict_data = zdict, write_checksum = True)
        header_length = math.ceil(header_length / 64) * 64
        print("Compressing files...")
        with io.BytesIO() as f:
            toc = []
            for i in range(len(file_list)):
                with open(file_list[i], 'rb') as f2:
                    unc_data = f2.read()
                if cmp_type == 0:
                    cmp_data = unc_data
                elif cmp_type == 1:
                    cmp_data = lz4.block.compress(unc_data, mode = 'high_compression', store_size=False)
                elif cmp_type in [2,3]:
                    cmp_data = zstd_compressor.compress(unc_data)
                if file_list[i] in assigned_paths:
                    file_path = assigned_paths[file_list[i]]
                    file_path = "".join([x if x not in ":*?<>|" else "_" for x in file_path]) #Sanitize
                else:
                    file_path = file_list[i]
                file_entry = {'name': file_path, 'cmp_type': cmp_type, 'cmp_size': len(cmp_data),
                    'unc_size': len(unc_data), 'offset': f.tell() + header_length,
                    'cmp_hash': xxhash.xxh64_intdigest(cmp_data), 'unc_hash': xxhash.xxh64_intdigest(unc_data)}
                f.write(cmp_data)
                file_data.append(file_entry)
                if i < len(file_list) - 1:
                    while f.tell() % 64 > 0: #64-byte alignment
                        f.write(b'\x00')
            f.seek(0)
            file_block = f.read()
        header = b'PH3ARCV\x00' + struct.pack("<2IQ", p3a_flags, p3a_ver, len(file_list))
        header += struct.pack("<Q", xxhash.xxh64_intdigest(header))
        if p3a_ver >= 1200:
            ext_header = struct.pack("<2I", 16, {1200: 304}[p3a_ver])
            header += struct.pack("<Q", xxhash.xxh64_intdigest(ext_header)) + ext_header
        for i in range(len(file_data)):
            file_entry_block = return_256_len_str(file_data[i]['name'].lower()) # All file names in P3A are lower case
            file_entry_block += struct.pack("<5Q", file_data[i]['cmp_type'], file_data[i]['cmp_size'],
                file_data[i]['unc_size'], file_data[i]['offset'], file_data[i]['cmp_hash'])
            if p3a_ver >= 1200:
                file_entry_block += struct.pack("<Q", file_data[i]['unc_hash'])
            header += file_entry_block
        if cmp_type == 3:
            header += b'P3ADICT\x00' + struct.pack("<Q", len(zdict.as_bytes())) + zdict.as_bytes()
        if len(header) % 64 > 0: #64-byte alignment
            header += b''.join([b'\x00']*(64-(len(header) % 64)))
        return(header + file_block)

    def extract_all_files (self, p3a_archive, output_dir = None, overwrite = False):
        with open(p3a_archive,'rb') as self.f:
            headers, entries, p3a_dict = self.read_p3a_toc()
            if output_dir == None:
                output_dir = p3a_archive[:-4]
            for i in range(len(entries)):
                file_data = self.read_file(entries[i], p3a_dict)
                if len(file_data) > 0:
                    overwrite_files = overwrite
                    if os.path.exists(output_dir + '/' + entries[i]['name']) and (overwrite == False):
                        if str(input(output_dir + '/' + entries[i]['name'] + " exists! Overwrite? (y/N) ")).lower()[0:1] == 'y':
                            overwrite_files = True
                    if not os.path.exists(output_dir + '/' + entries[i]['name']) or overwrite_files == True:
                        if not os.path.exists(output_dir + '/' + os.path.dirname(entries[i]['name'])):
                            os.makedirs(output_dir + '/' + os.path.dirname(entries[i]['name']))
                        with open(output_dir + '/' + entries[i]['name'], 'wb') as f2:
                            f2.write(file_data)
        return

    # if output_name is None, then the name of the folder will be used.
    def pack_folder (self, folder_name, output_name = None, overwrite = False, cmp_type = 1, p3a_ver = 1100):
        if output_name == None:
            p3a_name = folder_name + '.p3a'
        else:
            p3a_name = "".join([x if x not in "\\/:*?<>|" else "_" for x in output_name]) #Sanitize
            if not p3a_name.lower()[-4:] == '.p3a':
                p3a_name = p3a_name + '.p3a'
        if os.path.exists(p3a_name) and overwrite == False:
            if str(input(p3a_name + " exists! Overwrite? (y/N) ")).lower()[0:1] == 'y':
                overwrite = True
        if (overwrite == True) or not os.path.exists(p3a_name):
            file_list = [x.replace('\\','/') for x in glob.glob('**/*',root_dir=folder_name,recursive=True)
                if not os.path.isdir(folder_name+'/'+x)]
            assigned_paths = {folder_name+'/'+x:x for x in file_list}
            p3a_data = self.p3a_pack_files (list(assigned_paths.keys()), assigned_paths,
                cmp_type = cmp_type, p3a_ver = p3a_ver)
            with open(p3a_name, 'wb') as f:
                f.write(p3a_data)
        return



# ===========================================================================
# END EMBEDDED LIBRARY CODE
# ===========================================================================


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG = logging.getLogger("kuro_mdl_rename")


class _StripAnsiFormatter(logging.Formatter):
    """Drop ANSI SGR escape sequences from the formatted message. Used for
    the log FILE always, and for the CONSOLE when --no-color is active."""
    def format(self, record):
        return _ANSI_ESCAPE_RE.sub("", super().format(record))


class _ConsoleColorFormatter(logging.Formatter):
    """Console formatter for the colored case.

    Two layers of color:
      * Anything inline in the message (added by us via _c() / _green() / etc.)
        passes through verbatim and renders via colorama.
      * Warnings and errors additionally get a level-color wrapper around the
        whole line (yellow / red) so they stand out even when the message has
        no inline color of its own. We do NOT wrap INFO messages -- the
        inline ANSI we put in them would get cut off at the inner reset.
    """
    LEVEL_COLORS = {
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record):
        base = super().format(record)
        color = self.LEVEL_COLORS.get(record.levelno)
        if color:
            return color + base + Style.RESET_ALL
        return base


def setup_logging(log_path, verbose=False, no_color=False):
    """Configure the package logger to write a plain log file plus a
    (colored, when possible) console."""
    global _COLOR_ENABLED
    _COLOR_ENABLED = _COLORAMA_OK and not no_color

    LOG.setLevel(logging.DEBUG if verbose else logging.INFO)
    LOG.handlers.clear()

    # Log FILE: always plain text, no escapes ever.
    file_h = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(_StripAnsiFormatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    LOG.addHandler(file_h)

    # Console.
    console_h = logging.StreamHandler(sys.stdout)
    console_h.setLevel(logging.DEBUG if verbose else logging.INFO)
    if _COLOR_ENABLED:
        console_h.setFormatter(_ConsoleColorFormatter("%(message)s"))
    else:
        console_h.setFormatter(_StripAnsiFormatter("%(message)s"))
    LOG.addHandler(console_h)

    LOG.propagate = False


# Silence the underlying scripts' stray `print()` calls by routing stdout
# through a thin wrapper while still letting our own logger print normally.
# We keep their prints for verbose/debug visibility but tag them so they are
# distinguishable from the wrapper's own output.
class _PrintInterceptor:
    def __init__(self, real_stdout):
        self._real = real_stdout
        self._buf = ""

    def write(self, s):
        if not s:
            return
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.rstrip()
            if line:
                LOG.debug("[lib] %s", line)

    def flush(self):
        if self._buf.strip():
            LOG.debug("[lib] %s", self._buf.strip())
        self._buf = ""


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------
def _is_p3a_file(path):
    """Return True iff `path` is an existing file with a .p3a extension."""
    return os.path.isfile(path) and path.lower().endswith(".p3a")


def extract_p3a_archive(p3a_path, target_dir):
    """Extract `p3a_path` into `target_dir`. Creates target_dir if missing.
    Uses the embedded p3a_class. Verbose output is captured by the print
    interceptor and routed to LOG.debug."""
    os.makedirs(target_dir, exist_ok=True)
    old_stdout = sys.stdout
    try:
        sys.stdout = _PrintInterceptor(old_stdout)
        archive = p3a_class()
        archive.extract_all_files(p3a_path, output_dir=target_dir, overwrite=True)
    finally:
        sys.stdout = old_stdout


def pack_directory_to_p3a(dir_path, p3a_path, cmp_type=1, p3a_ver=1100):
    """Pack the contents of `dir_path` into a P3A archive at `p3a_path`.
    cmp_type: 0=none, 1=lz4, 2=zstd, 3=zstd-dict. p3a_ver: 1100 or 1200.

    Workaround: p3a_class.pack_folder() sanitises the output_name by
    replacing slashes with underscores, which mangles absolute paths. To
    avoid this we chdir into the parent of dir_path, call pack_folder with
    only the basename, then move the resulting archive to its real target
    location if necessary."""
    abs_dir = os.path.abspath(dir_path)
    abs_p3a = os.path.abspath(p3a_path)
    parent_of_dir = os.path.dirname(abs_dir)
    folder_basename = os.path.basename(abs_dir)
    target_basename = os.path.basename(abs_p3a)

    # Cleanup any pre-existing artefact at the FINAL destination AND at the
    # path pack_folder will write to (in parent_of_dir/target_basename).
    if os.path.exists(abs_p3a):
        os.remove(abs_p3a)
    pack_intermediate = os.path.join(parent_of_dir, target_basename)
    if os.path.exists(pack_intermediate) and pack_intermediate != abs_p3a:
        os.remove(pack_intermediate)

    os.makedirs(os.path.dirname(abs_p3a) or ".", exist_ok=True)

    old_cwd = os.getcwd()
    old_stdout = sys.stdout
    try:
        sys.stdout = _PrintInterceptor(old_stdout)
        os.chdir(parent_of_dir)
        archive = p3a_class()
        archive.pack_folder(
            folder_basename,
            output_name=target_basename,
            overwrite=True,
            cmp_type=cmp_type,
            p3a_ver=p3a_ver,
        )
    finally:
        sys.stdout = old_stdout
        os.chdir(old_cwd)

    # Move from <parent_of_dir>/<target_basename> to abs_p3a, but only if
    # the two paths differ (when the workdir lives in the same directory as
    # the target archive, no move is needed).
    if os.path.normcase(os.path.abspath(pack_intermediate)) != os.path.normcase(abs_p3a):
        if os.path.exists(abs_p3a):
            os.remove(abs_p3a)
        shutil.move(pack_intermediate, abs_p3a)


def resolve_project_root(user_path):
    """Resolve `user_path` to a project root that contains an `asset/` folder.

    Accepts any of:
      - The project root itself (folder containing `asset/`).
      - The `asset/` folder directly (we walk up one level).
      - Anything inside `asset/` (e.g. `asset/common/model`) -- we walk up
        until we find an ancestor that contains `asset/`.
      - A folder that has exactly one nested subfolder which itself contains
        `asset/` (the common zip-extraction layout `proj/proj/asset/...`).
      - The current working directory (when called with `.` or no argument).
      - A .p3a archive -- handled separately by the caller (this function
        rejects it; see _is_p3a_file).

    Returns (resolved_root, info_message) so the caller can log the chosen
    root after logging is set up. info_message is "" when the input was
    already the project root.
    """
    p = os.path.abspath(user_path)
    if not os.path.isdir(p):
        raise FileNotFoundError(
            "project path does not exist or is not a directory: {}".format(p)
        )

    # Case 1: direct hit -- this folder contains an `asset/` subdirectory.
    if os.path.isdir(os.path.join(p, "asset")):
        return p, ""

    # Case 2: the path is at or inside an `asset/` folder. Walk up the parent
    # chain looking for the first ancestor whose name is "asset" (case-
    # insensitive) and whose parent therefore IS the project root.
    cur = p
    while True:
        parent = os.path.dirname(cur)
        if not parent or parent == cur:
            break
        if os.path.basename(cur).lower() == "asset" and \
           os.path.isdir(os.path.join(parent, "asset")):
            return parent, ("Resolved project root by walking up from {} "
                            "to {}".format(p, parent))
        cur = parent

    # Case 3: zip-extraction layout -- exactly one nested subfolder that
    # itself contains `asset/`. Handles `pyrixiaSFW/pyrixiaSFW/asset/...`.
    children = [c for c in os.listdir(p) if os.path.isdir(os.path.join(p, c))]
    if len(children) == 1:
        nested = os.path.join(p, children[0])
        if os.path.isdir(os.path.join(nested, "asset")):
            return nested, "Descending into nested project root: {}".format(nested)

    # Last resort: produce a helpful error that lists what we DID find in
    # the directory, so the user can spot a typo or a misplaced file.
    try:
        entries = sorted(os.listdir(p))
    except OSError:
        entries = []
    if entries:
        listing = []
        for name in entries[:20]:  # cap to keep error readable
            full = os.path.join(p, name)
            tag = "<DIR>" if os.path.isdir(full) else "     "
            listing.append("    {}  {}".format(tag, name))
        if len(entries) > 20:
            listing.append("    ... ({} more entries)".format(len(entries) - 20))
        listing_text = "\n".join(listing)
    else:
        listing_text = "    (directory is empty)"

    raise FileNotFoundError(
        "could not find anything to process in {p!r}.\n"
        "I looked for:\n"
        "  - an 'asset/' folder (an extracted Kuro project tree), or\n"
        "  - one or more '.p3a' files (packed Kuro archives).\n"
        "Neither was found.\n"
        "\n"
        "What's actually in this directory:\n"
        "{listing}\n"
        "\n"
        "Hint: cd into a folder that contains 'asset/' or a '.p3a' file, or "
        "pass the path to one as an argument:\n"
        "    py kuro_mdl_rename.py C:\\path\\to\\project\n"
        "    py kuro_mdl_rename.py C:\\path\\to\\archive.p3a".format(
            p=p, listing=listing_text)
    )


def find_mdls(project_root):
    model_dir = os.path.join(project_root, "asset", "common", "model")
    if not os.path.isdir(model_dir):
        return []
    out = []
    for name in sorted(os.listdir(model_dir)):
        if name.lower().endswith(".mdl"):
            out.append(os.path.join(model_dir, name))
    return out


def index_image_dir(project_root):
    """Return (image_dir, {lower_filename: actual_filename})."""
    img_dir = os.path.join(project_root, "asset", "dx11", "image")
    if not os.path.isdir(img_dir):
        return img_dir, {}
    idx = {}
    for name in os.listdir(img_dir):
        full = os.path.join(img_dir, name)
        if not os.path.isfile(full):
            continue
        if name.lower() == "desktop.ini":
            continue
        idx[name.lower()] = name
    return img_dir, idx


# ---------------------------------------------------------------------------
# Multi-archive game directory index (for --game mode)
# ---------------------------------------------------------------------------
# A Trails / ED9 game directory holds the asset tree split across many .p3a
# archives at its top level (asset_common_model.p3a, asset_common_model_info.p3a,
# asset_image.p3a, asset_image_eng.p3a, ...). The exact filenames vary per
# game version, so we identify the relevant archives by content -- we read
# each .p3a's TOC and keep the ones that contribute entries under
# asset/common/model/, asset/common/model_info/, or asset/dx11/image/.
#
# We never extract eagerly: the TOC tells us where each entry lives and
# how to read its bytes; payloads are only extracted when the renaming
# pipeline actually needs them, into a transient scratch directory.
# ---------------------------------------------------------------------------
ASSET_PREFIX_MODEL      = "asset/common/model/"
ASSET_PREFIX_MODEL_INFO = "asset/common/model_info/"
ASSET_PREFIX_IMAGE      = "asset/dx11/image/"


class P3AGameDirIndex:
    """Lazy multi-archive index of a Trails / ED9 game directory.

    On construction, scans every '*.p3a' file directly inside `game_dir`
    (top-level only -- subdirectories like 'mods/' are NOT scanned, since
    they are typically downstream mods rather than base assets), reads
    each archive's TOC, and merges every entry whose path lives under one
    of the three asset prefixes we care about (model / model_info / image)
    into a single flat dict.

    Conflict policy: when the same entry path is present in more than one
    .p3a, the LAST archive read wins (alphabetical by filename). This is
    a deterministic but ad-hoc choice; the engine's actual load order is
    unknown to this script. A debug log line is emitted for every
    overridden entry.

    No payload bytes are read at scan time -- only the TOC and (for
    zstd-dict archives) the shared dictionary.
    """

    # File patterns we deliberately skip even before touching them, because
    # they are obviously not base-asset archives in any game version. This
    # is a heuristic short-circuit: anything not skipped here is opened and
    # tested by content.
    _SKIP_DIRS = ("mods",)  # don't recurse into these subdirs

    def __init__(self, game_dir, progress=None):
        self.game_dir = os.path.abspath(game_dir)
        # rel_path (lowercased, forward-slashed) -> (p3a_path, entry, p3a_dict)
        self.entries = {}
        # p3a_path -> (header, p3a_dict, [entries]) -- kept so debug code
        # can introspect; not used at runtime.
        self.archives = {}
        # archives that contributed at least one asset/* entry to the index
        self.contributing_p3a = []
        self._scan(progress)

    def _candidate_archives(self):
        """Return sorted list of *.p3a files at the game-dir top level."""
        out = []
        try:
            names = os.listdir(self.game_dir)
        except OSError:
            return []
        for n in names:
            full = os.path.join(self.game_dir, n)
            if os.path.isfile(full) and n.lower().endswith(".p3a"):
                out.append(full)
        out.sort(key=lambda p: os.path.basename(p).lower())
        return out

    def _scan(self, progress):
        candidates = self._candidate_archives()
        for i, p3a_path in enumerate(candidates, 1):
            if progress is not None:
                progress(i, len(candidates), p3a_path)
            try:
                with open(p3a_path, "rb") as fh:
                    archive = p3a_class()
                    archive.f = fh
                    header, entries, p3a_dict = archive.read_p3a_toc()
                if not entries:
                    continue
            except Exception as e:
                LOG.warning("[game] could not read %s: %s",
                            os.path.basename(p3a_path), e)
                continue

            self.archives[p3a_path] = (header, p3a_dict, entries)
            contributed = 0
            for ent in entries:
                # P3A stores names with forward slashes in lowercase; be
                # defensive in case some archive deviates.
                name = ent["name"].replace("\\", "/").lower()
                if not (name.startswith(ASSET_PREFIX_MODEL)
                        or name.startswith(ASSET_PREFIX_MODEL_INFO)
                        or name.startswith(ASSET_PREFIX_IMAGE)):
                    continue
                if name in self.entries:
                    prev_path = self.entries[name][0]
                    LOG.debug("[game] entry %s overridden: %s -> %s",
                              name, os.path.basename(prev_path),
                              os.path.basename(p3a_path))
                self.entries[name] = (p3a_path, ent, p3a_dict)
                contributed += 1
            if contributed:
                self.contributing_p3a.append(p3a_path)

    # --- listing helpers (no extraction) ---

    def list_mdls(self):
        """Return sorted list of asset/common/model/<basename>.mdl entries
        (top-level only -- entries in nested subdirectories are ignored,
        matching the on-disk find_mdls() contract)."""
        out = []
        for name in self.entries:
            if not name.startswith(ASSET_PREFIX_MODEL):
                continue
            tail = name[len(ASSET_PREFIX_MODEL):]
            if "/" in tail:
                continue  # nested subfolder; ignore
            if tail.endswith(".mdl"):
                out.append(name)
        out.sort()
        return out

    def list_mi_index(self):
        """Return {lower_basename_no_ext: rel_path} for asset/common/model_info/*.mi
        so the caller can look up an .mi side-car by its mdl basename."""
        idx = {}
        for name in self.entries:
            if not name.startswith(ASSET_PREFIX_MODEL_INFO):
                continue
            tail = name[len(ASSET_PREFIX_MODEL_INFO):]
            if "/" in tail or not tail.endswith(".mi"):
                continue
            stem = tail[:-3]
            idx[stem.lower()] = name
        return idx

    def list_image_index(self):
        """Return {lower_filename: lower_filename} for asset/dx11/image/*.

        The mapping mirrors the on-disk index_image_dir() format. P3A names
        are stored in lowercase, so the 'actual filename' is also lower.
        """
        idx = {}
        for name in self.entries:
            if not name.startswith(ASSET_PREFIX_IMAGE):
                continue
            tail = name[len(ASSET_PREFIX_IMAGE):]
            if "/" in tail:
                continue
            if tail == "desktop.ini":
                continue
            idx[tail.lower()] = tail
        return idx

    # --- extraction (lazy, single file) ---

    def extract(self, rel_path, target_path):
        """Extract one virtual file to `target_path` on disk. Creates parent
        directories. Raises FileNotFoundError if the entry isn't in the index."""
        key = rel_path.replace("\\", "/").lower()
        record = self.entries.get(key)
        if record is None:
            raise FileNotFoundError(rel_path)
        p3a_path, entry, p3a_dict = record
        os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
        with open(p3a_path, "rb") as fh:
            archive = p3a_class()
            archive.f = fh
            data = archive.read_file(entry, p3a_dict)
        if not data:
            raise IOError(
                "extraction of {} from {} returned empty data (corrupt?)".format(
                    rel_path, os.path.basename(p3a_path)))
        with open(target_path, "wb") as fh2:
            fh2.write(data)


def _materialize_game_subset(game_idx, selected_mdl_rel_paths, scratch_dir):
    """Materialize the .mdl files (and their .mi side-cars) for `selected_mdl_rel_paths`
    into `scratch_dir`, preserving the asset/ tree structure. Returns a tuple
    (mdl_count, mi_count, missing_mi_basenames).

    Image references are NOT materialized here -- the caller resolves them
    via build_plan() once the mdls are on disk, then calls back into
    game_idx.extract() for each matched image. This avoids materialising
    images that the mdl doesn't actually reference.
    """
    mi_index = game_idx.list_mi_index()
    mdl_count = 0
    mi_count = 0
    missing_mi = []
    for rel in selected_mdl_rel_paths:
        target = os.path.join(scratch_dir, rel.replace("/", os.sep))
        try:
            game_idx.extract(rel, target)
            mdl_count += 1
        except (FileNotFoundError, IOError) as e:
            LOG.warning("[game] failed to extract %s: %s", rel, e)
            continue
        # Compose .mi side-car lookup key: basename of the mdl, no ext.
        base = os.path.splitext(os.path.basename(rel))[0]
        mi_rel = mi_index.get(base.lower())
        if mi_rel is None:
            missing_mi.append(base)
            continue
        mi_target = os.path.join(scratch_dir, mi_rel.replace("/", os.sep))
        try:
            game_idx.extract(mi_rel, mi_target)
            mi_count += 1
        except (FileNotFoundError, IOError) as e:
            LOG.warning("[game] failed to extract mi side-car %s: %s", mi_rel, e)
    return mdl_count, mi_count, missing_mi


def _materialize_plan_images(game_idx, plans, scratch_image_dir):
    """For every image referenced in any plan's image_renames map, extract
    the original from the game index into `scratch_image_dir`. Returns the
    count of images extracted. Skips images already on disk."""
    os.makedirs(scratch_image_dir, exist_ok=True)
    needed = set()
    for plan in plans:
        for orig in plan.image_renames:
            needed.add(orig)
    n = 0
    for img_name in sorted(needed):
        target = os.path.join(scratch_image_dir, img_name)
        if os.path.exists(target):
            continue
        rel = ASSET_PREFIX_IMAGE + img_name.lower()
        try:
            game_idx.extract(rel, target)
            n += 1
        except (FileNotFoundError, IOError) as e:
            LOG.warning("[game] failed to extract image %s: %s", img_name, e)
    return n


# ---------------------------------------------------------------------------
# Per-MDL plan
# ---------------------------------------------------------------------------
class MdlPlan:
    """A plan for how to rename one .mdl and all of its referenced images.

    Attributes
    ----------
    src_mdl : str           absolute path to source .mdl
    src_basename : str      e.g. 'chr5113'
    new_basename : str      e.g. 'mod_chr5113'
    new_mdl_relpath : str   path inside the output project tree
    image_renames : dict    {original_disk_filename: new_filename} for matched images
    missing_refs : list     image_list entries that have no matching disk file
    src_mi : str|None       path to source .mi file (or None)
    new_mi_relpath : str    relative path of the renamed .mi inside the output
    """
    def __init__(self, src_mdl, src_basename, new_basename, new_mdl_relpath,
                 image_renames, missing_refs, src_mi, new_mi_relpath):
        self.src_mdl = src_mdl
        self.src_basename = src_basename
        self.new_basename = new_basename
        self.new_mdl_relpath = new_mdl_relpath
        self.image_renames = image_renames
        self.missing_refs = missing_refs
        self.src_mi = src_mi
        self.new_mi_relpath = new_mi_relpath


def _mdl_image_list(mdl_path):
    """Return the set of image references (with .dds extension) for an mdl,
    using the embedded library functions. Reads bytes only, writes nothing."""
    with open(mdl_path, "rb") as f:
        raw = f.read()
    raw = decryptCLE(raw)
    mat = obtain_material_data(raw)
    if mat is False or mat is None:
        return None  # not an mdl
    # Same logic as in the export's process_mdl() to compose image_list.json.
    refs = sorted({tex["texture_image_name"] + ".dds"
                   for m in mat for tex in m["textures"]})
    return refs


def make_image_rename(orig_disk_filename, new_mdl_basename):
    """Compute the renamed image filename for a given mdl context.

    The new mdl basename is used as the per-mdl prefix, which guarantees
    uniqueness when several mdls reference the same source image.
    """
    return "{0}_{1}".format(new_mdl_basename, orig_disk_filename)


def _index_model_info_dir(project_root):
    """Return {lower(basename_no_ext): actual_filename} for the model_info
    directory so we can find an .mi side-car case-insensitively."""
    mi_dir = os.path.join(project_root, "asset", "common", "model_info")
    if not os.path.isdir(mi_dir):
        return mi_dir, {}
    idx = {}
    for name in os.listdir(mi_dir):
        full = os.path.join(mi_dir, name)
        if not os.path.isfile(full):
            continue
        if name.lower().endswith(".mi"):
            stem = name[:-3]
            idx[stem.lower()] = name
    return mi_dir, idx


def build_plan(project_root, mdl_paths, image_index, prefix, suffix):
    plans = []
    mi_dir, mi_index = _index_model_info_dir(project_root)
    for mdl in mdl_paths:
        base_with_ext = os.path.basename(mdl)
        base = base_with_ext[:-4]  # strip .mdl
        new_base = "{0}{1}{2}".format(prefix, base, suffix)
        new_mdl_relpath = os.path.join("asset", "common", "model", new_base + ".mdl")

        try:
            refs = _mdl_image_list(mdl)
        except Exception as e:
            LOG.error("Failed to parse %s: %s", mdl, e)
            continue
        if refs is None:
            LOG.warning("Skipping %s (does not look like an mdl).", base_with_ext)
            continue

        image_renames = {}
        missing_refs = []
        for ref in refs:
            actual = image_index.get(ref.lower())
            if actual is None:
                missing_refs.append(ref)
            else:
                image_renames[actual] = make_image_rename(actual, new_base)

        # Optional .mi side-car. Look it up case-insensitively so a Linux
        # filesystem with mixed casing (e.g. CHR5113.MI vs chr5113.mdl)
        # still finds the side-car. A missing .mi is not an error -- some
        # models genuinely have none.
        actual_mi_filename = mi_index.get(base.lower())
        if actual_mi_filename is None:
            src_mi = None
            new_mi_relpath = None
        else:
            src_mi = os.path.join(mi_dir, actual_mi_filename)
            new_mi_relpath = os.path.join("asset", "common", "model_info", new_base + ".mi")

        plans.append(MdlPlan(
            src_mdl=mdl,
            src_basename=base,
            new_basename=new_base,
            new_mdl_relpath=new_mdl_relpath,
            image_renames=image_renames,
            missing_refs=missing_refs,
            src_mi=src_mi,
            new_mi_relpath=new_mi_relpath,
        ))
    return plans


# ---------------------------------------------------------------------------
# Plan reporting
# ---------------------------------------------------------------------------
def _name_arrow(src_name, new_name):
    """Return a visually distinct '<src>  -->  <new>' string. Source is dim,
    arrow is dim, new name is green when changed and yellow (kept) when
    equal to the source."""
    arrow = _dim("-->")
    if src_name == new_name:
        new_disp = _yellow(new_name) + _dim(" (kept)")
    else:
        new_disp = _green(new_name)
    return "{}  {}  {}".format(_dim(src_name), arrow, new_disp)


def report_plans(plans, src_image_dir, src_image_index, output_root, dry_run,
                 keep=False, kept_files=()):
    title = "DRY-RUN" if dry_run else "APPLY"
    title_color = _cyan if dry_run else _green
    LOG.info("")
    LOG.info(_bold(_cyan("=" * 72)))
    LOG.info(_bold(title_color("PLAN OVERVIEW ({})".format(title))))
    LOG.info(_bold(_cyan("=" * 72)))

    # Determine which disk images will be copied (as how many copies).
    referenced_disk_files = set()
    for p in plans:
        for orig in p.image_renames.keys():
            referenced_disk_files.add(orig)

    unreferenced_disk_files = [
        name for low, name in src_image_index.items() if name not in referenced_disk_files
    ]

    total_image_copies = sum(len(p.image_renames) for p in plans)
    total_missing = sum(len(p.missing_refs) for p in plans)
    total_mi_missing = sum(1 for p in plans if not p.src_mi)

    LOG.info("Output project root : %s", _cyan(output_root))
    LOG.info("Models to process   : %s", _bold(str(len(plans))))
    LOG.info("Images on disk      : %s", _bold(str(len(src_image_index))))
    LOG.info("  - referenced      : %s", _green(str(len(referenced_disk_files))))
    if keep:
        LOG.info("  - NOT referenced  : %s %s",
                 _yellow(str(len(unreferenced_disk_files))),
                 _dim("(will be copied verbatim, --keep)"))
    else:
        LOG.info("  - NOT referenced  : %s %s",
                 _yellow(str(len(unreferenced_disk_files))),
                 _dim("(will not be copied)"))
    LOG.info("Image copies to make: %s %s",
             _bold(_green(str(total_image_copies))),
             _dim("(each model gets its own copy)"))
    LOG.info("Missing references  : %s %s",
             _yellow(str(total_missing)),
             _dim("(left as-is in JSONs)"))
    if keep:
        LOG.info("Files to copy verbatim (--keep): %s",
                 _bold(_green(str(len(kept_files)))))
    if total_mi_missing:
        LOG.warning("Models without a .mi side-car: %d (continuing without it)",
                    total_mi_missing)
    LOG.info("")

    for i, p in enumerate(plans, 1):
        # Per-mdl header banner -- keeps each model's section visually
        # self-contained instead of running together.
        header = "MODEL [{}/{}]  {}".format(i, len(plans), p.src_basename)
        LOG.info("")
        LOG.info(_bold(_magenta("=" * 24 + " " + header + " " + "=" * (max(2, 47 - len(header))))))
        LOG.info("%s : %s", _bold("MDL"), _name_arrow(p.src_basename + ".mdl",
                                                       p.new_basename + ".mdl"))
        if p.src_mi:
            LOG.info("%s  : %s", _bold("MI"), _name_arrow(p.src_basename + ".mi",
                                                           p.new_basename + ".mi"))
        else:
            LOG.warning("MI   : %s.mi  -->  (NOT FOUND in source - skipping, this is OK if "
                        "the model genuinely has no .mi)", p.src_basename)
        LOG.info("Referenced images : %s  (matched on disk: %s, NOT on disk: %s)",
                 _bold(str(len(p.image_renames) + len(p.missing_refs))),
                 _green(str(len(p.image_renames))),
                 _yellow(str(len(p.missing_refs))))

        # Always show the matched rename map -- this is the headline output
        # of the plan and the user shouldn't need --verbose to see it.
        if p.image_renames:
            LOG.info("  %s", _bold("rename map (matched images, this model only):"))
            for orig, new in sorted(p.image_renames.items()):
                LOG.info("    %s", _name_arrow(orig, new))
        if p.missing_refs:
            LOG.info("  %s", _bold("missing references (left untouched in JSONs):"))
            for r in p.missing_refs:
                LOG.info("    %s", _yellow(r))

    # Bottom of the report. With --keep we list ALL files that would be
    # copied verbatim into the output (unreferenced images + anything else
    # in the source tree that the renaming pipeline doesn't touch). Without
    # --keep we keep the existing "what would be skipped" listing for the
    # unreferenced images only.
    if keep:
        if kept_files:
            LOG.info("")
            LOG.info(_dim("-" * 72))
            LOG.info("%s",
                     _bold("Files to be copied verbatim into the output (--keep):"))
            for rel in kept_files:
                LOG.info("    %s", _dim(rel))
    else:
        if unreferenced_disk_files:
            LOG.info("")
            LOG.info(_dim("-" * 72))
            LOG.info("%s",
                     _bold("Images on disk that no MDL references (will NOT be copied):"))
            for name in sorted(unreferenced_disk_files):
                LOG.info("    %s", _dim(name))

    LOG.info(_bold(_cyan("=" * 72)))


# ---------------------------------------------------------------------------
# Apply (the only side-effect path)
# ---------------------------------------------------------------------------
def _patch_image_list_json(json_path, image_renames, plan_label):
    """Rewrite image_list.json so matched entries use their new filenames.

    image_renames keys are the *actual on-disk filenames*. Entries in the
    JSON typically have a different case (e.g. UPPERCASE) -- we match
    case-insensitively and preserve unmatched entries verbatim.
    """
    with open(json_path, "rb") as f:
        data = json.loads(f.read().decode("utf-8"))
    # Build a lookup keyed by lower(disk-name) -> new disk name
    lookup = {orig.lower(): new for orig, new in image_renames.items()}
    out = []
    changed = 0
    for entry in data:
        repl = lookup.get(entry.lower())
        if repl is None:
            out.append(entry)  # leave untouched
        else:
            out.append(repl)
            changed += 1
    with open(json_path, "wb") as f:
        f.write(json.dumps(out, indent=4).encode("utf-8"))
    LOG.debug("[%s] image_list.json: %d entries rewritten", plan_label, changed)


def _patch_material_info_json(json_path, image_renames, plan_label):
    """Rewrite material_info.json. texture_image_name has NO extension here,
    so we strip the extension off our rename map for the comparison and
    write back the renamed name *also* without extension."""
    with open(json_path, "rb") as f:
        data = json.loads(f.read().decode("utf-8"))
    # Map: lower(stem) -> new stem (no extension)
    stem_lookup = {}
    for orig, new in image_renames.items():
        orig_stem = os.path.splitext(orig)[0]
        new_stem = os.path.splitext(new)[0]
        stem_lookup[orig_stem.lower()] = new_stem
    changed = 0
    for mat in data:
        for tex in mat.get("textures", []):
            name = tex.get("texture_image_name")
            if name is None:
                continue
            repl = stem_lookup.get(name.lower())
            if repl is not None:
                tex["texture_image_name"] = repl
                changed += 1
    with open(json_path, "wb") as f:
        f.write(json.dumps(data, indent=4).encode("utf-8"))
    LOG.debug("[%s] material_info.json: %d texture refs rewritten", plan_label, changed)


def _normcase_abs(p):
    return os.path.normcase(os.path.abspath(p))


def build_consumed_set(plans, src_image_dir, protected_image_filenames=None):
    """Return the set of absolute, case-normalised source paths whose content
    is already represented in the output by a renamed counterpart -- the
    source mdls (renamed), source mis (renamed), and source images that
    were matched and per-mdl-renamed.

    `protected_image_filenames` is an optional iterable of original on-disk
    image filenames (no path) that must NOT be marked consumed even if they
    appear in some plan's image_renames. This is used when the run filters
    the .mdl set to a subset and --keep is on: images referenced by the
    SKIPPED .mdl files (which are copied verbatim by --keep) must remain
    available in the output under their ORIGINAL names, so we leave them
    out of the consumed set so enumerate_kept_files() picks them up.
    """
    consumed = set()
    protected = {n.lower() for n in (protected_image_filenames or [])}
    for plan in plans:
        consumed.add(_normcase_abs(plan.src_mdl))
        if plan.src_mi:
            consumed.add(_normcase_abs(plan.src_mi))
        for orig in plan.image_renames:
            if orig.lower() in protected:
                continue
            consumed.add(_normcase_abs(os.path.join(src_image_dir, orig)))
    return consumed


def enumerate_kept_files(src_project, consumed_abs, extra_skip_abs=()):
    """Walk src_project and return the sorted list of relative paths whose
    full source location is NOT in `consumed_abs` and not in
    `extra_skip_abs`. These are the files --keep would copy verbatim."""
    skip = set(consumed_abs) | {_normcase_abs(p) for p in extra_skip_abs if p}
    out = []
    for root, dirs, files in os.walk(src_project):
        for fname in files:
            full = os.path.join(root, fname)
            if _normcase_abs(full) in skip:
                continue
            out.append(os.path.relpath(full, src_project))
    out.sort()
    return out


def copy_kept_files(src_project, output_root, kept_relpaths):
    """Copy each path in kept_relpaths from src_project to output_root,
    preserving the directory structure. Returns the count of files copied."""
    n = 0
    for rel in kept_relpaths:
        src = os.path.join(src_project, rel)
        dst = os.path.join(output_root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        LOG.info("[keep] %s/%s", _dim("verbatim"), rel)
        n += 1
    return n


def apply_plan(plan, source_root, output_root, src_image_dir):
    """Execute a single MdlPlan."""
    label = plan.new_basename

    # 1. Make sure output dirs exist.
    out_model_dir = os.path.join(output_root, "asset", "common", "model")
    out_image_dir = os.path.join(output_root, "asset", "dx11", "image")
    out_mi_dir    = os.path.join(output_root, "asset", "common", "model_info")
    os.makedirs(out_model_dir, exist_ok=True)
    os.makedirs(out_image_dir, exist_ok=True)
    os.makedirs(out_mi_dir, exist_ok=True)

    # 2. Copy the .mdl into the output folder under the new name.
    new_mdl_path = os.path.join(output_root, plan.new_mdl_relpath)
    shutil.copy2(plan.src_mdl, new_mdl_path)
    LOG.info("[%s] copied mdl to %s", label, new_mdl_path)

    # 3. If this mdl has any matched images, run export -> patch JSONs ->
    #    import to repack. If it has none, we just leave the copied mdl
    #    file alone (it's a straight copy under a new name).
    if plan.image_renames:
        # Run export. process_mdl creates a folder next to the mdl named the
        # same as the mdl (without .mdl), and writes JSONs + fmt/ib/vb there.
        old_cwd = os.getcwd()
        old_stdout = sys.stdout
        try:
            sys.stdout = _PrintInterceptor(old_stdout)
            os.chdir(out_model_dir)
            mdl_local = plan.new_basename + ".mdl"
            LOG.info("[%s] running export (decompile)...", label)
            process_mdl(mdl_local, complete_maps=True, trim_for_gpu=False,
                        dump_collision_nodes=False, overwrite=True)
        finally:
            sys.stdout = old_stdout
            os.chdir(old_cwd)

        scratch = os.path.join(out_model_dir, plan.new_basename)

        # Patch the JSONs.
        _patch_image_list_json(os.path.join(scratch, "image_list.json"),
                               plan.image_renames, label)
        _patch_material_info_json(os.path.join(scratch, "material_info.json"),
                                  plan.image_renames, label)
        LOG.info("[%s] patched image_list.json + material_info.json", label)

        # Run import (repack).
        old_cwd = os.getcwd()
        old_stdout = sys.stdout
        try:
            sys.stdout = _PrintInterceptor(old_stdout)
            os.chdir(out_model_dir)
            LOG.info("[%s] running import (recompile)...", label)
            # We rename the .bak away or just delete it after the run. The
            # import script makes one automatically before overwriting.
            process_mdl_import(plan.new_basename + ".mdl",
                               change_compression=False, force_kuro_version=False)
        finally:
            sys.stdout = old_stdout
            os.chdir(old_cwd)

        # Cleanup the scratch folder.
        shutil.rmtree(scratch, ignore_errors=True)
        # Cleanup any .bak files created by the import script.
        for sib in os.listdir(out_model_dir):
            if sib.startswith(plan.new_basename + ".mdl.bak"):
                try:
                    os.remove(os.path.join(out_model_dir, sib))
                except OSError:
                    pass
        LOG.info("[%s] cleaned up scratch + .bak files", label)
    else:
        LOG.info("[%s] no images to rename; mdl was copied verbatim under the new name", label)

    # 4. Copy renamed images into the output image dir. Skip if a sibling
    #    plan already produced this exact filename (shouldn't happen because
    #    each mdl puts its basename into the prefix, but be defensive).
    sorted_renames = sorted(plan.image_renames.items())
    n_total = len(sorted_renames)
    for idx, (orig, new) in enumerate(sorted_renames, 1):
        src = os.path.join(src_image_dir, orig)
        dst = os.path.join(out_image_dir, new)
        if os.path.exists(dst):
            LOG.info("[%s] image %d/%d (already exists, skipping): %s",
                     label, idx, n_total, _dim(new))
            continue
        shutil.copy2(src, dst)
        LOG.info("[%s] image %d/%d: %s",
                 label, idx, n_total, _name_arrow(orig, new))
    if n_total:
        LOG.info("[%s] copied %s renamed image(s) total",
                 label, _bold(_green(str(n_total))))

    # 5. Copy + rename the .mi side-car.
    if plan.src_mi and plan.new_mi_relpath:
        new_mi_path = os.path.join(output_root, plan.new_mi_relpath)
        shutil.copy2(plan.src_mi, new_mi_path)
        LOG.info("[%s] copied mi -> %s", label, new_mi_path)
    else:
        LOG.warning("[%s] no .mi side-car found for %s.mdl - the output will have "
                    "no %s.mi (continuing; this is OK if the source genuinely has none)",
                    label, plan.src_basename, plan.new_basename)


# ---------------------------------------------------------------------------
# A tiny shim: the embedded code defines two functions both called
# `process_mdl` -- the second one (from the import script) overwrites the
# first when we concatenate. We rebind them at module load below.
# ---------------------------------------------------------------------------
# (See the very end of the file -- after the embedded code -- for the
# rebinding.)


# ---------------------------------------------------------------------------
# MDL selection helpers (--only / --only-from / --select)
# ---------------------------------------------------------------------------
def _split_only_args(only_args):
    """Flatten a list of --only values into individual selection tokens.

    Each element of `only_args` may itself contain comma-separated tokens.
    A trailing '.mdl' (any case) is stripped from each token. Whitespace
    around tokens is trimmed; empty tokens are dropped.

    Tokens may be literal mdl basenames OR glob patterns (containing '*',
    '?', '[]') -- both flavours are accepted; glob expansion happens later
    in _filter_mdls_by_names() once the discovered mdl list is known.

    Returns a list of tokens in the order they appeared (preserving
    duplicates so the caller can decide what to do with them).
    """
    out = []
    for raw in only_args or []:
        for tok in str(raw).split(","):
            tok = tok.strip()
            if not tok:
                continue
            if tok.lower().endswith(".mdl"):
                tok = tok[:-4]
            out.append(tok)
    return out


def _read_only_from_file(path):
    """Read a list of selection tokens from a text file.

    Format: one token per line. A '#' starts a line comment (text after it
    is ignored). Blank lines are ignored. Trailing '.mdl' is stripped from
    each token (case-insensitive). The file is read as UTF-8 with an
    optional BOM.

    Each line may be a literal mdl basename OR a glob pattern (containing
    '*', '?', '[]'); both are accepted.

    Raises OSError if the file cannot be opened.
    """
    names = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if line.lower().endswith(".mdl"):
                line = line[:-4]
            names.append(line)
    return names


def _is_glob_pattern(token):
    """Return True iff `token` looks like a glob pattern -- i.e. it contains
    one of the fnmatch wildcard meta-characters: '*', '?', '['."""
    return any(ch in token for ch in "*?[")


def _glob_match_mdls(mdls, pattern):
    """Return mdl paths whose basename (without .mdl) matches `pattern`
    case-insensitively, in the order they appear in `mdls`.

    Pattern may have a trailing '.mdl' which is stripped before matching.
    Pattern syntax is fnmatch (Unix shell-style): '*' matches anything,
    '?' matches one character, '[abc]' is a character class.

    Returns an empty list when nothing matches.
    """
    import fnmatch
    pat = pattern
    if pat.lower().endswith(".mdl"):
        pat = pat[:-4]
    pat_lower = pat.lower()
    out = []
    for p in mdls:
        base = os.path.splitext(os.path.basename(p))[0].lower()
        if fnmatch.fnmatchcase(base, pat_lower):
            out.append(p)
    return out


def _filter_mdls_by_names(mdls, requested_tokens):
    """Resolve each requested token (literal basename or glob pattern) to
    matching mdl paths and return (selected_paths, unknown_tokens).

    Matching rules:
      * Tokens are case-insensitive; an optional trailing '.mdl' is stripped
        before matching.
      * A token containing '*', '?' or '[' is treated as a glob pattern
        and may match multiple mdls. A glob that matches NOTHING is
        reported as unknown.
      * Any other token is matched as an exact basename. A non-matching
        literal token is reported as unknown.

    The returned `selected_paths` preserves discovery order (i.e. the order
    in `mdls`) and is deduplicated. `unknown_tokens` preserves the order
    in which they were requested.
    """
    by_lower = {os.path.splitext(os.path.basename(p))[0].lower(): p for p in mdls}
    selected = []
    seen = set()
    unknown = []
    for n in requested_tokens:
        key = n.strip()
        if key.lower().endswith(".mdl"):
            key = key[:-4]
        if not key:
            unknown.append(n)
            continue
        if _is_glob_pattern(key):
            matches = _glob_match_mdls(mdls, key)
            if not matches:
                unknown.append(n)
                continue
            for m in matches:
                if m in seen:
                    continue
                seen.add(m)
                selected.append(m)
            continue
        match = by_lower.get(key.lower())
        if match is None:
            unknown.append(n)
            continue
        if match in seen:
            continue
        seen.add(match)
        selected.append(match)
    return selected, unknown


def _resolve_selection_tokens(text, mdls, view_list):
    """Parse one comma-separated selection input and resolve it to mdl paths.

    Token grammar (each comma-separated token, case-insensitive, optional
    trailing '.mdl' is stripped):
      * 'all'                -> every entry of `view_list`
      * '<int>'              -> the entry at that 1-based index in `view_list`
      * '<int>-<int>'        -> inclusive range of view_list indices
                                (reversed bounds are normalised)
      * literal basename     -> exact match against `mdls` (NOT view_list,
                                so 'add chr0001' works regardless of filter)
      * glob pattern         -> fnmatch against basenames of `mdls`

    Returns (paths, unmatched_tokens). `paths` is deduplicated and ordered
    by first appearance. `unmatched_tokens` are the input tokens that
    yielded nothing.
    """
    paths = []
    unmatched = []
    seen = set()
    if not text:
        return paths, unmatched

    by_lower = {os.path.splitext(os.path.basename(p))[0].lower(): p for p in mdls}

    for tok in str(text).split(","):
        raw_tok = tok
        tok = tok.strip()
        if not tok:
            continue

        if tok.lower() == "all":
            for p in view_list:
                if p not in seen:
                    seen.add(p)
                    paths.append(p)
            continue

        m = re.match(r"^(\d+)\s*-\s*(\d+)$", tok)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            if a < 1 or b > len(view_list):
                unmatched.append(raw_tok.strip())
                continue
            for i in range(a, b + 1):
                p = view_list[i - 1]
                if p not in seen:
                    seen.add(p)
                    paths.append(p)
            continue

        if tok.isdigit():
            i = int(tok)
            if 1 <= i <= len(view_list):
                p = view_list[i - 1]
                if p not in seen:
                    seen.add(p)
                    paths.append(p)
            else:
                unmatched.append(raw_tok.strip())
            continue

        # Name or glob token. Strip optional .mdl extension.
        nm = tok
        if nm.lower().endswith(".mdl"):
            nm = nm[:-4]

        if _is_glob_pattern(nm):
            matches = _glob_match_mdls(mdls, nm)
            if not matches:
                unmatched.append(raw_tok.strip())
                continue
            for mm in matches:
                if mm not in seen:
                    seen.add(mm)
                    paths.append(mm)
            continue

        match = by_lower.get(nm.lower())
        if match is None:
            unmatched.append(raw_tok.strip())
            continue
        if match not in seen:
            seen.add(match)
            paths.append(match)

    return paths, unmatched


def _interactive_select_mdls(mdls):
    """Interactive picker scaled to large mdl lists (hundreds to thousands).

    Supports a display filter (glob), pagination, glob-based selection and
    explicit add/remove commands. Returns the chosen subset of `mdls` (in
    discovery order) once the user types 'done'.

    The picker operates on three concepts:

      * Selection : the running set of mdl paths the user has chosen.
                    Survives filter changes; query with 'show'; reset
                    with 'clear'; finalised with 'done'.
      * View      : the visible subset, controlled by the display filter
                    ('/<glob>' to set, '/' alone to clear). Numeric
                    indices in input refer to the current view.
      * Page      : a windowed slice of the view rendered by 'list'.
                    Pages auto-advance; 'first' rewinds.

    Raises KeyboardInterrupt / EOFError if the user interrupts the prompt;
    raises SystemExit on an explicit 'quit' or empty-on-entry abort.
    """
    PAGE = 50
    AUTO_SHOW_MAX = 50  # auto-display the full list on entry up to this size

    selected = set()         # set of mdl paths currently selected
    filter_pat = None        # current display filter (glob), None = no filter
    page_offset = [0]        # mutable cell so nested fn can update

    def basename_of(p):
        return os.path.splitext(os.path.basename(p))[0]

    def current_view():
        return _glob_match_mdls(mdls, filter_pat) if filter_pat else mdls

    def display_page(view_list, size):
        """Render up to `size` items of view_list starting at page_offset[0].
        Updates page_offset[0] to the next position (wrapping to 0 when end
        reached). Returns nothing."""
        if not view_list:
            sys.stdout.write("  " + _dim("(no items in current view)") + "\n")
            page_offset[0] = 0
            return
        if page_offset[0] >= len(view_list):
            sys.stdout.write("  " + _cyan("(end reached; wrapping to start)") + "\n")
            page_offset[0] = 0
        start = page_offset[0]
        end = min(start + size, len(view_list))
        width = max(3, len(str(len(view_list))))
        for i in range(start, end):
            p = view_list[i]
            is_sel = p in selected
            marker = _green("[x]") if is_sel else _dim("[ ]")
            idx_str = _dim("{:>{w}}.".format(i + 1, w=width))
            name = _bold(basename_of(p)) if is_sel else basename_of(p)
            sys.stdout.write("  {} {}  {}\n".format(marker, idx_str, name))
        if end < len(view_list):
            sys.stdout.write(
                "  " + _dim("... {} more (type ".format(len(view_list) - end))
                + _bold(_green("'list'")) + _dim(" for next page, ")
                + _bold(_green("'first'")) + _dim(" to restart)") + "\n")
            page_offset[0] = end
        else:
            page_offset[0] = 0
            if start > 0:
                sys.stdout.write("  " + _dim("(end of list)") + "\n")

    def _cmd(name):
        """Style helper: command name in bold green for the help block."""
        return _bold(_green(name))

    def _kw(text):
        """Style helper: parameter / keyword in cyan."""
        return _cyan(text)

    def show_help():
        sys.stdout.write(
            "  " + _bold("Commands") + _dim(" (case-insensitive):") + "\n"
            "    " + _cmd("<selection>") + "         add to selection (numbers, ranges, names, globs, "
            + _kw("'all'") + ")\n"
            "    " + _dim("                        examples:  ")
            + _kw("1,3,5-7") + "   " + _kw("chr0001") + "   " + _kw("chr*_c01")
            + "   " + _kw("chr*_c??") + "   " + _kw("*_c0[12]") + "   " + _kw("all") + "\n"
            "    " + _cmd("add <selection>") + "     same as above (explicit form)\n"
            "    " + _cmd("remove <selection>") + "  remove items from the selection\n"
            "    " + _cmd("/<glob>") + "             set display filter (only show matching items)\n"
            "    " + _dim("                        examples:  ")
            + _kw("/chr*") + "    " + _kw("/*_c01") + "    " + _kw("/chr*_c??")
            + "    " + _kw("/*chr*_c01.mdl") + "\n"
            "    " + _dim("                        ")
            + _kw("'/'") + " alone clears the filter\n"
            "    " + _cmd("list [N]") + "            show next page of current view (default N=50)\n"
            "    " + _cmd("first") + "               restart paging from the top of the current view\n"
            "    " + _cmd("show") + "                list the current selection\n"
            "    " + _cmd("clear") + "               remove every item from the selection\n"
            "    " + _cmd("done") + "                accept current selection and continue\n"
            "    " + _cmd("quit") + "                abort the run\n"
            "    " + _cmd("help") + "                this message\n"
            "  " + _bold("Notes:") + "\n"
            "    " + _dim("- Numeric indices refer to the current VIEW (1..N of what is displayed).") + "\n"
            "    " + _dim("- Names and globs are matched case-insensitively against ALL discovered") + "\n"
            "    " + _dim("  .mdl files (not just the current view) -- so 'add chr0001' works even") + "\n"
            "    " + _dim("  when a filter hides it.") + "\n"
            "    " + _dim("- Glob syntax is fnmatch: * = any chars, ? = one char, [abc] = char class.") + "\n"
            "    " + _dim("- The trailing '.mdl' on names/globs is optional.") + "\n"
        )

    sys.stdout.write("\n" + _bold(_magenta("--- Select .mdl files to process ---")) + "\n")
    sys.stdout.write(_bold(str(len(mdls))) + " .mdl file(s) discovered under "
                     + _dim("asset/common/model/") + ".\n")
    show_help()
    if len(mdls) <= AUTO_SHOW_MAX:
        sys.stdout.write("\n")
        display_page(mdls, len(mdls))
    else:
        sys.stdout.write(
            "\n  " + _dim("(list is large; type ")
            + _bold(_green("'list'")) + _dim(" to page through it, or ")
            + _bold(_green("'/<glob>'")) + _dim(" to filter)") + "\n")

    while True:
        view = current_view()
        if filter_pat:
            status = (_dim("[filter '") + _cyan(filter_pat) + _dim("': ")
                      + _bold(_cyan(str(len(view)))) + _dim(" match]"))
        else:
            status = _dim("[no filter]")
        sel_count_str = (_bold(_green(str(len(selected))))
                         if len(selected) > 0 else _dim(str(len(selected))))
        prompt = "{} {}{}/{} {} ".format(
            status, _dim("selected:"),
            sel_count_str, _dim(str(len(mdls))),
            _bold(">"))
        try:
            raw = _real_input(prompt).strip()
        except (KeyboardInterrupt, EOFError):
            raise
        if not raw:
            continue

        # Filter command: starts with '/'.
        if raw.startswith("/"):
            pat = raw[1:].strip()
            if pat.lower().endswith(".mdl"):
                pat = pat[:-4]
            if not pat:
                filter_pat = None
                page_offset[0] = 0
                sys.stdout.write("  " + _cyan("Filter cleared.") + "\n")
                continue
            new_view = _glob_match_mdls(mdls, pat)
            filter_pat = pat
            page_offset[0] = 0
            if not new_view:
                sys.stdout.write(
                    "  " + _yellow("Filter '{}' matches 0 items.".format(pat))
                    + "  " + _dim("(Filter is still set; type ")
                    + _bold(_green("'/'")) + _dim(" alone to clear it.)") + "\n")
            else:
                sys.stdout.write(
                    "  " + _green("Filter '{}'".format(pat))
                    + " -> " + _bold(_green(str(len(new_view))))
                    + " match(es). Showing first page:\n")
                display_page(new_view, PAGE)
            continue

        parts = raw.split(None, 1)
        verb = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if verb in ("help", "?", "h"):
            show_help()
            continue

        if verb in ("done", "ok", "go", "accept"):
            if not selected:
                sys.stdout.write(
                    "  " + _yellow("Selection is empty.") + " Add items first, or type "
                    + _bold(_green("'quit'")) + " to abort.\n")
                continue
            return [p for p in mdls if p in selected]

        if verb in ("quit", "abort", "cancel", "exit", "q"):
            raise SystemExit("Aborted: no .mdl files selected.")

        if verb == "show":
            if not selected:
                sys.stdout.write("  " + _dim("(selection is empty)") + "\n")
            else:
                for p in mdls:
                    if p in selected:
                        sys.stdout.write("    " + _green(basename_of(p)) + "\n")
                sys.stdout.write("  " + _bold("total: ")
                                 + _bold(_green(str(len(selected)))) + "\n")
            continue

        if verb == "clear":
            n = len(selected)
            selected.clear()
            sys.stdout.write("  " + _yellow("Cleared {} item(s) from selection.".format(n))
                             + "\n")
            continue

        if verb in ("first", "reset", "top"):
            page_offset[0] = 0
            sys.stdout.write("  " + _cyan("Page offset reset to top of current view.")
                             + "\n")
            continue

        if verb == "list":
            size = PAGE
            if rest.strip().isdigit():
                size = max(1, int(rest.strip()))
            display_page(view, size)
            continue

        if verb in ("remove", "rm", "del", "drop"):
            if not rest.strip():
                sys.stdout.write("  " + _red("remove: missing argument.") + " Try "
                                 + _bold(_green("'help'")) + ".\n")
                continue
            paths, unknown = _resolve_selection_tokens(rest, mdls, view)
            removed = 0
            for p in paths:
                if p in selected:
                    selected.discard(p)
                    removed += 1
            if unknown:
                sys.stdout.write("  " + _red("Unmatched: ")
                                 + _yellow(", ".join(unknown)) + "\n")
            sys.stdout.write("  " + _bold(_yellow("- {}".format(removed)))
                             + " removed   "
                             + _dim("(selection: {}/{})".format(
                                 len(selected), len(mdls))) + "\n")
            continue

        # 'add <selection>' OR plain selection tokens (the common case).
        if verb == "add":
            if not rest.strip():
                sys.stdout.write("  " + _red("add: missing argument.") + " Try "
                                 + _bold(_green("'help'")) + ".\n")
                continue
            sel_text = rest
        else:
            sel_text = raw

        paths, unknown = _resolve_selection_tokens(sel_text, mdls, view)
        if not paths and not unknown:
            sys.stdout.write("  " + _yellow("Nothing to do.") + " Type "
                             + _bold(_green("'help'")) + " for commands.\n")
            continue
        added = 0
        for p in paths:
            if p not in selected:
                selected.add(p)
                added += 1
        if unknown:
            sys.stdout.write("  " + _red("Unmatched: ")
                             + _yellow(", ".join(unknown)) + "\n")
        sys.stdout.write("  " + _bold(_green("+ {}".format(added)))
                         + " added   "
                         + _dim("(selection: {}/{})".format(
                             len(selected), len(mdls))) + "\n")


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="kuro_mdl_rename",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Produce renamed mod .p3a archives for Kuro no Kiseki / ED9 games.\n"
            "The renaming is per-mdl and isolates each model's textures into a\n"
            "private namespace so mods that touch overlapping vanilla assets\n"
            "never overwrite each other.\n"
            "\n"
            "PRIMARY WORKFLOW\n"
            "----------------\n"
            "Point the script at the game's install directory with --game and\n"
            "interactively pick which .mdl files to mod with --select. The\n"
            "script reads every .p3a's table of contents at the game-folder\n"
            "top level, lets you filter / page / glob-pick the models, then\n"
            "extracts ONLY the files the selected mdls actually need into a\n"
            "transient scratch directory and packages them into a single mod\n"
            ".p3a archive in the directory the script was run from:\n"
            "\n"
            "    py kuro_mdl_rename.py --game \"D:\\Path\\To\\GameInstall\" --select --apply\n"
            "\n"
            "If the script lives inside the game folder, --game alone (no\n"
            "path) uses the script's own directory.\n"
            "\n"
            "ALL SUPPORTED SOURCES\n"
            "---------------------\n"
            "  * --game [PATH]   Trails / ED9 GAME DIRECTORY (the primary mode\n"
            "                    described above) -- a folder with many .p3a\n"
            "                    archives at top level. The script reads each\n"
            "                    archive's TOC and presents the discovered\n"
            "                    .mdl files for selection;\n"
            "  * <project>       a project directory tree (the layout under\n"
            "                    <project>/ with asset/common/model/,\n"
            "                    asset/common/model_info/, asset/dx11/image/,\n"
            "                    ...);\n"
            "  * <archive>.p3a   a single .p3a archive (auto-detected by\n"
            "                    extension and extracted to a temporary\n"
            "                    working directory).\n"
            "\n"
            "Output is either a directory tree (default for project / .p3a\n"
            "input) or a single .p3a archive (--p3a; default for --game).\n"
            "\n"
            "SUBSET SELECTION (default = all discovered .mdls)\n"
            "-------------------------------------------------\n"
            "  --select          interactive picker with display filter, paging\n"
            "                    and glob-based selection (recommended; scales\n"
            "                    to thousands of mdls)\n"
            "  --only NAMES      comma-separated mdl basenames or globs\n"
            "                    (e.g. --only chr0001,chr0002 or --only \"chr*_c01\")\n"
            "  --only-from FILE  read names/globs from a text file, one per line\n"
            "\n"
            "FOR EVERY .mdl IN SCOPE, THE SCRIPT:\n"
            "------------------------------------\n"
            "  1. Picks a new name for the mdl (prefix/suffix; or interactively\n"
            "     under --rename; you may keep the original name unchanged).\n"
            "  2. Copies the mdl under that name into a SEPARATE output\n"
            "     directory (the source is never modified).\n"
            "  3. Reads the mdl's texture references and matches them, case-\n"
            "     insensitively, against the project's image catalogue.\n"
            "  4. For each match, produces a per-mdl unique renamed copy in\n"
            "     the output's image folder. The image rename is anchored on\n"
            "     the chosen new mdl basename so two mdls that share the same\n"
            "     source texture each get their own private copy in the\n"
            "     output -- even if you keep one or both mdl names unchanged.\n"
            "  5. Patches image_list.json and material_info.json inside the\n"
            "     output mdl, then repacks it.\n"
            "  6. Renames the matching .mi side-car. A missing .mi is not\n"
            "     fatal (warned about and skipped).\n"
            "\n"
            "References to images that are NOT present in the source are left\n"
            "untouched in the JSONs (the engine is expected to find them\n"
            "elsewhere in the game). Images that no .mdl references are not\n"
            "copied to the output (in --game mode, they are not even extracted)."
        ),
        epilog=(
            "Primary workflow\n"
            "----------------\n"
            "Drop the script anywhere, point it at the game install directory,\n"
            "interactively pick the .mdl files you want to mod -- the resulting\n"
            "mod .p3a is written next to where you ran the script:\n"
            "    py kuro_mdl_rename.py --game \"D:\\Steam\\...\\TrailsXYZ\" --select --apply\n"
            "\n"
            "If the script lives inside the game folder itself, --game alone\n"
            "(no path) uses the script's own directory:\n"
            "    py kuro_mdl_rename.py --game --select --apply\n"
            "\n"
            "Game-directory mode with non-interactive subset selection:\n"
            "    py kuro_mdl_rename.py --game --only \"chr5113_c0?\" --apply\n"
            "    py kuro_mdl_rename.py --game \"D:\\Steam\\...\\TrailsXYZ\" \\\n"
            "                          --only \"chr*_c01\" --output mymod.p3a --apply\n"
            "\n"
            "Other source modes\n"
            "------------------\n"
            "Default interactive run, project at the current directory:\n"
            "    py kuro_mdl_rename.py\n"
            "\n"
            "Default interactive run pointed at a project folder:\n"
            "    py kuro_mdl_rename.py C:\\mods\\pyrixiaSFW\n"
            "\n"
            "Per-mdl interactive rename (each mdl asks for a new name):\n"
            "    py kuro_mdl_rename.py C:\\mods\\pyrixiaSFW --rename\n"
            "\n"
            "P3A in / P3A out (extract source archive, repack output):\n"
            "    py kuro_mdl_rename.py C:\\mods\\pyrixiaSFW.p3a --p3a --apply\n"
            "\n"
            "Directory in / P3A out (existing project, archive output):\n"
            "    py kuro_mdl_rename.py C:\\mods\\pyrixiaSFW --p3a --apply\n"
            "\n"
            "Process only a chosen subset of .mdl files (CLI list or globs):\n"
            "    py kuro_mdl_rename.py C:\\mods\\pyrixiaSFW --only chr0001,chr0002.mdl\n"
            "    py kuro_mdl_rename.py C:\\mods\\pyrixiaSFW --only chr0001 --only chr0002\n"
            "    py kuro_mdl_rename.py C:\\mods\\pyrixiaSFW --only \"chr*_c01\" --apply\n"
            "    py kuro_mdl_rename.py C:\\mods\\pyrixiaSFW --only-from list.txt --apply\n"
            "\n"
            "Pick the subset interactively (filter, page through, glob-add, etc.):\n"
            "    py kuro_mdl_rename.py C:\\mods\\pyrixiaSFW --select\n"
            "\n"
            "Subset + keep everything else verbatim (so the output is a complete project):\n"
            "    py kuro_mdl_rename.py C:\\mods\\pyrixiaSFW --only chr0001 --keep --apply\n"
            "\n"
            "Fully non-interactive run (CI / scripts; no prompts at all):\n"
            "    py kuro_mdl_rename.py C:\\mods\\pyrixiaSFW --non-interactive --apply --prefix mod_\n"
            "\n"
            "Path resolution is permissive -- all of these work:\n"
            "    py kuro_mdl_rename.py                              :: cwd\n"
            "    py kuro_mdl_rename.py C:\\mods\\pyrixiaSFW          :: project root\n"
            "    py kuro_mdl_rename.py C:\\mods\\pyrixiaSFW\\asset    :: asset folder itself\n"
            "    py kuro_mdl_rename.py asset\\common\\model           :: anything inside asset\\\n"
            "    py kuro_mdl_rename.py C:\\mods\\unzipped_root        :: contains a single nested project\n"
            "\n"
            "Notes\n"
            "-----\n"
            "* The script is INTERACTIVE BY DEFAULT. Any value you do not\n"
            "  pass on the CLI is asked for at runtime, with a sensible\n"
            "  default pre-filled and editable (Backspace, arrow keys, then\n"
            "  Enter on a real terminal; bracket-style [default] fallback on\n"
            "  pipes and dumb terminals).\n"
            "* Pass --non-interactive to disable all prompts. In that mode\n"
            "  any value not on the CLI takes its built-in default:\n"
            "      prefix = 'mod_'    suffix = ''\n"
            "      apply  = False (dry-run)    keep   = False\n"
            "      p3a    = False (or True in --game mode)\n"
            "      output = '<project>_modded' next to the source\n"
            "               (or '<cwd>/kuro_mdl_rename_output.p3a' in --game mode --\n"
            "                placed in the directory the script was run from, NOT\n"
            "                in the game directory itself)\n"
            "* The script is dry-run by default -- the plan is logged and\n"
            "  printed but no files are written until you pass --apply (or\n"
            "  answer 'yes' to the apply prompt in interactive mode).\n"
            "* In --game mode the source is many .p3a archives; only the\n"
            "  selected mdls and the files they actually reference are\n"
            "  extracted to a transient scratch directory. The scratch is\n"
            "  removed automatically on every exit path (success, error,\n"
            "  Ctrl+C). --keep is a no-op in --game mode (the scratch only\n"
            "  contains files the renaming pipeline already consumes).\n"
            "* The interactive --select picker scales to thousands of mdls:\n"
            "  type 'help' inside it for the full command list (filter,\n"
            "  paging, glob-add, etc.).\n"
            "* Glob patterns (in --only, --only-from, and inside --select)\n"
            "  use fnmatch syntax: '*' = any chars, '?' = one char,\n"
            "  '[abc]' = character class. On Windows cmd, quote patterns\n"
            "  to keep them intact (e.g. --only \"chr*_c01\").\n"
            "* Mutually exclusive flag combinations:\n"
            "      --rename + --non-interactive\n"
            "      --select + --non-interactive\n"
            "      --select + --only / --only-from\n"
            "* The log file is always written next to this Python script,\n"
            "  not into the output directory. Override with --log."
        ),
    )
    p.add_argument("project", nargs="?", default=".",
                   help="Path to the source project (default: current directory). "
                        "Accepts the project root, the 'asset/' folder itself, "
                        "anything nested inside 'asset/', or a folder that contains "
                        "exactly one nested project folder (zip-extraction layout). "
                        "Ignored when --game is active.")
    p.add_argument("--game", nargs="?", const="", default=None, metavar="GAMEDIR",
                   help="*** PRIMARY MODE *** -- treat the source as a Trails / ED9 "
                        "game directory. Combine with --select for the canonical "
                        "workflow ('py kuro_mdl_rename.py --game \"PATH\" --select --apply'). "
                        "The directory must contain many .p3a archives at its top level, "
                        "each carrying part of the asset tree (asset/common/model/, "
                        "asset/common/model_info/, asset/dx11/image/). The script "
                        "auto-detects which .p3a files contribute to those folders "
                        "by reading their tables of contents (no extraction at "
                        "scan time), presents the discovered .mdl files for "
                        "selection (via --only / --select / etc.), then extracts "
                        "ONLY the selected mdls + their .mi side-cars + the images "
                        "they actually reference into a transient scratch directory. "
                        "From there the existing renaming pipeline runs as usual "
                        "and the result defaults to a single .p3a archive output. "
                        "If --game is given without a path, the directory containing "
                        "this script is used (so you can drop the script into the "
                        "game folder and run 'py kuro_mdl_rename.py --game --select'); "
                        "if a path follows, that path is used. The positional "
                        "'project' argument is ignored when --game is active.")
    p.add_argument("--prefix", default=None,
                   help="Prefix added to renamed mdl files (default: 'mod_'). "
                        "Ignored under --rename. Empty is allowed.")
    p.add_argument("--suffix", default=None,
                   help="Suffix added to renamed mdl files, before .mdl (default: empty). "
                        "Ignored under --rename.")
    p.add_argument("--output", "-o", default=None,
                   help="Output destination. With --p3a (or in --game mode where it "
                        "defaults on) this is the .p3a archive path; without --p3a "
                        "this is the output project directory. Defaults: "
                        "'<project>_modded' next to the source for directory/p3a-input "
                        "modes; '<cwd>/kuro_mdl_rename_output.p3a' in --game mode "
                        "(placed in the directory the script was run from, not inside "
                        "the game folder, to keep the new mod separate from vanilla "
                        "data).")
    p.add_argument("--apply", action="store_true", default=None,
                   help="Actually write files. Without --apply (and without answering 'yes' "
                        "to the apply prompt in interactive mode) only the plan is logged.")
    p.add_argument("--keep", action="store_true", default=None,
                   help="Copy ALL unprocessed source files (the ones the renaming pipeline "
                        "doesn't touch) into the output project verbatim. This includes "
                        "unreferenced images, files in other folders under the project, etc. "
                        "Default: no -- only the renamed mdls, .mi side-cars and per-mdl "
                        "renamed image copies appear in the output. Effectively a no-op "
                        "in --game mode (the scratch directory contains only files the "
                        "pipeline already consumes).")
    p.add_argument("--p3a", action="store_true", default=None,
                   help="Pack the output as a P3A archive (.p3a) instead of a directory "
                        "tree. The intermediate directory is built and then packed and the "
                        "intermediate directory is removed afterwards. Source can also be "
                        "a .p3a file -- it is auto-detected and extracted on the fly. "
                        "In --game mode this flag defaults to ON (game-dir output is "
                        "almost always meant to be a single mod .p3a).")
    p.add_argument("--p3a-compression", default=None,
                   choices=["none", "lz4", "zstd", "zstd-dict"],
                   help="Compression algorithm for P3A output (default: 'lz4').")
    p.add_argument("--p3a-version", default=None,
                   choices=["1100", "1200"],
                   help="P3A format version for output (default: '1100').")
    p.add_argument("--rename", action="store_true",
                   help="Per-mdl interactive rename. Ignores --prefix/--suffix and prompts "
                        "for every .mdl's new basename. You may keep the original name by "
                        "editing the pre-filled default; image renames are still derived "
                        "from each chosen new basename, so per-mdl image uniqueness holds "
                        "even when several mdls share a source texture.")
    p.add_argument("--only", action="append", default=None, metavar="NAMES",
                   help="Process ONLY the listed .mdl files. NAMES is a comma-separated "
                        "list of mdl basenames or glob patterns (with or without the "
                        "'.mdl' extension; matching is case-insensitive). Glob syntax is "
                        "fnmatch: '*' matches any chars, '?' matches one char, '[abc]' is "
                        "a character class. The flag may be specified multiple times (all "
                        "values are unioned). On Windows cmd, quote patterns that contain "
                        "spaces; the shell does not glob-expand on its own. Examples: "
                        "--only chr0001,chr0002    --only \"chr*_c01\"    --only \"*_c0[12]\". "
                        "Models not in the list are excluded from the renaming pipeline; "
                        "combined with --keep they are copied verbatim into the output "
                        "(along with their .mi side-car and any images they need under "
                        "the original names). Mutually exclusive with --select.")
    p.add_argument("--only-from", default=None, metavar="FILE",
                   help="Read the list of .mdl selection tokens from FILE (one token per "
                        "line; '#' starts a line comment; blank lines are ignored). Each "
                        "line may be a literal mdl basename OR a glob pattern. Combined "
                        "with --only when both are given. Mutually exclusive with --select.")
    p.add_argument("--select", action="store_true",
                   help="Interactively pick which .mdl files to process. The picker is "
                        "scaled for large projects (hundreds to thousands of mdls): "
                        "set a display filter with '/<glob>' to narrow the view, page "
                        "through it with 'list', then add to the selection by index, "
                        "range, name or glob ('chr*_c01', '1-50', 'all', etc.). Type "
                        "'help' inside the picker for the full command list and 'done' "
                        "to confirm. Mutually exclusive with --only / --only-from and "
                        "with --non-interactive.")
    p.add_argument("--non-interactive", "--batch", dest="non_interactive",
                   action="store_true",
                   help="Disable ALL interactive prompts. Any value not present on the "
                        "command line takes its default: prefix='mod_', suffix='', "
                        "apply=False, keep=False, p3a=False (or True in --game mode), "
                        "output='<project>_modded' next to the source (or "
                        "'<cwd>/kuro_mdl_rename_output.p3a' in --game mode -- placed "
                        "in the directory the script was run from, not the game "
                        "folder). Mutually exclusive with --rename and with --select.")
    p.add_argument("--log", default=None,
                   help="Log file path (default: kuro_mdl_rename.log next to this script).")
    p.add_argument("--no-color", action="store_true",
                   help="Disable colored console output.")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Verbose console output (the log file is always verbose).")
    return p.parse_args(argv)


def _default_output_dir(project_path):
    parent = os.path.dirname(os.path.abspath(project_path))
    name = os.path.basename(os.path.abspath(project_path).rstrip(os.sep))
    # If the input was a .p3a archive, drop the extension so the default
    # output dir is "<base>_modded" rather than "<base>.p3a_modded".
    if name.lower().endswith(".p3a"):
        name = name[:-4]
    return os.path.join(parent, name + "_modded")


def _check_prefix_suffix(prefix, suffix):
    """Return None if OK, else a human-readable error message.

    We only validate filename-safety. Empty prefix AND empty suffix is
    allowed -- the output directory is always separate from the source,
    so leaving the mdl filenames unchanged is fine.
    """
    if not _is_safe_name((prefix or "") + (suffix or "")):
        return ("invalid character in prefix/suffix (no whitespace and none of "
                ": \\ / * ? \" < > | )")
    return None


def _validate_prefix_suffix(prefix, suffix):
    err = _check_prefix_suffix(prefix, suffix)
    if err:
        raise SystemExit(err)


def _interactive_collect_prefix_suffix(prefix_default, suffix_default):
    """Prompt for prefix and suffix, looping until validation passes."""
    sys.stdout.write("\n" + _bold(_magenta(
        "--- Interactive setup (press Enter to accept the pre-filled value) ---"))
        + "\n")
    while True:
        prefix = prompt_with_default(
            "Prefix added to renamed mdl files: ", prefix_default
        )
        suffix = prompt_with_default(
            "Suffix added to renamed mdl files (before .mdl): ", suffix_default
        )
        err = _check_prefix_suffix(prefix, suffix)
        if err is None:
            return prefix, suffix
        sys.stdout.write("  " + _red(err) + ". Try again.\n")
        prefix_default, suffix_default = prefix or prefix_default, suffix or suffix_default


def _interactive_collect_output_apply(default_dir_output, default_p3a_output,
                                       current_apply, current_keep, current_p3a):
    """Prompt for the output mode (dir vs p3a), the output path, the keep
    flag and the apply confirmation. Returns (output, apply, keep, p3a)."""
    p3a_out = prompt_yes_no(
        "Pack output as a P3A archive (instead of a directory tree)? "
        "(default no): ",
        default=bool(current_p3a),
    )
    if p3a_out:
        output = prompt_with_default("Output P3A archive path: ", default_p3a_output)
        if not output.lower().endswith(".p3a"):
            output = output + ".p3a"
    else:
        output = prompt_with_default("Output directory: ", default_dir_output)
    keep = prompt_yes_no(
        "Copy all unprocessed source files (unreferenced images and any other "
        "non-renamed files) verbatim into the output? (default no): ",
        default=bool(current_keep),
    )
    if current_apply:
        return output, True, keep, p3a_out
    apply_now = prompt_yes_no(
        "Apply changes now? (default no = dry-run only): ", default=False
    )
    return output, apply_now, keep, p3a_out


def _interactive_rename_each(plans):
    """Walk every plan and let the user pick a new basename for each .mdl.

    Image renames are re-derived from the chosen new basename via
    make_image_rename(), so each .mdl still gets a unique image-copy
    namespace even when several .mdl files share the same source image.

    Keeping the original mdl basename is allowed -- the script still
    duplicates images and patches the JSONs to reference the per-mdl
    renamed copies, so per-mdl isolation holds even for unchanged names.
    """
    sys.stdout.write("\n" + _bold(_magenta("--- Per-mdl interactive rename ---")) + "\n")
    sys.stdout.write(_dim(
        "For every .mdl, type the new basename (without the .mdl extension) "
        "and press Enter. The pre-filled default is 'mod_<orig>'. To keep "
        "the original name, just edit it back and press Enter.") + "\n\n")
    chosen = {}  # new_basename(lower) -> source_basename, to detect collisions
    for plan in plans:
        suggested = "mod_" + plan.src_basename
        while True:
            new_base = prompt_with_default(
                "Rename '{}.mdl' to (without .mdl): ".format(_cyan(plan.src_basename)),
                suggested,
                allow_empty=False,
            ).strip()
            if not new_base:
                sys.stdout.write("  " + _red("Name cannot be empty.") + " Try again.\n")
                continue
            if not _is_safe_name(new_base):
                sys.stdout.write("  " + _red("Invalid characters")
                                 + " (no whitespace and none of "
                                 ": \\ / * ? \" < > | ). Try again.\n")
                continue
            existing = chosen.get(new_base.lower())
            if existing is not None and existing != plan.src_basename:
                sys.stdout.write("  " + _red(
                    "Name '{}' is already used by '{}.mdl' in this run.".format(
                        new_base, existing)) + " Try again.\n")
                continue
            break
        chosen[new_base.lower()] = plan.src_basename

        # Apply the chosen new basename to the plan: mdl path, mi path,
        # and the image rename map (re-derive so per-mdl uniqueness holds
        # regardless of whether the user kept the original name or not).
        plan.new_basename = new_base
        plan.new_mdl_relpath = os.path.join("asset", "common", "model", new_base + ".mdl")
        plan.image_renames = {
            orig: make_image_rename(orig, new_base) for orig in plan.image_renames
        }
        if plan.src_mi:
            plan.new_mi_relpath = os.path.join(
                "asset", "common", "model_info", new_base + ".mi"
            )
    sys.stdout.write("\n")


def _script_dir():
    """Where the running script lives. Falls back to cwd when unavailable
    (e.g. when run as a frozen executable without __file__)."""
    try:
        if getattr(sys, "frozen", False):
            return os.path.dirname(os.path.abspath(sys.executable))
        return os.path.dirname(os.path.abspath(__file__))
    except (NameError, AttributeError):
        return os.getcwd()


def main(argv=None):
    """Top-level entry: parses args, optionally extracts a P3A source, and
    delegates to _run_main(). The try/finally ensures any transient
    extraction directory is removed on every exit path (success, error, or
    Ctrl+C)."""
    args = parse_args(argv)

    # Honour --no-color BEFORE any interactive prompt or scan output runs.
    # setup_logging() will re-evaluate this later, but we need the global
    # set up early so the picker / game-dir scan / source picker output
    # is plain text when the user asked for it.
    global _COLOR_ENABLED
    if args.no_color:
        _COLOR_ENABLED = False

    if args.rename and args.non_interactive:
        sys.stderr.write(
            "ERROR: --rename and --non-interactive are mutually exclusive "
            "(--rename is itself an interactive feature).\n"
        )
        return 2

    if args.select and args.non_interactive:
        sys.stderr.write(
            "ERROR: --select and --non-interactive are mutually exclusive "
            "(--select is itself an interactive feature).\n"
        )
        return 2

    if args.select and (args.only or args.only_from):
        sys.stderr.write(
            "ERROR: --select cannot be combined with --only / --only-from. "
            "Use one or the other.\n"
        )
        return 2

    # ---- Step 0a: GAME-DIRECTORY mode? Build a multi-archive index. ------
    # When --game is given (with or without an explicit path), we treat the
    # source as a Trails / ED9 game folder containing many .p3a archives at
    # its top level and build a virtual index spanning all of them. The
    # rest of the resolution code (P3A auto-detect, multi-source picker,
    # path resolution) is bypassed entirely in this branch -- the index IS
    # the source.
    game_idx = None
    src_p3a_path = None      # original .p3a, if input was an archive (non-game mode)
    src_extract_dir = None   # transient working dir (game scratch OR p3a extract)

    if args.game is not None:
        if args.game == "":
            game_dir = _script_dir()
            game_dir_origin = "script directory"
        else:
            game_dir = os.path.abspath(args.game)
            game_dir_origin = "command line"
        if not os.path.isdir(game_dir):
            sys.stderr.write(
                "ERROR: --game directory does not exist or is not a directory: {}\n".format(
                    game_dir))
            return 1
        sys.stdout.write(_bold(_magenta("--- Scanning game directory ---")) + "\n")
        sys.stdout.write("{} {} ({}): {}\n".format(
            _dim("Source:"),
            _bold("game directory"),
            _dim(game_dir_origin),
            _cyan(game_dir)))

        def _scan_progress(i, total, p3a_path):
            sys.stdout.write("  " + _dim("[{:>2}/{:>2}] reading TOC: ".format(i, total))
                             + _cyan(os.path.basename(p3a_path)) + "\n")
            sys.stdout.flush()

        try:
            game_idx = P3AGameDirIndex(game_dir, progress=_scan_progress)
        except Exception as e:
            sys.stderr.write("ERROR: failed to scan game directory: {}\n".format(e))
            return 1

        if not game_idx.contributing_p3a:
            sys.stderr.write(
                "ERROR: no .p3a archive in {} contributes asset/common/model/, "
                "asset/common/model_info/, or asset/dx11/image/ entries.\n"
                "Is this really a Trails / ED9 game directory? "
                "(Mod archives in subdirectories like 'mods/' are NOT scanned -- "
                "only top-level .p3a files.)\n".format(game_dir))
            return 1

        n_mdl = len(game_idx.list_mdls())
        n_mi = len(game_idx.list_mi_index())
        n_img = len(game_idx.list_image_index())
        sys.stdout.write(
            "  " + _bold(_green(str(len(game_idx.contributing_p3a))))
            + " contributing archive(s); virtual index: "
            + _bold(str(n_mdl)) + " mdl, "
            + _bold(str(n_mi)) + " mi, "
            + _bold(str(n_img)) + " image.\n")

        if n_mdl == 0:
            sys.stderr.write(
                "ERROR: game index built but contains 0 .mdl files. Nothing to do.\n")
            return 1

        # In game-dir mode the output defaults to a P3A archive (the user's
        # workflow is "produce a single mod .p3a"). The user may still flip
        # this in the interactive prompt or by leaving --p3a unset and
        # passing --output that ends in something else, but the SENSIBLE
        # default is on. We only flip it when not explicitly set.
        if args.p3a is None and args.non_interactive:
            args.p3a = True
        elif args.p3a is None:
            # Interactive mode: pre-tick the P3A choice in the prompt by
            # treating it as "currently True" (the prompt's default-yes).
            args.p3a = True

        # Set up a transient scratch directory; _run_main fills it lazily.
        # main()'s finally block cleans it up on every exit path.
        src_extract_dir = os.path.join(
            _script_dir(), "_kuro_mdl_rename_game_workdir")
        if os.path.exists(src_extract_dir):
            shutil.rmtree(src_extract_dir, ignore_errors=True)
        os.makedirs(src_extract_dir, exist_ok=True)
        # Make resolve_project_root happy by pre-creating the asset/ dir.
        os.makedirs(os.path.join(src_extract_dir, "asset", "common", "model"),
                    exist_ok=True)
        os.makedirs(os.path.join(src_extract_dir, "asset", "common", "model_info"),
                    exist_ok=True)
        os.makedirs(os.path.join(src_extract_dir, "asset", "dx11", "image"),
                    exist_ok=True)
        args.project = src_extract_dir

    # ---- Step 0: P3A INPUT? Auto-detect and extract on the fly. -----------
    user_path_abs = os.path.abspath(args.project)

    # Build a candidate list for the user-supplied directory:
    #   - 'dir' candidate: the directory itself, when it has an asset/ inside.
    #   - 'p3a' candidate: every .p3a file directly inside the directory.
    # 0 candidates --> fall through to the existing "no asset/" error path.
    # 1 candidate  --> use it silently.
    # 2+ candidates --> interactive numbered picker (or error in batch mode).
    if os.path.isdir(user_path_abs):
        has_asset = os.path.isdir(os.path.join(user_path_abs, "asset"))
        p3a_candidates = sorted(
            glob.glob(os.path.join(user_path_abs, "*.p3a"))
            + glob.glob(os.path.join(user_path_abs, "*.P3A"))
        )
        seen = set()
        p3a_candidates = [p for p in p3a_candidates
                          if not (p.lower() in seen or seen.add(p.lower()))]

        candidates = []
        if has_asset:
            candidates.append(("dir", user_path_abs))
        for p in p3a_candidates:
            candidates.append(("p3a", p))

        if len(candidates) == 1:
            kind, path = candidates[0]
            if kind == "p3a":
                user_path_abs = path
                args.project = path
                sys.stdout.write(
                    _dim("Found a P3A archive in ") + _dim(os.path.dirname(path))
                    + _dim(": using ") + _cyan(os.path.basename(path)) + "\n")
            # kind == 'dir' -> user_path_abs already set; nothing to do.
        elif len(candidates) >= 2:
            interactive = not args.non_interactive
            if not interactive:
                sys.stderr.write(
                    "ERROR: multiple possible sources found in {}.\n"
                    "Specify one explicitly on the command line:\n".format(user_path_abs))
                # Align filenames in a column so the suffix annotation lines
                # up regardless of how the basenames vary in length.
                err_name_w = max(len(p) for kind, p in candidates)
                for kind, path in candidates:
                    pad = " " * (err_name_w - len(path))
                    if kind == "dir":
                        sys.stderr.write(
                            "    {}{}     (extracted project tree)\n".format(path, pad))
                    else:
                        sys.stderr.write(
                            "    {}{}     (P3A archive)\n".format(path, pad))
                return 1
            # Interactive picker.
            sys.stdout.write(_bold(_magenta(
                "--- Multiple possible sources in {} ---".format(user_path_abs))) + "\n")
            # Align p3a basenames in a column so the size annotation lines
            # up regardless of filename length. The dir candidate (if any)
            # uses imperative phrasing ("use the extracted project tree...")
            # which doesn't share the basename column anyway, so it just
            # renders as a free-form line.
            p3a_basenames = [os.path.basename(p) for k, p in candidates if k == "p3a"]
            name_w = max((len(b) for b in p3a_basenames), default=0)
            for i, (kind, path) in enumerate(candidates, 1):
                idx_str = _bold(_green("[{}]".format(i)))
                if kind == "dir":
                    sys.stdout.write(
                        "  {} use the extracted project tree ({})\n".format(
                            idx_str, _dim("asset/ here")))
                else:
                    size_mb = os.path.getsize(path) / (1024 * 1024)
                    name = os.path.basename(path)
                    pad = " " * (name_w - len(name))
                    sys.stdout.write(
                        "  {} {}{}     {}\n".format(
                            idx_str, _cyan(name), pad,
                            _dim("({:.1f} MB P3A archive)".format(size_mb))))
            while True:
                try:
                    choice = _real_input(
                        "Pick one to process ({}, or just press Enter to abort): ".format(
                            _bold("1-{}".format(len(candidates))))).strip()
                except (KeyboardInterrupt, EOFError):
                    sys.stderr.write("\nCancelled.\n")
                    return 130
                if choice == "":
                    sys.stderr.write("Aborted.\n")
                    return 1
                try:
                    idx = int(choice)
                    if 1 <= idx <= len(candidates):
                        kind, path = candidates[idx - 1]
                        if kind == "p3a":
                            user_path_abs = path
                            args.project = path
                        # else kind == 'dir' -> user_path_abs already set
                        break
                except ValueError:
                    pass
                sys.stdout.write("  " + _yellow("Invalid choice. Try again.") + "\n")

    if _is_p3a_file(user_path_abs):
        src_p3a_path = user_path_abs
        base = os.path.splitext(os.path.basename(src_p3a_path))[0]
        src_extract_dir = os.path.join(
            _script_dir(), "_kuro_mdl_rename_p3a_in_" + base)
        sys.stdout.write(
            _dim("Source is a P3A archive: extracting to ")
            + _cyan(src_extract_dir) + _dim(" ...") + "\n"
        )
        if os.path.exists(src_extract_dir):
            shutil.rmtree(src_extract_dir, ignore_errors=True)
        try:
            extract_p3a_archive(src_p3a_path, src_extract_dir)
        except Exception as e:
            sys.stderr.write("ERROR: failed to extract source P3A: {}\n".format(e))
            shutil.rmtree(src_extract_dir, ignore_errors=True)
            return 1
        args.project = src_extract_dir

    try:
        return _run_main(args, src_p3a_path, src_extract_dir, game_idx)
    except FileNotFoundError as e:
        # User-friendly error path -- no Python traceback for problems we
        # can describe in plain English (e.g. nothing to process).
        sys.stderr.write("ERROR: {}\n".format(e))
        return 1
    finally:
        # Always clean up the transient P3A extraction directory (or
        # game-dir scratch directory).
        if src_extract_dir and os.path.exists(src_extract_dir):
            shutil.rmtree(src_extract_dir, ignore_errors=True)


def _run_main(args, src_p3a_path, src_extract_dir, game_idx=None):
    interactive = not args.non_interactive

    # ---- Step 1: discover mdls (silent, before any interactive prompts) ---
    # We do this before the prefix/suffix prompts so that the --select picker
    # (which needs to enumerate the discovered mdls) can run first and the
    # rest of the interactive flow only sees the filtered subset.
    if game_idx is not None:
        # Game-dir mode: the "project root" is the empty scratch directory.
        # Discovery is virtual -- all_mdls are P3A entry paths, not files
        # on disk. Real on-disk paths appear after materialisation below.
        src_project = src_extract_dir
        resolve_note = ""
        all_mdls = list(game_idx.list_mdls())
    else:
        src_project, resolve_note = resolve_project_root(args.project)
        all_mdls = find_mdls(src_project)

    if not all_mdls:
        if game_idx is not None:
            sys.stderr.write(
                "ERROR: game index contains 0 .mdl files. Nothing to do.\n")
        else:
            sys.stderr.write(
                "ERROR: No .mdl files found under {}/asset/common/model/\n".format(
                    src_project))
        return 1

    # ---- Step 1a: optional .mdl filtering (--only / --only-from / --select) -
    # When no filter flag is set this is a no-op and the run processes every
    # discovered .mdl, identical to the pre-existing default behaviour. The
    # filtering helpers operate purely on os.path.basename(), so they work
    # equally well on real on-disk paths and on virtual P3A entry paths.
    mdls = list(all_mdls)
    if args.select:
        try:
            mdls = _interactive_select_mdls(all_mdls)
        except (KeyboardInterrupt, EOFError):
            sys.stderr.write("\nCancelled.\n")
            return 130
        except SystemExit as e:
            sys.stderr.write("{}\n".format(e))
            return 1
    elif args.only or args.only_from:
        requested = list(_split_only_args(args.only))
        if args.only_from:
            try:
                requested.extend(_read_only_from_file(args.only_from))
            except OSError as e:
                sys.stderr.write(
                    "ERROR: cannot read --only-from file {!r}: {}\n".format(
                        args.only_from, e))
                return 1
        if not requested:
            sys.stderr.write(
                "ERROR: --only / --only-from produced an empty list of names.\n")
            return 1
        selected, unknown = _filter_mdls_by_names(all_mdls, requested)
        if unknown:
            sys.stderr.write(
                "ERROR: the following requested .mdl name(s) were not found in the "
                "project:\n")
            for u in unknown:
                sys.stderr.write("    {}\n".format(u))
            sys.stderr.write("Available .mdl files under asset/common/model/:\n")
            for p in all_mdls:
                sys.stderr.write("    {}\n".format(
                    os.path.splitext(os.path.basename(p))[0]))
            return 1
        if not selected:
            sys.stderr.write("ERROR: --only matched no .mdl files in the project.\n")
            return 1
        mdls = selected
    filtered_to_subset = (len(mdls) != len(all_mdls))
    total_discovered = len(all_mdls)

    # ---- Step 1b: GAME-DIR MATERIALIZATION (selected mdls + .mi only) -----
    # In game-dir mode the discovered list above is purely virtual. Now
    # that the user has chosen a subset, extract just those .mdl files
    # (and their matching .mi side-cars) from the source archives into
    # the scratch directory. Image references are resolved AFTER this --
    # build_plan() reads the materialised mdls to find them, and a second
    # extraction pass below pulls the matched images.
    if game_idx is not None:
        sys.stdout.write(
            "\n" + _bold(_magenta("--- Materializing selected game-dir files ---")) + "\n"
            + _dim("Extracting ") + _bold(str(len(mdls)))
            + _dim(" selected .mdl file(s) and matching .mi side-cars into scratch...") + "\n")
        try:
            mdl_n, mi_n, missing_mi = _materialize_game_subset(
                game_idx, mdls, src_project)
        except Exception as e:
            sys.stderr.write(
                "ERROR: failed to materialise selected files: {}\n".format(e))
            return 1
        sys.stdout.write(
            "  extracted " + _bold(_green(str(mdl_n))) + " mdl(s) + "
            + _bold(_green(str(mi_n))) + " mi side-car(s)"
            + (_dim(" ({} mdl(s) without a .mi side-car: ok)".format(len(missing_mi)))
               if missing_mi else "") + "\n")
        if mdl_n == 0:
            sys.stderr.write("ERROR: no selected mdl could be extracted.\n")
            return 1
        # Replace virtual paths with real on-disk paths going forward.
        mdls = find_mdls(src_project)

    # ---- Step 2: prefix/suffix (skipped under --rename) -------------------
    if args.rename:
        # Names will be picked per-mdl; build_plan gets empty placeholders
        # which it overwrites once the user has chosen each new basename.
        args.prefix = ""
        args.suffix = ""
    else:
        if interactive:
            try:
                args.prefix, args.suffix = _interactive_collect_prefix_suffix(
                    args.prefix if args.prefix is not None else "mod_",
                    args.suffix if args.suffix is not None else "",
                )
            except (KeyboardInterrupt, EOFError):
                sys.stderr.write("\nCancelled.\n")
                return 130
        else:
            if args.prefix is None:
                args.prefix = "mod_"
            if args.suffix is None:
                args.suffix = ""
        _validate_prefix_suffix(args.prefix, args.suffix)

    # ---- Step 3: silent discovery (image dir + plans) ---------------------
    if game_idx is not None:
        # Image lookup goes against the game-wide virtual index (so build_plan
        # can match references that live in asset_image.p3a etc.). The actual
        # image files are extracted into src_image_dir AFTER build_plan tells
        # us which ones are needed -- see the materialisation pass below.
        src_image_dir = os.path.join(src_project, "asset", "dx11", "image")
        os.makedirs(src_image_dir, exist_ok=True)
        image_index = game_idx.list_image_index()
    else:
        src_image_dir, image_index = index_image_dir(src_project)
    plans = build_plan(src_project, mdls, image_index, args.prefix, args.suffix)
    if not plans:
        sys.stderr.write("ERROR: No usable plans were produced.\n")
        return 1

    # ---- Step 3a: GAME-DIR IMAGE MATERIALIZATION --------------------------
    # build_plan() has now identified, per mdl, which image references are
    # present in the game index. Extract just those images into the scratch
    # so apply_plan() can read them like a normal project.
    if game_idx is not None:
        try:
            n_img = _materialize_plan_images(game_idx, plans, src_image_dir)
        except Exception as e:
            sys.stderr.write(
                "ERROR: failed to materialise referenced images: {}\n".format(e))
            return 1
        sys.stdout.write(
            "Materialized " + _bold(_green(str(n_img)))
            + " unique image(s) referenced by selected mdls.\n")

    # ---- Step 4: per-mdl interactive rename (only under --rename) ---------
    if args.rename:
        try:
            _interactive_rename_each(plans)
        except (KeyboardInterrupt, EOFError):
            sys.stderr.write("\nCancelled.\n")
            return 130

    # ---- Step 5: output destination + apply confirmation -----------------
    # Defaults for the output path differ depending on whether the user is
    # producing a directory or a P3A archive. In game-dir mode the source
    # is the scratch directory (not user-meaningful) and the GAME directory
    # itself is the place we DO NOT want to dump output into (the new mod
    # would land alongside the game's own .p3a archives, easy to mistake
    # for a vanilla file). So we anchor the default on the CURRENT WORKING
    # DIRECTORY -- the directory the user ran the script from -- which is
    # what most CLI tools do and what users expect.
    def _default_p3a_output(src_root, src_p3a):
        if game_idx is not None:
            return os.path.join(os.getcwd(), "kuro_mdl_rename_output.p3a")
        # If source was a P3A, place output next to it. Else next to source dir.
        if src_p3a:
            parent = os.path.dirname(os.path.abspath(src_p3a))
            base = os.path.splitext(os.path.basename(src_p3a))[0]
            return os.path.join(parent, base + "_modded.p3a")
        parent = os.path.dirname(os.path.abspath(src_root))
        base = os.path.basename(os.path.abspath(src_root).rstrip(os.sep))
        return os.path.join(parent, base + "_modded.p3a")

    def _default_output_dir_local(default_src):
        if game_idx is not None:
            return os.path.join(os.getcwd(), "kuro_mdl_rename_output")
        return _default_output_dir(default_src)

    if interactive:
        try:
            default_dir_out = args.output or _default_output_dir_local(src_p3a_path or src_project)
            default_p3a_out = (args.output if args.output and args.output.lower().endswith(".p3a")
                               else _default_p3a_output(src_project, src_p3a_path))
            args.output, args.apply, args.keep, args.p3a = _interactive_collect_output_apply(
                default_dir_out, default_p3a_out,
                bool(args.apply), bool(args.keep), bool(args.p3a),
            )
        except (KeyboardInterrupt, EOFError):
            sys.stderr.write("\nCancelled.\n")
            return 130
    else:
        if args.apply is None:
            args.apply = False  # default = dry-run
        if args.keep is None:
            args.keep = False  # default = no verbatim copy of unprocessed files
        if args.p3a is None:
            args.p3a = False
        if args.output is None:
            args.output = (_default_p3a_output(src_project, src_p3a_path)
                           if args.p3a else _default_output_dir_local(src_p3a_path or src_project))

    # P3A compression / version defaults (used only when args.p3a is True).
    if args.p3a_compression is None:
        args.p3a_compression = "lz4"
    if args.p3a_version is None:
        args.p3a_version = "1100"

    # When packing a P3A, the user-supplied "output" is the .p3a file;
    # internally we still build a working directory, then pack it, then
    # remove the working directory.
    if args.p3a:
        final_p3a_path = os.path.abspath(args.output)
        if not final_p3a_path.lower().endswith(".p3a"):
            final_p3a_path = final_p3a_path + ".p3a"
        out_project = final_p3a_path + "_workdir"
    else:
        final_p3a_path = None
        out_project = os.path.abspath(args.output)

    # ---- Step 6: set up logging (log file lives next to this script) ------
    log_path = args.log or os.path.join(_script_dir(), "kuro_mdl_rename.log")
    setup_logging(log_path, verbose=args.verbose, no_color=args.no_color)
    if resolve_note:
        LOG.info(resolve_note)

    LOG.info("kuro_mdl_rename starting at %s", _dim(datetime.now().isoformat(timespec="seconds")))
    LOG.info("Mode               : %s%s",
             _green("APPLY") if args.apply else _cyan("DRY-RUN"),
             _dim("  (--non-interactive)") if not interactive else "")
    if game_idx is not None:
        LOG.info("Source             : %s %s",
                 _cyan(game_idx.game_dir),
                 _dim("(game directory; {} contributing .p3a, lazy materialised)".format(
                     len(game_idx.contributing_p3a))))
    elif src_p3a_path:
        LOG.info("Source             : %s %s",
                 _cyan(src_p3a_path), _dim("(P3A archive, extracted to scratch)"))
    else:
        LOG.info("Source project     : %s", _cyan(src_project))
    if args.p3a:
        LOG.info("Output             : %s %s",
                 _cyan(final_p3a_path), _dim("(P3A archive)"))
        LOG.info("  P3A compression  : %s", _green(args.p3a_compression))
        LOG.info("  P3A version      : %s", _green(args.p3a_version))
        LOG.info("  working directory: %s", _dim(out_project))
    else:
        LOG.info("Output project     : %s", _cyan(out_project))
    if args.rename:
        LOG.info("Naming             : %s", _bold("per-mdl interactive (--rename)"))
    else:
        LOG.info("Prefix / suffix    : %s / %s",
                 _green(repr(args.prefix)), _green(repr(args.suffix)))
    LOG.info("Keep unused files  : %s",
             _green("yes (--keep)") if args.keep else _dim("no"))
    if filtered_to_subset:
        # Mention how the subset was chosen so the log makes the run
        # reproducible without having to consult the CLI line.
        if args.select:
            sel_source = "--select"
        elif args.only and args.only_from:
            sel_source = "--only + --only-from"
        elif args.only_from:
            sel_source = "--only-from"
        else:
            sel_source = "--only"
        LOG.info("MDL selection      : %s %s",
                 _bold("subset"),
                 _dim("({})".format(sel_source)))
    else:
        LOG.info("MDL selection      : %s", _dim("all .mdl files (no filter)"))
    LOG.info("Log file           : %s", _dim(log_path))
    if filtered_to_subset:
        LOG.info("Discovered %s .mdl file(s); selected %s for processing.",
                 _bold(str(total_discovered)), _bold(str(len(mdls))))
    else:
        LOG.info("Discovered %s .mdl file(s).", _bold(str(len(mdls))))
    LOG.info("Discovered %s image file(s) in %s.",
             _bold(str(len(image_index))),
             _dim("game index" if game_idx is not None else src_image_dir))

    # Sanity: refuse to write into the source directory. (For P3A input the
    # extracted source lives in a scratch dir, so this only fires for
    # directory-input runs where the user really pointed output back at the
    # source.)
    if not src_p3a_path and os.path.abspath(out_project) == os.path.abspath(src_project):
        LOG.error("Output path is the same as the source path. Aborting to protect source data.")
        return 2

    # When --keep is on AND the run was filtered to a subset of the
    # discovered .mdl files, the SKIPPED .mdl files (and their .mi side-cars
    # and image references) get copied verbatim by the --keep walk. Their
    # references point to the ORIGINAL image filenames -- so we must NOT
    # mark those originals as "consumed" by the renaming pipeline, otherwise
    # they would be omitted from the output and the kept-verbatim mdls would
    # reference missing files. Build the protected-image set here.
    #
    # In GAME-DIR mode this whole concern is moot: the scratch project only
    # contains the SELECTED mdls (no skipped ones materialised), so the
    # --keep walk has nothing extra to copy and we don't need to protect
    # any image. Skip the bookkeeping entirely in that case.
    protected_images = set()
    if game_idx is None and args.keep and filtered_to_subset:
        selected_set = {_normcase_abs(p) for p in mdls}
        skipped_mdls = [p for p in all_mdls if _normcase_abs(p) not in selected_set]
        for sm in skipped_mdls:
            try:
                refs = _mdl_image_list(sm)
            except Exception as e:
                LOG.debug("[keep] could not parse skipped mdl %s for image refs: %s",
                          sm, e)
                refs = None
            if not refs:
                continue
            for ref in refs:
                actual = image_index.get(ref.lower())
                if actual:
                    protected_images.add(actual)
        if protected_images:
            LOG.debug("[keep] %d image(s) protected from consumption "
                      "because skipped mdls reference them", len(protected_images))

    # Compute the list of files --keep would copy. We always compute it when
    # --keep is set so it's available both for the dry-run report and for
    # the apply step. We exclude the running script and the log file from
    # the walk; these may live INSIDE the project (the user often runs the
    # script from inside the project folder) and shouldn't be copied.
    consumed_abs = build_consumed_set(plans, src_image_dir,
                                       protected_image_filenames=protected_images)
    extra_skip = [log_path]
    try:
        extra_skip.append(os.path.abspath(__file__))
    except NameError:
        pass
    kept_files = []
    if args.keep:
        kept_files = enumerate_kept_files(src_project, consumed_abs, extra_skip)

    # ---- Step 7: report and apply -----------------------------------------
    report_plans(plans, src_image_dir, image_index, out_project,
                 dry_run=not args.apply, keep=args.keep, kept_files=kept_files)

    if not args.apply:
        LOG.info("")
        if args.p3a:
            LOG.info("%s Re-run with %s (or answer %s) to write the P3A archive: %s",
                     _cyan(_bold("Dry-run complete.")),
                     _bold("--apply"), _bold("'yes'"),
                     _cyan(final_p3a_path))
        else:
            LOG.info(_cyan(_bold("Dry-run complete.")) + " Re-run with " + _bold("--apply")
                     + " (or answer " + _bold("'yes'") + " to the apply prompt) to write the new project.")
        return 0

    if os.path.exists(out_project) and os.listdir(out_project):
        LOG.warning("Output directory already exists and is not empty: %s", out_project)
        LOG.warning("Existing files may be overwritten or left over.")
    os.makedirs(out_project, exist_ok=True)

    failures = 0
    for i, plan in enumerate(plans, 1):
        # A clearly visible banner so the per-mdl actions that follow are
        # unmistakably attributed to this model and not all "in one heap"
        # when several models are processed.
        header = "MODEL [{}/{}]  {}  -->  {}".format(
            i, len(plans), plan.src_basename + ".mdl",
            plan.new_basename + ".mdl")
        LOG.info("")
        LOG.info(_bold(_magenta("=" * 8 + " " + header + " " + "=" * max(2, 60 - len(header)))))
        try:
            apply_plan(plan, src_project, out_project, src_image_dir)
            LOG.info("[%s] %s", plan.new_basename, _bold(_green("OK")))
        except Exception as e:
            LOG.exception("[%s] FAILED: %s", plan.new_basename, e)
            failures += 1

    # --keep: after every per-mdl apply has run, walk the source tree once
    # more and copy every file that wasn't consumed by the renaming pipeline.
    if args.keep and kept_files:
        LOG.info("")
        LOG.info(_bold(_magenta("=" * 8 + " KEEP: copying unprocessed source files "
                                + "=" * 22)))
        try:
            n = copy_kept_files(src_project, out_project, kept_files)
            LOG.info("[keep] %s file(s) copied verbatim",
                     _bold(_green(str(n))))
        except Exception as e:
            LOG.exception("[keep] FAILED: %s", e)
            failures += 1

    # --p3a OUTPUT: pack the working directory into a P3A archive, then
    # remove the working directory. Skipped on dry-run, skipped on failure.
    cmp_map = {"none": 0, "lz4": 1, "zstd": 2, "zstd-dict": 3}
    if args.p3a and args.apply and failures == 0:
        LOG.info("")
        LOG.info(_bold(_magenta("=" * 8 + " PACK: building P3A archive " + "=" * 35)))
        LOG.info("[pack] source workdir : %s", _dim(out_project))
        LOG.info("[pack] target archive : %s", _cyan(final_p3a_path))
        LOG.info("[pack] compression    : %s", _green(args.p3a_compression))
        LOG.info("[pack] format version : %s", _green(args.p3a_version))
        try:
            pack_directory_to_p3a(
                out_project,
                final_p3a_path,
                cmp_type=cmp_map[args.p3a_compression],
                p3a_ver=int(args.p3a_version),
            )
            LOG.info("[pack] %s -> %s",
                     _bold(_green("OK")), _cyan(final_p3a_path))
            # Now that the archive is on disk, we don't need the workdir.
            shutil.rmtree(out_project, ignore_errors=True)
            LOG.info("[pack] removed working directory")
        except Exception as e:
            LOG.exception("[pack] FAILED: %s", e)
            LOG.error("[pack] working directory left in place for inspection: %s",
                      out_project)
            failures += 1

    LOG.info("")
    LOG.info(_bold(_cyan("=" * 72)))
    if failures:
        LOG.error("Done, with %d failure(s). See log: %s", failures, log_path)
        return 1
    if args.apply:
        if args.p3a:
            LOG.info("%s Output P3A archive written to: %s",
                     _bold(_green("Done.")), _cyan(final_p3a_path))
        else:
            LOG.info("%s Output project written to: %s",
                     _bold(_green("Done.")), _cyan(out_project))
    else:
        # Dry-run: just remind the user where the output WOULD have gone.
        if args.p3a:
            LOG.info("%s (dry-run: would have produced P3A: %s)",
                     _bold(_cyan("Done.")), _dim(final_p3a_path))
        else:
            LOG.info("%s (dry-run: would have produced directory: %s)",
                     _bold(_cyan("Done.")), _dim(out_project))
    LOG.info("Log file: %s", _dim(log_path))
    return 0


if __name__ == "__main__":
    # The embedded code defines two functions named process_mdl. The second
    # (from the import script) wins after concatenation. We re-bind them
    # under explicit names right here. See the alias block injected after
    # the embedded code for details.
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrupted.\n")
        sys.exit(130)
