import json
import sys

# Check if an argument was provided
if len(sys.argv) < 2:
    print(
        "Usage: python shops_find_unique_item_id_from_kurodlc.py <.kurodlc.json>\n"
        "\n"
        "This script extracts all unique item IDs from a .kurodlc JSON file.\n"
        "It combines IDs found in 'ShopItem' and 'CostumeParam' sections.\n"
        "\n"
        "Arguments:\n"
        "  .kurodlc.json   Path to the JSON file containing shop and costume data.\n"
        "\n"
        "Example:\n"
        "  python shops_find_unique_item_id_from_kurodlc.py my_data.kurodlc.json\n"
        "      Outputs a sorted list of all unique item IDs found in the file."
    )
    sys.exit(1)


# File name from argument
json_file = sys.argv[1]

# Load JSON file
with open(json_file, "r", encoding="utf-8") as f:
    data = json.load(f)

# Extract item_id values from ShopItem
shop_item_ids = [
    item["item_id"]
    for item in data.get("ShopItem", [])
    if "item_id" in item
]

# Extract item_id values from CostumeParam
costume_item_ids = [
    item["item_id"]
    for item in data.get("CostumeParam", [])
    if "item_id" in item
]

# Combine and get unique item_id values
unique_item_ids = sorted(set(shop_item_ids + costume_item_ids))

# Print result
print(unique_item_ids)
