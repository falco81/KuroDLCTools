# Converts .kurodlc.json files made for Trails in the Sky 1st Chapter
# to the table layout of Trails in the Sky 2nd Chapter, and checks that the
# shops the mod sells its items in actually exist in 2nd Chapter.
#
# Usage: Place in the 2nd Chapter table folder (e.g. table_en) together with
# kurodlc_schema.json, the original .tbl files and the .kurodlc.json files, then run.
# - Target layouts are read from the .tbl files in the folder (from *.tbl.original
#   if it exists). If a table is missing, known 2nd Chapter layouts are used.
# - Every converted file is backed up first as <name>.sky1_backup
#   (the backup does not end in .kurodlc.json, so kurodlc_make_tbls.py ignores it).
# - Files that already match 2nd Chapter are left untouched, so it is safe to run
#   repeatedly.
# - Shop ids in ShopItem are checked against ShopInfo in t_shop.tbl. Ids that do
#   not exist in 2nd Chapter must be replaced (or their entries dropped); valid
#   ids can be changed too. A shop picker with name search is built in.
#
# Also accepts files named *_kurodlc.json; they are saved as *.kurodlc.json.
#
# Options:
#   --no-shop-check   skip the shop id check entirely
#   --no-interactive  never prompt; report shop problems and leave the ids alone

import os, sys, glob, json, struct, shutil

# Entry lengths of the 2nd Chapter tables (fallback when the .tbl is not in the folder)
SKY2_FALLBACK = {
    'CharaArrange': 72, 'CharaSettingInfo': 20, 'CostumeAttachOffset': 56,
    'CostumeParam': 56, 'DLCTableData': 64, 'ItemKindParam2': 16,
    'ItemShopTabType': 8, 'ItemTabType': 12, 'ItemTableData': 256,
    'MedalItem': 8, 'NameTableData': 104, 'ShopConv': 36, 'ShopInfo': 72,
    'ShopItem': 40, 'ShopTypeDesc': 24, 'TradeItem': 52,
}

SHOP_TABLE = 't_shop.tbl'
PAGE = 20

# ---------------------------------------------------------------------------
# Console helpers - the shop names contain characters the Windows console
# cannot always encode, so every print goes through here.
# ---------------------------------------------------------------------------

def out(text=''):
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or 'ascii'
        print(text.encode(enc, 'replace').decode(enc, 'replace'))


def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return ''


def pause_and_exit(code):
    ask("Press Enter to exit.")
    sys.exit(code)


def load_schemas():
    if not os.path.exists('kurodlc_schema.json'):
        out("kurodlc_schema.json is missing! Place it next to this script.")
        pause_and_exit(1)
    with open('kurodlc_schema.json', 'rb') as f:
        return {(x['table_header'], x['schema_length']): x['schema'] for x in json.loads(f.read())}


# ---------------------------------------------------------------------------
# Minimal .tbl reading. Only the section table and ShopInfo are needed, so the
# script stays independent of kurodlc_lib.
# ---------------------------------------------------------------------------

def read_sections(table_name):
    """Return {section_name: (entry_length, start_offset, num_entries)}."""
    sections = {}
    with open(table_name, 'rb') as f:
        data = f.read()
    if data[:4] != b'#TBL':
        return sections
    num_sections, = struct.unpack("<I", data[4:8])
    pos = 8
    for _ in range(num_sections):
        name = data[pos:pos + 64].replace(b'\x00', b'').decode('utf-8', 'replace')
        _crc, start, entry_length, num = struct.unpack("<4I", data[pos + 64:pos + 80])
        pos += 80
        sections[name] = (entry_length, start, num)
    return sections, data


def read_table_lengths():
    lengths = {}
    tables = glob.glob('*.tbl.original') + [x for x in glob.glob('*.tbl') if not os.path.exists(x + '.original')]
    for table_name in tables:
        try:
            sections, _ = read_sections(table_name)
        except (OSError, IOError):
            continue
        for name, (entry_length, _s, _n) in sections.items():
            lengths[name] = entry_length
    return lengths


_STRUCT_SIZES = {'b': 1, 'B': 1, 'h': 2, 'H': 2, 'i': 4, 'I': 4, 'f': 4,
                 'q': 8, 'Q': 8, 'd': 8}


def expand_struct(fmt):
    """'<4Q2H7f' -> ['Q','Q','Q','Q','H','H','f',...]"""
    chars, count = [], ''
    for ch in fmt.lstrip('<>=!'):
        if ch.isdigit():
            count += ch
        else:
            chars.extend([ch] * int(count or 1))
            count = ''
    return chars


