# Best schema pack v1.3.38 — recommended

Combines four sources of TBL section schema knowledge:

1. **Manually crafted (top-30)** — derived from per-offset analysis of
   real TBL data. Floats, toffsets, padding, and integer ranges are
   verified from actual byte distributions.
2. **Auto-generated v2** for the remaining sections, using the smart
   inferencer with toffset confidence scoring and float detection.
3. **EXE-verified existence** — every schema is annotated with
   `exe_evidence` listing which game EXEs (Sky 1st, Daybreak, Daybreak
   II, Beyond Horizon, Ys X) confirm the section exists via RTTI
   strings or class identifiers. 249 / 426 sections have direct EXE
   evidence; the rest are TBL-only sections (e.g. localization
   tables) that don't have a corresponding C++ class.
4. **Roundtrip-tested** against 1543 real TBL files from 5 Falcom games.

## Validation summary

| Metric | Result |
|---|---:|
| Files tested | 1543 |
| **Functionally identical roundtrip** | **1543 / 1543 (100%)** |
| Bit-identical roundtrip | 1469 / 1543 (95.2%) |
| Bad / errors | 0 |
| Sections with schema | 424 / 426 (99.5%) |
| Sections with EXE evidence | 249 / 426 (58%) |

**100% functionally identical** = your edits will round-trip correctly.
The 4.8% non-bit-identical cases are due to JSON-level float
representation differences (e.g., `0.10000000149011612` vs `0.1`).
Data integrity is preserved.

## Per-game breakdown

| Game | Files | Func-identical | Bad |
|---|---:|---:|---:|
| Sky 1st Chapter | 237 | 237 (100%) | 0 |
| Trails through Daybreak | 179 | 179 (100%) | 0 |
| Trails through Daybreak II | 473 | 473 (100%) | 0 |
| Trails beyond the Horizon | 411 | 411 (100%) | 0 |
| Ys X Nordics (3 lang) | 243 | 243 (100%) | 0 |
| **TOTAL** | **1543** | **1543 (100%)** | **0** |

## How to install

Copy all `*.json` from this folder into your plugin's `schemas/headers/`
directory. Restart Total Commander. Sections previously shown as raw
passthrough now appear as typed grids you can edit.

## Schema annotations

Each schema includes:
- `game` — primary target game (or "Multi" for cross-game)
- `note` — quality/source description
- `exe_evidence` — which game EXEs confirm this section exists
- `schema` — field definitions

Example:

```json
{
  "GENERATED": {
    "game": "Multi",
    "schema": {
      "id": "ulong",
      "name": "toffset",
      "volume": "float",
      "flags": "uint"
    },
    "note": "Manually verified — types confirmed by per-offset analysis on real TBL data. Confirmed in EXE RTTI/strings of: Beyond Horizon, Daybreak, Daybreak II, Sky 1st.",
    "exe_evidence": ["Beyond Horizon", "Daybreak", "Daybreak II", "Sky 1st"]
  }
}
```

## Limitations

These schemas are sufficient for **safe round-trip editing** through
the plugin. Two things are NOT 100%:

1. **Field names** — many use placeholder names (`field0`, `field1`).
   Manual KuroTools-style RE work would give them semantic names.
2. **Some types** — when 1×ulong vs 2×uint is binary-ambiguous, the
   pack may show 2×uint. This is harmless: saving back produces the
   same bytes, so the game reads it correctly either way.

For real-world editing of items, BGM, etc., the plugin works perfectly
with this pack.
