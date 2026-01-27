import json
import sys
import os
from glob import glob

def extract_item_ids(json_file):
    """Load a JSON file and return a list of item_id from CostumeParam."""
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [
        item["item_id"]
        for item in data.get("CostumeParam", [])
        if "item_id" in item
    ]

# Check arguments
if len(sys.argv) < 2:
    print("""
Usage: python find_unique_item_id_from_kurodlc.py <mode_or_file>

Modes:
  <file.kurodlc.json>    Process a single JSON file and print unique item_ids.
  searchall              Process all .kurodlc.json files in the current directory and print unique item_ids as a list.
  searchallbydlc         Process all .kurodlc.json files, print each file name followed by its item_ids, then unique item_ids across all files.
  searchallline          Process all .kurodlc.json files and print each unique item_id on a separate line.

Example:
  python find_unique_item_id_from_kurodlc.py costume1.kurodlc.json
  python find_unique_item_id_from_kurodlc.py searchall
  python find_unique_item_id_from_kurodlc.py searchallbydlc
  python find_unique_item_id_from_kurodlc.py searchallline
""")
    sys.exit(1)

arg = sys.argv[1].lower()

if arg == "searchall":
    # Find all .kurodlc.json files in the current directory
    all_files = glob("*.kurodlc.json")
    if not all_files:
        print("No .kurodlc.json files found in the current directory.")
        sys.exit(0)

    # Collect all item_ids from all files
    all_item_ids = []
    for file in all_files:
        all_item_ids.extend(extract_item_ids(file))

    # Unique and sorted
    unique_item_ids = sorted(set(all_item_ids))
    print(unique_item_ids)

elif arg == "searchallbydlc":
    # Find all .kurodlc.json files in the current directory
    all_files = glob("*.kurodlc.json")
    if not all_files:
        print("No .kurodlc.json files found in the current directory.")
        sys.exit(0)

    all_item_ids = []
    for file in all_files:
        item_ids = extract_item_ids(file)
        all_item_ids.extend(item_ids)
        print(f"{file}:")     # File name
        print(item_ids)       # Print item_ids
        print()               # Empty line after the list

    # Finally, unique item_ids across all files
    unique_item_ids = sorted(set(all_item_ids))
    print("Unique item_ids across all files:")
    print(unique_item_ids)

elif arg == "searchallline":
    # Find all .kurodlc.json files in the current directory
    all_files = glob("*.kurodlc.json")
    if not all_files:
        print("No .kurodlc.json files found in the current directory.")
        sys.exit(0)

    all_item_ids = []
    for file in all_files:
        all_item_ids.extend(extract_item_ids(file))

    # Unique and sorted
    unique_item_ids = sorted(set(all_item_ids))
    # Print each item_id on a separate line
    for item_id in unique_item_ids:
        print(item_id)

else:
    # Original functionality for a single file
    json_file = sys.argv[1]
    unique_item_ids = sorted(set(extract_item_ids(json_file)))
    print(unique_item_ids)
