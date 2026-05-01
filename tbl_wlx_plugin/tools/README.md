# TBL Schema Generator

Auto-generate KuroTools-compatible schema JSONs for TBL sections that
the plugin doesn't already know about.

## Usage

```
python tbl_schema_generator.py <input_dir> <output_dir> \
    [--schemas-dir <plugin_schemas_dir>]
```

* `<input_dir>` — folder with extracted .tbl files (recursive scan,
  can mix multiple games)
* `<output_dir>` — destination for generated schemas
* `--schemas-dir` — optional. Points to your existing
  `schemas/headers/` folder; sections that already have a schema there
  will be skipped. If omitted, every section gets a fresh schema.

## What it does

Scans every TBL it can parse, groups data by section name + row size,
and infers a field layout for each missing section. The inference is
heuristic but conservative:

* 8-byte aligned slot whose values dereference to printable UTF-8
  strings → `toffset`
* 4-byte slot with all values looking like floats → `float`
* 4-byte slot of small varying bytes → 4 × `ubyte` (packed flags)
* Otherwise: `int` / `uint` / `short` / `ushort` / `byte` / `ubyte` by
  alignment + signed-ness

Field names are always generic placeholders (`field0`, `field1`, ...).

## Limitations

* **Field names won't be meaningful.** You'll want to rename them by
  hand based on what the data looks like in the grid.
* **`long`/`ulong` is never generated.** A 64-bit int and two 32-bit
  ints look identical at the binary level when high bits are set; we
  default to two `uint`s, which round-trips correctly.
* **Nested arrays aren't inferred.** If a generated schema doesn't
  match the binary cleanly, the section likely contains an embedded
  array of structs. Edit the JSON and replace the affected fields
  with the nested syntax (see `headers/ItemTableData.json` for a
  full example of nested array syntax in practice).

## Workflow

1. Extract your game's TBL archive (P3A or PAC) somewhere.
2. Run this tool with `--schemas-dir` pointing at the plugin's
   existing schemas to skip what's already known.
3. Review generated JSONs, rename fields, fix obvious miss-typings.
4. Drop the JSONs into the plugin's `schemas/headers/` folder.
5. Restart Total Commander. F3 over a TBL — your section should
   render as a typed grid now instead of passthrough.

## Round-trip safety

Even if the inferred types are slightly wrong, **save round-trips
correctly** as long as the total row size matches. The plugin
serializes per-field; whatever bytes were in a field on read get
written back verbatim if you didn't edit the cell. This means it's
safe to ship inaccurate schemas — at worst the grid displays a value
in an inconvenient format (e.g. a bitfield as a uint).
