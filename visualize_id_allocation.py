#!/usr/bin/env python3
"""
visualize_id_allocation.py - ID Allocation Map Visualizer

Analyzes and visualizes the allocation of item IDs from multiple data sources.
Shows occupied and free ID ranges with color-coded maps and statistics.

Supported sources:
- t_item.json
- t_item.tbl
- t_item.tbl.original
- script_en.p3a / script_eng.p3a (extracts t_item.tbl)
- zzz_combined_tables.p3a (extracts t_item.tbl)

Features:
- Color-coded console visualization
- HTML report generation
- Gap analysis and statistics
- Fragmentation metrics
- Free block identification

Usage:
  python visualize_id_allocation.py [options]

Options:
  --source=TYPE       Force specific source: json, tbl, original, p3a, zzz
  --no-interactive    Auto-select first source if multiple found
  --keep-extracted    Keep temporary extracted files from P3A
  --format=FORMAT     Output format: console, html, both (default: both)
  --block-size=N      Block size for visualization (default: 50)
  --output=FILE       HTML output filename (default: id_allocation_map.html)
  --help              Show this help message

Examples:
  python visualize_id_allocation.py
      Visualize ID allocation from auto-detected source (console + HTML)

  python visualize_id_allocation.py --source=json --format=console
      Show console visualization only, using JSON source

  python visualize_id_allocation.py --format=html --output=my_report.html
      Generate only HTML report with custom filename

  python visualize_id_allocation.py --block-size=100
      Use larger blocks for visualization (better for large ID ranges)

Workflow:
  1. Auto-detect or select data source
  2. Load item IDs from source
  3. Analyze allocation patterns
  4. Generate console visualization with color-coded blocks
  5. Generate HTML report with interactive visualization
  6. Display statistics and free block analysis
"""

import sys
import os
import json
from collections import defaultdict

# -------------------------
# Colorama for Windows CMD colors with fallback
# -------------------------
try:
    import colorama
    from colorama import Fore, Back, Style
    colorama.init(autoreset=True)
    USE_COLOR = True
except ImportError:
    USE_COLOR = False
    # Fallback: empty strings for color codes
    class ColorFallback:
        RED = GREEN = YELLOW = BLUE = CYAN = MAGENTA = WHITE = ''
        RESET_ALL = ''
    
    class BackFallback:
        RED = GREEN = YELLOW = BLUE = CYAN = MAGENTA = WHITE = BLACK = ''
        RESET = ''
    
    Fore = ColorFallback()
    Back = BackFallback()
    Style = ColorFallback()

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
# Engine Configuration
# -------------------------

# Kuro Engine ID Range Limit
# All Kuro games (Kuro 1, Kuro 2, etc.) support IDs in range 1-5000
# This is a hard limit imposed by the game engine.
# Grid visualization will always show the full range up to this limit,
# not just up to the last occupied ID.
# 
# NOTE: If future Kuro engine versions increase this limit,
#       update this constant accordingly.
KURO_ENGINE_MAX_ID = 5000


# -------------------------
# Enhanced data loading functions
# -------------------------

# -------------------------
# Enhanced data loading functions
# -------------------------

def extract_enhanced_data_from_items(items):
    """
    Extract enhanced data from already loaded items list.
    Works with any source format (JSON, TBL, P3A) since it processes the items directly.
    
    Args:
        items: List of item dictionaries
        
    Returns:
        dict: Enhanced data structure with items, categories, etc.
    """
    enhanced_data = {
        'items': {},
        'costumes': {},
        'categories': {},
        'subcategories': {},
        'character_names': {}
    }
    
    # Process all items
    for item in items:
        item_id = item.get('id')
        if item_id is None:
            continue
        
        # Extract item information (handle both JSON and TBL field names)
        enhanced_data['items'][item_id] = {
            'name': item.get('name', ''),
            'description': item.get('description', item.get('desc', '')),
            'category': item.get('category', 0),
            'subcategory': item.get('subcategory', 0),
            'price': item.get('price', 0),
            'stack_size': item.get('stack_size', 1),
            'item_icon': item.get('item_icon', 0),
            'element': item.get('element', 0),
            'character_restriction': item.get('character_restriction', item.get('chr_restrict', 65535)),
            # Stats (handle both naming conventions)
            'hp': item.get('hp', 0),
            'ep': item.get('ep', 0),
            'str': item.get('str', 0),
            'def': item.get('def', 0),
            'ats': item.get('ats', 0),
            'adf': item.get('adf', 0),
            'agl': item.get('agl', 0),
            'dex': item.get('dex', 0),
            'spd': item.get('spd', 0),
            'mov': item.get('mov', 0),
        }
    
    # Build category mappings from actual data
    category_counts = defaultdict(lambda: defaultdict(int))
    for item_id, item_data in enhanced_data['items'].items():
        cat = item_data.get('category', 0)
        subcat = item_data.get('subcategory', 0)
        category_counts[cat][subcat] += 1
    
    # Create category names based on common patterns
    category_names = {
        0: 'Sepith/Materials',
        1: 'Quest Items',
        2: 'Books/Documents',
        17: 'Costumes',
        30: 'Consumables/Currency'
    }
    
    for cat in category_counts.keys():
        if cat not in category_names:
            category_names[cat] = f'Category {cat}'
    
    enhanced_data['categories'] = category_names
    
    # Character names mapping (common character IDs)
    enhanced_data['character_names'] = {
        0: 'Van',
        1: 'Agnès',
        2: 'Feri',
        3: 'Aaron',
        4: 'Risette',
        5: 'Quatre',
        6: 'Bergard',
        7: 'Judith',
    }
    
    return enhanced_data


