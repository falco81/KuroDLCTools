#!/usr/bin/env python3
"""
find_unique_item_id_for_t_costumes.py - Standalone version

Extract unique item IDs from costume data (CostumeParam section).

Supported sources:
- t_costume.json
- t_costume.tbl
- t_costume.tbl.original
- script_en.p3a / script_eng.p3a (extracts t_costume.tbl)
- zzz_combined_tables.p3a (extracts t_costume.tbl)
"""

import sys
import os
import json

# -------------------------
# Import required libraries with error handling
# -------------------------
try:
    from p3a_lib import p3a_class
    from kurodlc_lib import kuro_tables
    HAS_LIBS = True
except ImportError as e:
    HAS_LIBS = False
    MISSING_LIB = str(e)


# -------------------------
# Data loading functions
# -------------------------

def detect_sources(base_name='t_costume'):
    """Detect available data sources."""
    sources = []
    json_file = f"{base_name}.json"
    tbl_original = f"{base_name}.tbl.original"
    tbl_file = f"{base_name}.tbl"
    
    if os.path.exists(json_file):
        sources.append(('json', json_file))
    if os.path.exists(tbl_original):
        sources.append(('original', tbl_original))
    if os.path.exists(tbl_file):
        sources.append(('tbl', tbl_file))
    if os.path.exists("script_en.p3a"):
        sources.append(('p3a', 'script_en.p3a'))
    if os.path.exists("script_eng.p3a"):
        sources.append(('p3a', 'script_eng.p3a'))
    if os.path.exists("zzz_combined_tables.p3a"):
        sources.append(('zzz', 'zzz_combined_tables.p3a'))
    
    return sources


def select_source_interactive(sources):
    """Let user select a source interactively."""
    print("\nMultiple data sources detected. Select source to use:")
    for i, (stype, path) in enumerate(sources, 1):
        if stype in ('p3a', 'zzz'):
            print(f"  {i}) {path} (extract t_costume.tbl)")
        else:
            print(f"  {i}) {path}")
    
    while True:
        try:
            choice = input(f"\nEnter choice [1-{len(sources)}]: ").strip()
            idx = int(choice)
            if 1 <= idx <= len(sources):
                return sources[idx - 1]
            print(f"Invalid choice. Please enter a number between 1 and {len(sources)}.")
        except ValueError:
            print("Invalid input. Please enter a number.")
        except KeyboardInterrupt:
            print("\n\nOperation cancelled by user.")
            sys.exit(0)


def extract_from_p3a(p3a_file, table_name='t_costume.tbl', out_file='t_costume.tbl.tmp'):
    """Extract a TBL file from a P3A archive."""
    if not HAS_LIBS:
        print(f"Error: Required library missing: {MISSING_LIB}")
        print("P3A extraction requires p3a_lib module.")
        return False
    
    try:
        if not os.path.exists(p3a_file):
            print(f"Error: P3A file not found: {p3a_file}")
            return False
        
        p3a = p3a_class()
        print(f"Extracting {table_name} from {p3a_file}...")
        
        with open(p3a_file, 'rb') as p3a.f:
            headers, entries, p3a_dict = p3a.read_p3a_toc()
            
            for entry in entries:
                if os.path.basename(entry['name']) == table_name:
                    data = p3a.read_file(entry, p3a_dict)
                    with open(out_file, 'wb') as f:
                        f.write(data)
                    print(f"Successfully extracted to {out_file}")
                    return True
            
            print(f"Error: {table_name} not found in {p3a_file}")
            return False
    
    except Exception as e:
        print(f"Error extracting from P3A: {e}")
        return False


def load_costumes_from_json(json_file='t_costume.json'):
    """Load costume data from JSON file."""
    try:
        if not os.path.exists(json_file):
            print(f"Error: JSON file not found: {json_file}")
            return None
        
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Handle different JSON structures
        if isinstance(data, dict):
            # Structure: {"data": [{"name": "CostumeParam", "data": [...]}]}
            if "data" in data and isinstance(data["data"], list):
                for section in data["data"]:
                    if section.get("name") == "CostumeParam":
                        costumes = section.get("data", [])
                        if not costumes:
                            print(f"Warning: No costumes found in CostumeParam section")
                        return costumes
                
                print(f"Warning: CostumeParam section not found in {json_file}")
                return []
            
            # Direct structure: {CostumeParam: [...]}
            elif "CostumeParam" in data:
                costumes = data["CostumeParam"]
                if not isinstance(costumes, list):
                    print(f"Error: CostumeParam is not a list in {json_file}")
                    return None
                return costumes
        
        print(f"Error: Unexpected JSON structure in {json_file}")
        return None
    
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {json_file}: {e}")
        return None
    except Exception as e:
        print(f"Error loading {json_file}: {e}")
        return None


