import json
import sys
import os

# --- Functions -------------------------------------------------------------

def extract_item_ids(json_file):
    """Load a .kurodlc.json file and return a list of item_id values from CostumeParam."""
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [item["item_id"] for item in data.get("CostumeParam", []) if "item_id" in item]

def get_all_kurodlc_files():
    """Return all *.kurodlc.json files (case-insensitive) in the current directory."""
    files = [f for f in os.listdir(".") if f.lower().endswith(".kurodlc.json") and os.path.isfile(f)]
    if not files:
        print("No .kurodlc.json files found in the current directory.")
        sys.exit(0)
    return files

# ---- Argument handling -----------------------------------------------------

if len(sys.argv) < 2:
    print("""
Usage:
  python find_unique_item_id_from_kurodlc.py <mode_or_file>

Description:
  Extracts item_id values from the "CostumeParam" section of *.kurodlc.json files.

Modes:
  <file.kurodlc.json>
      Process a single file and print unique item_id values as a sorted list.

  searchall
      Process all *.kurodlc.json files in the current directory and print
      all unique item_id values as a single sorted list.

  searchallline
      Same as searchall, but print each unique item_id on a separate line.

  searchallbydlc
      For each *.kurodlc.json file:
        - print the file name
        - print item_id values found in that file as a list
      Then print all unique item_id values across all files as a list.

  searchallbydlcline
      Same as searchallbydlc, but item_id values are printed line by line.
      The final summary of unique item_id values is also printed line by line.

  check
      Same as searchallline, but for each ID, automatically check
      t_item.json, t_item.tbl.original, or t_item.tbl and print its name if assigned.
      Output uses [OK] for available IDs, [BAD] for assigned IDs.
      ID and name are aligned for better readability.
      At the end, shows total IDs, counts of OK/BAD, and the source file.

Examples:
  python find_unique_item_id_from_kurodlc.py costume1.kurodlc.json
  python find_unique_item_id_from_kurodlc.py searchall
  python find_unique_item_id_from_kurodlc.py searchallline
  python find_unique_item_id_from_kurodlc.py searchallbydlc
  python find_unique_item_id_from_kurodlc.py searchallbydlcline
  python find_unique_item_id_from_kurodlc.py check
""")
    sys.exit(1)

raw_arg = sys.argv[1]
arg = raw_arg.lower()

# ---- Modes -----------------------------------------------------------------

if arg == "searchall":
    all_item_ids = []
    for f in get_all_kurodlc_files():
        all_item_ids.extend(extract_item_ids(f))
    print(sorted(set(all_item_ids)))

elif arg == "searchallline":
    all_item_ids = []
    for f in get_all_kurodlc_files():
        all_item_ids.extend(extract_item_ids(f))
    for item_id in sorted(set(all_item_ids)):
        print(item_id)

elif arg == "searchallbydlc":
    all_item_ids = []
    for f in get_all_kurodlc_files():
        item_ids = extract_item_ids(f)
        all_item_ids.extend(item_ids)
        print(f"{f}:")
        print(item_ids)
        print()
    print("Unique item_ids across all files:")
    print(sorted(set(all_item_ids)))

elif arg == "searchallbydlcline":
    all_item_ids = []
    for f in get_all_kurodlc_files():
        item_ids = extract_item_ids(f)
        all_item_ids.extend(item_ids)
        print(f"{f}:")
        for item_id in sorted(set(item_ids)):
            print(item_id)
        print()
    print("Unique item_ids across all files:")
    for item_id in sorted(set(all_item_ids)):
        print(item_id)

elif arg == "check":
    items_dict = {}
    source = "unknown"

    # --- Load t_item.json if exists ---
    if os.path.exists('t_item.json'):
        with open('t_item.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            items_list = []
            for section in data.get("data", []):
                if section.get("name") == "ItemTableData":
                    items_list = section.get("data", [])
                    break
            items_dict = {x['id']: x['name'] for x in items_list}
            source = "t_item.json"
    else:
        # fallback to t_item.tbl / t_item.tbl.original
        try:
            from kurodlc_lib import kuro_tables
        except ModuleNotFoundError:
            print("Error: kurodlc_lib.py not found, required for check mode with tbl files.")
            sys.exit(1)

        kt = kuro_tables()
        if getattr(sys, 'frozen', False):
            os.chdir(os.path.dirname(sys.executable))
        else:
            os.chdir(os.path.abspath(os.path.dirname(__file__)))

        if os.path.exists('t_item.tbl.original'):
            t_item = kt.read_table('t_item.tbl.original')
            source = "t_item.tbl.original"
        elif os.path.exists('t_item.tbl'):
            t_item = kt.read_table('t_item.tbl')
            source = "t_item.tbl"
        else:
            print("Error: t_item.json, t_item.tbl or t_item.tbl.original not found!")
            sys.exit(1)

        t_item = kt.update_table_with_kurodlc(t_item)
        items_dict = {x['id']: x['name'] for x in t_item['ItemTableData']}

    # --- Collect all unique item_ids from .kurodlc.json files ---
    all_item_ids = []
    for f in get_all_kurodlc_files():
        all_item_ids.extend(extract_item_ids(f))

    all_item_ids_set = sorted(set(all_item_ids))

    # --- Determine max lengths for dynamic alignment ---
    max_id_len = max(len(str(i)) for i in all_item_ids_set)
    max_name_len = max([len(name) for name in items_dict.values()] + [len("available")])

    # --- Print each ID with name and status dynamically aligned ---
    ok_count = 0
    bad_count = 0
    for item_id in all_item_ids_set:
        if item_id in items_dict:
            status = "[BAD]"  # assigned
            name = items_dict[item_id]
            bad_count += 1
        else:
            status = "[OK]"   # available
            name = "available"
            ok_count += 1
        print(f"{str(item_id).ljust(max_id_len)}  {name.ljust(max_name_len)} {status}")

    # --- Print summary and source ---
    print(f"\nTotal IDs: {len(all_item_ids_set)}")
    print(f"Total OK: {ok_count}")
    print(f"Total BAD: {bad_count}")
    print(f"Source used for check: {source}")

# ---- Single file -----------------------------------------------------------

else:
    if not os.path.isfile(raw_arg):
        print(f"Error: Unknown parameter or file not found: '{raw_arg}'")
        print("Use one of: searchall, searchallline, searchallbydlc, searchallbydlcline, check")
        sys.exit(1)
    if not raw_arg.lower().endswith(".kurodlc.json"):
        print(f"Error: Invalid file type: '{raw_arg}' (expected .kurodlc.json)")
        sys.exit(1)

    unique_item_ids = sorted(set(extract_item_ids(raw_arg)))
    print(unique_item_ids)
