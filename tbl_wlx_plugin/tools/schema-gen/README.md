# Schema generator toolkit

These scripts let you generate **starter schema files** for TBL
sections the plugin doesn't already recognize. Useful when:

- Falcom releases a new game with new section types
- You're working with TBLs from a region/version not covered by the
  bundled KuroTools schemas
- You see a section showing up as raw passthrough in the plugin and
  want it as a typed grid instead

## What's in here

| File | Purpose |
|---|---|
| `p3a_lib.py` | P3A archive read/write library (by eArmada8) |
| `p3a_extract.py` | Extract `.p3a` archives → folder of files |
| `sky_extract_pac.py` | Extract `.pac` archives (Trails in the Sky 1st Chapter) |
| `generate_schemas.py` | v1 schema generator (legacy, kept for reference) |
| `generate_schemas_v2.py` | v2 with EXE class hints + better heuristics |
| **`tbl_schema_autogen.py`** | **v3 — comprehensive auto-generator (recommended)** |
| `falcom-schema-source/` | FalcomSchema-main source + converter |
| `falcom-enums/` | Cross-game enum constants from FalcomToolsCollection |
| `kurotools-guide/` | Original KuroTools modding guide PDF |
| `kuro-dlc-tool-source/` | kuro_dlc_tool reference implementation |

## Recommended workflow for a new Falcom game

```bash
# 1. Extract TBL files from the game's archive (.p3a or .pac)
python3 p3a_extract.py game.p3a /tmp/game_extracted/

# 2. Auto-generate schemas for ALL section types
#    --merge-with skips sections already covered by bundled schemas
python3 tbl_schema_autogen.py /tmp/game_extracted/table/ \
    -o /tmp/new_schemas/ \
    --merge-with /path/to/wcx_tbl/schemas/headers/ \
    -p "GENERATED_NewGame" \
    -g "NewGame" \
    --reports

# 3. Review the generated schemas. The .json files use placeholder
#    field names (id, name, description, text<N>, float<N>, unk<N>).
#    For sections you care about, rename fields to semantic names
#    based on game knowledge.

# 4. Drop the .json files into wcx_tbl/schemas/headers/ alongside
#    bundled schemas. Plugin scans this folder at load.

# 5. Verify with roundtrip:
./tests/testroundtrip /path/to/wcx_tbl/schemas /tmp/game_extracted/table/
# Goal: 100% Func-identical, 0 Bad. Bit-identical varies due to
# JSON float serialization but is not required.
```

## Requirements

```
pip install lz4 zstandard xxhash
```

Python 3.8+.

## Workflow

### 1. Extract your game's tables

If you have `.p3a` archives (Daybreak / Beyond Horizon / Ys X / etc.):

```bash
python3 p3a_extract.py path/to/script_en.p3a -f extracted/MyGame -o
```

For Trails in the Sky 1st Chapter `.pac`:

```bash
python3 sky_extract_pac.py path/to/table_en.pac
# extracts to current directory
```

You can extract multiple games into the same parent folder. The
generator scans recursively, so any layout works.

### 2. Run the generator

```bash
python3 generate_schemas.py \
    --tbl-dir extracted \
    --schema-dir /path/to/plugin/schemas/headers \
    --output-dir generated_schemas
```

Output: one `.json` per section that doesn't have a schema yet.

### 3. Review the output

The generated JSON looks like:

```json
{
    "GENERATED": {
        "game": "Unknown",
        "note": "Auto-generated from 1366 sampled rows across 3 TBL files...",
        "schema": {
            "field0": "toffset",
            "field1": "uint",
            "field2": "float",
            ...
        }
    }
}
```

Field NAMES are always placeholders (`field0`, `field1`, ...). You
should rename them based on what the values look like in the grid.

### 4. Drop into the plugin

Copy `generated_schemas/*.json` into your plugin's `schemas/headers/`
folder, then restart Total Commander.

## Accuracy

Validated against the existing 282 KuroTools schemas: roughly **40-50%
of fields match exactly**. The breakdown:

- **Float** detection is solid (~95%).
- **toffset** (string pointer) detection works for fields that are
  populated in most rows.
- **uint vs int**: usually right when there are clearly negative values.
- **byte/ushort/uint** alignment: correct by construction.

## Limitations

The script can't reliably distinguish:

- **`ulong` from `2×uint`** at the same 8-aligned offset. We always
  emit `2×uint`. **This round-trips correctly through the plugin**
  (saves are byte-identical), so the failure mode is benign — the
  grid just shows two columns instead of one. Manually merge in the
  generated JSON if you care.
- **`u8array`/`u16array`/`u32array`** (variable-length nested data)
  are never inferred. They'll appear as a stretch of `byte`/`ubyte`
  fields. If the section was a passthrough section and is now a
  typed grid that looks "wrong", check whether it has a variable
  array — those need manual schema authoring.
- **Nested struct arrays** (the `{"size": N, "schema": {...}}` form
  in real KuroTools schemas) aren't detected; their bytes appear as
  a stretch of primitive fields in the parent.
- **Field names** are always placeholders. The generator has no way
  to know that `field2` should be called `description`.

## Tips for cleaning up generated schemas

1. **Look at the data in the plugin's grid.** Columns whose values
   are all small integers (1, 2, 3...) are usually enums or counts.
2. **`uint` followed by `uint` where the second is always 0** is
   probably a single `ulong`.
3. **A column showing IDs from 1..N** is likely the section's
   primary key — rename to `id`.
4. **Strings that all look like `chr5001`, `cap0123`** are usually
   model/asset paths — keep as `toffset`.
5. **Floats clustered around 0..1** are often probabilities or
   percentages.
6. **Floats around -1..1** are direction vectors or angles.

If you produce a polished schema, consider contributing it back to
the KuroTools project.