def read_cstring(data, offset):
    end = data.find(b'\x00', offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode('utf-8', 'replace')


def decode_rows(data, start, entry_length, count, schema):
    """Decode a section into dicts using a kurodlc_schema entry."""
    chars = expand_struct(schema['schema'])
    rows = []
    for i in range(count):
        base, ci, row = start + i * entry_length, 0, {}
        offset = base
        for key, kind in zip(schema['keys'], schema['values']):
            if kind == 't':
                ptr, = struct.unpack_from('<Q', data, offset)
                row[key] = read_cstring(data, ptr)
                offset += 8
                ci += 1
            elif kind in ('a', 'b'):
                offset += _STRUCT_SIZES[chars[ci]] + _STRUCT_SIZES[chars[ci + 1]]
                row[key] = []
                ci += 2
            else:
                ch = chars[ci]
                row[key] = struct.unpack_from('<' + ch, data, offset)[0]
                offset += _STRUCT_SIZES[ch]
                ci += 1
        rows.append(row)
    return rows


def load_shops(schemas):
    """Return {shop_id: shop_name} from t_shop.tbl, or None if unavailable."""
    table = SHOP_TABLE + '.original' if os.path.exists(SHOP_TABLE + '.original') else SHOP_TABLE
    if not os.path.exists(table):
        return None, "{} not found - shop ids cannot be checked.".format(SHOP_TABLE)
    try:
        sections, data = read_sections(table)
    except (OSError, IOError) as e:
        return None, "{} could not be read: {}".format(table, e)
    if 'ShopInfo' not in sections:
        return None, "{} has no ShopInfo section.".format(table)
    entry_length, start, count = sections['ShopInfo']
    schema = schemas.get(('ShopInfo', entry_length))
    if schema is None:
        return None, "No ShopInfo schema for entry length {}.".format(entry_length)
    try:
        rows = decode_rows(data, start, entry_length, count, schema)
    except (struct.error, IndexError, KeyError) as e:
        return None, "ShopInfo could not be decoded: {}".format(e)
    shops = {}
    for row in rows:
        shop_id = row.get('id')
        name = row.get('shop_name') or row.get('name') or ''
        if isinstance(shop_id, int):
            shops[shop_id] = name
    return shops, "{} shops read from {}".format(len(shops), os.path.basename(table))


# ---------------------------------------------------------------------------
# Shop picker
# ---------------------------------------------------------------------------

def shop_label(shops, shop_id):
    name = shops.get(shop_id, '')
    return "{0:>4}  {1}".format(shop_id, name if name else '(no name)')


def print_shop_page(shops, ids, page):
    total_pages = max(1, (len(ids) + PAGE - 1) // PAGE)
    page = max(0, min(page, total_pages - 1))
    out("")
    for n, shop_id in enumerate(ids[page * PAGE:(page + 1) * PAGE], start=1 + page * PAGE):
        out("  [{0:>3}] {1}".format(n, shop_label(shops, shop_id)))
    out("  page {0}/{1}".format(page + 1, total_pages))
    return page


def search_shops(shops, text):
    text = text.lower()
    hits = []
    for shop_id in sorted(shops):
        if text in shops[shop_id].lower() or text in str(shop_id):
            hits.append(shop_id)
    return hits


def pick_shop(shops, prompt, allow_drop, allow_keep):
    """Interactive shop picker. Returns an id, 'drop', 'keep' or None (skip)."""
    all_ids = sorted(shops)
    out("")
    out(prompt)
    out("  type part of a shop name to search, or a shop id directly")
    options = ["  l = list all shops"]
    if allow_keep:
        options.append("k = keep as is")
    if allow_drop:
        options.append("d = drop these shop entries")
    options.append("s = skip this file")
    out("  ".join(options))
    while True:
        answer = ask("> ")
        if answer == '':
            continue
        low = answer.lower()
        if low == 's':
            return None
        if allow_keep and low == 'k':
            return 'keep'
        if allow_drop and low == 'd':
            return 'drop'
        if low == 'l':
            page = 0
            while True:
                page = print_shop_page(shops, all_ids, page)
                sub = ask("  number to pick, n/p = next/previous page, q = back: ").strip().lower()
                if sub == 'q':
                    break
                if sub == 'n':
                    page += 1
                    continue
                if sub == 'p':
                    page -= 1
                    continue
                if sub.isdigit():
                    index = int(sub) - 1
                    if 0 <= index < len(all_ids):
                        return all_ids[index]
                    out("  Out of range.")
            continue
        if answer.isdigit():
            shop_id = int(answer)
            if shop_id in shops:
                out("  -> {}".format(shop_label(shops, shop_id)))
                return shop_id
            out("  Shop {} does not exist in 2nd Chapter. Search by name instead.".format(shop_id))
            continue
        hits = search_shops(shops, answer)
        if not hits:
            out("  Nothing found for '{}'.".format(answer))
            continue
        if len(hits) > PAGE:
            out("  {} matches, showing the first {}:".format(len(hits), PAGE))
            hits = hits[:PAGE]
        out("")
        for n, shop_id in enumerate(hits, start=1):
            out("  [{0:>3}] {1}".format(n, shop_label(shops, shop_id)))
        sub = ask("  number to pick, or Enter to search again: ").strip()
        if sub.isdigit():
            index = int(sub) - 1
            if 0 <= index < len(hits):
                return hits[index]
            out("  Out of range.")


def apply_shop_mapping(entries, mapping):
    """Apply {old_id: new_id or 'drop'} to a list of ShopItem entries.

    Remapping two shops onto the same one can make the same item appear twice
    in that shop, so duplicate (shop_id, item_id) pairs are dropped. Returns
    (entries, duplicates_removed).
    """
    result, seen, duplicates = [], set(), 0
    for entry in entries:
        shop_id = entry.get('shop_id')
        if shop_id in mapping:
            target = mapping[shop_id]
            if target == 'drop':
                continue
            entry = dict(entry)
            entry['shop_id'] = target
        key = (entry.get('shop_id'), entry.get('item_id'))
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        result.append(entry)
    return result, duplicates


def check_shop_ids(data, json_name, shops, interactive):
    """Validate and optionally remap the shop ids of one file.

    Returns (changed, notes, blocked). `blocked` is True when invalid ids are
    still in the file, which means it would not work in 2nd Chapter.
    """
    entries = data.get('ShopItem')
    if not isinstance(entries, list) or not entries:
        return False, [], False

    used = sorted({e['shop_id'] for e in entries if isinstance(e, dict) and 'shop_id' in e})
    if not used:
        return False, [], False

    missing = [s for s in used if s not in shops]
    out("")
    out("Shops used by {}:".format(json_name))
    for shop_id in used:
        count = sum(1 for e in entries if e.get('shop_id') == shop_id)
        if shop_id in shops:
            out("  [OK]      {0}   ({1} items)".format(shop_label(shops, shop_id), count))
        else:
            out("  [MISSING] {0:>4}  does not exist in 2nd Chapter   ({1} items)".format(shop_id, count))

    if not interactive:
        if missing:
            return False, ["shop ids not in 2nd Chapter: {}".format(missing)], True
        return False, [], False

    mapping = {}

    # Invalid ids have to be dealt with - the items would be unreachable.
    for shop_id in missing:
        choice = pick_shop(
            shops,
            "Shop {} does not exist in 2nd Chapter. Pick a replacement:".format(shop_id),
            allow_drop=True, allow_keep=False)
        if choice is None:
            out("  Skipped - {} keeps the invalid shop id.".format(json_name))
            return False, ["invalid shop ids left unchanged: {}".format(missing)], True
        mapping[shop_id] = choice

    # Valid ids can be changed as well, but only if asked for.
    valid = [s for s in used if s in shops]
    if valid:
        answer = ask("\nChange any of the valid shop ids too? [y/N]: ").strip().lower()
        if answer in ('y', 'yes'):
            for shop_id in valid:
                choice = pick_shop(
                    shops,
                    "Shop {} - keep or replace?".format(shop_label(shops, shop_id)),
                    allow_drop=True, allow_keep=True)
                if choice is None:
                    break
                if choice != 'keep':
                    mapping[shop_id] = choice

    if not mapping:
        return False, [], False

    data['ShopItem'], duplicates = apply_shop_mapping(entries, mapping)
    notes = []
    for old, new in sorted(mapping.items(), key=lambda kv: kv[0]):
        if new == 'drop':
            notes.append("ShopItem: shop {} entries removed".format(old))
        else:
            notes.append("ShopItem: shop {0} -> {1} ({2})".format(
                old, new, shops.get(new, '')))
    if duplicates:
        notes.append("ShopItem: {} duplicate item/shop pairs removed".format(duplicates))
    notes.append("ShopItem: {} entries after remapping".format(len(data['ShopItem'])))
    return True, notes, False


# ---------------------------------------------------------------------------
# Table layout conversion
# ---------------------------------------------------------------------------

def default_value(value_type):
    return [] if value_type in ('a', 'b') else ("" if value_type == 't' else 0)


def convert_value(value, value_type):
    if value_type in ('a', 'b') and not isinstance(value, list):
        return [value]            # e.g. chr_restrict: 0 -> [0]
    if value_type == 'n' and isinstance(value, list):
        return value[0] if len(value) > 0 else 0
    return value


def convert_entry(entry, keys, values):
    return {k: convert_value(entry[k], v) if k in entry else default_value(v) for k, v in zip(keys, values)}


def convert_tables(data, lengths, schemas):
    """Reshape every section to the 2nd Chapter layout. Returns (changed, notes)."""
    changed, notes = False, []
    for table in data:
        if not isinstance(data[table], list) or len(data[table]) == 0:
            continue
        if table not in lengths or (table, lengths[table]) not in schemas:
            notes.append("{}: unknown table in 2nd Chapter, left unchanged".format(table))
            continue
        schema = schemas[(table, lengths[table])]
        keys, values = schema['keys'], schema['values']
        new_entries = [convert_entry(e, keys, values) for e in data[table]]
        if new_entries != data[table]:
            changed = True
            src_keys = set().union(*[e.keys() for e in data[table]])
            added = [k for k in keys if k not in src_keys]
            removed = sorted(src_keys - set(keys))
            if added:
                notes.append("{}: added {}".format(table, added))
            if removed:
                notes.append("{}: removed {}".format(table, removed))
            wrapped = [k for k, v in zip(keys, values) if v in ('a', 'b') and k in src_keys
                       and any(not isinstance(e.get(k), list) for e in data[table] if k in e)]
            if wrapped:
                notes.append("{}: converted to list {}".format(table, wrapped))
            data[table] = new_entries
    return changed, notes


def main():
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))
    else:
        os.chdir(os.path.abspath(os.path.dirname(__file__)))

    check_shops = '--no-shop-check' not in sys.argv
    interactive = '--no-interactive' not in sys.argv and sys.stdin is not None

    schemas = load_schemas()
    lengths = dict(SKY2_FALLBACK)
    from_tbl = read_table_lengths()
    lengths.update(from_tbl)
    if from_tbl.get('ItemTableData', 256) != 256:
        out("Warning: t_item.tbl in this folder is not from Sky 2nd Chapter (entry length {}).".format(
            from_tbl['ItemTableData']))
        out("The files will be converted to the layout of the tables in this folder.\n")

    shops, shop_status = (None, '')
    if check_shops:
        shops, shop_status = load_shops(schemas)
        out(shop_status)
        if shops is None:
            out("Shop ids will not be checked.")

    json_files = sorted(set(glob.glob('*.kurodlc.json') + glob.glob('*_kurodlc.json')))
    if not json_files:
        out("No *.kurodlc.json files found.")
        pause_and_exit(0)

    blocked_files = []

    for json_name in json_files:
        with open(json_name, 'r', encoding='utf-8') as f:
            try:
                data = json.loads(f.read())
            except json.JSONDecodeError as e:
                out("[ERROR] {}: invalid JSON ({} at line {})".format(json_name, e.msg, e.lineno))
                continue

        changed, notes = convert_tables(data, lengths, schemas)

        if shops:
            shop_changed, shop_notes, blocked = check_shop_ids(data, json_name, shops, interactive)
            changed = changed or shop_changed
            notes.extend(shop_notes)
            if blocked:
                blocked_files.append(json_name)

        out_name = json_name[:-len('_kurodlc.json')] + '.kurodlc.json' \
            if json_name.endswith('_kurodlc.json') else json_name
        if not changed and out_name == json_name:
            out("[OK]        {} already matches 2nd Chapter".format(json_name))
            for n in notes:
                out("              " + n)
            continue

        if os.path.exists(out_name) and out_name != json_name:
            out("[SKIPPED]   {}: {} already exists".format(json_name, out_name))
            continue

        backup = json_name + '.sky1_backup'
        if not os.path.exists(backup):
            shutil.copy2(json_name, backup)
        with open(out_name, 'w', encoding='utf-8') as f:
            f.write(json.dumps(data, indent=4, ensure_ascii=False))
        if out_name != json_name:
            os.remove(json_name)
        out("[CONVERTED] {} -> {} (backup: {})".format(json_name, out_name, backup))
        for n in notes:
            out("              " + n)

    if blocked_files:
        out("")
        out("These files still use shop ids that do not exist in 2nd Chapter:")
        for name in blocked_files:
            out("  " + name)
        out("Their items will not show up in any shop until the ids are fixed.")

    out("\nDone. Now run kurodlc_make_tbls.py.")
    ask("Press Enter to exit.")


if __name__ == "__main__":
    main()
