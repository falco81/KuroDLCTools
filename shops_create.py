import json
import sys
from pathlib import Path

# argument check
if len(sys.argv) < 2:
    print(
        "Usage: python shops_create.py path_to_config_file.json\n"
        "\n"
        "This script generates a JSON file that assigns items to shops.\n"
        "You need to provide a configuration JSON file with the following structure:\n"
        "{\n"
        "    \"item_ids\": [list of item IDs],\n"
        "    \"shop_ids\": [list of shop IDs]\n"
        "}\n"
        "\n"
        "Example:\n"
        "  python shops_create.py my_config.json\n"
        "This will create 'output_my_config.json' containing all combinations of items and shops."
    )
    sys.exit(1)


config_path = Path(sys.argv[1])

if not config_path.exists():
    print(f"Error: File '{config_path}' does not exist.")
    sys.exit(1)

# load configuration
with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)

item_ids = config.get("item_ids", [])
shop_ids = config.get("shop_ids", [])

shop_items = []

for item_id in item_ids:
    for shop_id in shop_ids:
        shop_items.append({
            "shop_id": shop_id,
            "item_id": item_id,
            "unknown": 1,
            "start_scena_flags": [],
            "empty1": 0,
            "end_scena_flags": [],
            "int2": 0
        })

# wrap result
result = {
    "ShopItem": shop_items
}

# output file name
output_path = config_path.with_name(f"output_{config_path.name}")

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=4, ensure_ascii=False)

print(f"Success: File '{output_path.name}' was created successfully.")
