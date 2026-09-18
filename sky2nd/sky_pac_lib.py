#!/usr/bin/env python3
"""
sky_pac_lib.py - FPAC (.pac) archive support for Trails in the Sky 1st / 2nd Chapter

The Sky remakes ship their tables and assets inside `.pac` archives (FPAC format)
instead of the `.p3a` archives used by Kuro / Daybreak / Ys X.  This module gives
the rest of the toolkit a read-only interface to those archives that mirrors
`p3a_lib.p3a_class`, so the existing extraction code paths work unchanged:

    archive = sky_pac_class()
    with open(path, 'rb') as archive.f:
        headers, entries, _ = archive.read_p3a_toc()
        data = archive.read_file(entries[0], None)

Format (little-endian):
    0x00  4   magic 'FPAC'
    0x04  4   file count
    0x08  4   header size
    0x0c  4   version
    0x10      entries[count], 0x20 bytes each:
                0x00 4  name CRC32 (XOR 0xFFFFFFFF)
                0x04 4  flags
                0x08 8  name offset (absolute)
                0x10 8  data size
                0x18 8  data offset (absolute)
    then      NUL-terminated names, then the uncompressed data block.

Unlike P3A, FPAC needs no compression libraries (no lz4 / zstandard / xxhash),
so table extraction from a Sky install works even on a bare Python install.

Part of the KuroDLC Modding Toolkit.
"""

import os
import struct

__all__ = [
    'sky_pac_class',
    'is_pac_file',
    'list_pac_tables',
    'extract_table_from_pac',
    'find_sky_pac_archives',
]


class sky_pac_class:
    """Read-only reader for the FPAC (.pac) archives of Trails in the Sky."""

    def __init__(self):
        self.f = None

    @staticmethod
    def _read_cstring(f, offset):
        """Read a NUL-terminated UTF-8 string at `offset`, restoring position."""
        save = f.tell()
        try:
            f.seek(offset)
            buf = bytearray()
            while True:
                ch = f.read(1)
                if not ch or ch == b"\x00":
                    break
                buf.extend(ch)
            return buf.decode("utf-8", errors="replace")
        finally:
            f.seek(save)

    def read_toc(self):
        """Read header + entry table. Returns (header, entries, None).

        Entry keys mirror p3a_class: 'name', 'offset', 'cmp_size', 'unc_size',
        'cmp_type'.  FPAC stores everything uncompressed, so cmp_size equals
        unc_size and cmp_type is always 0.  The third return value exists only
        for API symmetry with P3A (its per-archive ZSTD dictionary); FPAC has
        no equivalent.
        """
        self.f.seek(0)
        magic = self.f.read(4)
        if magic != b"FPAC":
            raise IOError("not a PAC archive (bad magic: {!r})".format(magic))
        count, header_size, version = struct.unpack("<3I", self.f.read(12))
        header = {
            "magic": "FPAC",
            "num_files": count,
            "header_size": header_size,
            "version": version,
        }
        raw_entries = []
        for _ in range(count):
            name_hash, flags, name_off, size, data_off = struct.unpack(
                "<2I3Q", self.f.read(0x20))
            raw_entries.append((name_hash, flags, name_off, size, data_off))
        entries = []
        for name_hash, flags, name_off, size, data_off in raw_entries:
            entries.append({
                "name": self._read_cstring(self.f, name_off),
                "name_hash": name_hash,
                "flags": flags,
                "offset": data_off,
                "cmp_size": size,
                "unc_size": size,
                "cmp_type": 0,
            })
        return header, entries, None

    # API symmetry with p3a_class.
    def read_p3a_toc(self):
        return self.read_toc()

    def read_file(self, entry, _unused_dict=None):
        """Return the raw bytes of `entry`."""
        self.f.seek(entry["offset"])
        data = self.f.read(entry["cmp_size"])
        if len(data) != entry["cmp_size"]:
            raise IOError("short read for {}: expected {} bytes, got {}".format(
                entry["name"], entry["cmp_size"], len(data)))
        return data


def is_pac_file(path):
    """True if `path` is an FPAC archive (content sniff, not extension)."""
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == b"FPAC"
    except (OSError, IOError):
        return False


def list_pac_tables(pac_file):
    """Return the .tbl file names (basenames) contained in `pac_file`."""
    try:
        pac = sky_pac_class()
        with open(pac_file, "rb") as pac.f:
            _headers, entries, _ = pac.read_toc()
            return sorted({os.path.basename(e["name"]) for e in entries
                           if e["name"].lower().endswith(".tbl")})
    except (OSError, IOError):
        return []


def extract_table_from_pac(pac_file, table_name, out_file, quiet=False):
    """Extract `table_name` (e.g. 't_item.tbl') from a .pac archive.

    Returns True on success.  Mirrors the return contract of the
    extract_from_p3a() helpers in the toolkit scripts.
    """
    try:
        if not os.path.exists(pac_file):
            if not quiet:
                print("Error: PAC file not found: {}".format(pac_file))
            return False
        pac = sky_pac_class()
        with open(pac_file, "rb") as pac.f:
            _headers, entries, _ = pac.read_toc()
            for entry in entries:
                if os.path.basename(entry["name"]).lower() == table_name.lower():
                    data = pac.read_file(entry, None)
                    with open(out_file, "wb") as f:
                        f.write(data)
                    return True
        if not quiet:
            print("Error: {} not found in {}".format(table_name, pac_file))
        return False
    except Exception as e:
        print("Error extracting from PAC: {}".format(e))
        return False


# Archives that hold the tables in a Sky install.  `table_en.pac` is the
# English table archive, `table.pac` the Japanese one; the other languages use
# table_de / table_es / table_fr / table_kr / table_tc.  In an untouched install
# they live under pac/steam/, so that directory is searched as well.
_PAC_NAMES = [
    "table_en.pac", "table.pac", "table_de.pac", "table_es.pac",
    "table_fr.pac", "table_kr.pac", "table_tc.pac",
]
_PAC_DIRS = ["", os.path.join("pac", "steam")]


def find_sky_pac_archives(base_dir=".", table_name=None):
    """Return Sky `.pac` archives that can serve as a table source.

    Looks in `base_dir` and in `base_dir/pac/steam`.  If `table_name` is given
    (e.g. 't_item.tbl'), only archives that actually contain that table are
    returned.  Paths come back *relative to base_dir*, so callers can join them
    with their own base directory exactly like the other source candidates.
    Results keep the order of _PAC_NAMES, English first.
    """
    found = []
    seen = set()
    root = base_dir or "."
    for directory in _PAC_DIRS:
        folder = os.path.join(root, directory) if directory else root
        if not os.path.isdir(folder):
            continue
        for name in _PAC_NAMES:
            rel = os.path.join(directory, name) if directory else name
            path = os.path.join(root, rel)
            if not os.path.exists(path):
                continue
            real = os.path.realpath(path)
            if real in seen:
                continue
            if not is_pac_file(path):
                continue
            if table_name and table_name.lower() not in [
                    t.lower() for t in list_pac_tables(path)]:
                continue
            seen.add(real)
            found.append(rel)
    return found
