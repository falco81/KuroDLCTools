import json
import sys

# Check if an argument was provided
if len(sys.argv) < 2:
    print(
        "Usage: python shops_find_unique_item_id_from_kurodlc.py <.kurodlc.json> [shop|costume]\n"
        "\n"
        "This script extracts all unique item IDs from a .kurodlc JSON file.\n"
        "Default behavior (no parameter):\n"
        "  - Combines IDs from 'ShopItem' and 'CostumeParam'\n"
        "\n"
        "Optional parameters:\n"
        "  shop     -> search only in 'ShopItem'\n"
        "  costume  -> search only in 'CostumeParam'\n"
    )
    sys.exit(1)

# File name from argument
json_file = sys.argv[1]

# Optional mode argument
mode = None
if len(sys.argv) >= 3:
    mode = sys.argv[2].lower()
    if mode not in ("shop", "costume"):
        print(f"Error: Unknown parameter '{mode}'.")
        print("Allowed parameters are: shop, costume")
        sys.exit(1)

# Load JSON file
with open(json_file, "r", encoding="utf-8") as f:
    data = json.load(f)

shop_item_ids = []
costume_item_ids = []

# Extract item_id values from ShopItem
if mode is None or mode == "shop":
    shop_item_ids = [
        item["item_id"]
        for item in data.get("ShopItem", [])
        if "item_id" in item
    ]

# Extract item_id values from CostumeParam
if mode is None or mode == "costume":
    costume_item_ids = [
        item["item_id"]
        for item in data.get("CostumeParam", [])
        if "item_id" in item
    ]

# Combine and get unique item_id values
unique_item_ids = sorted(set(shop_item_ids + costume_item_ids))

# Print result
print(unique_item_ids)