def load_costumes_from_tbl(tbl_file):
    """Load costume data from TBL file."""
    if not HAS_LIBS:
        print(f"Error: Required library missing: {MISSING_LIB}")
        print("TBL reading requires kurodlc_lib module.")
        return None
    
    try:
        if not os.path.exists(tbl_file):
            print(f"Error: TBL file not found: {tbl_file}")
            return None
        
        kt = kuro_tables()
        table = kt.read_table(tbl_file)
        
        if not isinstance(table, dict):
            print(f"Error: Invalid TBL structure in {tbl_file}")
            return None
        
        if 'CostumeParam' not in table:
            print(f"Error: CostumeParam section not found in {tbl_file}")
            return None
        
        costumes = table['CostumeParam']
        if not isinstance(costumes, list):
            print(f"Error: CostumeParam is not a list in {tbl_file}")
            return None
        
        if not costumes:
            print(f"Warning: No costumes found in CostumeParam section")
        
        return costumes
    
    except Exception as e:
        print(f"Error loading {tbl_file}: {e}")
        return None


def load_costumes(force_source=None, no_interactive=False, keep_extracted=False):
    """
    Load costume data from any supported source format.
    
    Returns:
        Tuple of (costumes_list, source_info) or (None, None) on error
    """
    # Detect sources
    sources = detect_sources('t_costume')
    
    if not sources:
        print(f"Error: No data sources found for t_costume")
        print(f"\nLooked for:")
        print(f"  - t_costume.json")
        print(f"  - t_costume.tbl.original")
        print(f"  - t_costume.tbl")
        print(f"  - script_en.p3a / script_eng.p3a")
        print(f"  - zzz_combined_tables.p3a")
        return None, None
    
    # Filter by forced source if specified
    if force_source:
        sources = [(t, p) for t, p in sources if t == force_source]
        if not sources:
            print(f"Error: No sources found matching type '{force_source}'")
            return None, None
    
    # Select source
    if len(sources) == 1 or no_interactive:
        stype, path = sources[0]
        print(f"Using source: {path}")
    else:
        stype, path = select_source_interactive(sources)
    
    # Load data based on source type
    temp_file = None
    extracted_temp = False
    
    try:
        if stype == 'json':
            costumes = load_costumes_from_json(path)
            source_info = {'type': 'json', 'path': path}
        
        elif stype in ('tbl', 'original'):
            costumes = load_costumes_from_tbl(path)
            source_info = {'type': stype, 'path': path}
        
        elif stype in ('p3a', 'zzz'):
            temp_file = 't_costume.tbl.tmp'
            if extract_from_p3a(path, 't_costume.tbl', temp_file):
                extracted_temp = True
                costumes = load_costumes_from_tbl(temp_file)
                source_info = {'type': stype, 'path': f"{path} -> {temp_file}"}
            else:
                print(f"Failed to extract t_costume.tbl from {path}")
                return None, None
        
        else:
            print(f"Error: Unknown source type '{stype}'")
            return None, None
        
        # Cleanup temporary files
        if extracted_temp and temp_file and not keep_extracted:
            if os.path.exists(temp_file):
                os.remove(temp_file)
                print(f"Cleaned up temporary file: {temp_file}")
        
        return costumes, source_info
    
    except Exception as e:
        print(f"Error during data loading: {e}")
        
        # Cleanup on error
        if extracted_temp and temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
        
        return None, None


# -------------------------
# Main script functionality
# -------------------------

def get_unique_ids(costumes):
    """Extract unique item IDs from costume data."""
    unique_ids = set()
    
    for item in costumes:
        item_id = item.get("item_id")
        # Filter out None values
        if item_id is not None:
            unique_ids.add(item_id)
    
    if not unique_ids:
        print("Warning: No item IDs found in CostumeParam category.", file=sys.stderr)
        return []
    
    return sorted(unique_ids)


