import json
import sys

def get_unique_ids_by_category(json_path, category):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    unique_ids = set()

    for block in data.get("data", []):
        if block.get("name") == "ItemTableData":
            for item in block.get("data", []):
                if item.get("category") == category:
                    unique_ids.add(item.get("id"))

    return sorted(unique_ids)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            "Usage: python find_unique_item_id_for_t_item_category.py <t_item.json> <category>\n"
            "\n"
            "This script extracts all unique item IDs from a specified category in a t_item JSON file.\n"
            "\n"
            "Arguments:\n"
            "  t_item.json   Path to the JSON file containing item data.\n"
            "  category      Category number to filter items by (integer).\n"
            "\n"
            "Example:\n"
            "  python find_unique_item_id_for_t_item_category.py t_item.json 5\n"
            "      Outputs a sorted list of unique item IDs belonging to category 5."
        )
        sys.exit(1)


    json_file = sys.argv[1]
    category = int(sys.argv[2])

    ids = get_unique_ids_by_category(json_file, category)

    # Print result
    print(ids)
