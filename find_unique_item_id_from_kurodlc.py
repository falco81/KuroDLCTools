import json
import sys
import os
from glob import glob

# ------------------------------------------------------------
# Utilities
# ------------------------------------------------------------

def get_all_files():
    return [f for f in os.listdir('.') if f.lower().endswith('.kurodlc.json')]

def extract_item_ids(json_file):
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [
        item["item_id"]
        for item in data.get("CostumeParam", [])
        if "item_id" in item
    ]

# ------------------------------------------------------------
# Source detection & selection (CHECK MODE)
# ------------------------------------------------------------

def detect_sources():
    sources = []

    if os.path.exists("t_item.json"):
        sources.append(("json", "t_item.json"))

    if os.path.exists("t_item.tbl.original"):
        sources.append(("original", "t_item.tbl.original"))

    if os.path.exists("t_item.tbl"):
        sources.append(("tbl", "t_item.tbl"))

    if os.path.exists("script_en.p3a"):
        sources.append(("p3a", "script_en.p3a"))

    if os.path.exists("script_eng.p3a"):
        sources.append(("p3a", "script_eng.p3a"))

    return sources

def select_source_interactive(sources):
    print("\nMultiple item sources detected.\n")
    print("Select source to use for check:")

    for i, (stype, name) in enumerate(sources, 1):
        if stype == "p3a":
            print(f"  {i}) {name} (extract t_item.tbl.original.tmp)")
        else:
            print(f"  {i}) {name}")

    while True:
        choice = input(f"\nEnter choice [1-{len(sources)}]: ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(sources):
                return sources[idx]
        print("Invalid choice, try again.")

# ------------------------------------------------------------
# Extraction from P3A
# ------------------------------------------------------------

def extract_from_p3a(p3a_file, out_file):
    from p3a_lib import p3a_class

    p3a = p3a_class()
    with open(p3a_file, 'rb') as p3a.f:
        headers, entries, p3a_dict = p3a.read_p3a_toc()
        for entry in entries:
            if os.path.basename(entry['name']) == 't_item.tbl':
                data = p3a.read_file(entry, p3a_dict)
                with open(out_file, 'wb') as f:
                    f.write(data)
                return True
    return False

# ------------------------------------------------------------
# Load item table
# ------------------------------------------------------------

def load_items_from_json():
    with open('t_item.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    for section in data.get("data", []):
        if section.get("name") == "ItemTableData":
            return {x['id']: x['name'] for x in section.get("data", [])}
    return {}

def load_items_from_tbl(tbl_file):
    from kurodlc_lib import kuro_tables
    kt = kuro_tables()
    table = kt.read_table(tbl_file)
    return {x['id']: x['name'] for x in table['ItemTableData']}

# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

if len(sys.argv) < 2:
    print("""
Usage: python script.py <mode> [options]

Modes:
  <file.kurodlc.json>
  searchall
  searchallbydlc
  searchallbydlcline
  searchallline
  check

Check options:
  --source json|tbl|original|p3a
  --no-interactive
  --keep-extracted
""")
    sys.exit(1)

arg = sys.argv[1].lower()
options = sys.argv[2:]

# ------------------------------------------------------------
# CHECK MODE
# ------------------------------------------------------------

if arg == "check":
    keep_extracted = "--keep-extracted" in options
    no_interactive = "--no-interactive" in options

    forced_source = None
    for opt in options:
        if opt.startswith("--source"):
            _, forced_source = opt.split("=") if "=" in opt else (None, None)

    sources = detect_sources()
    if not sources:
        print("Error: No valid item source found.")
        sys.exit(1)

    extracted_temp = False
    temp_tbl = "t_item.tbl.original.tmp"
    used_source = None

    if forced_source:
        for stype, path in sources:
            if stype == forced_source:
                used_source = (stype, path)
                break
        if not used_source:
            print("Forced source not available.")
            sys.exit(1)
    else:
        if len(sources) == 1 or no_interactive:
            used_source = sources[0]
        else:
            used_source = select_source_interactive(sources)

    stype, path = used_source

    if stype == "json":
        items_dict = load_items_from_json()
        source_used = "t_item.json"

    elif stype in ("tbl", "original"):
        items_dict = load_items_from_tbl(path)
        source_used = path

    elif stype == "p3a":
        if extract_from_p3a(path, temp_tbl):
            extracted_temp = True
            items_dict = load_items_from_tbl(temp_tbl)
            source_used = f"{path} → {temp_tbl}"
        else:
            print("Failed to extract t_item.tbl from P3A.")
            sys.exit(1)

    # Collect IDs
    all_item_ids = []
    for f in get_all_files():
        all_item_ids.extend(extract_item_ids(f))

    unique_ids = sorted(set(all_item_ids))

    max_id_len = max(len(str(i)) for i in unique_ids)
    max_name_len = max(len(name) for name in items_dict.values()) if items_dict else 0

    ok_count = 0
    bad_count = 0

    for item_id in unique_ids:
        id_str = str(item_id).rjust(max_id_len)
        if item_id in items_dict:
            name = items_dict[item_id].ljust(max_name_len)
            print(f"{id_str} : {name} [BAD]")
            bad_count += 1
        else:
            print(f"{id_str} : {'available'.ljust(max_name_len)} [OK]")
            ok_count += 1

    print("\nSummary:")
    print(f"Total IDs : {len(unique_ids)}")
    print(f"OK        : {ok_count}")
    print(f"BAD       : {bad_count}")
    print(f"\nSource used for check: {source_used}")

    if extracted_temp and not keep_extracted:
        os.remove(temp_tbl)
        print(f"Cleaned up temporary file: {temp_tbl}")

    sys.exit(0)

# ------------------------------------------------------------
# OTHER MODES (unchanged)
# ------------------------------------------------------------

files = get_all_files()

if arg == "searchall":
    ids = []
    for f in files:
        ids.extend(extract_item_ids(f))
    print(sorted(set(ids)))

elif arg == "searchallbydlc":
    all_ids = []
    for f in files:
        ids = extract_item_ids(f)
        all_ids.extend(ids)
        print(f"{f}:")
        print(ids)
        print()
    print("Unique item_ids across all files:")
    print(sorted(set(all_ids)))

elif arg == "searchallbydlcline":
    all_ids = []
    for f in files:
        ids = extract_item_ids(f)
        all_ids.extend(ids)
        print(f"{f}:")
        for i in sorted(ids):
            print(i)
        print()
    print("Unique item_ids across all files:")
    for i in sorted(set(all_ids)):
        print(i)

elif arg == "searchallline":
    ids = []
    for f in files:
        ids.extend(extract_item_ids(f))
    for i in sorted(set(ids)):
        print(i)

else:
    print(sorted(set(extract_item_ids(sys.argv[1]))))
