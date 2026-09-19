# Script to write new dlc tables (t_costume.tbl, t_dlc.tbl, t_item.tbl) by reading
# new entries from all .kurodlc.json files.
# Usage:  Place in a folder with the original tables (which will be renamed to
# t_costume.tbl.original, t_dlc.tbl.original, t_item.tbl.original) and all the
# .kurodlc.json files and run.
#
# Requires kurodlc_lib.py, place in the same folder.
#
# GitHub eArmada8/kuro_dlc_tool
#
# MODIFIED: also writes t_dlc_appid_convert.tbl (Trails in the Sky 1st / 2nd Chapter).
# In the Sky games every DLC entry is mapped to a Steam AppID in that table, and DLC
# without a mapping does not show up in the in-game DLC menu.  This version adds a
# mapping for every new DLC id found in the .kurodlc.json files.
# Requires the DLCAppIDConvertTableData schema in kurodlc_schema.json.
#
# The AppID used for new DLC is read from dlc_appid_map.json, e.g.:
#     { "200": 4975970, "201": 4975970 }
# If an id is missing there, the script asks once and saves the answer to that file.
# Use the AppID of a DLC you actually own - the game asks Steam about ownership.

try:
    import os, sys, json
    from kurodlc_lib import kuro_tables
except ModuleNotFoundError as e:
    print("Python module missing! {}".format(e.msg))
    input("Press Enter to abort.")
    raise   

APPID_TABLE = 't_dlc_appid_convert.tbl'
APPID_SECTION = 'DLCAppIDConvertTableData'
APPID_MAP_FILE = 'dlc_appid_map.json'

def table_available(table_name):
    return os.path.exists(table_name) or os.path.exists(table_name + '.original')

def read_appid_map():
    if os.path.exists(APPID_MAP_FILE):
        try:
            with open(APPID_MAP_FILE, 'r', encoding='utf-8') as f:
                return {int(k): int(v) for k, v in json.loads(f.read()).items()}
        except (ValueError, TypeError):
            print("{} is not valid, ignoring it.".format(APPID_MAP_FILE))
    return {}

def write_appid_map(appid_map):
    with open(APPID_MAP_FILE, 'w', encoding='utf-8') as f:
        f.write(json.dumps({str(k): v for k, v in sorted(appid_map.items())}, indent=4))

def add_appid_entries(kt):
    # DLC ids added by the .kurodlc.json files
    new_dlc_ids = [x['id'] for x in kt.new_entries.get('DLCTableData', [])]
    if len(new_dlc_ids) == 0:
        return
    if kt.get_schema(APPID_SECTION, kt.schema_dict.get(APPID_SECTION, 8)) == {}:
        print("Schema for {} is missing, {} will not be updated!".format(APPID_SECTION, APPID_TABLE))
        print("(Add the DLCAppIDConvertTableData entry to kurodlc_schema.json.)")
        input("Press Enter to continue.")
        return

    original = APPID_TABLE + '.original' if os.path.exists(APPID_TABLE + '.original') else APPID_TABLE
    existing = kt.read_table(original).get(APPID_SECTION, [])
    known = {x['dlc_id']: x['app_id'] for x in existing}
    # Mappings supplied by the .kurodlc.json files themselves take priority
    known.update({x['dlc_id']: x['app_id'] for x in kt.new_entries.get(APPID_SECTION, [])})

    appid_map = read_appid_map()
    missing = [i for i in new_dlc_ids if i not in known and i not in appid_map]
    if len(missing) > 0:
        dlc_names = {x['id']: x['name'] for x in kt.read_table(
            't_dlc.tbl.original' if os.path.exists('t_dlc.tbl.original') else 't_dlc.tbl'
            ).get('DLCTableData', [])} if table_available('t_dlc.tbl') else {}
        default_appid = existing[-1]['app_id'] if len(existing) > 0 else 0
        print("\nThese DLC have no Steam AppID mapping: {}".format(missing))
        print("The game only shows DLC whose AppID you own, so use the AppID of a DLC you own.")
        print("Known mappings in {}:".format(os.path.basename(original)))
        for x in existing:
            print("  DLC {0:>4} -> AppID {1}   {2}".format(x['dlc_id'], x['app_id'], dlc_names.get(x['dlc_id'], '')))
        for dlc_id in missing:
            try:
                answer = input("AppID for DLC {0} [{1}]: ".format(dlc_id, default_appid)).strip()
            except EOFError:        # run from a batch file / without a console
                answer = ''
                print("(no input - using {})".format(default_appid))
            try:
                appid_map[dlc_id] = int(answer) if answer else default_appid
            except ValueError:
                print("Not a number, using {}.".format(default_appid))
                appid_map[dlc_id] = default_appid
        write_appid_map(appid_map)
        print("Saved to {}, edit that file to change these later.\n".format(APPID_MAP_FILE))

    entries = [{'dlc_id': i, 'app_id': appid_map.get(i, known.get(i))} for i in new_dlc_ids]
    entries = [x for x in entries if x['app_id'] is not None]
    if APPID_SECTION in kt.new_entries:
        have = [x['dlc_id'] for x in kt.new_entries[APPID_SECTION]]
        kt.new_entries[APPID_SECTION].extend([x for x in entries if x['dlc_id'] not in have])
    else:
        kt.new_entries[APPID_SECTION] = entries
    print("{}: mapping {}".format(APPID_TABLE,
        ", ".join(["DLC {0} -> AppID {1}".format(x['dlc_id'], x['app_id']) for x in kt.new_entries[APPID_SECTION]])))

if __name__ == "__main__":
    # Set current directory
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))
    else:
        os.chdir(os.path.abspath(os.path.dirname(__file__)))

    kt = kuro_tables()
    
    # Read *.kurodlc.json files
    kt.read_all_kurodlc_jsons()

    # Add Steam AppID mappings for new DLC (Sky 1st / 2nd Chapter)
    if table_available(APPID_TABLE):
        add_appid_entries(kt)
    
    # Write the new tables
    if os.path.exists('t_costume.tbl') or os.path.exists('t_costume.tbl.original'):
        kt.write_table('t_costume.tbl')
    if os.path.exists('t_dlc.tbl') or os.path.exists('t_dlc.tbl.original'):
        kt.write_table('t_dlc.tbl')
    if os.path.exists(APPID_TABLE) or os.path.exists(APPID_TABLE + '.original'):
        kt.write_table(APPID_TABLE)
    if os.path.exists('t_item.tbl') or os.path.exists('t_item.tbl.original'):
        kt.write_table('t_item.tbl')
    if os.path.exists('t_recipe.tbl') or os.path.exists('t_recipe.tbl.original'):
        kt.write_table('t_recipe.tbl')
    if os.path.exists('t_shop.tbl') or os.path.exists('t_shop.tbl.original'):
        kt.write_table('t_shop.tbl')
    if os.path.exists('t_shop_normal.tbl') or os.path.exists('t_shop_normal.tbl.original'):
        kt.write_table('t_shop_normal.tbl')
    if os.path.exists('t_skill.tbl') or os.path.exists('t_skill.tbl.original'):
        kt.write_table('t_skill.tbl')
    if os.path.exists('t_voice.tbl') or os.path.exists('t_voice.tbl.original'):
        kt.write_table('t_voice.tbl')
