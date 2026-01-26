import json
import sys

def collect_shops(node, result):
    if isinstance(node, dict):
        if "id" in node and "shop_name" in node:
            result[str(node["id"])] = node["shop_name"]

        for value in node.values():
            collect_shops(value, result)

    elif isinstance(node, list):
        for item in node:
            collect_shops(item, result)


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python find_all_shops.py t_shop.json [search_text]\n"
            "\n"
            "This script searches through a JSON file containing shops and extracts all shop IDs and names.\n"
            "\n"
            "Arguments:\n"
            "  t_shop.json   Path to the JSON file containing shop data.\n"
            "  search_text   (Optional) Filter shops by text in their name (case-insensitive).\n"
            "\n"
            "Examples:\n"
            "  python find_all_shops.py t_shop.json\n"
            "      Lists all shops from the file.\n"
            "  python find_all_shops.py t_shop.json blacksmith\n"
            "      Lists all shops with 'blacksmith' in their name."
        )
        return


    filename = sys.argv[1]
    search_text = sys.argv[2].lower() if len(sys.argv) >= 3 else None

    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error loading file: {e}")
        return

    result = {}
    collect_shops(data, result)

    if search_text:
        filtered = {
            sid: name for sid, name in result.items()
            if search_text in str(name).lower()
        }
    else:
        filtered = result

    if not filtered:
        print("No matching shops found.")
        return

    # Determine padding based on longest ID
    max_len = max(len(sid) for sid in filtered.keys())

    for shop_id, shop_name in filtered.items():
        print(f"{shop_id.rjust(max_len)} : {shop_name}")


if __name__ == "__main__":
    main()
