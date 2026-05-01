# KuroDLC Modding Toolkit

A comprehensive Python toolkit for creating and managing DLC mods for games using the KuroDLC format. The toolkit covers item discovery, ID management, conflict resolution, shop assignment, schema conversion from KuroTools, ID allocation visualization, MDL-to-DLC entry generation, per-mdl asset namespacing for game directories, and 3D model viewing with textures, animations, and scene rendering.

[![Python Version](https://img.shields.io/badge/python-3.7%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-GPL--3.0-green)](LICENSE)

---

## 3D Model Viewer Overview

**`viewer_mdl_textured_anim.py` / `.exe`** — full-featured 3D model viewer with textures, skeleton, animations, physics, controller support, scene mode, FXO shader fallback, video recording, skybox, lighting, mesh focus and highlighting.

Ideally associate the `.exe` with `.mdl` files. For correct display of textures the viewer expects the standard folder structure relative to the model file. For full functionality the model needs all referenced data extracted in the standard game directory layout, including `model_info` and the `.mdl` with animations.

```
└───asset
    ├───common
    │   └───model
    │   └───model_info
    └───dx11
        └───image
        └───shader
```

### Capabilities at a glance

- **Textures and materials** — DDS texture loading with path resolution under `asset/dx11/image/`
- **Skeleton and animations** — T-Pose, Idle, Wave, Walk, plus facial animations
- **Physics** — character physics with collision, intensity controls, mouse-driven character movement
- **Controllers** — DualSense, DualShock, Switch Pro, Generic gamepads; keyboard fallback (WSAD)
- **Shaders** — game FXO shaders when available, generated shaders as a fallback (force generated shaders with `--no-shaders`)
- **Camera** — orbit camera plus 3D FreeCam mode for landscapes, buildings, and other large geometry
- **Mesh tools** — focus on the entire model or on individual meshes; meshes whose names contain `box`, `shadow`, or `kage` are hidden by default
- **Lighting and skybox** — adjustable lighting, background color, skybox support, emissive_g fix
- **Recording** — video recording and screenshots with quality settings
- **Scene mode** — `--scene` flag for rendering map / building scene JSONs in `scene/`

### Screenshots

<img src="doc/viewer_anim10.png" width="100%">
<img src="doc/viewer_anim9.png" width="100%">
<img src="doc/viewer_anim8b.png" width="100%">
<img src="doc/viewer_anim7a.png" width="100%">
<img src="doc/scene.png" width="100%">

### Companion viewers

- **`viewer_mdl_textured_scene.py`** — scene viewer (binary scene JSON parsing, FPS camera, full viewer UI)
- **`viewer_mdl_textured.py`** — textured model preview without animations
- **`viewer_mdl.py`** — generates a shareable HTML viewer (Three.js)
- **`viewer_mdl_window.py`** — native window viewer (no files left behind)
- **`viewer_mdl_optimized.py`** — base64-compressed HTML for very large models
- **`viewer.py`** — minimal standalone core viewer

> **⚠️ GPL-3.0 License Notice**
> This project uses libraries from [eArmada8/kuro_dlc_tool](https://github.com/eArmada8/kuro_dlc_tool) which are licensed under GPL-3.0.
> Therefore, this entire toolkit is distributed under GPL-3.0.
> See [License](#-license) section for details.

---

## 📋 Table of Contents

- [Why This Toolkit Exists](#-why-this-toolkit-exists)
- [Features](#-features)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [Scripts Overview](#-scripts-overview)
- [Common Workflows](#-common-workflows)
- [File Formats](#-file-formats)
- [Troubleshooting](#-troubleshooting)
- [Best Practices](#-best-practices)
- [External Dependencies](#-external-dependencies)
- [Contributing](#-contributing)
- [License](#-license)
- [Advanced Documentation](#-advanced-documentation) ⭐

---

## 🎯 Why This Toolkit Exists

### The Problem

When creating DLC mods for Kuro engine games, modders face several recurring challenges:

**1. ID Conflicts (Primary Problem)**
- DLC mods use item IDs that may conflict with existing game items
- Manual ID conflict detection is tedious and error-prone
- A single conflicting ID can break an entire mod
- The game engine has a hard limit of 5000 IDs that cannot be expanded
- Finding safe, available ID ranges manually is time-consuming

**2. Shop Assignment Tedium (Secondary Problem)**
- Adding items to shops requires editing hundreds of entries by hand
- Assigning 50 items to 10 shops = 500 entries
- Copy-paste errors are common
- Bulk shop edits across many DLC files are awkward without tooling

**3. Schema Incompatibility**
- Recently-added TBL files from game updates may not have schema definitions
- The KuroTools project supports more files but uses a different format
- Manual schema conversion is complex and error-prone
- Missing schemas prevent reading the corresponding TBL files

**4. ID Range Planning (Visibility Problem)**
- No visual overview of which IDs are occupied vs. free
- Hard to find safe ID ranges for large mods
- Team coordination requires manual tracking
- Fragmentation analysis is impossible by hand

**5. MDL-to-DLC Entry Creation**
- Adding costume models to a DLC requires creating entries in four sections by hand
- Character identification from filenames is error-prone
- Finding safe item IDs across game data and existing DLCs is tedious
- DLC ID assignment requires checking t_dlc data
- A single mod can contain dozens of MDL files to process

**6. Asset Conflicts Between Mods**
- Two costume mods that touch the same vanilla character end up referencing the same texture filenames; whichever loads last wins, the other looks wrong
- Renaming a `.mdl` to a unique name is not enough — the textures it references must be renamed in lockstep, in both the binary mesh data and the embedded JSON metadata
- Hand-renaming a single character costume can mean editing dozens of file references; doing it for a multi-character mod across many archives is impractical

**7. Model Preview (3D Visualization Problem)**
- No quick way to preview `.mdl` 3D models with textures and animations
- External tools required for model inspection
- Difficult to verify model integrity, shaders, and physics
- No scene-level visualization for maps and buildings

### The Solution

This toolkit addresses all of the above:

**Primary: ID Conflict Resolution**
```bash
python resolve_id_conflicts_in_kurodlc.py repair --apply
```

**Secondary: Bulk Shop Assignment**
```bash
python shops_find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json --generate-template
python shops_create.py template_my_mod.json
```

**Schema Conversion**
```bash
python convert_kurotools_schemas.py
```

**ID Allocation Visualization**
```bash
python visualize_id_allocation.py
```

**MDL Entry Generation**
```bash
# Preview what would be added (dry-run, default)
python kurodlc_add_mdl.py FalcoDLC.kurodlc.json

# Apply changes
python kurodlc_add_mdl.py FalcoDLC.kurodlc.json --apply

# Create a DLC file from scratch
python kurodlc_add_mdl.py NewMod.kurodlc.json --apply
```
- Scans a directory for `.mdl` files not yet in your DLC
- Creates `.kurodlc.json` from scratch when the target file does not exist
- Identifies characters from filenames using t_name data
- Finds safe item IDs from game data + all existing `.kurodlc.json` files
- Uses t_dlc for DLC ID assignment when creating new DLCTableData records
- Interactive t_shop search for shop ID selection
- Generates complete CostumeParam, ItemTableData, DLCTableData, and ShopItem entries
- Dry-run by default; `--apply` is required to write

**Per-mdl Asset Namespacing (game-directory mode)**
```bash
# Drop the script anywhere, point it at the game install directory,
# pick the .mdl files you want to mod, get a single mod .p3a archive
python kuro_mdl_rename.py --game "D:\Steam\steamapps\common\TrailsXYZ" --select --apply
```
- Reads every `.p3a` archive in the game folder lazily (TOC only at scan time)
- Interactive picker for selecting which `.mdl` files to include in the mod
- Extracts only the selected mdls plus their `.mi` side-cars and the images they actually reference into a transient scratch directory
- Renames each `.mdl` and produces per-mdl unique copies of the textures it uses (anchored on the renamed mdl basename) so two mods can never collide on the same vanilla texture
- Patches `image_list.json` and `material_info.json` inside the renamed mdl, then repacks
- Default output is a single `.p3a` archive in the directory the script was run from (the game folder is never written to)

**3D Model Viewing with Textures, Animations, and Scenes**
```bash
# Character viewer with textures + animations (recommended)
python viewer_mdl/viewer_mdl_textured_anim.py character.mdl

# Scene viewer (maps, buildings)
python viewer_mdl/viewer_mdl_textured_scene.py --scene mp0010.json

# Simple viewers
python viewer_mdl/viewer_mdl.py character.mdl
python viewer_mdl/viewer_mdl_window.py character.mdl
```

---

## ✨ Features

### ID Conflict Resolution
- **Conflict detection** — flag every ID in the DLC that collides with game data
- **Smart resolution** — middle-out search starting from 2500, restricted to the safe 1–5000 range
- **Even distribution** — IDs are placed for good spacing rather than packed at the bottom of the range
- **Safety nets** — timestamped backups and detailed logs for every modification
- **Validation** — comprehensive `.kurodlc.json` structure checks

### Bulk Shop Assignment
- **Template-driven shop generation** — customizable template with variable substitution
- **Bulk assignment** — assign hundreds of items to multiple shops at once
- **Custom templates** — define your own shop item structure (supports custom output sections)
- **Non-interactive mode** — for batch / scripted runs
- **Shop-only files** — `.kurodlc.json` files containing just a `ShopItem` section are supported
- **Batch shop ID replacement** — change shop IDs across all `.kurodlc.json` files in a directory at once

### Schema Conversion
- **KuroTools schema converter** — convert 280+ KuroTools schemas in seconds
- **Massive expansion** — from 39 to 344+ supported TBL structures
- **Multi-game support** — Kuro 1, Kuro 2, Kai, Ys X, Sky 1st
- **Smart detection** — duplicate prevention and merging
- **Reports** — detailed conversion logs and statistics

### ID Allocation Visualization
- **Interactive HTML maps** — color-coded visualization of ID usage
- **Console visualization** — terminal-based ID allocation display
- **Statistics dashboard** — occupancy rates and fragmentation metrics
- **Gap analysis** — identify free ID blocks and optimal ranges
- **Range planning** — find safe ID ranges for large mod projects

### MDL Entry Generation
- **Directory scan** — finds `.mdl` files not yet present in the target DLC
- **File creation** — creates `.kurodlc.json` from scratch if the target does not exist
- **Character identification** — uses t_name data for `char_restrict` and naming
- **Smart item ID assignment** — searches the 1–5000 range across game data + all `.kurodlc.json` files
- **DLC ID assignment** — uses t_dlc data (range 1–350) for DLCTableData record creation
- **Shop ID selection** — interactive t_shop search (`?` in prompt) with name/ID lookup
- **Complete entries** — generates `CostumeParam`, `ItemTableData`, `DLCTableData`, `ShopItem`
- **Safe defaults** — dry-run by default, timestamped backups when applying
- **UTF-8 support** — `--no-ascii-escape` for proper character display (e.g. Agnès)

### Per-mdl Asset Namespacing (`kuro_mdl_rename.py`)
- **Game-directory mode** — point at a Trails / ED9 install, the script reads every top-level `.p3a` lazily
- **Interactive picker** — display filter, paging, glob-add, scales to thousands of mdls
- **Subset by globs** — `--only "chr*_c01"`, `--only-from list.txt`, comma-separated names, etc.
- **Per-mdl texture isolation** — each renamed mdl gets its own private copies of the textures it references; no two mods collide
- **Image_list.json + material_info.json patching** — both texture name carriers are kept in sync inside the rebuilt mdl
- **Output formats** — directory tree (default for project / single-archive input) or `.p3a` archive (default for game-directory input)
- **Mixed compression preserved** — when packing a `.p3a`, existing entries pulled from the source keep their original `cmp_type` (LZ4 / ZSTD / ZSTD-with-dictionary); only the renamed entries are recompressed
- **Dry-run by default** — `--apply` required to write; full plan is printed first
- **Source-data immutability** — the game directory and source archives are never modified

### 3D Model Viewing
- **Textured rendering** — DDS texture support with path resolution
- **Skeleton & animations** — T-Pose, Idle, Wave, Walk, facial animations
- **Physics simulation** — character physics with collision and intensity controls
- **Controller support** — DualSense, DualShock, Switch Pro, Generic, keyboard (WSAD)
- **Scene mode** — parse binary scene JSON and render 3D map layouts with FPS camera
- **FXO shader support** — game shader files with fallback to generated shaders
- **Video recording** — quality settings for video and screenshots
- **Skybox & lighting** — background colors, lighting settings, emissive fix
- **FreeCam mode** — 3D free camera for landscapes and buildings
- **Mesh focus & highlighting** — focus on individual meshes; auto-hide meshes named `box`/`shadow`/`kage`

### Additional Tools
- **Item discovery** — search and browse game items from JSON, TBL, and P3A sources
- **Name browser** — search character names from the game database
- **Shop browser** — search shops from the game database
- **Multiple formats** — JSON, TBL, and P3A archive formats
- **Subcategory fix** — batch fix `subcategory` values in `ItemTableData` across all DLC files
- **Friendly UI** — interactive menus and colored output (Windows CMD compatible)

---

## 📦 Requirements

### Python Version
- Python 3.7 or higher (Python 3.11 recommended for `viewer_mdl` with pywebview)

### Required Python Libraries
Install via `install_python_modules.bat` (Windows) or manually:
```bash
pip install colorama --break-system-packages
```

### External Libraries (Included in Repository)

This toolkit uses libraries from [eArmada8/kuro_dlc_tool](https://github.com/eArmada8/kuro_dlc_tool):

- **`p3a_lib.py`** — P3A archive handling (GPL-3.0)
- **`kurodlc_lib.py`** — Kuro table (.tbl) file handling (GPL-3.0)

**⚠️ GPL-3.0 License Implications:**

- ✅ This entire toolkit is licensed under GPL-3.0
- ✅ You can freely use, modify, and distribute this toolkit
- ⚠️ Any modifications must also be GPL-3.0
- ⚠️ Source code must be made available to users
- ⚠️ You cannot incorporate this into proprietary software

See the [License](#-license) section for full details.

### Optional Dependencies

**For P3A / TBL support and `kuro_mdl_rename.py`:**
```bash
pip install lz4 zstandard xxhash blowfish numpy --break-system-packages
```

**For 3D model viewing (`viewer_mdl/`):**
```bash
pip install numpy blowfish zstandard xxhash --break-system-packages

# For the textured viewers (viewer_mdl_textured*.py):
pip install pywebview Pillow --break-system-packages

# For video recording:
pip install av --break-system-packages
```

**All viewer dependencies at once:**
```bash
pip install colorama zstandard lz4 xxhash blowfish av pywebview Pillow numpy --break-system-packages
```

**Note:** If you only work with JSON files (`.kurodlc.json`, `t_item.json`, etc.), the optional dependencies are not needed. All core JSON-driven functionality works without them.

---

## 🚀 Installation

### Option 1: Download Release (Recommended)
1. Download the latest release from [Releases](https://github.com/falco81/KuroDLCTools/releases)
2. Extract to your desired location
3. Run `install_python_modules.bat` (Windows) or install packages manually

### Option 2: Clone Repository
```bash
git clone https://github.com/falco81/KuroDLCTools.git
cd KuroDLCTools
```

### Install Dependencies

**Windows (root toolkit):**
```bash
install_python_modules.bat
```

**Windows (`viewer_mdl` — includes Pillow, pywebview, av):**
```bash
cd viewer_mdl
install_python_modules.bat
```

**Linux/Mac:**
```bash
pip install colorama --break-system-packages

# Optional: for P3A/TBL support and kuro_mdl_rename.py
pip install lz4 zstandard xxhash blowfish numpy --break-system-packages

# Optional: for 3D model viewing
pip install pywebview Pillow av --break-system-packages
```

### Setup for Schema Conversion

To use the schema converter, you need KuroTools schemas:

1. Download KuroTools from https://github.com/nnguyen259/KuroTools
2. Extract the `schemas/` folder
3. Place it in the same directory as `convert_kurotools_schemas.py`

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

### 1. Build a costume / character mod from a game install (`kuro_mdl_rename.py`)
```bash
# Drop the script anywhere, point it at the game folder, pick the
# .mdl files you want to mod — output is a single .p3a archive next
# to where you ran the script
python kuro_mdl_rename.py --game "D:\Steam\steamapps\common\TrailsXYZ" --select --apply

# If the script lives inside the game folder itself, --game alone is enough
python kuro_mdl_rename.py --game --select --apply

# Non-interactive subset selection by glob (game-directory mode)
python kuro_mdl_rename.py --game --only "chr5113_c0?" --apply
```

### 2. Fix ID Conflicts in your DLC
```bash
# Detect conflicts
python resolve_id_conflicts_in_kurodlc.py checkbydlc

# Repair with the smart algorithm
python resolve_id_conflicts_in_kurodlc.py repair --apply

# Export mapping for manual editing
python resolve_id_conflicts_in_kurodlc.py repair --export --export-name=my_mod

# Import an edited mapping
python resolve_id_conflicts_in_kurodlc.py repair --import --mapping-file=id_mapping_my_mod.json
```

### 3. Generate Shop Assignments
```bash
# Generate template from your DLC
python shops_find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json --generate-template

# Customize template_my_mod.json if needed

# Generate shop assignments
python shops_create.py template_my_mod.json
```

### 4. Add MDL Models to a DLC
```bash
# Preview what would be added (dry-run, default)
python kurodlc_add_mdl.py FalcoDLC.kurodlc.json

# Apply changes with backup
python kurodlc_add_mdl.py FalcoDLC.kurodlc.json --apply

# Create a DLC file from scratch (file does not need to exist)
python kurodlc_add_mdl.py NewMod.kurodlc.json --apply

# With custom shop IDs and ID range
python kurodlc_add_mdl.py FalcoDLC.kurodlc.json --shop-ids=21,22 --min-id=3000 --max-id=4000 --apply
```

### 5. Replace Shop IDs in DLC Files
```bash
# Preview replacement for all files in directory
python shops_replace_in_kurodlc.py --new-shop-ids=21,22,248,258

# Apply to a single file
python shops_replace_in_kurodlc.py FalcoDLC.kurodlc.json --new-shop-ids=21,22 --apply

# Per-file interactive mode
python shops_replace_in_kurodlc.py --per-file --apply
```

### 6. Visualize ID Allocation
```bash
# Generate both console and HTML visualization
python visualize_id_allocation.py

# Console only
python visualize_id_allocation.py --format=console

# HTML only with custom name
python visualize_id_allocation.py --format=html --output=my_report.html
```

### 7. View 3D Models
```bash
# Full viewer with textures + animations + physics (recommended)
python viewer_mdl/viewer_mdl_textured_anim.py character.mdl

# Scene mode (maps, buildings)
python viewer_mdl/viewer_mdl_textured_scene.py --scene mp0010.json

# Textured viewer without animations
python viewer_mdl/viewer_mdl_textured.py character.mdl

# Simple HTML output
python viewer_mdl/viewer_mdl.py character.mdl

# Native window (no files left behind)
python viewer_mdl/viewer_mdl_window.py character.mdl

# Disable toon shaders
python viewer_mdl/viewer_mdl_textured_anim.py character.mdl --no-shaders
```

### 8. Convert KuroTools Schemas
```bash
python convert_kurotools_schemas.py
# Output: kurodlc_schema_updated.json and conversion_report.txt
```

### 9. Browse Game Items
```bash
python find_all_items.py
python find_all_names.py
python find_all_shops.py
python find_unique_item_id_for_t_costumes.py
python find_unique_item_id_for_t_item_category.py
```

---

## 📚 Scripts Overview

### Asset Authoring

#### `kuro_mdl_rename.py`
**Purpose:** Produce renamed mod `.p3a` archives for Kuro no Kiseki / ED9 games. The renaming is per-mdl and isolates each model's texture set into a private namespace so two mods that touch overlapping vanilla assets never collide.

**What it does, per `.mdl`:**
1. Picks a new mdl basename (`prefix + original + suffix`; or a name typed under `--rename`; or the original name kept unchanged).
2. Reads the mdl's material data and resolves which images it references.
3. Compares those references against the project's image catalogue and produces a unique renamed copy for every image actually available. The image rename is anchored on the *new* mdl basename so two mdls that share a source image still end up referencing their own private copies.
4. Patches `image_list.json` (extension preserved) and `material_info.json` (texture_image_name has no extension in this file).
5. Repacks the `.mdl` using the embedded import logic, writes it under the new name, then cleans up scratch files.
6. Renames the matching `.mi` side-car (if present).

**Source modes:**
- **Game directory** (`--game [PATH]`) — primary mode; the folder containing the game's many top-level `.p3a` archives. The script reads each archive's table of contents lazily, presents discovered `.mdl` files in the picker, and extracts ONLY the selected mdls + their `.mi` side-cars + the images they reference into a transient scratch directory.
- **Project directory** — a folder with the standard layout (`asset/common/model/`, `asset/common/model_info/`, `asset/dx11/image/`, ...).
- **Single `.p3a` archive** — auto-detected by extension and extracted to a temporary working directory.

**Output:**
- Directory tree (default for project / single-archive input) or
- `.p3a` archive (`--p3a`; default for `--game` mode). Default output path in `--game` mode is `<cwd>/kuro_mdl_rename_output.p3a` — i.e. the directory the script was run from, never inside the game folder.

**Subset selection (default = all discovered mdls):**
```
--select          interactive picker with display filter, paging, glob-add,
                  show / clear / first / done / quit / help commands
--only NAMES      comma-separated mdl basenames or globs, e.g.
                    --only chr0001,chr0002      --only "chr*_c01"
                    --only chr*_c??             --only "*_c0[12]"
                  (repeatable; the trailing .mdl is optional)
--only-from FILE  read names/globs from a text file, one per line
                  (# starts a comment)
```

Glob syntax is `fnmatch`: `*` = any chars, `?` = exactly one char, `[abc]` = character class. On Windows cmd, quote patterns to keep them intact (`--only "chr*_c01"`).

**Usage:**
```bash
# Game-directory mode (primary workflow)
python kuro_mdl_rename.py --game "D:\Steam\steamapps\common\TrailsXYZ" --select --apply
python kuro_mdl_rename.py --game --select --apply              # script lives in the game folder
python kuro_mdl_rename.py --game --only "chr5113_c0?" --apply  # non-interactive subset

# Project directory mode
python kuro_mdl_rename.py C:\mods\pyrixiaSFW --apply
python kuro_mdl_rename.py C:\mods\pyrixiaSFW --select          # interactive subset
python kuro_mdl_rename.py C:\mods\pyrixiaSFW --rename          # per-mdl rename prompt
python kuro_mdl_rename.py C:\mods\pyrixiaSFW --p3a --apply     # output as .p3a

# Single-archive input
python kuro_mdl_rename.py C:\mods\pyrixiaSFW.p3a --p3a --apply

# Non-interactive run (for scripts / CI)
python kuro_mdl_rename.py C:\mods\pyrixiaSFW --non-interactive --apply --prefix mod_
```

**Key options:**
```
--game [PATH]               Treat source as a Trails / ED9 game install directory.
                            With no path: uses the script's own directory.
--prefix STR                Prefix added to renamed mdl files (default 'mod_')
--suffix STR                Suffix added before .mdl
--rename                    Per-mdl interactive rename (each mdl asks for a new name)
--apply                     Apply changes (without this, runs in dry-run mode)
--keep                      Copy non-mdl/non-image files verbatim into the output
--p3a                       Pack the output as a .p3a archive
--p3a-compression TYPE      none | lz4 | zstd | zstd-dict
--p3a-version 1100|1200     Output P3A format version (default 1200)
--output PATH               Output destination (directory or .p3a path)
--non-interactive           Disable all prompts (CLI-only run)
--no-color                  Plain text output (no ANSI colors)
-v / --verbose              Verbose log output
```

**Requirements:** `blowfish`, `zstandard`, `xxhash`, `numpy`, `lz4` (and optionally `colorama` for colored interactive blocks).

For full parameter reference and worked examples see [Advanced Documentation](doc/ADVANCED_DOCUMENTATION.md#kuro_mdl_renamepy).

### ID & DLC Management

#### `resolve_id_conflicts_in_kurodlc.py`
**Purpose:** Detect and resolve ID conflicts between DLC mods and game data.

**Highlights:**
- Smart ID assignment algorithm
- Searches only in the safe range 1–5000
- Starts from the middle (2500) for better distribution
- Timestamped backups and detailed logs
- Export / import workflow for manual control

**Usage:**
```bash
python resolve_id_conflicts_in_kurodlc.py checkbydlc
python resolve_id_conflicts_in_kurodlc.py repair --apply
python resolve_id_conflicts_in_kurodlc.py repair --export --export-name=my_mod
python resolve_id_conflicts_in_kurodlc.py repair --import --mapping-file=id_mapping_my_mod.json
```

#### `kurodlc_add_mdl.py`
**Purpose:** Scan a directory for `.mdl` files and create complete DLC entries.

**Highlights:**
- Scans the directory for `.mdl` files not already in the target `.kurodlc.json`
- Creates `.kurodlc.json` from scratch when the target file does not exist
- Uses t_name data for character identification (`char_restrict` and character names)
- Smart item ID assignment: collects used IDs from t_item + all `.kurodlc.json` files in range 1–5000
- Tries a continuous ID block first, falls back to scattered search
- DLC ID assignment via t_dlc data (range 1–350) when creating new `DLCTableData` records
- Interactive t_shop search (`?` in prompt) for shop ID selection
- Generates `CostumeParam`, `ItemTableData`, `DLCTableData`, `ShopItem` entries
- Dry-run by default; `--apply` required to write
- Timestamped backups (`_YYYYMMDD_HHMMSS.bak`)
- UTF-8 support with `--no-ascii-escape`

**Usage:**
```bash
# Preview (dry-run, default)
python kurodlc_add_mdl.py FalcoDLC.kurodlc.json

# Apply changes
python kurodlc_add_mdl.py FalcoDLC.kurodlc.json --apply

# Create DLC file from scratch
python kurodlc_add_mdl.py NewMod.kurodlc.json --apply

# Custom options
python kurodlc_add_mdl.py FalcoDLC.kurodlc.json --shop-ids=21,22 --apply
python kurodlc_add_mdl.py FalcoDLC.kurodlc.json --min-id=3000 --max-id=4000 --apply
python kurodlc_add_mdl.py FalcoDLC.kurodlc.json --no-interactive --no-ascii-escape --apply
```

**Options:**
```
--apply             Apply changes (without this, runs in dry-run mode)
--dry-run           Explicit dry-run (default behavior, no changes written)
--shop-ids=1,2,3    Override shop IDs (default: detect from file)
--min-id=N          Minimum ID for search range (default: 1)
--max-id=N          Maximum ID for search range (default: 5000)
--no-interactive    Select sources without prompting
--no-backup         Skip backup creation when applying
--no-ascii-escape   Write UTF-8 directly (e.g. Agnès instead of Agn\u00e8s)
```

**Requirements (in the same directory):**
- `.mdl` files to add
- t_name source (`t_name.json`, `t_name.tbl`, or P3A archive)
- t_item source (`t_item.json`, `t_item.tbl`, or P3A archive)
- t_dlc source (optional, for DLC ID assignment when creating new DLCTableData)

#### `find_unique_item_id_from_kurodlc.py`
Extract unique item IDs from DLC files.
```bash
python find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json
```

#### `find_unique_item_id_for_t_costumes.py`
Find available IDs for the costume category.
```bash
python find_unique_item_id_for_t_costumes.py
```

#### `find_unique_item_id_for_t_item_category.py`
Find available IDs by item category.
```bash
python find_unique_item_id_for_t_item_category.py
```

### Shop Management

#### `shops_find_unique_item_id_from_kurodlc.py`
**Purpose:** Extract item IDs from DLC and generate shop assignment templates.

**Highlights:**
- Pulls IDs from multiple sections of a `.kurodlc.json`
- Template generation for `shops_create.py`
- Detect or manual shop ID specification
- `--no-interactive` flag for batch / scripted runs
- Supports shop-only `.kurodlc.json` files (e.g. `Daybreak2CostumeShop`)

**Usage:**
```bash
python shops_find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json
python shops_find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json --generate-template
python shops_find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json --generate-template --shop-ids=5,6,10
```

#### `shops_create.py`
**Purpose:** Generate shop assignments from a template configuration.

**Highlights:**
- Variable substitution (`${shop_id}`, `${item_id}`, `${index}`, `${count}`)
- Custom output sections
- Custom template support
- Backward compatible with the original v1 templates

**Usage:**
```bash
python shops_create.py template_my_mod.json
python shops_create.py config.json output.json
```

#### `shops_replace_in_kurodlc.py`
**Purpose:** Batch replace shop IDs in `.kurodlc.json` files with t_shop validation and interactive search.

**Highlights:**
- Rebuilds the entire `ShopItem` section from the Cartesian product of `item_ids × new shop_ids`
- Batch mode: processes all `.kurodlc.json` files in the directory at once
- Per-file mode: prompts for different shop IDs per file (`--per-file`)
- Extraction modes: select which sections to take item_ids from (`all`, `shop`, `costume`, `item`, `dlc`, or combinations)
- t_shop validation: when t_shop data is available, validates shop IDs and shows shop names
- Interactive search (`?`): search t_shop by name or ID with `id:` / `name:` prefixes
- Supports both full DLC files and shop-only files
- Dry-run by default; `--apply` required to write

**Usage:**
```bash
# Preview all files in directory (dry-run, default)
python shops_replace_in_kurodlc.py --new-shop-ids=21,22,248,258

# Apply to single file
python shops_replace_in_kurodlc.py FalcoDLC.kurodlc.json --new-shop-ids=21,22 --apply

# Per-file interactive (different IDs per file)
python shops_replace_in_kurodlc.py --per-file --apply

# Costume items only
python shops_replace_in_kurodlc.py FalcoDLC.kurodlc.json costume --new-shop-ids=100,200 --apply

# Shop-only file
python shops_replace_in_kurodlc.py UMat.kurodlc.json shop --new-shop-ids=21,22,248,258
```

**Options:**
```
--new-shop-ids=1,2,3  Replacement shop IDs (same for all files)
--per-file            Prompt for replacement shop IDs individually per file
--apply               Apply changes (without this, runs in dry-run mode)
--dry-run             Explicit dry-run (default behavior)
--no-backup           Skip backup creation when applying
--no-interactive      Error out instead of prompting
--no-ascii-escape     Write UTF-8 directly (e.g. Agnès instead of Agn\u00e8s)
```

**t_shop sources (for validation, optional):**
- `t_shop.json`, `t_shop.tbl`, `t_shop.tbl.original`
- `script_en.p3a`, `script_eng.p3a`, `zzz_combined_tables.p3a`

### ID Visualization & Schema Tooling

#### `visualize_id_allocation.py`
**Purpose:** Visualize ID allocation patterns and statistics.

**Highlights:**
- Interactive HTML report with color-coded ID map
- Console visualization with statistics
- Gap analysis and free block identification
- Fragmentation metrics
- Customizable block sizes
- Multiple source support (JSON, TBL, P3A)

**Usage:**
```bash
python visualize_id_allocation.py
python visualize_id_allocation.py --format=html --output=my_report.html
python visualize_id_allocation.py --format=console --block-size=100
python visualize_id_allocation.py --source=json --no-interactive
```

#### `convert_kurotools_schemas.py`
**Purpose:** Convert KuroTools schema definitions to `kurodlc_schema.json` format.

**Highlights:**
- Converts 280+ KuroTools schemas
- Type mapping
- Nested structure flattening
- Duplicate detection and merging
- Detailed conversion reports

**Usage:**
```bash
python convert_kurotools_schemas.py
```

**Requirements:** KuroTools `schemas/` folder in the same directory.

**Output:** `kurodlc_schema_updated.json` and `conversion_report.txt`.

### Discovery Scripts

#### `find_all_items.py`
Browse all items from the game database (supports JSON, TBL, P3A sources).
```bash
python find_all_items.py
python find_all_items.py --source=json
```

#### `find_all_names.py`
Browse character names from the game database (supports JSON, TBL, P3A sources).
```bash
python find_all_names.py
```

#### `find_all_shops.py`
Browse all shops from the game database (supports JSON, TBL, P3A sources).
```bash
python find_all_shops.py
```

### Utility Scripts

#### `fix_subcategory.py`
**Purpose:** Batch fix `subcategory` values in `ItemTableData` entries across all `.kurodlc.json` files in the current directory. Scans for entries where `category=17` and `subcategory=15`, changes `subcategory` to `16`. Dry-run by default.
```bash
python fix_subcategory.py           # dry-run (preview)
python fix_subcategory.py --apply   # apply changes with backups
```

### 3D Model Viewer Scripts (`viewer_mdl/`)

#### `viewer_mdl_textured_anim.py` ⭐ MAIN VIEWER
**Purpose:** Full-featured 3D model viewer with textures, skeleton, animations, physics, controller support, FXO shaders, facial animations, skybox, and video recording.

**Usage:**
```bash
python viewer_mdl/viewer_mdl_textured_anim.py character.mdl
python viewer_mdl/viewer_mdl_textured_anim.py character.mdl --recompute-normals
python viewer_mdl/viewer_mdl_textured_anim.py character.mdl --no-shaders
python viewer_mdl/viewer_mdl_textured_anim.py character.mdl --debug --skip-popup
```

**Options:**
```
--recompute-normals  Recompute smooth normals instead of using originals from the MDL
--debug              Verbose console logging in browser
--skip-popup         Skip loading progress popup on startup
--no-shaders         Disable toon shader rendering, use standard PBR materials
```

**Key features:**
- DDS texture loading with path resolution
- Skeleton hierarchy visualization
- Animations: T-Pose, Idle, Wave, Walk, facial animations
- Physics simulation with collision and intensity controls
- Controller support: DualSense, DualShock, Switch Pro, Generic, keyboard (WSAD)
- FXO game shader support with fallback
- Video recording with quality settings
- Skybox support, lighting and background color customization
- Mesh highlighting; auto-hide of `box` / `shadow` / `kage` meshes
- Configurable via [`viewer_mdl_textured_config.md`](viewer_mdl/viewer_mdl_textured_config.md)

#### `viewer_mdl_textured_scene.py` — Scene Viewer
**Purpose:** Extended viewer with scene mode for rendering 3D map layouts, building interiors, and terrain.

**Usage:**
```bash
# Single model (same behavior as viewer_mdl_textured_anim.py)
python viewer_mdl/viewer_mdl_textured_scene.py character.mdl

# Scene mode — load binary scene JSON
python viewer_mdl/viewer_mdl_textured_scene.py --scene mp0010.json
```

**Scene mode features:**
- Parses binary scene JSON files from `scene/` directory
- Loads MDL models from `asset/`
- Full viewer UI: textures, shaders, gamepad, screenshots
- FreeCam, minimap, search, category filters
- Fog, grid, wireframe, and all MDL viewer features

**Expected directory structure:**
```
├───scene/          (scene JSON files)
└───asset/
    ├───common/
    │   ├───model/
    │   └───model_info/
    └───dx11/
        ├───image/
        └───shader/
```

#### `viewer_mdl_textured.py` — Textured Viewer (no animations)
Simplified textured model preview without skeleton or animations.
```bash
python viewer_mdl/viewer_mdl_textured.py character.mdl
```

#### `viewer_mdl.py` — HTML Viewer
Generates an HTML visualization of `.mdl` files using Three.js.
```bash
python viewer_mdl/viewer_mdl.py character.mdl
python viewer_mdl/viewer_mdl.py character.mdl --use-original-normals
```

**Output:** `<model_name>_viewer.html`

#### `viewer_mdl_window.py` — Native Window Viewer
Preview models in a native window without leaving HTML files behind.
```bash
python viewer_mdl/viewer_mdl_window.py character.mdl
```

**Requires:** `pip install pywebview`

**Platform support:** Windows (Edge WebView2), Linux (GTK + WebKit2), macOS (WKWebView)

#### `viewer_mdl_optimized.py` — Optimized Viewer
Performance-optimized version using base64 compression for large models.
```bash
python viewer_mdl/viewer_mdl_optimized.py character.mdl
```

#### `viewer.py` — Standalone Core Viewer
Minimal standalone viewer with integrated loading functions.
```bash
python viewer_mdl/viewer.py character.mdl
```

### Support Libraries (`viewer_mdl/`)

| File | Description | Source |
|------|-------------|--------|
| `kuro_mdl_export_meshes.py` | MDL model parsing and mesh export | [eArmada8/kuro_mdl_tool](https://github.com/eArmada8/kuro_mdl_tool) |
| `lib_fmtibvb.py` | Format / Index / Vertex buffer handling | [eArmada8/kuro_mdl_tool](https://github.com/eArmada8/kuro_mdl_tool) |
| `lib_texture_loader.py` | DDS texture loading and conversion | KuroDLCTools |
| `three.min.js` | Three.js 3D rendering library | [three.js](https://threejs.org/) |
| `viewer_mdl_textured_config.md` | Viewer configuration reference | KuroDLCTools |

---

## 🔄 Common Workflows

### Workflow 1: Build a costume mod from a game install
```bash
# Step 1 — drop kuro_mdl_rename.py somewhere convenient
# Step 2 — point at the game install, pick the .mdl files in the picker:
python kuro_mdl_rename.py --game "D:\Steam\steamapps\common\TrailsXYZ" --select --apply
# → output: <cwd>/kuro_mdl_rename_output.p3a (a single mod archive,
#           never written into the game folder)

# Optional: do a dry run first (prints the full plan and does not write)
python kuro_mdl_rename.py --game "D:\Steam\..." --select

# Optional: skip the picker and use a glob for non-interactive runs
python kuro_mdl_rename.py --game "D:\Steam\..." --only "chr*_c01" --apply

# Optional: rename mdls one by one (each prompts for a new name)
python kuro_mdl_rename.py --game "D:\Steam\..." --select --rename --apply

# Optional: a richer prefix/suffix scheme
python kuro_mdl_rename.py --game "D:\Steam\..." --only "chr5113_c0?" \
                          --prefix mymod_ --suffix _v1 --apply
```

### Workflow 2: Complete Mod Creation
```bash
# Step 1: Visualize available ID ranges
python visualize_id_allocation.py

# Step 2: Add MDL models to DLC
python kurodlc_add_mdl.py my_mod.kurodlc.json --apply

# Step 3: Check for conflicts
python resolve_id_conflicts_in_kurodlc.py checkbydlc

# Step 4: Resolve conflicts
python resolve_id_conflicts_in_kurodlc.py repair --apply

# Step 5: Generate shop assignments
python shops_find_unique_item_id_from_kurodlc.py my_mod.kurodlc.json --generate-template
python shops_create.py template_my_mod.json
```

### Workflow 3: Batch MDL Addition
```bash
# Place all .mdl files in the working directory alongside game data

# Preview what would be added
python kurodlc_add_mdl.py FalcoDLC.kurodlc.json

# Apply with custom ID range and shop IDs
python kurodlc_add_mdl.py FalcoDLC.kurodlc.json --shop-ids=21,22 --min-id=3000 --max-id=4000 --apply

# Or create a DLC file from scratch (no existing file needed)
python kurodlc_add_mdl.py NewMod.kurodlc.json --apply

# Verify results
python find_unique_item_id_from_kurodlc.py FalcoDLC.kurodlc.json
```

### Workflow 4: Batch Shop ID Replacement
```bash
# Preview shop replacement for all DLC files in directory
python shops_replace_in_kurodlc.py --new-shop-ids=21,22

# Apply with t_shop validation (shows shop names)
python shops_replace_in_kurodlc.py --new-shop-ids=21,22,248,258 --apply

# Per-file mode (different shop IDs per file)
python shops_replace_in_kurodlc.py --per-file --apply

# Costume IDs only, single file
python shops_replace_in_kurodlc.py FalcoDLC.kurodlc.json costume --new-shop-ids=21,22 --apply
```

### Workflow 5: Manual ID Control
```bash
# Export repair plan
python resolve_id_conflicts_in_kurodlc.py repair --export --export-name=my_mod

# Edit id_mapping_my_mod.json by hand

# Import and apply
python resolve_id_conflicts_in_kurodlc.py repair --import --mapping-file=id_mapping_my_mod.json
```

### Workflow 6: Team Coordination
```bash
# Team lead generates an ID allocation report
python visualize_id_allocation.py --format=html --output=team_report.html

# Share team_report.html with the team
# Each modder uses assigned ID ranges from the report
```

### Workflow 7: Schema Update
```bash
# Download the KuroTools schemas folder, then convert:
python convert_kurotools_schemas.py

# Replace kurodlc_schema.json with kurodlc_schema_updated.json
# Test with the corresponding TBL files
python find_all_items.py --source=tbl
```

### Workflow 8: 3D Model Inspection
```bash
# Full-featured viewer (recommended)
python viewer_mdl/viewer_mdl_textured_anim.py character.mdl

# Without toon shaders
python viewer_mdl/viewer_mdl_textured_anim.py character.mdl --no-shaders

# Scene viewer for maps
python viewer_mdl/viewer_mdl_textured_scene.py --scene mp1010.json

# Quick preview without animations
python viewer_mdl/viewer_mdl_textured.py character.mdl

# Generate shareable HTML
python viewer_mdl/viewer_mdl.py character.mdl
```

### Workflow 9: Per-mdl Asset Namespacing for an existing project
```bash
# Existing project tree (asset/common/model/, asset/dx11/image/, ...):
# Step 1: dry run with a glob subset (verify what would be renamed)
python kuro_mdl_rename.py C:\mods\pyrixiaSFW --only "chr*_c01"

# Step 2: per-mdl interactive rename (each mdl prompts for a name)
python kuro_mdl_rename.py C:\mods\pyrixiaSFW --rename --apply

# Step 3: package as a single .p3a, copy non-mdl assets verbatim too
python kuro_mdl_rename.py C:\mods\pyrixiaSFW --p3a --keep --apply

# Or in one line: read from a single .p3a, write to a single .p3a
python kuro_mdl_rename.py C:\mods\pyrixiaSFW.p3a --p3a --apply
```

---

## 📄 File Formats

### `.kurodlc.json` Format
Main DLC mod configuration file. Contains:
- **CostumeParam** — costume definitions with `item_id` references
- **ItemTableData** — item metadata (names, descriptions, categories)
- **DLCTableData** — DLC pack definitions with item lists
- **ShopItem** — shop assignment entries (optional, can be standalone)

### ID Mapping Format
```json
{
  "source_file": "my_mod.kurodlc.json",
  "timestamp": "2026-02-04 12:00:00",
  "game_database": "t_item.json",
  "game_id_count": 2116,
  "game_id_range": [1, 4921],
  "mappings": {
    "310": 2500,
    "311": 2501
  },
  "conflicts": [
    {
      "old_id": 310,
      "new_id": 2500,
      "reason": "Conflict with game item: Earth Sepith"
    }
  ]
}
```

### Shop Template Format
```json
{
  "_comment": ["Template for shops_create.py"],
  "item_ids": [3596, 3597, 3598],
  "shop_ids": [5, 6, 10],
  "template": {
    "shop_id": "${shop_id}",
    "item_id": "${item_id}",
    "unknown": 1,
    "start_scena_flags": [],
    "empty1": 0,
    "end_scena_flags": [],
    "int2": 0
  }
}
```

### Visualization Report
- **HTML format** — interactive color-coded ID allocation map
- **Console format** — terminal-based visualization with statistics

### 3D Model Formats
- **Input:** `.mdl` files (Kuro engine 3D models)
- **Input:** `.json` scene files (binary scene format, for `--scene` mode)
- **Output:** HTML with Three.js or native window display

### `.p3a` Archive Format
Falcom container used in Kuro / ED9 games. Holds the asset tree under `asset/`. Format details (used by `kuro_mdl_rename.py`, the P3A WCX plugin, and other tooling):
- Versions `1100` and `1200` supported (round-trip preserved)
- Compression types: `0` none, `1` LZ4, `2` ZSTD, `3` ZSTD with per-archive training dictionary
- `kuro_mdl_rename.py` preserves existing entry compression verbatim when possible (the renamed mdls and renamed images are written using the chosen `--p3a-compression`)

---

## 🔧 Troubleshooting

### Common Issues

**1. "No module named 'colorama'"**
```bash
pip install colorama --break-system-packages
```

**2. "Cannot read .tbl files"**
```bash
pip install lz4 zstandard xxhash --break-system-packages
```

**3. "No schemas found" (`convert_kurotools_schemas.py`)**
Download KuroTools and place its `schemas/` folder in the toolkit directory.

**4. "No free IDs available"**
The game has reached the 5000 ID limit. Use `visualize_id_allocation.py` to find gaps.

**5. "viewer_mdl_textured_anim.py not working"**
Install all viewer dependencies:
```bash
pip install pywebview Pillow numpy blowfish zstandard xxhash --break-system-packages
```

**6. Textures not loading in viewer**
Ensure the standard folder structure exists relative to the model file:
```
└───asset
    ├───common
    │   └───model
    │   └───model_info
    └───dx11
        └───image
        └───shader
```

**7. "kurodlc_add_mdl.py: No t_name source found"**
Place `t_name.json`, `t_name.tbl`, or a P3A archive in the working directory.

**8. Visualization shows no data**
Ensure the data source (`t_item.json` or `.tbl`) is in the current directory.

**9. pywebview issues on Python 3.12+**
Python 3.11 is recommended for pywebview compatibility. See `viewer_mdl/build.txt` for details.

**10. Costumes not showing in-game despite correct IDs**
Check `subcategory` in `ItemTableData`. Run `fix_subcategory.py` to batch-fix entries where `category=17` has `subcategory=15` (should be 16).

**11. `kuro_mdl_rename.py`: "no .p3a archive in <game_dir> contributes asset/common/model/"**
You pointed `--game` at a directory that does not look like a Trails / ED9 game install. The script only scans top-level `.p3a` archives — mod archives in subdirectories like `mods/` are intentionally ignored. Verify the path holds the game's vanilla `.p3a` files at the top level.

**12. `kuro_mdl_rename.py`: missing dependencies**
The script needs `blowfish`, `zstandard`, `xxhash`, `numpy`, `lz4` (and optionally `colorama`):
```bash
pip install blowfish zstandard xxhash numpy lz4 colorama --break-system-packages
```

### Platform-Specific Notes

**Windows:**
- Use `install_python_modules.bat` for easy setup
- Colored output works in CMD and PowerShell
- WebView2 required for viewer windows (usually pre-installed on Win 10+)

**Linux:**
- Use `--break-system-packages` flag with pip
- Install GTK and WebKit2 for viewer windows
- Some distributions may need `python3` instead of `python`

**macOS:**
- Use `--break-system-packages` flag with pip
- WKWebView is used for viewer windows

---

## 💡 Best Practices

### ID Management
1. **Visualize first** — run `visualize_id_allocation.py` before creating mods
2. **Use safe ranges** — choose IDs from large free blocks (>50 IDs)
3. **Start from middle** — the smart algorithm uses 2500+ for better distribution
4. **Leave a buffer** — don't use every ID in a range, leave space for future additions
5. **Document ranges** — keep notes on which ID ranges your mods use

### MDL Entry Generation
1. **Preview first** — always run `kurodlc_add_mdl.py` without `--apply` first
2. **Have game data ready** — ensure t_name and t_item sources are in the directory
3. **Check ID ranges** — use `--min-id` and `--max-id` to control where IDs are assigned
4. **Use UTF-8** — add `--no-ascii-escape` for proper character display in JSON
5. **Fresh files** — point to a non-existent `.kurodlc.json` and the script initializes it

### Shop Assignment
1. **Generate templates** — use `shops_find_unique_item_id_from_kurodlc.py --generate-template`
2. **Review before applying** — check the generated template before running `shops_create.py`
3. **Use real shop IDs** — match actual game shop IDs from `t_shop.json`
4. **Shop-only files** — `.kurodlc.json` files with only a `ShopItem` section are supported
5. **Batch replace** — use `shops_replace_in_kurodlc.py` to change shop IDs across all DLC files at once

### Per-mdl Asset Namespacing (`kuro_mdl_rename.py`)
1. **Always dry-run first** — without `--apply` the script prints the full per-mdl plan (renamed mdls, renamed images, missing references) so you can confirm before writing
2. **Output goes next to where you ran the script, not into the game folder** — by design; never override `--output` to point inside the game directory unless you have a reason
3. **Use `--select` instead of `--only` when scanning a real game install** — the picker scales to thousands of mdls (filter, paging, glob-add)
4. **Quote globs on Windows cmd** — `--only "chr*_c01"` not `--only chr*_c01` (otherwise cmd may try to expand the pattern itself)
5. **Mods can coexist** — pick a unique `--prefix` (default `mod_`) per mod author/project so two mods never use the same renamed basename
6. **Keep the source archive untouched** — the script never modifies the game's own `.p3a` files; the output is always a separate file

### 3D Model Viewing
1. **Use the full viewer** — `viewer_mdl_textured_anim.py` is the most complete viewer
2. **Scene mode for maps** — use `--scene` for map / building exploration
3. **Disable shaders if needed** — `--no-shaders` for standard PBR rendering
4. **See config** — `viewer_mdl/viewer_mdl_textured_config.md` for viewer customization

### General
1. **Keep backups** — scripts make timestamped backups, but keep your own too
2. **Read logs** — log files contain detailed information about each operation
3. **Test incrementally** — try changes on small DLCs before large projects
4. **Version control** — use git or similar to track your mod files

---

## 🔗 External Dependencies

### From [eArmada8/kuro_dlc_tool](https://github.com/eArmada8/kuro_dlc_tool)
- **`p3a_lib.py`** — P3A archive handling
- **`kurodlc_lib.py`** — Kuro table (.tbl) file handling

**License:** GPL-3.0 | **Author:** eArmada8

### From [eArmada8/kuro_mdl_tool](https://github.com/eArmada8/kuro_mdl_tool)
- **`kuro_mdl_export_meshes.py`** — MDL model parsing and mesh export
- **`lib_fmtibvb.py`** — Format / Index / Vertex buffer handling

**License:** GPL-3.0 | **Author:** eArmada8

**Note:** These libraries are included in the repository. All credit goes to the original authors.

### From [nnguyen259/KuroTools](https://github.com/nnguyen259/KuroTools)
- **Schema definitions** — 280+ TBL structure definitions in `schemas/headers/`

**Note:** KuroTools schemas are NOT included in this repository. Users must download them separately.

### Python Packages

| Package | License | Used for |
|---------|---------|----------|
| `colorama` | BSD | Colored terminal output (Windows CMD compatible) |
| `numpy` | BSD | 3D model vertex processing, mdl rename pipeline |
| `pywebview` | BSD | Native window viewer |
| `Pillow` | HPND | DDS texture conversion |
| `av` | LGPL | Video recording in viewer |
| `blowfish` | MIT | CLE encrypted asset decryption |
| `lz4` | BSD | LZ4 compression (P3A / TBL) |
| `zstandard` | BSD | Zstandard compression (P3A / TBL) |
| `xxhash` | BSD | xxHash hashing (P3A / TBL) |

---

## 🤝 Contributing

Contributions are welcome. Since this project is GPL-3.0, all contributions must be GPL-3.0 compatible.

### How to Contribute

1. **Fork the repository**
2. **Create a feature branch:** `git checkout -b feature/your-feature`
3. **Make your changes** — follow existing code style, add comments, update docs
4. **Test your changes** — test with real DLC files, verify backward compatibility
5. **Submit a pull request** — describe changes clearly, reference related issues

### Code Style
- Python 3.7+ compatible syntax
- PEP 8 guidelines
- Meaningful variable names
- Docstrings on functions
- `with open()` for file operations
- Avoid bare `except:` clauses

---

## 📜 License

### GPL-3.0 License

This project is licensed under the **GNU General Public License v3.0**.

**Why GPL-3.0?** This toolkit uses libraries from [eArmada8/kuro_dlc_tool](https://github.com/eArmada8/kuro_dlc_tool) and [eArmada8/kuro_mdl_tool](https://github.com/eArmada8/kuro_mdl_tool), both GPL-3.0 licensed.

✅ **You CAN:** Use, modify, distribute freely
⚠️ **You MUST:** Keep the GPL-3.0 license, make source available, license modifications under GPL-3.0
❌ **You CANNOT:** Incorporate this into proprietary / closed-source software

See the [LICENSE](LICENSE) file for the complete text.

**More info:** [gnu.org/licenses/gpl-3.0](https://www.gnu.org/licenses/gpl-3.0.html) | [choosealicense.com/gpl-3.0](https://choosealicense.com/licenses/gpl-3.0/)

---

## 🙏 Acknowledgments

- **eArmada8** — for [kuro_dlc_tool](https://github.com/eArmada8/kuro_dlc_tool) and [kuro_mdl_tool](https://github.com/eArmada8/kuro_mdl_tool) libraries
- **nnguyen259** — for [KuroTools](https://github.com/nnguyen259/KuroTools) schema definitions
- **The Kuro modding community** — for testing and feedback
- **All contributors** — thank you for your contributions

---

## 📚 Advanced Documentation

For comprehensive, in-depth documentation see:

**[ADVANCED_DOCUMENTATION.md](doc/ADVANCED_DOCUMENTATION.md)** — Complete parameter reference, real data examples, data structure specs, advanced workflows.

**Quick links:**
- [Script Parameter Reference](doc/ADVANCED_DOCUMENTATION.md#script-reference)
- [`kuro_mdl_rename.py` Reference](doc/ADVANCED_DOCUMENTATION.md#kuro_mdl_renamepy)
- [Data Structure Specs](doc/ADVANCED_DOCUMENTATION.md#data-structure-specifications)
- [Real Data Examples](doc/ADVANCED_DOCUMENTATION.md#real-data-examples)
- [Schema Conversion Guide](doc/ADVANCED_DOCUMENTATION.md#convert_kurotools_schemaspy)
- [3D Viewer Guide](doc/ADVANCED_DOCUMENTATION.md#3d-model-viewer-scripts)

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
