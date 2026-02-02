# KuroDLC Modding Toolkit

A comprehensive Python toolkit for creating and managing DLC mods for games using the KuroDLC format. This toolkit provides utilities for item discovery, ID management, conflict resolution, shop assignment automation, and **schema conversion from KuroTools**.

[![Python Version](https://img.shields.io/badge/python-3.7%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-GPL--3.0-green)](LICENSE)

> **⚠️ GPL-3.0 License Notice**  
> This project uses libraries from [eArmada8/kuro_dlc_tool](https://github.com/eArmada8/kuro_dlc_tool) which are licensed under GPL-3.0.  
> Therefore, this entire toolkit is also distributed under GPL-3.0 license.  
> See [License](#-license) section for details.

## 📋 Table of Contents

- [Why This Toolkit Exists](#-why-this-toolkit-exists)
- [Features](#-features)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [Scripts Overview](#-scripts-overview)
- [Detailed Documentation](#-detailed-documentation)
- [Common Workflows](#-common-workflows)
- [File Formats](#-file-formats)
- [Troubleshooting](#-troubleshooting)
- [Best Practices](#-best-practices)
- [Version History](#-version-history)
- [External Dependencies](#-external-dependencies)
- [Contributing](#-contributing)
- [License](#-license)
- [Advanced Documentation](#-advanced-documentation) ⭐

---

## 🎯 Why This Toolkit Exists

### The Problem

When creating DLC mods for Kuro engine games, modders face multiple challenges:

**1. ID Conflicts (Primary Problem)**
- DLC mods use item IDs that may conflict with existing game items
- Manual ID conflict detection is tedious and error-prone
- A single conflicting ID can break your entire mod
- Game engine has a hard limit of 5000 IDs that cannot be expanded
- Finding safe, available ID ranges manually is time-consuming

**2. Shop Assignment Tedium (Secondary Problem)**
- Adding items to shops requires editing hundreds of entries manually
- Assigning 50 items to 10 shops = 500 manual entries
- Copy-paste errors are common
- No easy way to bulk-update shop assignments

**3. Schema Incompatibility (New Files Problem)** ⭐ NEW
- New TBL files from game updates don't have schema definitions
- KuroTools project supports new files but uses different format
- Manual schema conversion is complex and error-prone
- Missing schemas prevent reading new TBL files

### The Solution

This toolkit automates all three problems:

**Primary: Automatic ID Conflict Resolution**
```bash
# One command to detect and fix all conflicts
python resolve_id_conflicts_in_kurodlc.py repair --apply
```
- Automatically finds safe IDs within the 5000 limit
- Smart distribution algorithm for better ID organization
- Detailed logging and automatic backups
- Manual control option for complex mods

**Secondary: Bulk Shop Assignment**
```bash
# Generate 500 shop assignments in seconds
python shops_find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json --generate-template
python shops_create.py template_my_mod.json
```
- Batch assign items to multiple shops
- Customizable templates for different shop structures
- 50 items × 10 shops = 500 entries generated instantly

**Tertiary: Schema Conversion** ⭐ NEW
```bash
# Convert KuroTools schemas to kurodlc format
python convert_kurotools_schemas.py
```
- Automatically converts 280+ schemas from KuroTools
- Adds support for new TBL files (Kuro 1, 2, Kai, Ys X, Sky)
- Expands schema coverage from 39 to 344+ structures
- Works with local schemas folder (no internet needed)

---

## ✨ Features

### Primary Purpose: ID Conflict Resolution
The main reason this toolkit was created - **automatic detection and resolution of item ID conflicts** between your DLC mods and game data. Never worry about conflicting IDs breaking your mods again!

- **⚠️ Conflict Detection**: Automatically detect ID conflicts between DLC and game data
- **🔧 Smart Resolution v2.7**: Intelligent ID assignment algorithm with 1-5000 range limit
- **🎯 Better Distribution**: IDs assigned from middle of range (2500) for optimal spacing
- **💾 Safety First**: Automatic backups and detailed logging for all modifications
- **✅ Validation**: Comprehensive .kurodlc.json structure validation

### Secondary Purpose: Bulk Shop Assignment
Quickly assign items to multiple shops without manual editing - **batch generate shop assignments** for your entire item set with a single command!

- **🛒 Shop Integration v2.1**: Generate shop assignments with customizable templates
- **📦 Bulk Operations**: Assign hundreds of items to multiple shops instantly
- **🎨 Custom Templates**: Define your own shop item structure
- **🤖 CI/CD Support**: Non-interactive mode for automated workflows

### Tertiary Purpose: Schema Conversion ⭐ NEW
Automatically convert KuroTools schemas to expand support for new TBL files!

- **🔄 Automatic Conversion**: Convert 280+ KuroTools schemas in seconds
- **📈 Massive Expansion**: From 39 to 344+ supported TBL structures
- **🎮 Multi-Game Support**: Kuro 1, Kuro 2, Kai, Ys X, Sky 1st
- **🔍 Smart Detection**: Automatically prevents duplicates
- **📊 Detailed Reports**: Full conversion logs and statistics

### Additional Tools
- **🔍 Item Discovery**: Search and browse game items from JSON, TBL, and P3A sources
- **📋 Multiple Formats**: Support for JSON, TBL, and P3A archive formats
- **🎨 User-Friendly**: Interactive menus and colored output (Windows CMD compatible)

---

## 📦 Requirements

### Python Version
- Python 3.7 or higher

### Required Python Libraries
Install via `install_python_modules.bat` (Windows) or manually:
```bash
pip install colorama --break-system-packages
```

### External Libraries (Included in Repository)

This toolkit uses libraries from [eArmada8/kuro_dlc_tool](https://github.com/eArmada8/kuro_dlc_tool):

- **`p3a_lib.py`** - P3A archive handling (GPL-3.0)
- **`kurodlc_lib.py`** - Kuro table (.tbl) file handling (GPL-3.0)

**⚠️ GPL-3.0 License Implications:**

Because this toolkit uses GPL-3.0 licensed libraries, the following applies:
- ✅ **This entire toolkit is licensed under GPL-3.0**
- ✅ **You can freely use, modify, and distribute this toolkit**
- ⚠️ **Any modifications must also be GPL-3.0**
- ⚠️ **Source code must be made available to users**
- ⚠️ **You cannot incorporate this into proprietary software**

See the [License](#-license) section for full details.

### Optional Dependencies (for P3A/TBL Support)

If you want to work with `.p3a` archives or `.tbl` files, install:
```bash
pip install lz4 zstandard xxhash --break-system-packages
```

**Note:** If you only work with JSON files (`.kurodlc.json`, `t_item.json`, etc.), these optional dependencies are not needed. All core functionality works with JSON only.

---

## 🚀 Installation

### Option 1: Download Release (Recommended)
1. Download the latest release from [Releases](https://github.com/falco81/KuroDLCTools/releases)
2. Extract to your desired location
3. Run `install_python_modules.bat` (Windows) or install packages manually

### Option 2: Clone Repository
```bash
git clone https://github.com/falco81/KuroDLCTools.git
cd kurodlc-toolkit
```

### Install Dependencies

**Windows:**
```bash
install_python_modules.bat
```

**Linux/Mac:**
```bash
pip install colorama --break-system-packages

# Optional: for P3A/TBL support
pip install lz4 zstandard xxhash --break-system-packages
```

### Setup for Schema Conversion ⭐ NEW

To use the schema converter, you need KuroTools schemas:

**Option A: Download KuroTools (Recommended)**
1. Download KuroTools from https://github.com/nnguyen259/KuroTools
2. Extract the `schemas/` folder
3. Place it in the same directory as `convert_kurotools_schemas.py`

**Option B: Already Have KuroTools**
If you already have KuroTools installed, just copy the `schemas/` folder to your toolkit directory.

**File Structure:**
```
KuroDLCTools/
├── convert_kurotools_schemas.py
├── kurodlc_schema.json
└── schemas/
    └── headers/
        ├── ATBonusParam.json
        ├── ItemTableData.json
        └── ... (280+ files)
```

---

## 🚀 Quick Start

### 1. Fix ID Conflicts in Your DLC (Primary Use Case)
```bash
# Detect conflicts
python resolve_id_conflicts_in_kurodlc.py repair

# Fix conflicts automatically
python resolve_id_conflicts_in_kurodlc.py repair --apply
```

### 2. Generate Shop Assignments (Secondary Use Case)
```bash
# Step 1: Extract IDs and generate template
python shops_find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json --generate-template

# Step 2: Create shop assignments
python shops_create.py template_my_mod.kurodlc.json

# Step 3: Copy ShopItem section from output_template_my_mod.kurodlc.json into your my_mod.kurodlc.json
```

### 3. Visualize ID Allocation ⭐ NEW
```bash
# Analyze current ID allocation and find free ranges
python visualize_id_allocation.py

# Opens interactive HTML report showing:
# - Color-coded ID map (occupied vs free)
# - Statistics and fragmentation metrics
# - List of all available ID ranges
```

### 4. Browse Characters ⭐ NEW
```bash
# Search for character by name
python find_all_names.py van

# Search by ID
python find_all_names.py 100

# Show full names and models
python find_all_names.py van --show-full --show-model
```

### 5. Convert KuroTools Schemas
```bash
# Expand schema support for new TBL files
python convert_kurotools_schemas.py

# Result: kurodlc_schema_updated.json with 344+ schemas
# Replace your kurodlc_schema.json with this file
```

### 6. Browse Game Items
```bash
# Search for items (auto-detects t_item.json, t_item.tbl, or P3A archives)
python find_all_items.py sepith

# Browse all shops (auto-detects sources)
python find_all_shops.py

# Force specific source if needed
python find_all_items.py sepith --source=json
```

---

## 📚 Scripts Overview

### Core Scripts (Latest Versions)

| Script | Version | Purpose | Main Features |
|--------|---------|---------|---------------|
| **`resolve_id_conflicts_in_kurodlc.py`** | v2.7.1 | ID conflict resolution | Smart algorithm (v2.7), automatic repair, 1-5000 range limit |
| **`shops_find_unique_item_id_from_kurodlc.py`** | v2.1 | Template generation | Extract IDs, generate templates, CI/CD support |
| **`shops_create.py`** | v2.0 | Shop assignment generation | Bulk assignments, custom templates, variable substitution |
| **`convert_kurotools_schemas.py`** ⭐ NEW | v1.0 | Schema conversion | KuroTools → kurodlc format, 280+ schemas, multi-game support |

### Analysis & Visualization Scripts ⭐ NEW

| Script | Version | Purpose | Main Features |
|--------|---------|---------|---------------|
| **`visualize_id_allocation.py`** ⭐ NEW | v1.0 | ID allocation visualization | Interactive HTML map, gap analysis, fragmentation metrics, free block identification |
| **`find_all_names.py`** ⭐ NEW | v1.0 | Character name search | Multi-source support, smart search (ID/name/model), detailed filtering |

### Utility Scripts

| Script | Version | Purpose |
|--------|---------|---------|
| **`find_all_items.py`** | v2.0 | Search and browse game items (multi-source support) |
| **`find_all_shops.py`** | v2.0 | List all shops from game data (multi-source support) |
| **`find_unique_item_id_for_t_costumes.py`** | v2.0 | Extract costume IDs (multi-source support) |
| **`find_unique_item_id_for_t_item_category.py`** | v2.0 | Extract category IDs (multi-source support) |
| **`find_unique_item_id_from_kurodlc.py`** | v1.0 | Check DLC IDs against game data |

### Installation Helper

| Script | Purpose |
|--------|---------|
| **`install_python_modules.bat`** | Install required Python packages (Windows) |

---

## 📖 Detailed Documentation

### resolve_id_conflicts_in_kurodlc.py

**Purpose:** Detect and automatically fix ID conflicts between your DLC and game data

#### Quick Reference

```bash
# Check for conflicts (read-only)
python resolve_id_conflicts_in_kurodlc.py checkbydlc

# Repair mode (shows what would change)
python resolve_id_conflicts_in_kurodlc.py repair

# Repair and apply changes automatically
python resolve_id_conflicts_in_kurodlc.py repair --apply

# Export ID mapping for manual editing
python resolve_id_conflicts_in_kurodlc.py repair --export --export-name=MyMod

# Import and apply manually edited mappings
python resolve_id_conflicts_in_kurodlc.py repair --import --mapping-file=id_mapping_MyMod.json
```

#### Parameters

- **`checkbydlc`** - Check all .kurodlc.json files for conflicts
- **`repair`** - Generate repair plan for conflicts
- **`--apply`** - Apply changes immediately (creates backups)
- **`--export`** - Export ID mapping to JSON file
- **`--export-name=NAME`** - Custom name for export file
- **`--import`** - Import and apply ID mapping
- **`--mapping-file=FILE`** - Specify mapping file to import
- **`--source=TYPE`** - Force source type (json/tbl/p3a)
- **`--no-interactive`** - Auto-select options (for CI/CD)

#### How It Works

1. **Detection**: Scans all .kurodlc.json files and compares against game database
2. **Smart Assignment (v2.7)**: 
   - Starts from ID 2500 for better distribution
   - Tries continuous blocks first
   - Falls back to scattered search
   - Enforces 1-5000 range limit
3. **Safety**: Creates backups before any changes
4. **Logging**: Detailed logs of all operations

---

### shops_find_unique_item_id_from_kurodlc.py

**Purpose:** Extract item IDs from DLC and generate templates for shop assignments

#### Quick Reference

```bash
# Generate template with auto-detected shop IDs
python shops_find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json --generate-template

# Generate with custom shop IDs
python shops_find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json --generate-template --shop-ids 5,6,10

# Custom output name
python shops_find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json --generate-template --output=custom_template.json

# CI/CD mode (non-interactive)
python shops_find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json --generate-template --no-interactive --default-shop-ids 5,10,21
```

#### Parameters

- **`--generate-template`** - Generate template for shops_create.py
- **`--shop-ids ID,ID,...`** - Comma-separated shop IDs
- **`--output=FILE`** - Custom output filename
- **`--no-interactive`** - Non-interactive mode (for CI/CD)
- **`--default-shop-ids ID,ID,...`** - Default shop IDs for non-interactive mode

---

### shops_create.py

**Purpose:** Generate shop assignments from templates with variable substitution

#### Quick Reference

```bash
# Generate from template
python shops_create.py template_my_mod.json

# See example configs
type example_config_basic.json
type example_config_advanced.json
type example_config_custom_template.json
```

#### Template Variables

- **`${shop_id}`** - Current shop ID
- **`${item_id}`** - Current item ID
- **`${index}`** - Item index (0-based)
- **`${count}`** - Total items per shop

#### Configuration

Templates support:
- Custom output sections (default: "ShopItem")
- Custom entry templates
- Multiple shop IDs
- Multiple item IDs
- Variable substitution

---

### convert_kurotools_schemas.py ⭐ NEW

**Purpose:** Convert KuroTools schemas to kurodlc_schema.json format

#### Quick Reference

```bash
# Convert schemas (run in directory with schemas/ folder)
python convert_kurotools_schemas.py

# Output files:
# - kurodlc_schema_updated.json (merged schemas)
# - conversion_report.txt (detailed report)
```

#### What It Does

1. **Loads** existing kurodlc_schema.json (if exists)
2. **Scans** schemas/headers/ for KuroTools schemas
3. **Converts** each schema to kurodlc format:
   - Maps data types (ubyte → B, uint → I, toffset → Q, etc.)
   - Calculates schema sizes
   - Flattens nested structures
   - Detects primary keys
4. **Merges** with existing schemas (no duplicates)
5. **Outputs**:
   - `kurodlc_schema_updated.json` - Updated schema file
   - `conversion_report.txt` - Conversion statistics

#### Conversion Statistics

- **Original schemas**: 39
- **KuroTools schemas**: 282 files
- **Converted variants**: 343
- **New schemas added**: 305
- **Total schemas**: 344

#### Supported Games

- **Kuro no Kiseki 1** (Kuro1)
- **Kuro no Kiseki 2** (Kuro2)
- **Kai no Kiseki** (Kai)
- **Ys X: Nordics** (Ys_X)
- **Trails in the Sky 1st** (Sora1)

#### Type Conversion

| KuroTools | Struct | Size | Type |
|-----------|--------|------|------|
| ubyte | B | 1 | number |
| byte | b | 1 | number |
| ushort | H | 2 | number |
| short | h | 2 | number |
| uint | I | 4 | number |
| int | i | 4 | number |
| ulong | Q | 8 | number |
| long | q | 8 | number |
| float | f | 4 | number |
| toffset | Q | 8 | text |
| array | QI | 12 | array |

#### Nested Structures

Nested structures (e.g., effects arrays) are automatically flattened:

**KuroTools format:**
```json
"effects": {
    "size": 5,
    "schema": {
        "id": "uint",
        "value1": "uint",
        "value2": "uint"
    }
}
```

**Converted to:**
```json
"keys": [
    "eff1_id", "eff1_value1", "eff1_value2",
    "eff2_id", "eff2_value1", "eff2_value2",
    ...
]
```

#### Usage Workflow

1. **Backup** original kurodlc_schema.json:
   ```bash
   copy kurodlc_schema.json kurodlc_schema.json.backup
   ```

2. **Run converter**:
   ```bash
   python convert_kurotools_schemas.py
   ```

3. **Review report**:
   ```bash
   type conversion_report.txt
   ```

4. **Replace schema**:
   ```bash
   copy kurodlc_schema_updated.json kurodlc_schema.json
   ```

5. **Test** with new TBL files

#### Troubleshooting

**Problem: "Headers directory not found"**
- Ensure `schemas/headers/` folder exists in same directory
- Download from https://github.com/nnguyen259/KuroTools

**Problem: "No schemas found"**
- Check folder structure: `schemas/headers/*.json`
- Verify JSON files are valid

**Problem: Schema has wrong size**
- Check nested structures in KuroTools schema
- Verify data type sizes
- May need manual adjustment for complex types

---

### visualize_id_allocation.py ⭐ NEW

**Purpose:** Analyze and visualize ID allocation patterns to identify free ID ranges and fragmentation

#### Quick Reference

```bash
# Generate both console and HTML visualization
python visualize_id_allocation.py

# Console visualization only
python visualize_id_allocation.py --format=console

# HTML report only with custom filename
python visualize_id_allocation.py --format=html --output=my_report.html

# Use larger blocks for better overview
python visualize_id_allocation.py --block-size=100

# Force specific data source
python visualize_id_allocation.py --source=json
```

#### Features

- **📊 Interactive HTML Map**: Beautiful, interactive visualization with tooltips
- **🎨 Color-Coded Display**: Green for occupied IDs, gray for free IDs
- **📈 Gap Analysis**: Identifies and lists all free ID ranges
- **📊 Statistics Dashboard**: Shows allocation metrics and fragmentation
- **💾 Dual Output**: Both console and HTML formats
- **🔍 Block-Based View**: Configurable block sizes for better overview

#### HTML Report Features

The generated HTML report (`id_allocation_map.html`) includes:

**Statistics Dashboard:**
- Engine Range (1-5000)
- Highest Used ID
- Occupied IDs count and percentage
- Free IDs count and percentage
- Average Gap Size
- Fragmentation Index
- Largest Free Block
- Total Free Blocks

**Visual ID Map:**
- 100-column grid showing all 5000 IDs
- Green cells = occupied IDs
- Gray cells = free IDs
- Hover tooltips with ID numbers
- Search functionality for specific IDs

**Free Blocks Table:**
- Lists all available ID ranges
- Shows block size for each range
- Sortable by start ID or size
- Perfect for finding safe ID ranges for new mods

#### Example Output

**Console Output:**
```
Loading item data...

Loaded 2116 items from: t_item.json

ID Allocation Analysis
═══════════════════════════════════════════════════════════

Statistics:
  Engine Range:       1 - 5000
  Highest Used ID:    4921
  Occupied IDs:       2116 / 5000  (42.3%)
  Free IDs:           2884 / 5000  (57.7%)
  Average Gap Size:   7.8 IDs
  Fragmentation:      0.73 (73% fragmented)
  Largest Free Block: 79 IDs (4922-5000)
  Total Free Blocks:  370

ID Allocation Map (Block Size: 50)
═══════════════════════════════════════════════════════════

    0: ████████████████████████████████████████████████ [  0 -  49]  100.0%
   50: ████████████████████████████████████████████████ [ 50 -  99]  100.0%
  100: ████████████████████████████████████████████████ [100 - 149]  100.0%
  ...
 4950: ██████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ [4950-4999]   12.0%

Legend: █ Occupied  ░ Free

HTML report generated: id_allocation_map.html
```

#### Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--source=TYPE` | Force specific source (json, tbl, original, p3a, zzz) | Auto-detect |
| `--no-interactive` | Auto-select first source if multiple found | Interactive |
| `--keep-extracted` | Keep temporary extracted files from P3A | Delete after use |
| `--format=FORMAT` | Output format: console, html, both | both |
| `--block-size=N` | Block size for console visualization | 50 |
| `--output=FILE` | Custom HTML output filename | id_allocation_map.html |
| `--help` | Show help message | - |

#### Use Cases

**1. Before Creating New Mods:**
```bash
# Check current ID allocation
python visualize_id_allocation.py

# Look for large free blocks in HTML report
# Example: IDs 3500-3650 (150 IDs available)
```

**2. Planning Multi-Mod Projects:**
```bash
# Generate report to coordinate ID ranges between mods
python visualize_id_allocation.py --output=project_allocation.html

# Share HTML report with team to avoid conflicts
```

**3. Analyzing Fragmentation:**
```bash
# Check fragmentation index
# High fragmentation (>0.7) = many small gaps
# Low fragmentation (<0.3) = few large gaps
```

**4. Finding Optimal ID Ranges:**
```bash
# Look at "Largest Free Block" statistic
# Use HTML table to find multiple suitable ranges
```

#### Supported Data Sources

- **t_item.json** - JSON format item table
- **t_item.tbl** - Binary table file
- **t_item.tbl.original** - Original backup
- **script_en.p3a / script_eng.p3a** - P3A archives (extracts t_item.tbl)
- **zzz_combined_tables.p3a** - Combined tables archive

#### Workflow Integration

```bash
# Step 1: Analyze current allocation
python visualize_id_allocation.py

# Step 2: Open HTML report to find free ranges
start id_allocation_map.html

# Step 3: Use free ranges in your DLC
# Example: Use IDs 3500-3650 for weapons

# Step 4: After adding items, verify no conflicts
python resolve_id_conflicts_in_kurodlc.py my_mod.kurodlc.json --check
```

---

### find_all_names.py ⭐ NEW

**Purpose:** Search and browse character names from game data with intelligent filtering

#### Quick Reference

```bash
# List all characters
python find_all_names.py

# Search by character name (auto-detect)
python find_all_names.py van

# Search by ID (auto-detect)
python find_all_names.py 100

# Explicit search modes
python find_all_names.py name:100       # Search "100" in names
python find_all_names.py id:100         # Search character ID 100
python find_all_names.py full_name:arkride
python find_all_names.py model:chr0000

# Show additional fields
python find_all_names.py van --show-full --show-model

# Force specific source
python find_all_names.py --source=json
```

#### Features

- **👤 Character Discovery**: Browse all game characters
- **🔍 Smart Search**: Auto-detects ID vs name searches
- **📋 Multi-Source Support**: JSON, TBL, P3A archives
- **🎯 Multi-Field Filtering**: Search by ID, name, full name, or model
- **📊 Clean Output**: Formatted tables with alignment
- **⚙️ Flexible Options**: Show/hide additional fields

#### Search Modes

**Auto-Detection:**
```bash
python find_all_names.py 100     # → ID search (it's a number)
python find_all_names.py van     # → Name search (it's text)
```

**Explicit Modes:**
```bash
python find_all_names.py id:100          # Search by character ID
python find_all_names.py name:van        # Search in character names
python find_all_names.py name:100        # Search "100" in names (not ID!)
python find_all_names.py full_name:arkride  # Search in full names
python find_all_names.py model:chr0100   # Search in model names
```

#### Example Output

**Basic Search:**
```bash
$ python find_all_names.py van

Loading character name data...

Loaded 500 characters from: t_name.json

100 : ヴァン
101 : ヴァン・アークライド
225 : ヴァンダール

Total: 3 character(s)
```

**With Full Names and Models:**
```bash
$ python find_all_names.py van --show-full --show-model

Loading character name data...

Loaded 500 characters from: t_name.json

100 : ヴァン              | Van Arkride           | chr0100_01
101 : ヴァン・アークライド | Van Arkride (Full)    | chr0100_02
225 : ヴァンダール        | Vandaal               | chr0225

Total: 3 character(s)
```

#### Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `search_query` | Search query with optional prefix | `van`, `id:100`, `name:ark` |
| `--source=TYPE` | Force specific source | `--source=json` |
| `--no-interactive` | Auto-select first source | Auto-select if multiple |
| `--keep-extracted` | Keep P3A extracted files | Keep temp files |
| `--show-full` | Show full names in output | Display full_name field |
| `--show-model` | Show model names in output | Display model field |
| `--help` | Show help message | Display usage |

#### Use Cases

**1. Character ID Lookup:**
```bash
# Find character ID for scripting
python find_all_names.py "ヴァン"
# Output: 100 : ヴァン
```

**2. Verify Character Model:**
```bash
# Check which model a character uses
python find_all_names.py id:100 --show-model
# Output: 100 : ヴァン | chr0100_01
```

**3. Browse Character Names:**
```bash
# List all characters with "アーロン" in name
python find_all_names.py アーロン --show-full
```

**4. Model Reference:**
```bash
# Find all characters using specific model
python find_all_names.py model:chr0100
```

#### Supported Data Sources

- **t_name.json** - JSON format name table
- **t_name.tbl** - Binary table file
- **t_name.tbl.original** - Original backup
- **script_en.p3a / script_eng.p3a** - P3A archives (extracts t_name.tbl)
- **zzz_combined_tables.p3a** - Combined tables archive

#### Important Notes

**Auto-Detection Caveat:**
```bash
# These behave differently!
python find_all_names.py 100      # → Searches for character ID 100
python find_all_names.py name:100 # → Searches for "100" in character names

# Script shows auto-detection hints:
# Auto-detected ID search for '100'
# Use 'name:100' to search for '100' in character names instead
```

**Output Fields:**
- **ID**: Character ID number
- **Name**: Character display name (Japanese/English)
- **Full Name**: Complete character name (with --show-full)
- **Model**: 3D model identifier (with --show-model)

---

### find_all_items.py

**Purpose:** Search and browse game items with auto-source detection

#### Quick Reference

```bash
# Search items (auto-detects source)
python find_all_items.py sepith

# Browse all items
python find_all_items.py

# Force specific source
python find_all_items.py sepith --source=json
python find_all_items.py sepith --source=tbl
python find_all_items.py sepith --source=p3a
```

#### Auto-Detection Priority

1. `t_item.json` (fastest)
2. `t_item.tbl` or `t_item.tbl.original`
3. `script_en.p3a` / `script_eng.p3a`
4. `zzz_combined_tables.p3a`

---

### find_all_shops.py

**Purpose:** List all shops from game data

#### Quick Reference

```bash
# Auto-detect and list shops
python find_all_shops.py

# Force source
python find_all_shops.py --source=json
```

---

## 🔄 Common Workflows

### Workflow 1: Complete DLC Creation

```bash
# 1. Create your DLC items in my_mod.kurodlc.json

# 2. Check and fix ID conflicts
python resolve_id_conflicts_in_kurodlc.py repair --apply

# 3. Generate shop template
python shops_find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json --generate-template

# 4. Create shop assignments
python shops_create.py template_my_mod.json

# 5. Merge ShopItem section into your DLC

# 6. Test in game!
```

### Workflow 2: ID Allocation Planning ⭐ NEW

```bash
# 1. Analyze current ID allocation
python visualize_id_allocation.py

# 2. Open HTML report
start id_allocation_map.html

# 3. Review statistics and find suitable free blocks
# Look for:
# - Largest free blocks (e.g., 3500-3650: 150 IDs)
# - Low fragmentation areas
# - Gaps large enough for your mod items

# 4. Plan your ID ranges based on findings
# Example: Weapons in 3500-3549, Armor in 3550-3599

# 5. Create your DLC using planned ID ranges
# (edit .kurodlc.json manually or with scripts)

# 6. Verify no conflicts
python resolve_id_conflicts_in_kurodlc.py my_mod.kurodlc.json --check

# 7. If conflicts found, let algorithm reassign
python resolve_id_conflicts_in_kurodlc.py my_mod.kurodlc.json repair --apply
```

### Workflow 3: Character Reference Lookup ⭐ NEW

```bash
# 1. Find character ID by name
python find_all_names.py "ヴァン"
# Output: 100 : ヴァン

# 2. Verify character model for custom events
python find_all_names.py 100 --show-model
# Output: 100 : ヴァン | chr0100_01

# 3. Find all characters in a series
python find_all_names.py アーロン --show-full
# Output: List of all Aaron characters with full names

# 4. Export character list for documentation
python find_all_names.py > character_reference.txt
```

### Workflow 4: Schema Expansion

```bash
# 1. Download/copy KuroTools schemas folder

# 2. Backup current schema
copy kurodlc_schema.json kurodlc_schema.json.backup

# 3. Run conversion
python convert_kurotools_schemas.py

# 4. Review report
type conversion_report.txt

# 5. Replace schema
copy kurodlc_schema_updated.json kurodlc_schema.json

# 6. Now you can work with new TBL files!
```

### Workflow 5: Manual ID Control

```bash
# 1. Export ID mapping
python resolve_id_conflicts_in_kurodlc.py repair --export --export-name=MyMod

# 2. Edit id_mapping_MyMod.json manually
# Change specific IDs as needed

# 3. Import and apply
python resolve_id_conflicts_in_kurodlc.py repair --import --mapping-file=id_mapping_MyMod.json
```

### Workflow 6: CI/CD Integration

```bash
# Non-interactive conflict resolution
python resolve_id_conflicts_in_kurodlc.py repair --apply --no-interactive

# Non-interactive shop generation
python shops_find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json \
    --generate-template \
    --no-interactive \
    --default-shop-ids 5,10,21

python shops_create.py template_my_mod.kurodlc.json
```

---

## 📁 File Formats

### .kurodlc.json Structure

```json
{
    "ItemTableData": [
        {
            "id": 4000,
            "name": "My Custom Item",
            ...
        }
    ],
    "ShopItem": [
        {
            "shop_id": 5,
            "item_id": 4000,
            ...
        }
    ],
    "DLCTableData": [
        {
            "id": 1,
            "items": 4000,
            ...
        }
    ]
}
```

### ID Mapping Export Format

```json
{
    "metadata": {
        "timestamp": "2026-02-02T14:30:00",
        "total_conflicts": 5,
        "dlc_files": ["my_mod.kurodlc.json"]
    },
    "mappings": {
        "my_mod.kurodlc.json": {
            "old_id": "new_id",
            "310": "4000",
            "311": "4001"
        }
    }
}
```

### Schema Conversion Report Format ⭐ NEW

```
KuroTools Schema Conversion Report
======================================================================

Original schemas: 39
KuroTools schemas found: 282
Converted schemas: 343
New schemas added: 305
Total schemas: 344

New Schema Tables:
----------------------------------------------------------------------
  RecaptureIslandSkillTable    Size:  144  Game: Ys_X
  BattleBGM                    Size:   56  Game: Kuro2
  ...
```

---

## 🔧 Troubleshooting

### Common Issues

**"No .kurodlc.json files found"**
- Ensure you're in the correct directory
- Check filename extensions (.kurodlc.json, not .json)

**"No valid source found for conflict detection"**
- Need at least one: t_item.json, t_item.tbl, or script_en.p3a
- Check file locations and names

**"Not enough available IDs"**
- Game has 5000 ID limit
- Reduce number of items or check existing game data
- Review repair plan to see ID usage

**"Headers directory not found"** ⭐ NEW
- Download KuroTools schemas folder
- Place in same directory as convert_kurotools_schemas.py
- Structure: `schemas/headers/*.json`

**"Schema size mismatch"** ⭐ NEW
- Complex nested structures may need manual adjustment
- Check conversion report for details
- Compare with KuroTools schema definitions

### Debug Mode

Enable detailed logging by checking script output - all scripts provide comprehensive error messages and suggestions.

---

## 💡 Best Practices

### ID Management
1. **Always check for conflicts** before releasing your mod
2. **Visualize ID allocation** first with `visualize_id_allocation.py` to find safe ranges
3. **Use the smart algorithm** (v2.7) for better ID distribution
4. **Keep backups** - automatic backups are created, but keep your own too
5. **Export ID mappings** if you need to manually adjust specific IDs
6. **Test your mod** after applying ID changes

### ID Allocation Analysis ⭐ NEW
1. **Run visualize_id_allocation.py** before starting a new mod project
2. **Review HTML report** to identify large free blocks
3. **Plan ID ranges** based on available gaps (avoid fragmentation)
4. **Check fragmentation index** - aim for larger continuous blocks
5. **Share reports** with team to coordinate ID usage
6. **Re-analyze** after major game updates

### Character Reference ⭐ NEW
1. **Use find_all_names.py** to look up character IDs for scripting
2. **Verify model names** before creating custom events
3. **Check full names** for accurate dialogue references
4. **Export character lists** for documentation purposes

### Shop Assignments
1. **Review templates** before generating assignments
2. **Use meaningful shop IDs** that match actual game shops
3. **Customize templates** for different item types if needed
4. **Test in-game** - verify items appear in correct shops

### Schema Conversion ⭐ NEW
1. **Backup original** kurodlc_schema.json before conversion
2. **Review report** to see what was added
3. **Test with TBL files** to verify schemas work
4. **Keep KuroTools updated** to get latest schemas
5. **Re-run converter** when KuroTools adds new schemas

### Development Workflow
1. **Work with JSON files** - easier to edit and track changes
2. **Use version control** (git) to track modifications
3. **Document your changes** in commit messages
4. **Test incrementally** - don't change everything at once

---

## 📝 Version History

### v1.0 (2026-02-02) - NEW ANALYSIS TOOLS ⭐ NEW
- **New Script:** `visualize_id_allocation.py` - ID allocation visualization
  - Interactive HTML map generation
  - Color-coded visualization (occupied vs free)
  - Gap analysis and fragmentation metrics
  - Free block identification
  - Dual output: console + HTML
  - Configurable block sizes
- **New Script:** `find_all_names.py` - Character name search
  - Multi-source support (JSON, TBL, P3A)
  - Smart search with auto-detection
  - Multi-field filtering (ID, name, full_name, model)
  - Clean formatted output
  - Optional field display
- **Documentation:** Updated README with detailed examples
- **Status:** Production ready

### v1.0 (2026-02-02) - convert_kurotools_schemas.py RELEASE
- **New:** Schema conversion from KuroTools to kurodlc format
- **New:** Support for 280+ KuroTools schema files
- **New:** Multi-game support (Kuro 1/2, Kai, Ys X, Sky)
- **New:** Automatic type mapping and size calculation
- **New:** Nested structure flattening
- **New:** Detailed conversion reports
- **New:** Duplicate detection and merging
- **Result:** 305 new schemas added (39 → 344 total)

### v2.7.1 (2026-01-31) - resolve_id_conflicts BUGFIX
- **Fixed:** Removed bare except clause (line 929)
- **Improved:** 100% code quality score
- **Improved:** Better error handling for timestamp parsing
- **Status:** Production ready

### v2.7.0 (2026-01-31) - resolve_id_conflicts SMART ALGORITHM
- **New:** Smart ID distribution algorithm
- **New:** Middle-out assignment starting from ID 2500
- **New:** Better ID spacing for cleaner organization
- **New:** Enforced 1-5000 range limit
- **Improved:** More efficient ID allocation

### v2.1 (2026-01-31) - shops_find BUGFIX & CI/CD SUPPORT
- **Fixed:** EOFError in non-interactive environments
- **New:** `--no-interactive` flag for CI/CD pipelines
- **New:** `--default-shop-ids` flag for automatic fallback
- **Improved:** Clear error messages with actionable solutions
- **Improved:** Better handling of DLCs without ShopItem section
- **Improved:** 100% code quality score
- **Status:** Production ready

### v2.0 (2026-01-31) - shops_find TEMPLATE GENERATION
- **New:** Template generation for shops_create.py
- **New:** Auto-extract item IDs from DLC
- **New:** Auto-extract shop IDs from ShopItem section
- **New:** Auto-extract template structure
- **New:** Custom output filenames
- **Improved:** Workflow integration with shops_create.py

### v2.0 (2026-01-31) - shops_create ENHANCED
- **New:** Variable substitution: ${shop_id}, ${item_id}, ${index}, ${count}
- **New:** Custom output sections
- **New:** Custom templates support
- **Improved:** Backward compatible with v1.0
- **Improved:** Better error messages

### v1.0 (2025) - Initial Release
- Basic ID extraction
- Shop assignment generation
- Item discovery tools
- Conflict detection

---

## 🔗 External Dependencies

This toolkit uses the following external libraries:

### From [eArmada8/kuro_dlc_tool](https://github.com/eArmada8/kuro_dlc_tool)
- **`p3a_lib.py`** - P3A archive handling
- **`kurodlc_lib.py`** - Kuro table (.tbl) file handling

**License:** GPL-3.0  
**Author:** eArmada8  
**Repository:** https://github.com/eArmada8/kuro_dlc_tool

**Note:** These libraries are included in this repository for convenience. All credit for these components goes to the original author.

### From [nnguyen259/KuroTools](https://github.com/nnguyen259/KuroTools) ⭐ NEW
- **Schema definitions** - 280+ TBL structure definitions in `schemas/headers/`

**Note:** KuroTools schemas are NOT included in this repository. Users must download them separately for schema conversion functionality.

**How to get KuroTools schemas:**
1. Visit https://github.com/nnguyen259/KuroTools
2. Download or clone the repository
3. Copy the `schemas/` folder to your toolkit directory

### Python Packages
- **`colorama`** - Cross-platform colored terminal output
  - License: BSD
  - Used for: User-friendly colored output in Windows CMD

- **`lz4`** (optional) - LZ4 compression
- **`zstandard`** (optional) - Zstandard compression  
- **`xxhash`** (optional) - xxHash hashing
  - Required for: P3A and TBL file support

---

## 🤝 Contributing

Contributions are welcome! Since this project is GPL-3.0, all contributions must also be GPL-3.0 compatible.

### How to Contribute

1. **Fork the repository**
2. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature
   ```
3. **Make your changes**
   - Follow existing code style
   - Add comments for complex logic
   - Update documentation if needed
4. **Test your changes**
   - Test with real DLC files
   - Verify backward compatibility
5. **Submit a pull request**
   - Describe your changes clearly
   - Reference any related issues

### Code Style
- Use Python 3.7+ compatible syntax
- Follow PEP 8 guidelines
- Use meaningful variable names
- Add docstrings to functions
- Use `with open()` for file operations
- Avoid bare `except:` clauses

### Testing
- Test with both JSON and TBL sources
- Test with various DLC structures
- Verify error handling
- Check Windows CMD compatibility

---

## 📜 License

### GPL-3.0 License

This project is licensed under the **GNU General Public License v3.0**.

**Why GPL-3.0?**

This toolkit uses libraries from [eArmada8/kuro_dlc_tool](https://github.com/eArmada8/kuro_dlc_tool) which are licensed under GPL-3.0. Under GPL-3.0 terms, any software that incorporates GPL-3.0 licensed code must also be licensed under GPL-3.0.

**What This Means for You:**

✅ **You CAN:**
- Use this toolkit freely for any purpose
- Modify the toolkit for your needs
- Distribute the toolkit to others
- Distribute modified versions
- Use it in your modding projects

⚠️ **You MUST:**
- Keep the GPL-3.0 license with the software
- Make source code available to recipients
- License any modifications under GPL-3.0
- Document your changes
- Include copyright notices

❌ **You CANNOT:**
- Incorporate this into proprietary/closed-source software
- Change the license to a non-GPL-compatible license
- Remove license or copyright notices

**Full License Text:**

See the [LICENSE](LICENSE) file for the complete GNU General Public License v3.0 text.

**External Libraries:**
- `p3a_lib.py` and `kurodlc_lib.py` are from [eArmada8/kuro_dlc_tool](https://github.com/eArmada8/kuro_dlc_tool) (GPL-3.0)
- All credit for these components goes to the original author

**Questions about the License?**

For more information about GPL-3.0, see:
- https://www.gnu.org/licenses/gpl-3.0.html
- https://choosealicense.com/licenses/gpl-3.0/

---

## 🙏 Acknowledgments

- **eArmada8** - For the original [kuro_dlc_tool](https://github.com/eArmada8/kuro_dlc_tool) libraries (p3a_lib.py, kurodlc_lib.py)
- **nnguyen259** - For [KuroTools](https://github.com/nnguyen259/KuroTools) schema definitions ⭐ NEW
- **The Kuro modding community** - For testing and feedback
- **All contributors** - Thank you for your contributions!

---

## 📚 Advanced Documentation

For comprehensive, in-depth documentation including:
- **Complete parameter reference** for all scripts
- **Real data examples** from t_item.json, t_shop.json, t_costume.json
- **Data structure specifications** (.kurodlc.json, exports, imports, logs)
- **Advanced workflows** (CI/CD, batch processing, manual ID mapping)
- **Real-world scenarios** with actual game data
- **Schema conversion details** ⭐ NEW

See **[ADVANCED_DOCUMENTATION.md](ADVANCED_DOCUMENTATION.md)** ⭐

**What's included:**
- ✅ All script parameters documented
- ✅ Examples with real game data (Sepith items: 310-318, Shops: 5,6,10,21-23)
- ✅ Complete .kurodlc.json structure specification
- ✅ Export/Import format specifications
- ✅ Log file formats and examples
- ✅ Advanced workflows (CI/CD, batch processing, custom ID mapping)
- ✅ Real-world examples (costume packs, large collections)
- ✅ Schema conversion guide ⭐ NEW

**Quick links:**
- [Script Parameter Reference](ADVANCED_DOCUMENTATION.md#script-reference)
- [Data Structure Specs](ADVANCED_DOCUMENTATION.md#data-structure-specifications)
- [Real Data Examples](ADVANCED_DOCUMENTATION.md#real-data-examples)
- [Advanced Workflows](ADVANCED_DOCUMENTATION.md#advanced-workflows)
- [Schema Conversion Guide](ADVANCED_DOCUMENTATION.md#schema-conversion) ⭐ NEW

---

## 📧 Support

- **Issues:** [GitHub Issues](https://github.com/falco81/KuroDLCTools/issues)
- **Discussions:** [GitHub Discussions](https://github.com/falco81/KuroDLCTools/discussions)

---

<p align="center">
  <strong>Happy Modding! 🎮</strong>
</p>

<p align="center">
  Made with ❤️ for the Kuro modding community
</p>