def load_costume_data(project_dir='.'):
    """
    Load costume data from available sources (JSON or TBL).
    
    Args:
        project_dir: Directory to search for costume data
        
    Returns:
        dict: Costume mappings {item_id: costume_info}
    """
    costumes = {}
    
    # Try JSON first
    try:
        t_costume_path = os.path.join(project_dir, 't_costume.json')
        if os.path.exists(t_costume_path):
            with open(t_costume_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Extract CostumeParam
            for section in data.get('data', []):
                if section.get('name') == 'CostumeParam':
                    for costume in section.get('data', []):
                        item_id = costume.get('item_id')
                        if item_id is not None:
                            costumes[item_id] = {
                                'character_id': costume.get('character_id', 0),
                                'costume_name': costume.get('name', ''),
                                'attach_name': costume.get('attach_name', '')
                            }
            if costumes:
                return costumes
    except Exception as e:
        pass  # Try next source
    
    # Try TBL if JSON not available
    if not HAS_LIBS:
        return costumes
        
    try:
        t_costume_tbl = os.path.join(project_dir, 't_costume.tbl')
        if os.path.exists(t_costume_tbl):
            kuro = kuro_tables(t_costume_tbl, 'Kuro1', 't_costume.tbl')
            costume_data = kuro.read_table('CostumeParam')
            
            if costume_data:
                for costume in costume_data:
                    item_id = costume.get('item_id')
                    if item_id is not None:
                        costumes[item_id] = {
                            'character_id': costume.get('character_id', 0),
                            'costume_name': costume.get('name', ''),
                            'attach_name': costume.get('attach_name', '')
                        }
    except Exception as e:
        pass  # Silently fail
    
    return costumes


def load_all_json_data(project_dir='.'):
    """
    Load all available JSON data files for enhanced information display.
    Returns a dictionary with item details, categories, costumes, etc.
    
    Loads data from:
    - t_item.json: Main item table with names, descriptions, stats, categories
    - t_costume.json: Costume details and character mappings
    
    Returns:
        dict: {
            'items': {id: {name, description, category, ...}},
            'costumes': {item_id: costume_info},
            'categories': {category_id: category_name},
            'subcategories': {(cat, subcat): name}
        }
    """
    enhanced_data = {
        'items': {},
        'costumes': {},
        'categories': {},
        'subcategories': {},
        'character_names': {}
    }
    
    # Try to load t_item.json for item details
    try:
        t_item_path = os.path.join(project_dir, 't_item.json')
        if os.path.exists(t_item_path):
            with open(t_item_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Extract ItemTableData
            for section in data.get('data', []):
                if section.get('name') == 'ItemTableData':
                    for item in section.get('data', []):
                        item_id = item.get('id')
                        if item_id is not None:
                            enhanced_data['items'][item_id] = {
                                'name': item.get('name', ''),
                                'description': item.get('description', ''),
                                'category': item.get('category', 0),
                                'subcategory': item.get('subcategory', 0),
                                'price': item.get('price', 0),
                                'stack_size': item.get('stack_size', 1),
                                'item_icon': item.get('item_icon', 0),
                                'element': item.get('element', 0),
                                'character_restriction': item.get('character_restriction', 65535),
                                # Stats
                                'hp': item.get('hp', 0),
                                'ep': item.get('ep', 0),
                                'str': item.get('str', 0),
                                'def': item.get('def', 0),
                                'ats': item.get('ats', 0),
                                'adf': item.get('adf', 0),
                                'agl': item.get('agl', 0),
                                'dex': item.get('dex', 0),
                                'spd': item.get('spd', 0),
                                'mov': item.get('mov', 0),
                            }
    except Exception as e:
        print(f"{Fore.YELLOW}Warning: Could not load t_item.json: {e}{Style.RESET_ALL}")
    
    # Try to load t_costume.json for costume details
    try:
        t_costume_path = os.path.join(project_dir, 't_costume.json')
        if os.path.exists(t_costume_path):
            with open(t_costume_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Extract CostumeParam
            for section in data.get('data', []):
                if section.get('name') == 'CostumeParam':
                    for costume in section.get('data', []):
                        item_id = costume.get('item_id')
                        if item_id is not None:
                            enhanced_data['costumes'][item_id] = {
                                'character_id': costume.get('character_id', 0),
                                'costume_name': costume.get('name', ''),
                                'attach_name': costume.get('attach_name', '')
                            }
    except Exception as e:
        print(f"{Fore.YELLOW}Warning: Could not load t_costume.json: {e}{Style.RESET_ALL}")
    
    # Build category and subcategory mappings from actual data
    # This creates a reverse mapping to identify common category patterns
    category_counts = defaultdict(lambda: defaultdict(int))
    for item_id, item_data in enhanced_data['items'].items():
        cat = item_data.get('category', 0)
        subcat = item_data.get('subcategory', 0)
        category_counts[cat][subcat] += 1
    
    # Create category names based on common patterns
    category_names = {
        0: 'Sepith/Materials',
        1: 'Quest Items',
        2: 'Books/Documents',
        17: 'Costumes',
        30: 'Consumables/Currency'
    }
    
    for cat in category_counts.keys():
        if cat not in category_names:
            category_names[cat] = f'Category {cat}'
    
    enhanced_data['categories'] = category_names
    
    # Character names mapping (common character IDs)
    enhanced_data['character_names'] = {
        0: 'Van',
        1: 'Agnès',
        2: 'Feri',
        3: 'Aaron',
        4: 'Risette',
        5: 'Quatre',
        6: 'Bergard',
        7: 'Judith',
        # Add more as discovered
    }
    
    return enhanced_data


# -------------------------
# Data loading functions (adapted from existing scripts)
# -------------------------

def detect_sources(base_name='t_item'):
    """Detect available data sources for items."""
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
    print(f"\n{Fore.CYAN}Multiple data sources detected. Select source to use:{Style.RESET_ALL}")
    for i, (stype, path) in enumerate(sources, 1):
        if stype in ('p3a', 'zzz'):
            print(f"  {Fore.YELLOW}{i}{Style.RESET_ALL}) {path} (extract t_item.tbl)")
        else:
            print(f"  {Fore.YELLOW}{i}{Style.RESET_ALL}) {path}")
    
    while True:
        try:
            choice = input(f"\nEnter choice [1-{len(sources)}]: ").strip()
            idx = int(choice)
            if 1 <= idx <= len(sources):
                return sources[idx - 1]
            print(f"{Fore.RED}Invalid choice. Please enter a number between 1 and {len(sources)}.{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.RED}Invalid input. Please enter a number.{Style.RESET_ALL}")
        except KeyboardInterrupt:
            print(f"\n\n{Fore.YELLOW}Operation cancelled by user.{Style.RESET_ALL}")
            sys.exit(0)


def extract_from_p3a(p3a_file, table_name='t_item.tbl', out_file='t_item.tbl.tmp'):
    """Extract a TBL file from a P3A archive."""
    if not HAS_LIBS:
        print(f"{Fore.RED}Error: Required library missing: {MISSING_LIB}{Style.RESET_ALL}")
        print("P3A extraction requires p3a_lib module.")
        return False
    
    try:
        if not os.path.exists(p3a_file):
            print(f"{Fore.RED}Error: P3A file not found: {p3a_file}{Style.RESET_ALL}")
            return False
        
        p3a = p3a_class()
        print(f"{Fore.CYAN}Extracting {table_name} from {p3a_file}...{Style.RESET_ALL}")
        
        with open(p3a_file, 'rb') as p3a.f:
            headers, entries, p3a_dict = p3a.read_p3a_toc()
            
            for entry in entries:
                if os.path.basename(entry['name']) == table_name:
                    data = p3a.read_file(entry, p3a_dict)
                    with open(out_file, 'wb') as f:
                        f.write(data)
                    print(f"{Fore.GREEN}Successfully extracted to {out_file}{Style.RESET_ALL}")
                    return True
            
            print(f"{Fore.RED}Error: {table_name} not found in {p3a_file}{Style.RESET_ALL}")
            return False
    
    except Exception as e:
        print(f"{Fore.RED}Error extracting from P3A: {e}{Style.RESET_ALL}")
        return False


def load_items_from_json(json_file='t_item.json'):
    """Load item data from JSON file."""
    try:
        if not os.path.exists(json_file):
            print(f"{Fore.RED}Error: JSON file not found: {json_file}{Style.RESET_ALL}")
            return None
        
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Handle different JSON structures
        if isinstance(data, dict):
            # Structure: {"data": [{"name": "ItemTableData", "data": [...]}]}
            if "data" in data and isinstance(data["data"], list):
                for section in data["data"]:
                    if section.get("name") == "ItemTableData":
                        items = section.get("data", [])
                        if not items:
                            print(f"{Fore.YELLOW}Warning: No items found in ItemTableData section{Style.RESET_ALL}")
                        return items
                
                print(f"{Fore.YELLOW}Warning: ItemTableData section not found in {json_file}{Style.RESET_ALL}")
                return []
            
            # Direct structure: {ItemTableData: [...]}
            elif "ItemTableData" in data:
                items = data["ItemTableData"]
                if not isinstance(items, list):
                    print(f"{Fore.RED}Error: ItemTableData is not a list in {json_file}{Style.RESET_ALL}")
                    return None
                return items
        
        print(f"{Fore.RED}Error: Unexpected JSON structure in {json_file}{Style.RESET_ALL}")
        return None
    
    except json.JSONDecodeError as e:
        print(f"{Fore.RED}Error: Invalid JSON in {json_file}: {e}{Style.RESET_ALL}")
        return None
    except Exception as e:
        print(f"{Fore.RED}Error loading {json_file}: {e}{Style.RESET_ALL}")
        return None


def load_items_from_tbl(tbl_file):
    """Load item data from TBL file."""
    if not HAS_LIBS:
        print(f"{Fore.RED}Error: Required library missing: {MISSING_LIB}{Style.RESET_ALL}")
        print("TBL reading requires kurodlc_lib module.")
        return None
    
    try:
        if not os.path.exists(tbl_file):
            print(f"{Fore.RED}Error: TBL file not found: {tbl_file}{Style.RESET_ALL}")
            return None
        
        kt = kuro_tables()
        table = kt.read_table(tbl_file)
        
        if not isinstance(table, dict):
            print(f"{Fore.RED}Error: Invalid TBL structure in {tbl_file}{Style.RESET_ALL}")
            return None
        
        if 'ItemTableData' not in table:
            print(f"{Fore.RED}Error: ItemTableData section not found in {tbl_file}{Style.RESET_ALL}")
            return None
        
        items = table['ItemTableData']
        if not isinstance(items, list):
            print(f"{Fore.RED}Error: ItemTableData is not a list in {tbl_file}{Style.RESET_ALL}")
            return None
        
        if not items:
            print(f"{Fore.YELLOW}Warning: No items found in ItemTableData section{Style.RESET_ALL}")
        
        return items
    
    except Exception as e:
        print(f"{Fore.RED}Error loading {tbl_file}: {e}{Style.RESET_ALL}")
        return None


def load_items(force_source=None, no_interactive=False, keep_extracted=False):
    """
    Load item data from any supported source format.
    
    Returns:
        Tuple of (items_list, source_info) or (None, None) on error
    """
    # Detect available sources
    sources = detect_sources('t_item')
    
    if not sources:
        print(f"{Fore.RED}Error: No data sources found for t_item{Style.RESET_ALL}")
        print(f"\n{Fore.YELLOW}Looked for:{Style.RESET_ALL}")
        print(f"  - t_item.json")
        print(f"  - t_item.tbl.original")
        print(f"  - t_item.tbl")
        print(f"  - script_en.p3a / script_eng.p3a")
        print(f"  - zzz_combined_tables.p3a")
        return None, None
    
    # Filter by forced source if specified
    if force_source:
        sources = [(t, p) for t, p in sources if t == force_source]
        if not sources:
            print(f"{Fore.RED}Error: No sources found matching type '{force_source}'{Style.RESET_ALL}")
            return None, None
    
    # Select source
    if len(sources) == 1 or no_interactive:
        stype, path = sources[0]
        print(f"{Fore.CYAN}Using source: {path}{Style.RESET_ALL}")
    else:
        stype, path = select_source_interactive(sources)
    
    # Load data based on source type
    temp_file = None
    extracted_temp = False
    
    try:
        if stype == 'json':
            items = load_items_from_json(path)
            source_info = {'type': 'json', 'path': path}
        
        elif stype in ('tbl', 'original'):
            items = load_items_from_tbl(path)
            source_info = {'type': stype, 'path': path}
        
        elif stype in ('p3a', 'zzz'):
            # Extract TBL from P3A
            temp_file = 't_item.tbl.tmp'
            if extract_from_p3a(path, 't_item.tbl', temp_file):
                extracted_temp = True
                items = load_items_from_tbl(temp_file)
                source_info = {'type': stype, 'path': f"{path} -> {temp_file}"}
            else:
                print(f"{Fore.RED}Failed to extract t_item.tbl from {path}{Style.RESET_ALL}")
                return None, None
        
        else:
            print(f"{Fore.RED}Error: Unknown source type '{stype}'{Style.RESET_ALL}")
            return None, None
        
        # Cleanup temporary files
        if extracted_temp and temp_file and not keep_extracted:
            if os.path.exists(temp_file):
                os.remove(temp_file)
                print(f"{Fore.CYAN}Cleaned up temporary file: {temp_file}{Style.RESET_ALL}")
        
        return items, source_info
    
    except Exception as e:
        print(f"{Fore.RED}Error during data loading: {e}{Style.RESET_ALL}")
        
        # Cleanup on error
        if extracted_temp and temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        
        return None, None


# -------------------------
# ID Analysis functions
# -------------------------

def analyze_ids(items):
    """
    Analyze ID allocation from items list.
    Uses Kuro Engine maximum ID limit (KURO_ENGINE_MAX_ID) for range calculation.
    Grid will always show full range from 1 to KURO_ENGINE_MAX_ID, not just to last occupied ID.
    
    Returns:
        Dictionary with analysis results
    """
    if not items:
        return None
    
    # Extract IDs
    ids = sorted(set(item['id'] for item in items if 'id' in item))
    
    if not ids:
        return None
    
    # Use engine limits for range calculation
    min_id = 1  # Always start from 1 (engine minimum)
    max_id = KURO_ENGINE_MAX_ID  # Always go to engine maximum (5000)
    actual_max_occupied = max(ids)  # Highest actually used ID (for info)
    
    total_range = max_id - min_id + 1
    occupied_count = len(ids)
    free_count = total_range - occupied_count
    
    # Find free IDs in the full engine range
    all_ids_in_range = set(range(min_id, max_id + 1))
    free_ids = sorted(all_ids_in_range - set(ids))
    
    # Find free blocks (consecutive free IDs)
    free_blocks = []
    if free_ids:
        block_start = free_ids[0]
        block_end = free_ids[0]
        
        for i in range(1, len(free_ids)):
            if free_ids[i] == block_end + 1:
                block_end = free_ids[i]
            else:
                free_blocks.append((block_start, block_end, block_end - block_start + 1))
                block_start = free_ids[i]
                block_end = free_ids[i]
        
        # Add last block
        free_blocks.append((block_start, block_end, block_end - block_start + 1))
        
        # Sort by size (descending)
        free_blocks.sort(key=lambda x: x[2], reverse=True)
    
    # Calculate fragmentation
    fragmentation = (len(free_blocks) / total_range * 100) if total_range > 0 else 0
    
    return {
        'ids': ids,
        'free_ids': free_ids,
        'min_id': min_id,
        'max_id': max_id,
        'actual_max_occupied': actual_max_occupied,  # For informational purposes
        'total_range': total_range,
        'occupied_count': occupied_count,
        'free_count': free_count,
        'occupation_percent': (occupied_count / total_range * 100) if total_range > 0 else 0,
        'free_blocks': free_blocks,
        'fragmentation': fragmentation
    }


def find_optimal_block_size(total_range):
    """Determine optimal block size for visualization based on range."""
    if total_range <= 500:
        return 10
    elif total_range <= 1000:
        return 20
    elif total_range <= 2500:
        return 50
    elif total_range <= 5000:
        return 100
    else:
        return 200


# -------------------------
# Console visualization
# -------------------------

def visualize_console(analysis, block_size=None, source_info=None):
    """Generate color-coded console visualization of ID allocation."""
    
    if analysis is None:
        print(f"{Fore.RED}No analysis data available{Style.RESET_ALL}")
        return
    
    # Auto-determine block size if not specified
    if block_size is None:
        block_size = find_optimal_block_size(analysis['total_range'])
    
    print(f"\n{Fore.CYAN}{'='*80}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}ID ALLOCATION MAP{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*80}{Style.RESET_ALL}\n")
    
    if source_info:
        print(f"{Fore.YELLOW}Source:{Style.RESET_ALL} {source_info['path']}\n")
    
    # Statistics
    print(f"{Fore.CYAN}Statistics:{Style.RESET_ALL}")
    print(f"  Engine Range:    {analysis['min_id']} - {analysis['max_id']} (Kuro Engine limit)")
    print(f"  Highest Used ID: {Fore.MAGENTA}{analysis['actual_max_occupied']}{Style.RESET_ALL}")
    print(f"  Total Range:     {analysis['total_range']} IDs")
    print(f"  Occupied IDs:    {Fore.GREEN}{analysis['occupied_count']}{Style.RESET_ALL} ({analysis['occupation_percent']:.1f}%)")
    print(f"  Free IDs:        {Fore.YELLOW}{analysis['free_count']}{Style.RESET_ALL} ({100 - analysis['occupation_percent']:.1f}%)")
    print(f"  Free Blocks:     {len(analysis['free_blocks'])}")
    print(f"  Fragmentation:   {analysis['fragmentation']:.2f}%")
    print()
    
    # Legend
    if USE_COLOR:
        print(f"{Fore.CYAN}Legend:{Style.RESET_ALL}")
        print(f"  {Back.GREEN} {Style.RESET_ALL} Occupied ID")
        print(f"  {Back.BLACK} {Style.RESET_ALL} Free ID")
        print()
    
    # Visualization blocks
    print(f"{Fore.CYAN}Allocation Map (Block size: {block_size} IDs):{Style.RESET_ALL}\n")
    
    ids_set = set(analysis['ids'])
    min_id = analysis['min_id']
    max_id = analysis['max_id']
    
    # Calculate blocks
    num_blocks = (max_id - min_id) // block_size + 1
    
    for block_idx in range(num_blocks):
        block_start = min_id + (block_idx * block_size)
        block_end = min(block_start + block_size - 1, max_id)
        
        # Count occupied in this block
        occupied_in_block = sum(1 for id in range(block_start, block_end + 1) if id in ids_set)
        total_in_block = block_end - block_start + 1
        occupation_ratio = occupied_in_block / total_in_block
        
        # Visual representation
        bar_length = 50
        filled = int(bar_length * occupation_ratio)
        
        if USE_COLOR:
            bar = f"{Back.GREEN}{' ' * filled}{Style.RESET_ALL}{Back.BLACK}{' ' * (bar_length - filled)}{Style.RESET_ALL}"
        else:
            bar = '█' * filled + '░' * (bar_length - filled)
        
        # Print block info
        range_str = f"[{block_start:5d} - {block_end:5d}]"
        stats_str = f"{occupied_in_block:4d}/{total_in_block:4d} ({occupation_ratio * 100:5.1f}%)"
        print(f"{range_str} {bar} {stats_str}")
    
    print()
    
    # Top free blocks
    if analysis['free_blocks']:
        print(f"{Fore.CYAN}Top 10 Largest Free Blocks:{Style.RESET_ALL}\n")
        
        for i, (start, end, size) in enumerate(analysis['free_blocks'][:10], 1):
            if size == 1:
                range_str = f"{start}"
            else:
                range_str = f"{start} - {end}"
            print(f"  {i:2d}. {Fore.YELLOW}[{range_str:20s}]{Style.RESET_ALL} Size: {Fore.GREEN}{size:5d}{Style.RESET_ALL} IDs")
        
        print()
    
    print(f"{Fore.CYAN}{'='*80}{Style.RESET_ALL}\n")


# -------------------------
# HTML report generation
# -------------------------

def generate_html_report(analysis, output_file='id_allocation_map.html', source_info=None, enhanced_data=None):
    """Generate HTML report with interactive visualization and enhanced item information."""
    
    if analysis is None:
        print(f"{Fore.RED}No analysis data available for HTML generation{Style.RESET_ALL}")
        return False
    
    try:
        # Prepare data for visualization
        ids_set = set(analysis['ids'])
        min_id = analysis['min_id']
        max_id = analysis['max_id']
        
        # Generate grid data (100 cells per row for better visualization)
        cells_per_row = 100
        total_ids = max_id - min_id + 1
        
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ID Allocation Map</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            color: #333;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        
        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }}
        
        .header p {{
            font-size: 1.1em;
            opacity: 0.9;
        }}
        
        .stats-container {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            padding: 30px;
            background: #f8f9fa;
        }}
        
        .stat-card {{
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            text-align: center;
            transition: transform 0.2s;
        }}
        
        .stat-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        }}
        
        .stat-label {{
            font-size: 0.9em;
            color: #666;
            margin-bottom: 10px;
        }}
        
        .stat-value {{
            font-size: 2em;
            font-weight: bold;
            color: #667eea;
        }}
        
        .stat-subvalue {{
            font-size: 0.9em;
            color: #999;
            margin-top: 5px;
        }}
        
        .legend {{
            padding: 20px 30px;
            background: #f0f0f0;
            border-top: 1px solid #ddd;
            border-bottom: 1px solid #ddd;
        }}
        
        .legend-items {{
            display: flex;
            justify-content: center;
            gap: 30px;
            flex-wrap: wrap;
        }}
        
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        
        .legend-color {{
            width: 30px;
            height: 30px;
            border-radius: 5px;
            border: 1px solid #ccc;
        }}
        
        .legend-color.occupied {{
            background: #4caf50;
        }}
        
        .legend-color.free {{
            background: #e0e0e0;
        }}
        
        .map-container {{
            padding: 30px;
        }}
        
        .map-grid {{
            display: grid;
            grid-template-columns: repeat({cells_per_row}, 1fr);
            gap: 2px;
            margin-top: 20px;
        }}
        
        .id-cell {{
            aspect-ratio: 1;
            border-radius: 2px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        
        .id-cell.occupied {{
            background: #4caf50;
        }}
        
        .id-cell.free {{
            background: #e0e0e0;
        }}
        
        .id-cell:hover {{
            transform: scale(1.5);
            box-shadow: 0 0 10px rgba(0,0,0,0.5);
            z-index: 10;
        }}
        
        .tooltip {{
            position: absolute;
            background: rgba(0,0,0,0.95);
            color: white;
            padding: 15px;
            border-radius: 8px;
            font-size: 0.9em;
            pointer-events: none;
            z-index: 1000;
            display: none;
            min-width: 280px;
            max-width: 400px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        }}
        
        .tooltip-header {{
            font-size: 1.1em;
            font-weight: bold;
            margin-bottom: 8px;
            padding-bottom: 8px;
            border-bottom: 1px solid rgba(255,255,255,0.3);
        }}
        
        .tooltip-section {{
            margin: 8px 0;
        }}
        
        .tooltip-label {{
            color: #aaa;
            font-size: 0.85em;
            text-transform: uppercase;
            margin-bottom: 3px;
        }}
        
        .tooltip-value {{
            color: #fff;
            margin-bottom: 5px;
        }}
        
        .tooltip-stats {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 5px;
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid rgba(255,255,255,0.2);
        }}
        
        .tooltip-stat {{
            font-size: 0.85em;
        }}
        
        .tooltip-stat-label {{
            color: #888;
        }}
        
        .tooltip-stat-value {{
            color: #4caf50;
            font-weight: bold;
        }}
        
        .tooltip-badge {{
            display: inline-block;
            background: #667eea;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 0.8em;
            margin: 2px;
        }}
        
        .search-container {{
            padding: 20px 30px;
            background: #f8f9fa;
            border-bottom: 2px solid #e0e0e0;
        }}
        
        .search-box {{
            display: flex;
            gap: 15px;
            align-items: center;
            max-width: 800px;
        }}
        
        .search-input {{
            flex: 1;
            padding: 12px 20px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 1em;
            transition: all 0.3s;
        }}
        
        .search-input:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }}
        
        .search-btn {{
            padding: 12px 24px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1em;
            cursor: pointer;
            transition: all 0.3s;
            font-weight: 600;
        }}
        
        .search-btn:hover {{
            background: #5568d3;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        }}
        
        .clear-btn {{
            padding: 12px 24px;
            background: #f0f0f0;
            color: #333;
            border: none;
            border-radius: 8px;
            font-size: 1em;
            cursor: pointer;
            transition: all 0.3s;
            font-weight: 600;
        }}
        
        .clear-btn:hover {{
            background: #e0e0e0;
        }}
        
        .search-results {{
            margin-top: 15px;
            padding: 10px 15px;
            background: white;
            border-radius: 8px;
            display: none;
        }}
        
        .search-results.visible {{
            display: block;
        }}
        
        .id-cell.highlighted {{
            animation: highlight-pulse 1.5s ease-in-out infinite;
            box-shadow: 0 0 15px rgba(255, 193, 7, 0.8) !important;
            border: 2px solid #ffc107 !important;
        }}
        
        @keyframes highlight-pulse {{
            0%, 100% {{
                transform: scale(1);
                box-shadow: 0 0 15px rgba(255, 193, 7, 0.8);
            }}
            50% {{
                transform: scale(1.2);
                box-shadow: 0 0 25px rgba(255, 193, 7, 1);
            }}
        }}
        
        .free-blocks {{
            padding: 30px;
            background: #f8f9fa;
        }}
        
        .free-blocks h2 {{
            color: #667eea;
            margin-bottom: 20px;
        }}
        
        .block-list {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 15px;
        }}
        
        .block-item {{
            background: white;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #ffc107;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        
        .block-rank {{
            display: inline-block;
            background: #ffc107;
            color: white;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.8em;
            font-weight: bold;
            margin-right: 10px;
        }}
        
        .block-range {{
            font-weight: bold;
            color: #333;
            margin: 5px 0;
        }}
        
        .block-size {{
            color: #4caf50;
            font-weight: bold;
        }}
        
        .footer {{
            padding: 20px;
            text-align: center;
            background: #f0f0f0;
            color: #666;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🗺️ ID Allocation Map</h1>
            <p>Visual analysis of item ID distribution and availability</p>
            {f'<p style="margin-top: 10px; font-size: 0.9em;">Source: {source_info["path"]}</p>' if source_info else ''}
        </div>
        
        <div class="stats-container">
            <div class="stat-card">
                <div class="stat-label">Engine Range</div>
                <div class="stat-value">{analysis['min_id']} - {analysis['max_id']}</div>
                <div class="stat-subvalue">Kuro Engine limit</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">Highest Used ID</div>
                <div class="stat-value" style="color: #9b59b6;">{analysis['actual_max_occupied']}</div>
                <div class="stat-subvalue">{analysis['total_range']} total IDs</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">Occupied IDs</div>
                <div class="stat-value">{analysis['occupied_count']}</div>
                <div class="stat-subvalue">{analysis['occupation_percent']:.1f}%</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">Free IDs</div>
                <div class="stat-value">{analysis['free_count']}</div>
                <div class="stat-subvalue">{100 - analysis['occupation_percent']:.1f}%</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-label">Free Blocks</div>
                <div class="stat-value">{len(analysis['free_blocks'])}</div>
                <div class="stat-subvalue">{analysis['fragmentation']:.2f}% fragmentation</div>
            </div>
        </div>
        
        <div class="legend">
            <div class="legend-items">
                <div class="legend-item">
                    <div class="legend-color occupied"></div>
                    <span>Occupied ID</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color free"></div>
                    <span>Free ID</span>
                </div>
            </div>
        </div>
        
        <div class="search-container">
            <div class="search-box">
                <input type="text" id="search-input" class="search-input" placeholder="Search by ID, name, description, category...">
                <button onclick="performSearch()" class="search-btn">🔍 Search</button>
                <button onclick="clearSearch()" class="clear-btn">✕ Clear</button>
            </div>
            <div id="search-results" class="search-results"></div>
        </div>
        
        <div class="map-container">
            <h2 style="color: #667eea; margin-bottom: 10px;">Allocation Grid</h2>
            <p style="color: #666; margin-bottom: 20px;">Hover over cells to see ID details. Each cell represents one ID.</p>
            <div class="map-grid" id="map-grid">
"""
        
        # Generate grid cells with enhanced information
        for id_val in range(min_id, max_id + 1):
            is_occupied = id_val in ids_set
            cell_class = 'occupied' if is_occupied else 'free'
            status = 'Occupied' if is_occupied else 'Available'
            
            # Build data attributes for tooltip
            data_attrs = f'data-id="{id_val}" data-status="{status}"'
            
            # Add enhanced information if available
            if enhanced_data and is_occupied:
                item_info = enhanced_data.get('items', {}).get(id_val)
                if item_info:
                    # Escape quotes in strings for HTML attributes
                    def escape_attr(s):
                        return str(s).replace('"', '&quot;').replace("'", '&#39;')
                    
                    name = escape_attr(item_info.get('name', ''))
                    desc = escape_attr(item_info.get('description', ''))
                    category = item_info.get('category', 0)
                    subcategory = item_info.get('subcategory', 0)
                    price = item_info.get('price', 0)
                    stack_size = item_info.get('stack_size', 1)
                    
                    # Get category name
                    category_name = enhanced_data.get('categories', {}).get(category, f'Category {category}')
                    
                    # Build attributes
                    if name:
                        data_attrs += f' data-name="{name}"'
                    if desc:
                        data_attrs += f' data-description="{desc}"'
                    data_attrs += f' data-category="{category}"'
                    data_attrs += f' data-category-name="{escape_attr(category_name)}"'
                    data_attrs += f' data-subcategory="{subcategory}"'
                    data_attrs += f' data-price="{price}"'
                    data_attrs += f' data-stack="{stack_size}"'
                    
                    # Add stats if non-zero
                    stats = []
                    for stat_name in ['hp', 'ep', 'str', 'def', 'ats', 'adf', 'agl', 'dex', 'spd', 'mov']:
                        value = item_info.get(stat_name, 0)
                        if value != 0:
                            stats.append(f'{stat_name}:{value}')
                    if stats:
                        data_attrs += f' data-stats="{escape_attr(",".join(stats))}"'
                    
                    # Check for costume info
                    costume_info = enhanced_data.get('costumes', {}).get(id_val)
                    if costume_info:
                        costume_name = escape_attr(costume_info.get('costume_name', ''))
                        char_id = costume_info.get('character_id', 0)
                        char_name = enhanced_data.get('character_names', {}).get(char_id, f'Character {char_id}')
                        data_attrs += f' data-costume="{costume_name}"'
                        data_attrs += f' data-character="{escape_attr(char_name)}"'
            
            html_content += f'                <div class="id-cell {cell_class}" {data_attrs}></div>\n'
        
        html_content += """            </div>
        </div>
"""
        
        # Free blocks section
        if analysis['free_blocks']:
            html_content += """        <div class="free-blocks">
            <h2>📋 Top Free Blocks</h2>
            <div class="block-list">
"""
            
            for i, (start, end, size) in enumerate(analysis['free_blocks'][:20], 1):
                if size == 1:
                    range_str = f"ID {start}"
                else:
                    range_str = f"IDs {start} - {end}"
                
                html_content += f"""                <div class="block-item">
                    <span class="block-rank">#{i}</span>
                    <div class="block-range">{range_str}</div>
                    <div class="block-size">Size: {size} IDs</div>
                </div>
"""
            
            html_content += """            </div>
        </div>
"""
        
        html_content += """        <div class="footer">
            Generated by visualize_id_allocation.py
        </div>
    </div>
    
    <div class="tooltip" id="tooltip"></div>
    
    <script>
        // Enhanced tooltip handling
        const tooltip = document.getElementById('tooltip');
        const cells = document.querySelectorAll('.id-cell');
        
        // Smart tooltip positioning function
        function positionTooltip(e) {
            // Get tooltip dimensions
            const tooltipRect = tooltip.getBoundingClientRect();
            const tooltipWidth = tooltipRect.width || 280; // Fallback to min-width
            const tooltipHeight = tooltipRect.height || 200; // Fallback estimate
            
            // Get viewport dimensions
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            
            // Calculate initial position (right and below cursor)
            let left = e.pageX + 15;
            let top = e.pageY + 15;
            
            // Check right edge - if tooltip would overflow, show it to the left of cursor
            if (e.clientX + tooltipWidth + 15 > viewportWidth) {
                left = e.pageX - tooltipWidth - 15;
            }
            
            // Check bottom edge - if tooltip would overflow, show it above cursor
            if (e.clientY + tooltipHeight + 15 > viewportHeight) {
                top = e.pageY - tooltipHeight - 15;
            }
            
            // Make sure tooltip doesn't go off the left edge
            if (left < 0) {
                left = 10;
            }
            
            // Make sure tooltip doesn't go off the top edge
            if (top < 0) {
                top = 10;
            }
            
            tooltip.style.left = left + 'px';
            tooltip.style.top = top + 'px';
        }
        
        cells.forEach(cell => {
            cell.addEventListener('mouseenter', (e) => {
                const id = cell.getAttribute('data-id');
                const status = cell.getAttribute('data-status');
                const name = cell.getAttribute('data-name');
                const description = cell.getAttribute('data-description');
                const category = cell.getAttribute('data-category');
                const categoryName = cell.getAttribute('data-category-name');
                const subcategory = cell.getAttribute('data-subcategory');
                const price = cell.getAttribute('data-price');
                const stack = cell.getAttribute('data-stack');
                const stats = cell.getAttribute('data-stats');
                const costume = cell.getAttribute('data-costume');
                const character = cell.getAttribute('data-character');
                
                // Build tooltip content
                let content = '<div class="tooltip-header">ID ' + id;
                if (status === 'Available') {
                    content += ' <span style="color: #ffc107;">(Available)</span>';
                }
                content += '</div>';
                
                if (name) {
                    content += '<div class="tooltip-section">';
                    content += '<div class="tooltip-label">Name</div>';
                    content += '<div class="tooltip-value">' + name + '</div>';
                    content += '</div>';
                }
                
                if (description) {
                    content += '<div class="tooltip-section">';
                    content += '<div class="tooltip-label">Description</div>';
                    content += '<div class="tooltip-value" style="font-size: 0.85em;">' + description + '</div>';
                    content += '</div>';
                }
                
                if (categoryName) {
                    content += '<div class="tooltip-section">';
                    content += '<span class="tooltip-badge">' + categoryName + '</span>';
                    if (subcategory && subcategory !== '0') {
                        content += '<span class="tooltip-badge">Subcat: ' + subcategory + '</span>';
                    }
                    content += '</div>';
                }
                
                if (character) {
                    content += '<div class="tooltip-section">';
                    content += '<div class="tooltip-label">Character</div>';
                    content += '<div class="tooltip-value">' + character;
                    if (costume) {
                        content += ' - ' + costume;
                    }
                    content += '</div>';
                    content += '</div>';
                }
                
                if (price && price !== '0') {
                    content += '<div class="tooltip-section">';
                    content += '<div class="tooltip-label">Price / Stack</div>';
                    content += '<div class="tooltip-value">' + price + ' mira';
                    if (stack && stack !== '1') {
                        content += ' (Stack: ' + stack + ')';
                    }
                    content += '</div>';
                    content += '</div>';
                }
                
                if (stats) {
                    content += '<div class="tooltip-stats">';
                    const statPairs = stats.split(',');
                    statPairs.forEach(statPair => {
                        const [statName, statValue] = statPair.split(':');
                        content += '<div class="tooltip-stat">';
                        content += '<span class="tooltip-stat-label">' + statName.toUpperCase() + ':</span> ';
                        content += '<span class="tooltip-stat-value">+' + statValue + '</span>';
                        content += '</div>';
                    });
                    content += '</div>';
                }
                
                if (status === 'Available') {
                    content += '<div class="tooltip-section" style="margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.2);">';
                    content += '<div style="color: #4caf50; font-weight: bold;">✓ This ID is available for use</div>';
                    content += '</div>';
                }
                
                tooltip.innerHTML = content;
                tooltip.style.display = 'block';
                
                // Position tooltip immediately (prevents initial flash at wrong position)
                positionTooltip(e);
            });
            
            cell.addEventListener('mousemove', (e) => {
                // Update position as mouse moves
                positionTooltip(e);
            });
            
            cell.addEventListener('mouseleave', () => {
                tooltip.style.display = 'none';
            });
        });
        
        // Search functionality
        function performSearch() {
            const searchTerm = document.getElementById('search-input').value.toLowerCase().trim();
            const cells = document.querySelectorAll('.id-cell');
            const resultsDiv = document.getElementById('search-results');
            
            // Clear previous highlights
            clearSearch();
            
            if (!searchTerm) {
                resultsDiv.textContent = 'Please enter a search term.';
                resultsDiv.classList.add('visible');
                return;
            }
            
            const matches = [];
            
            cells.forEach(cell => {
                const id = cell.getAttribute('data-id');
                const name = (cell.getAttribute('data-name') || '').toLowerCase();
                const description = (cell.getAttribute('data-description') || '').toLowerCase();
                const categoryName = (cell.getAttribute('data-category-name') || '').toLowerCase();
                const character = (cell.getAttribute('data-character') || '').toLowerCase();
                const costume = (cell.getAttribute('data-costume') || '').toLowerCase();
                
                // Check if search term matches any attribute
                if (id.includes(searchTerm) || 
                    name.includes(searchTerm) || 
                    description.includes(searchTerm) || 
                    categoryName.includes(searchTerm) ||
                    character.includes(searchTerm) ||
                    costume.includes(searchTerm)) {
                    
                    cell.classList.add('highlighted');
                    matches.push({
                        id: id,
                        name: cell.getAttribute('data-name') || 'N/A',
                        category: categoryName || 'N/A'
                    });
                }
            });
            
            // Display results
            if (matches.length === 0) {
                resultsDiv.innerHTML = '<span style="color: #999;">No matches found for "' + searchTerm + '"</span>';
            } else {
                let html = '<strong style="color: #667eea;">Found ' + matches.length + ' match(es):</strong> ';
                
                if (matches.length <= 10) {
                    // Show all matches if 10 or fewer
                    const matchList = matches.map(m => 
                        '<span style="color: #4caf50; font-weight: bold;">ID ' + m.id + '</span> (' + m.name + ')'
                    ).join(', ');
                    html += matchList;
                } else {
                    // Show first 10 and count
                    const matchList = matches.slice(0, 10).map(m => 
                        '<span style="color: #4caf50; font-weight: bold;">ID ' + m.id + '</span> (' + m.name + ')'
                    ).join(', ');
                    html += matchList + ', <span style="color: #999;">... and ' + (matches.length - 10) + ' more</span>';
                }
                
                resultsDiv.innerHTML = html;
                
                // Scroll to first match
                if (matches.length > 0) {
                    const firstMatch = document.querySelector('.id-cell.highlighted');
                    if (firstMatch) {
                        firstMatch.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }
                }
            }
            
            resultsDiv.classList.add('visible');
        }
        
        function clearSearch() {
            const cells = document.querySelectorAll('.id-cell.highlighted');
            cells.forEach(cell => cell.classList.remove('highlighted'));
            
            const resultsDiv = document.getElementById('search-results');
            resultsDiv.classList.remove('visible');
            resultsDiv.innerHTML = '';
        }
        
        // Allow Enter key to trigger search
        document.getElementById('search-input').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                performSearch();
            }
        });
    </script>
</body>
</html>"""
        
        # Write HTML file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"{Fore.GREEN}HTML report generated: {output_file}{Style.RESET_ALL}")
        return True
    
    except Exception as e:
        print(f"{Fore.RED}Error generating HTML report: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()
        return False


# -------------------------
# Main script
# -------------------------

def print_usage():
    """Print usage information."""
    print(__doc__)


def main():
    """Main function."""
    # Default options
    force_source = None
    no_interactive = False
    keep_extracted = False
    output_format = 'both'  # console, html, or both
    block_size = None  # Auto-determine
    html_output = 'id_allocation_map.html'
    
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
                print(f"{Fore.RED}Error: Invalid source type '{force_source}'{Style.RESET_ALL}")
                print("Valid types: json, tbl, original, p3a, zzz")
                sys.exit(1)
        
        elif arg.startswith('--format='):
            output_format = arg.split('=', 1)[1]
            if output_format not in ('console', 'html', 'both'):
                print(f"{Fore.RED}Error: Invalid format '{output_format}'{Style.RESET_ALL}")
                print("Valid formats: console, html, both")
                sys.exit(1)
        
        elif arg.startswith('--block-size='):
            try:
                block_size = int(arg.split('=', 1)[1])
                if block_size < 1:
                    raise ValueError
            except ValueError:
                print(f"{Fore.RED}Error: Invalid block size. Must be a positive integer.{Style.RESET_ALL}")
                sys.exit(1)
        
        elif arg.startswith('--output='):
            html_output = arg.split('=', 1)[1]
            if not html_output.endswith('.html'):
                html_output += '.html'
        
        elif arg == '--no-interactive':
            no_interactive = True
        
        elif arg == '--keep-extracted':
            keep_extracted = True
        
        elif arg.startswith('--'):
            print(f"{Fore.RED}Error: Unknown option '{arg}'{Style.RESET_ALL}")
            print("Use --help for usage information.")
            sys.exit(1)
    
    # Load data
    print(f"{Fore.CYAN}Loading item data...{Style.RESET_ALL}\n")
    items, source_info = load_items(force_source, no_interactive, keep_extracted)
    
    if items is None:
        print(f"\n{Fore.RED}Failed to load item data.{Style.RESET_ALL}")
        sys.exit(1)
    
    if not items:
        print(f"\n{Fore.YELLOW}No items found in source.{Style.RESET_ALL}")
        sys.exit(0)
    
    print(f"\n{Fore.GREEN}Loaded {len(items)} items{Style.RESET_ALL}\n")
    
    # Extract enhanced data from loaded items (works with any source: JSON, TBL, P3A)
    print(f"{Fore.CYAN}Extracting enhanced data from items...{Style.RESET_ALL}")
    enhanced_data = extract_enhanced_data_from_items(items)
    
    # Load costume data from available sources
    costume_data = load_costume_data('.')
    enhanced_data['costumes'] = costume_data
    
    # Report what was loaded
    if enhanced_data:
        items_count = len(enhanced_data.get('items', {}))
        costumes_count = len(enhanced_data.get('costumes', {}))
        categories_count = len(enhanced_data.get('categories', {}))
        
        print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Item details: {items_count} items")
        if costumes_count > 0:
            print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Costume info: {costumes_count} costumes")
        print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Categories: {categories_count} categories")
        print()
    
    # Analyze IDs
    print(f"{Fore.CYAN}Analyzing ID allocation...{Style.RESET_ALL}\n")
    analysis = analyze_ids(items)
    
    if analysis is None:
        print(f"{Fore.RED}Failed to analyze IDs{Style.RESET_ALL}")
        sys.exit(1)
    
    # Generate outputs
    if output_format in ('console', 'both'):
        visualize_console(analysis, block_size, source_info)
    
    if output_format in ('html', 'both'):
        generate_html_report(analysis, html_output, source_info, enhanced_data)
        print(f"\n{Fore.CYAN}Open {html_output} in your browser to view the interactive map.{Style.RESET_ALL}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{Fore.YELLOW}Operation cancelled by user.{Style.RESET_ALL}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Fore.RED}Unexpected error: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
