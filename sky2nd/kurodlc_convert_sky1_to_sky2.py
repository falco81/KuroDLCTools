# Converts .kurodlc.json files made for Trails in the Sky 1st Chapter
# to the table layout of Trails in the Sky 2nd Chapter.
#
# Usage: Place in the 2nd Chapter table folder (e.g. table_en) together with
# kurodlc_schema.json, the original .tbl files and the .kurodlc.json files, then run.
# - Target layouts are read from the .tbl files in the folder (from *.tbl.original
#   if it exists). If a table is missing, known 2nd Chapter layouts are used.
# - Every converted file is backed up first as <name>.sky1_backup
#   (the backup does not end in .kurodlc.json, so kurodlc_make_tbls.py ignores it).
# - Files that already match 2nd Chapter are left untouched, so it is safe to run
#   repeatedly.
#
# Also accepts files named *_kurodlc.json; they are saved as *.kurodlc.json.

import os, sys, glob, json, struct, shutil

# Entry lengths of the 2nd Chapter tables (fallback when the .tbl is not in the folder)
SKY2_FALLBACK = {
    'CharaArrange': 72, 'CharaSettingInfo': 20, 'CostumeAttachOffset': 56,
    'CostumeParam': 56, 'DLCTableData': 64, 'ItemKindParam2': 16,
    'ItemShopTabType': 8, 'ItemTabType': 12, 'ItemTableData': 256,
    'MedalItem': 8, 'NameTableData': 104, 'ShopConv': 36, 'ShopInfo': 72,
    'ShopItem': 40, 'ShopTypeDesc': 24, 'TradeItem': 52,
}

def pause_and_exit(code):
    input("Press Enter to exit.")
    sys.exit(code)

def load_schemas():
    if not os.path.exists('kurodlc_schema.json'):
        print("kurodlc_schema.json is missing! Place it next to this script.")
        pause_and_exit(1)
    with open('kurodlc_schema.json', 'rb') as f:
        return {(x['table_header'], x['schema_length']): x['schema'] for x in json.loads(f.read())}

def read_table_lengths():
    lengths = {}
    tables = glob.glob('*.tbl.original') + [x for x in glob.glob('*.tbl') if not os.path.exists(x + '.original')]
    for table_name in tables:
        with open(table_name, 'rb') as f:
            if f.read(4) != b'#TBL':
                continue
            num_sections, = struct.unpack("<I", f.read(4))
            for _ in range(num_sections):
                name = f.read(64).replace(b'\x00', b'').decode('utf-8')
                _crc, _start, entry_length, _num = struct.unpack("<4I", f.read(16))
                lengths[name] = entry_length
    return lengths

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

def main():
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))
    else:
        os.chdir(os.path.abspath(os.path.dirname(__file__)))

    schemas = load_schemas()
    lengths = dict(SKY2_FALLBACK)
    from_tbl = read_table_lengths()
    lengths.update(from_tbl)
    if from_tbl.get('ItemTableData', 256) != 256:
        print("Warning: t_item.tbl in this folder is not from Sky 2nd Chapter (entry length {}).".format(
            from_tbl['ItemTableData']))
        print("The files will be converted to the layout of the tables in this folder.\n")

    json_files = sorted(set(glob.glob('*.kurodlc.json') + glob.glob('*_kurodlc.json')))
    if not json_files:
        print("No *.kurodlc.json files found.")
        pause_and_exit(0)

    for json_name in json_files:
        with open(json_name, 'r', encoding='utf-8') as f:
            try:
                data = json.loads(f.read())
            except json.JSONDecodeError as e:
                print("[ERROR] {}: invalid JSON ({} at line {})".format(json_name, e.msg, e.lineno))
                continue

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

        out_name = json_name[:-len('_kurodlc.json')] + '.kurodlc.json' if json_name.endswith('_kurodlc.json') else json_name
        if not changed and out_name == json_name:
            print("[OK]        {} already matches 2nd Chapter".format(json_name))
            for n in notes:
                print("              " + n)
            continue

        if os.path.exists(out_name) and out_name != json_name:
            print("[SKIPPED]   {}: {} already exists".format(json_name, out_name))
            continue

        backup = json_name + '.sky1_backup'
        if not os.path.exists(backup):
            shutil.copy2(json_name, backup)
        with open(out_name, 'w', encoding='utf-8') as f:
            f.write(json.dumps(data, indent=4, ensure_ascii=False))
        if out_name != json_name:
            os.remove(json_name)
        print("[CONVERTED] {} -> {} (backup: {})".format(json_name, out_name, backup))
        for n in notes:
            print("              " + n)

    print("\nDone. Now run kurodlc_make_tbls.py.")
    input("Press Enter to exit.")

if __name__ == "__main__":
    main()