def print_usage():
    """Print usage information."""
    print(
        "Usage: python find_unique_item_id_for_t_costumes.py [options]\n"
        "\n"
        "This script extracts all unique item IDs from the 'CostumeParam' category\n"
        "in costume data files.\n"
        "\n"
        "Supported sources (auto-detected in priority order):\n"
        "  1. t_costume.json\n"
        "  2. t_costume.tbl.original\n"
        "  3. t_costume.tbl\n"
        "  4. script_en.p3a / script_eng.p3a (extracts t_costume.tbl)\n"
        "  5. zzz_combined_tables.p3a (extracts t_costume.tbl)\n"
        "\n"
        "Options:\n"
        "  --source=TYPE       Force specific source: json, tbl, original, p3a, zzz\n"
        "  --no-interactive    Auto-select first source if multiple found\n"
        "  --keep-extracted    Keep temporary extracted files from P3A\n"
        "  --format=FORMAT     Output format: list (default), count, range\n"
        "  --help              Show this help message\n"
        "\n"
        "Output formats:\n"
        "  list   - Print Python list of IDs: [100, 101, 102, ...]\n"
        "  count  - Print count of unique IDs: 150 unique item IDs\n"
        "  range  - Print ID range: 100-5000 (150 IDs)\n"
        "\n"
        "Examples:\n"
        "  python find_unique_item_id_for_t_costumes.py\n"
        "      Outputs a sorted list of unique item IDs from auto-detected source.\n"
        "\n"
        "  python find_unique_item_id_for_t_costumes.py --source=json\n"
        "      Use t_costume.json source explicitly.\n"
        "\n"
        "  python find_unique_item_id_for_t_costumes.py --format=count\n"
        "      Display only the count of unique IDs.\n"
        "\n"
        "  python find_unique_item_id_for_t_costumes.py --format=range\n"
        "      Display ID range and count."
    )


def main():
    """Main function."""
    # Parse command line arguments
    force_source = None
    no_interactive = False
    keep_extracted = False
    output_format = 'list'
    
    args = sys.argv[1:]
    
    # Check for help
    if '--help' in args or '-h' in args:
        print_usage()
        return
    
    # Parse options
    for arg in args:
        if arg.startswith('--source='):
            force_source = arg.split('=', 1)[1]
            if force_source not in ('json', 'tbl', 'original', 'p3a', 'zzz'):
                print(f"Error: Invalid source type '{force_source}'")
                print("Valid types: json, tbl, original, p3a, zzz")
                sys.exit(1)
        elif arg.startswith('--format='):
            output_format = arg.split('=', 1)[1]
            if output_format not in ('list', 'count', 'range'):
                print(f"Error: Invalid format '{output_format}'")
                print("Valid formats: list, count, range")
                sys.exit(1)
        elif arg == '--no-interactive':
            no_interactive = True
        elif arg == '--keep-extracted':
            keep_extracted = True
        elif arg.startswith('--'):
            print(f"Error: Unknown option '{arg}'")
            print("Use --help for usage information.")
            sys.exit(1)
        else:
            print(f"Error: Unexpected argument '{arg}'")
            print("Use --help for usage information.")
            sys.exit(1)
    
    # Load data
    print("Loading costume data...\n", file=sys.stderr)
    costumes, source_info = load_costumes(force_source, no_interactive, keep_extracted)
    
    if costumes is None:
        print("\nFailed to load costume data.", file=sys.stderr)
        sys.exit(1)
    
    if not costumes:
        print("\nNo costumes found in source.", file=sys.stderr)
        sys.exit(0)
    
    print(f"\nLoaded {len(costumes)} costumes from: {source_info['path']}\n", file=sys.stderr)
    
    # Extract unique IDs
    unique_ids = get_unique_ids(costumes)
    
    if not unique_ids:
        sys.exit(0)
    
    # Output based on format
    if output_format == 'list':
        print(unique_ids)
    elif output_format == 'count':
        print(f"{len(unique_ids)} unique item IDs")
    elif output_format == 'range':
        min_id = min(unique_ids)
        max_id = max(unique_ids)
        print(f"{min_id}-{max_id} ({len(unique_ids)} IDs)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
