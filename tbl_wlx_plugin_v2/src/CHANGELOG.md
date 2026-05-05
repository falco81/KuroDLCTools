# Changelog

## v1.3.43 (2026-05) — Auto-schema generator v3 (`tbl_schema_autogen.py`)

### Added
- **`tools/schema-gen/tbl_schema_autogen.py`** — comprehensive schema
  auto-generator that takes any directory of `#TBL` files and emits
  KuroTools-format schemas. Designed for **future Falcom games** with
  no manual setup required.

### How it works (3-phase pipeline)

**Phase 1 — Evidence aggregation.** Walks all directories, parses every
`#TBL` file, and pools rows by `(section_name, entry_length)` tuple.
Pooling across multiple files dramatically improves type inference
quality compared to per-file analysis.

**Phase 2 — Layout solver.** For each unique tuple, walks through the
entry bytes picking the highest-confidence type at each offset:

  - **toffset** — strict validation: 8-byte value must be `>= data2_start`
    AND point to a NUL-terminated UTF-8 string. Rejects coincidental
    matches where small integers happen to land on header bytes.
  - **u32array / u16array / u8array** — 12-byte slot interpreted as
    8-byte offset + 4-byte count. Validates `offset + count*elem_size`
    fits in file and offset is in data2 region.
  - **float vs uint** — IEEE 754 plausibility (range 1e-6 to 1e9, no NaN/Inf)
    plus distribution heuristics (common values like 0.5, 1.0, 1.5, 2.0
    indicate float; large 32-bit IDs indicate uint).
  - **ulong fallback** — used when 8-byte slot doesn't match toffset
    or array. Post-pass splits ulong → uint+uint when upper half is
    always zero AND lower half scores ≥ 0.95 as float.

**Phase 3 — Field naming.** Positional conventions:
  - First uint at offset 0 → `id`
  - Last toffset → `name`, second-to-last → `description`
  - Other toffsets → `text<N>`, floats → `float<N>`, etc.

### Features
- **`--merge-with <existing_schemas>`** — skip sections that already
  have a variant for the same entry_length. Lets you generate ONLY
  the genuinely-unknown sections without overwriting community work.
- **`--reports`** — emit per-section markdown analysis with hex dump
  + field-by-field confidence scores so a human can verify.
- **CLI**: `--platform`, `--game` for variant tagging; `--min-rows`,
  `--min-confidence` for tuning.

### Validation results

Tested by generating schemas from scratch against Sky 1st Chapter
(237 TBL files, ground-truth = bundled hand-curated schemas):

| Configuration | Bit-id | Func-id | Bad |
|---|---:|---:|---:|
| Passthrough (no schemas) | 100% | 100% | 0 |
| **Auto-generated v3 only** | **16.5%** | **100%** | **0** |
| Hand-curated production | 97.5% | 100% | 0 |

The auto-generator achieves **100% functional roundtrip** (every TBL
parses to JSON, edits work, writes back without data loss) but only
~16% bit-identical because:
- Auto-generated field names differ from canonical (cosmetic)
- Some 8-byte slots are kept as `ulong` when GT splits to `uint+uint`
- JSON float serialization uses different formatting than original

For genuinely-unknown sections (the actual use case for v3), the
generator produces working starter schemas that can be refined by
hand for the few critical sections (item, character, NPC).

### Type inference quality (vs bundled hand-curated schemas)

Field-by-field comparison across 396 sections / 3793 fields:

| Quality bucket | Sections |
|---|---:|
| 100% type-exact match | 28 |
| 75-99% match | 17 |
| 50-74% match | 91 |
| 25-49% match | 125 |
| <25% match | 135 |

Best results: short flat tables (NameTable, BGMTable, EffectTable —
85%+ exact). Worst: deeply nested structs with mixed primitives
(ItemTableData with embedded effects/stats arrays).

### Validation (1543 TBL files)
| Metric | v1.3.42 | v1.3.43 |
|---|---:|---:|
| Functionally identical | 1543 (100%) | **1543 (100%)** |
| Bit-identical          | 1490 (96.6%) | **1490 (96.6%)** |
| Bad / errors           | 0 | **0** |

No change to plugin schemas or behavior — this release adds the
**generator tool** for future game support.

## v1.3.42 (2026-05) — Documentation & enum reference enrichment

### Added
- **`tools/schema-gen/kurotools-guide/`** — original KuroTools modding
  guide PDF (by Twn, with tools by Twn, SoftBrilliant, hell259), plus
  README documenting the field-name conventions confirmed by the guide.
  The PDF describes the same TBL format the plugin handles and gives
  worked examples for `t_npc_<map>.tbl`, `t_name.tbl`, `t_achievement.tbl`,
  and `t_item.tbl`. All field names match our integrated schemas.

- **`tools/schema-gen/falcom-enums/`** — 6 enum definitions extracted
  from FalcomToolsCollection (Sky FC/SC/THIRD era), 172 total constants:
  - `EffectEnum` — 106 effect type IDs (PHYS_DAMAGE=1, HEAL=3, POISON=10,
    FREEZE=11, etc.) used in item/skill effect_id fields
  - `ElementEnum` — 8 elements (EARTH=1, WATER=2, FIRE=3, WIND=4,
    SPACE=5, MIRAGE=6, TIME=7) — confirmed consistent from Sky to
    current games
  - `AbilityFlagEnum` — 17-bit skill/item flags (HEAL, HITS_ENEMY,
    HITS_DEAD, BENEFICIAL, MAGIC, CANNON, etc.)
  - `AiType` — 6 AI behavior types
  - `StatusResistanceEnum` — 33-value resistance bitfield
  - `Gender` — MALE=0, FEMALE=1
  - Each enum is provided as both the original C# source AND a
    programmatic `enums.json` for future plugin features (e.g. showing
    "FIRE" instead of "3" in the grid).

### Investigated and excluded
- **FalcomToolsCollection** (143 files) — comprehensive tool suite, but
  exclusively targets the **old Sky trilogy** (PC FC/SC/THIRD, ~2004-2007).
  No `#TBL` magic anywhere; uses SHIFT-JIS encoding and `LB DAT`/`LB DIR`
  archive formats. Schema files are Kaitai (`.ksy`) for `T_BGMTBL`,
  `T_BOOK`, `T_COOK2`, `T_WORLD`, `BTSET`, `MS`, `T_MAGIC`. Only the
  `Shared/*Enum.cs` files yielded transferable knowledge (the enums
  documented above).

### Validation (1543 TBL files) — unchanged from v1.3.41
| Metric | Value |
|---|---:|
| Files tested | 1543 |
| Functionally identical | 1543 (100%) |
| Bit-identical | 1490 (96.6%) |
| Bad / errors | 0 |

This release adds **documentation and reference data only** — no schema
or code changes. The plugin behavior is identical to v1.3.41.

## v1.3.41 (2026-05) — FalcomSchema (Trails-Research-Group) integration

### Added
- **FalcomSchema integration**: 226 schema files from
  [Trails-Research-Group/FalcomSchema](https://github.com/Trails-Research-Group/FalcomSchema)
  merged into the plugin's schema set, covering 181 unique TBL sections
  across Daybreak 1, Daybreak 2, and Ys X with authoritative field
  names and exact types.
  - **16 placeholder-name schemas replaced** with FalcomSchema authentic
    field names (e.g. `bgm_track` instead of `name`, semantic stat names
    like `hp`, `ep`, `patk`, `pdef`, `crit`, `eva` for stat arrays).
  - **191 new platform variants** added as `FALCOMSCHEMA_Daybreak1`,
    `FALCOMSCHEMA_Daybreak2`, `FALCOMSCHEMA_Ys_X` keys.
  - 2 new common types added as standalone reference schemas:
    `Effect` and `StatArrayDaybreak`.

- **Type-precise FalcomSchema converter** handles all FalcomSchema
  type vocabulary correctly:
  - Primitives: u8/s8 → ubyte/byte, u16/s16 → ushort/short,
    u32/s32 → uint/int, u64/s64 → ulong/long, f32 → float
  - Pointers: ptr_str_utf8, ptr_str_latin1 → toffset
  - Arrays: arr_u8/u16/u32 → u8array/u16array/u32array
  - Raw: dN → N × ubyte (flattened with `_b0`, `_b1`, ... suffixes)
  - Refs: `ref_<CommonName>` → inlined common schema fields
  - Nested: `{"repeat": N, "type": ...}` → N copies, with optional
    nested struct inside; `{"type": "ref_X"}` without repeat →
    single instance of common type

- **`tools/schema-gen/falcom-schema-source/`** — original
  FalcomSchema files + LICENSE + integration notes.

### Improved
- **`testroundtrip` — PreferGame inference from path**: when test
  iterates through e.g. `Trails through Daybreak II/table_en/`, it
  now passes `Kuro2` as preferred game tag to the schema database,
  selecting the most accurate variant when multiple variants share
  the same entry length. This mirrors how end users will configure
  the plugin in Total Commander.

### Validation (1543 TBL files)
| Metric | v1.3.40 | v1.3.41 | Δ |
|---|---:|---:|---:|
| Files tested | 1543 | 1543 | = |
| **Functionally identical** | 1543 (100%) | **1543 (100%)** | = |
| **Bit-identical** | 1480 (95.9%) | **1490 (96.6%)** | **+10** |
| Bad / errors | 0 | **0** | = |

### Per-game roundtrip results
| Game | Files | Func-id | Bit-id | Bad |
|---|---:|---:|---:|---:|
| Sky 1st Chapter | 237 | 237 (100%) | 231 (97.5%) | 0 |
| **Trails through Daybreak** | **179** | **179 (100%)** | **179 (100%)** ⭐ | 0 |
| Trails through Daybreak II | 473 | 473 (100%) | 466 (98.5%) | 0 |
| Trails beyond the Horizon | 411 | 411 (100%) | 401 (97.6%) | 0 |
| Ys X Nordics (3 lang) | 243 | 243 (100%) | 213 (87.6%) | 0 |
| **TOTAL** | **1543** | **1543** | **1490 (96.6%)** | **0** |

### Schema corpus inventory (cumulative across versions)
- **428 schema files** total
- **282** from KuroTools (base)
- **39** from kuro_dlc_tool (v1.3.39, type-precise via v1.3.40)
- **207** new variants from FalcomSchema (this release)
- **30** manually validated (v1.3.38)
- **144** auto-generated v2 (v1.3.38)

### Investigated and excluded
The following projects were inspected file-by-file but did not yield
new schema data:
- **KuroTools-master_2** — identical to base KuroTools (byte-for-byte)
- **SenSchema-master** — Cold Steel only (cs3), Kaitai (.ksy) format,
  not compatible with Daybreak/YsX
- **SenScriptsDecompiler-main** — Cold Steel script decompiler,
  unrelated to TBL
- **misc_kiseki-main** — Cold Steel utility scripts, no TBL schemas
- **Doc-main** — `kuro/README.md` says "TBD" (no content yet)
- **FalcomTBLTool-main** — uses FalcomSchema as data source (already
  integrated); reference parser confirmed our converter correctness

## v1.3.40 (2026-05) — type-precise KDT integration

### Improved
- **Type-precise schema conversion** from kuro_dlc_tool: previous v1.3.39
  conversion mapped all `n` (number) value codes to `uint`. v1.3.40 now
  uses the underlying Python struct format characters (`B`/`H`/`I`/`Q`/`f`/etc.)
  to extract exact types: `ubyte`, `ushort`, `uint`, `ulong`, `float`,
  `byte`, `short`, `int`, `long`.

### Affected sections (now type-precise)
- ItemTableData (Sky 1st 232b, Kuro 1/2 248b, Ys X 176b) — fields
  `category` and `subcategory` are now correctly `ubyte`, `item_icon`/
  `effect_icon`/`element` are `ushort`, `float1`/`float2`/`float3` are
  `float`, etc.
- DLCTableData (Kuro 1 88b) — `unk2`/`unk3` are `ushort` not `uint`
- CostumeParam, ShopInfo, BargainItem, etc. — now use mixed type
  schemas matching the original game binaries.

### Validation (1543 TBL files)
- Func-identical: 1543/1543 (100%) — unchanged
- Bit-identical:  1480/1543 (95.9%) — unchanged
- Bad: 0 — unchanged
- **Schema fidelity: significantly improved** for editing — fields now
  display proper byte/short/float types in the grid instead of being
  shoehorned into uint columns.

### Documentation
- `tools/schema-gen/kuro-dlc-tool-source/` updated with detailed
  conversion notes explaining how the bidirectional mapping
  (KDT struct format ↔ KuroTools type names) works.

## v1.3.39 (2026-05) — kuro_dlc_tool integration

### Added
- **kuro_dlc_tool schema integration**: 39 schema entries from
  eArmada8's kuro_dlc_tool project merged into the plugin's schema
  set, providing:
  - **13 sections enriched** with semantic field names
    (e.g. `id`, `name`, `desc`, `items`, `quantity` replacing
    KuroTools' generic `int1`, `arr1`, `text1`)
  - **26 new size/game variants** added (e.g. DLCTableData EL=88
    for Kuro 1, missing in KuroTools-master)
  - Coverage: Kuro 1, Kuro 2, Sky 1st, Ys X, Kai

- `tools/schema-gen/kuro-dlc-tool-source/` — original
  kuro_dlc_tool schema JSON + license + integration notes.

### Quality (vs v1.3.38)
- Func-identical roundtrip: 1543 / 1543 (100%) — unchanged
- **Bit-identical roundtrip: 1480 / 1543 (95.9%)** — improved from 95.2%
- Bad: 0 — unchanged
- Type accuracy: significantly improved on 13 commonly-edited tables
  (item, costume, shop, recipe, skill, etc.)

## v1.3.38 (2026-05) — 100% functional roundtrip on 1543 TBL files

### Added
- **`tools/schema-gen/best-schemas-pack/`** — recommended schema
  pack combining manually-crafted schemas (top-30 sections) with
  auto-generated v2 schemas, annotated with EXE evidence.
  Validated against 1543 TBL files from 5 Falcom games:

  - **Functionally identical roundtrip: 1543 / 1543 (100%)**
  - Bit-identical roundtrip: 1469 / 1543 (95.2%)
  - Bad (errors): 0
  - Coverage: 424 / 426 unique sections

- **30 manually-crafted schemas** for high-volume sections:
  MapSceneActorInfo, HackingStageMap, SETableData,
  BreakObjectTableData, SETable, HackingEnemySetting, MarkerTable,
  MarkerTiming, BTResultTable, STokenTableData, AniParam,
  BGMTableData, GachaItem, SSceneInfoTable, FootPrintTable,
  ConstantValueF, StopperTable, EventBoxTableData,
  CollisionFootStepInfo, MapBrkObjMana, TalkChrData,
  EffectTableData, Status, BalanceTestData, DropItemTable,
  TimelyWordsEventData, VoiceData, EnemyLevel, SBGMTable,
  EffectTableDataChr.

- **EXE evidence cross-reference**: 249 sections confirmed
  present in game EXE RTTI / strings. Each schema in best-pack
  annotated with `exe_evidence` listing originating games.

- **`generate_schemas_v2.py`** — improved type inferencer with
  per-section markdown reports.

- **EXE-derived class catalog** — 74 distinct `TableHolder<*Table>`
  classes extracted from Beyond Horizon RTTI as authoritative
  reference for which Tables exist.

### Quality
- Top-30 manual schemas: 100% type-correct (verified by analysis)
- Auto-generated v2: ~50% strict accuracy, but 100%
  func-identical roundtrip on test corpus
- All 426 sections preserve data integrity through plugin

## v1.3.37 (2026-04)

### Added
- **`tools/schema-gen/`** — schema generator toolkit shipped in the
  source distribution. Lets users produce starter schemas for TBL
  sections the plugin doesn't already recognize:
  - `generate_schemas.py` — heuristic field-type inferencer that walks
    extracted .tbl files, finds sections without a schema, and emits
    KuroTools-compatible JSONs.
  - `p3a_lib.py`, `p3a_extract.py`, `sky_extract_pac.py` — bundled
    archive extractors (P3A for Daybreak/Beyond Horizon/Ys X, PAC for
    Trails in the Sky 1st Chapter). Credit: eArmada8.
  - `generated-schemas-pack/` — **144 pre-generated schemas** covering
    sections found in: Sky 1st Chapter, Daybreak, Daybreak II, Beyond
    Horizon, Ys X (5 games, 1543 .tbl files scanned). Drop-in to
    `schemas/headers/` for instant coverage of previously-passthrough
    sections.
  - `tools/schema-gen/README.md` — workflow + accuracy notes +
    cleanup tips.
- Section coverage now goes from 280 (KuroTools) -> 424 unique
  sections after applying the generated pack.

### Notes
- Generated schemas use the `"GENERATED"` platform key so they're
  distinguishable from real KuroTools-authored schemas. Field names
  are placeholders (`field0`, `field1`, ...); types are best-effort
  heuristic with ~40-50% accuracy on validation against known
  schemas.
- The plugin grid shows typed columns instead of raw passthrough
  for any section the user adds via the pack. Saves still
  round-trip byte-identical even when generated types are imprecise
  (a `ulong` mis-inferred as `2x uint` saves identically; the
  difference is purely in how the grid displays the column).

## v1.3.36 (2026-04)

### Fixed
- **`build.bat` w64devkit download URL.** The asset is named
  `w64devkit-x64-2.7.0.7z.exe` (with the `.7z.exe` suffix that
  was added in v2.2.0 to emphasize the 7-zip nature), not
  `w64devkit-x64-2.7.0.exe`. Download was failing with HTTP 404.
- BUILD.md updated with the correct filename and accurate
  download size (~56 MB, not ~110 MB).

## v1.3.35 (2026-04)

### Added
- **Self-contained Windows build.** `build.bat` is now analogous
  to `build.sh` on Linux: it auto-detects FPC, auto-detects a
  working gcc, and bootstraps a portable mingw-w64 toolchain
  (w64devkit, ~110 MB) if none is found. First-run download is
  cached in `tools\w64devkit\` for subsequent builds.
- **`BUILD.md` Windows section** with prerequisites, build steps,
  what the script does internally, and troubleshooting for the
  common failure modes (FPC's bundled cc.exe being mistaken for
  a usable gcc, curl.exe missing on old Windows, AV quarantine).

### Notes
- The previous `build.bat` failed when the user only had Lazarus
  installed and tried to use FPC's bundled `cc.exe` — it lacks
  stdlib include paths, so ZSTD compilation died with "No
  include path in which to find limits.h". Now the script tests
  the gcc it finds before trusting it, and falls back to
  bootstrapping w64devkit if the test fails.
- No prebuilt object files are shipped in the source ZIP; the
  user always builds everything from source. The bootstrap is
  identical in spirit to how `build.sh` bootstraps Win64 RTL
  units when they're missing.

## v1.3.34 (2026-04)

### Fixed
- **Scroll bars stay visible after tab switches.** The
  v1.3.33 fix worked for the initial-open case but reset on
  every tab switch. Reason: the host's tab-switch sequence is
  `ShowWindow(SW_SHOW)` immediately followed by
  `MoveWindow(...)`, and the `WM_SIZE` from the MoveWindow
  was arriving right after the `RedrawWindow` we scheduled in
  WM_SHOWWINDOW — invalidating it before it could paint.

  Fix: instead of calling RedrawWindow synchronously, **post**
  a custom message (`WM_GRID_REFRESH_BARS = WM_APP + 100`)
  from both WM_SHOWWINDOW and WM_SIZE. By the time it gets
  dispatched, the entire show/size/move chain has finished;
  the listview is in its final state; the frame paint sticks.

  The handler does the full refresh:
  - `SetWindowPos(SWP_FRAMECHANGED)` for non-client recompute,
  - `RedrawWindow(RDW_FRAME | RDW_INVALIDATE)` for the paint.

  Multiple posts in the queue (one from WM_SHOWWINDOW, one
  from the WM_SIZE that follows) just means the refresh runs
  twice; both are cheap and idempotent.

## v1.3.33 (2026-04)

### Fixed
- **Grid scroll bars now appear on viewer open and after tab
  switches**, not just after a mouse hover or wheel scroll.

  The remaining issue: the listview's default proc updates the
  scroll RANGE on `WM_SIZE` and `WM_SHOWWINDOW`, but doesn't
  schedule a frame REPAINT. The bars only became visible when
  something else triggered a frame paint — mouse hover (which
  the listview wants for hot-tracking) and wheel scroll were
  both doing this as a side effect, which is why the bars
  "appeared after the first hover/scroll."

  The fix is two new subclass-handler additions:
  - **`WM_SIZE`**: after the default proc, call
    `RedrawWindow(RDW_FRAME | RDW_INVALIDATE)` to schedule the
    frame paint explicitly.
  - **`WM_SHOWWINDOW`**: same, but only when the window is
    actually being shown (`wParam <> 0`). Catches the initial
    viewer open and the moment a previously-hidden tab becomes
    active.

  With `LVS_EX_DOUBLEBUFFER` enabled (v1.3.32), the explicit
  frame paint is flicker-free.

## v1.3.32 (2026-04)

### Fixed
- **Scroll bars and grid no longer overdraw each other.** Two
  bugs were stacked:
  - **Missing double-buffer.** The listview was rendering its
    client area and its non-client (scroll bar) area in
    separate paint passes, with no off-screen compositing —
    so on Windows 10 the user could see the grid contents
    bleed across the scroll-bar region and vice versa within
    the same frame. Setting `LVS_EX_DOUBLEBUFFER` makes the
    control composite to an off-screen bitmap and blit once
    per paint cycle. Eliminates the visible "fighting".
  - **The 1-pixel size nudge from v1.3.31 was the trigger.**
    Resizing the listview by 1px and back forced two `WM_SIZE`
    cycles in the same frame; the listview repaints its
    client on the first and its frame on the second, which
    was the literal source of the overlap the user saw. The
    nudge was an attempt to force scroll-range recompute, but
    `SWP_FRAMECHANGED` on its own gives the same effect
    without the second WM_SIZE. Replaced.

### Removed (cleanup)
- `ForceScrollBarsVisible` (SetScrollInfo + SIF_DISABLENOSCROLL)
  — was conflicting with the listview's own scroll-range
  tracking. Listview computes scroll range correctly from the
  column widths once we let it; the override was making it
  fight against itself.
- `ShowScrollBar(SB_VERT/HORZ, True)` calls in WM_SIZE — were
  scheduling extra paint cycles that contributed to the
  overdraw. Default proc handles the bars cleanly with
  LVS_EX_DOUBLEBUFFER on.

## v1.3.31 (2026-04)

### Fixed
- **Win 10 grid scroll bars now appear immediately, not after
  hover.** Previous diagnosis was wrong (kept blaming Win 11
  auto-hide; the user is on Win 10). The actual cause: after
  `AutoSizeColumns` sets new column widths, the listview
  computes the new scroll range, but the **non-client area**
  (where scroll bars are painted) doesn't repaint — there's no
  invalidation event scheduled for the frame. Mouse hover /
  wheel scroll happen to trigger that repaint as a side
  effect, which is why the bars "appear" after hovering.

  The fix is `RefreshGridScrollBars`, called once after the
  column widths are set:
  - `SetWindowPos(SWP_FRAMECHANGED)` → forces `WM_NCCALCSIZE`,
    which makes the listview reconsider its non-client area.
  - 1-pixel size nudge and back → fires `WM_SIZE` on the
    listview itself, which is when its internal scroll-range
    code actually runs and registers the bars.
  - `RedrawWindow(RDW_FRAME)` → paints the bars right away.

  This is the same sequence Windows uses internally when an
  app's MDI frame switches active children; we just call it
  explicitly here.

### Notes
- The `SetScrollInfo` + `SIF_DISABLENOSCROLL` call from v1.3.28
  is kept as a backstop. It doesn't conflict with the new
  refresh logic.
- Applies to top-level grids and sub-grid popups (both go
  through `CreateGridWindow`).
- Modern listview look is preserved (no `SetWindowTheme` hack).

## v1.3.30 (2026-04)

### Reverted
- **v1.3.29 `SetWindowTheme(' ', ' ')` call removed.** Disabling
  theming on the grid had unintended side effects (broken
  rendering / interaction in user testing) beyond the cosmetic
  classic-look tradeoff documented for v1.3.29. The control is
  back to modern theming, identical to v1.3.28 behaviour.

### Status of Win11 scrollbar auto-hide
- The `SetScrollInfo` + `SIF_DISABLENOSCROLL` workaround from
  v1.3.28 stays — it does what it can at the per-control level.
- The Win11 overlay auto-hide remains in effect; this is a
  property of the modern visual style and cannot be turned off
  for a single control without disabling theming entirely.
- **Workaround:** Settings → Accessibility → Visual effects →
  Always show scrollbars (system-wide setting).
- **Permanent fix on the roadmap:** owner-drawn custom scroll
  bars rendered as child controls over the grid. This is a
  larger refactor (~200 LoC); not included in v1.3.30.

## v1.3.29 (2026-04)

### Fixed
- **Scroll bars now always visible — no more Windows 11 auto-hide.**
  `SetWindowTheme(Grid, ' ', ' ')` disables visual theming for the
  grid control, which makes Win32 fall back to the classic
  always-solid scroll bars. The auto-hide overlay behaviour is part
  of the visual style, so opting out of theming opts out of the
  overlay too.

### Visual change
- The grid now has a **classic Win9x/2000 look**:
  - Column headers are 3D-button-style (raised) instead of flat.
  - Row separator lines are sharper.
  - Scroll bars are the chunky old-style ones, always visible.
- This applies to the top-level grids and the sub-grid popups for
  nested arrays (both routed through `CreateGridWindow`).

### Tradeoff explanation
- Windows 11's "auto-hide scrollbars" is a property of the
  modern visual theme — you cannot keep modern theming AND get
  always-visible scroll bars without a system-wide setting change.
- The two options are:
  1. **Modern theming + Win11 setting "Always show scrollbars"** —
     OS Settings → Accessibility → Visual Effects → toggle on.
     Affects every app on the system.
  2. **Classic look on this grid only** — what we did.
- If you prefer option 1 (or owner-drawn custom scroll bars), let
  us know and we'll revert this change. The `SetWindowTheme` line
  is one line in `gridwin.pas`.

## v1.3.28 (2026-04)

### Fixed
- **Scroll bars now register as always-visible at the OS level.**
  Calling `SetScrollInfo` with `SIF_DISABLENOSCROLL` after the grid
  is built tells Windows "this control wants its scroll bars
  drawn permanently, even when content fits." The listview's own
  scroll-range calculation overrides this for the active state
  (visible bar with a real thumb), but the OS no longer treats the
  control as scroll-bar-eligible-for-hiding.

### Known limitation
- **Windows 11 "auto-hide scrollbars"** is a system-level
  accessibility default that overrides any per-control hint an
  application can give. If your scroll bars only appear when you
  hover the grid:
  - **Settings → Accessibility → Visual effects → Always show
    scrollbars → ON**
  - This is a system-wide setting; it affects File Explorer,
    Notepad, every other app too.
  - We chose not to override this from inside the plugin via
    `SetWindowTheme(' ', ' ')` (which would force classic
    Win9x-style scroll bars by disabling theming) because it
    would also classic-ify the column headers and row separators,
    which most users would consider an aesthetic regression
    worse than the auto-hide.

## v1.3.27 (2026-04)

### Fixed
- **Grid scroll bars now render correctly.** Three things were
  wrong:
  - The ListView was created without explicit `WS_VSCROLL` /
    `WS_HSCROLL` styles; it relied on Win32's auto-scrollbar
    behaviour which is inconsistent across Win10/11 builds and
    interacts poorly with the auto-sized columns added in v1.3.25
    (when columns were wider than the viewport, the horizontal
    bar sometimes didn't appear until the user clicked the grid).
  - After `AutoSizeColumns` resized the columns, the listview
    didn't recompute its scroll range — `LVM_SETCOLUMNWIDTH`
    doesn't trigger that on its own. We now re-issue
    `LVM_SETITEMCOUNT` (cheap, forces the recompute) and call
    `ShowScrollBar` for both axes immediately after.
  - The grid subclass didn't have a `WM_SIZE` handler, so
    resizing the Lister window (or switching tabs, which moves
    the grid via `MoveWindow` in `ShowTabAt`) didn't reliably
    refresh the bars. Added one that calls the default proc and
    then nudges both scroll bars visible.

### Notes
- These changes apply to top-level grids and to the sub-grid
  popups for nested arrays (both go through `CreateGridWindow`).
- `WS_CLIPCHILDREN` was added at the same time — prevents
  flicker on the inline edit overlay.

## v1.3.26 (2026-04)

### Added
- **JSON ↔ grid sync on tab switch.** Edits in one view now
  propagate to the other when you click a different tab,
  instead of only at save time:
  - **Leaving JSON tab** (entering anything else): the Edit's
    text is parsed, validated against the original section
    structure, and pushed into the model via `Tbl.FromJSON`.
    Grid tabs are then rebuilt so their cell data reflects
    the typed JSON. If the JSON is unparseable or fails
    structure validation, the model is left untouched and
    the user will get a proper error if they try to save.
  - **Leaving a grid tab to enter the JSON tab**: the model
    (already updated by the grid edits in place) is
    re-serialized via `BuildJSONView` and the result is
    pushed into the JSON Edit. Grid references stay valid;
    no rebuild needed.
  - Grid → grid switches: nothing to sync (both views read
    the same `section.Rows` references).
  - Config tab is excluded from sync (no editable model
    state lives there).

### Notes
- Sync is short-circuited if the instance isn't dirty — the
  cheap path is the no-op. Same on first activation
  (FromIdx = -1).
- The dirty flag is reset by `SaveInstance` after a successful
  write; sync uses it as the "anything to push?" signal.
- If the user has invalid JSON when leaving the JSON tab, the
  switch still completes (no nag dialog, no blocking) but the
  model isn't updated. They'll see the parse error if they
  Ctrl+S.

## v1.3.25 (2026-04)

### Added
- **Auto-sized columns on open.** Each grid column now sizes itself
  to fit the longest cell text, measured in pixels at the grid's
  current font. Header text is the floor; cell text is sampled
  across up to 500 rows per column (covers >99% of TBLs entirely;
  larger ones get a representative sample). Width is clamped to
  60px minimum / 600px maximum, with 18px padding for the sort
  arrow + breathing room. Applies to top-level grids and sub-grid
  popups.

### Notes
- Ranges:
  - **Min** 60px — narrower than this is unreadable for most
    column headers anyway.
  - **Max** 600px — keeps a single very-long string column from
    pushing all the others off-screen.
  - **Padding** 18px — leaves room for the sort-direction arrow
    that appears on the active sort column.
- Auto-fit runs once at grid creation (i.e. on F3 open + after
  any save that triggers a tab rebuild). Manually resized
  columns are preserved between sorts and edits, but reset on
  the next save / reload — that's a tradeoff for keeping the
  auto-fit logic simple.

## v1.3.24 (2026-04)

### Fixed
- **JSON Edit text length limit raised from default ~30,000 chars
  to ~2 GB.** This was the actual root cause of the "typing
  doesn't work" symptom — and explains every weird detail:
  - Default Win32 multi-line Edit caps text at ~30k chars (32k
    ANSI / 16k Unicode in older builds).
  - Larger TBLs (e.g. `t_name.tbl`) serialize to JSON well over
    that limit, so loading silently truncated the text. The
    closing `}` and parts of the `sections` array got cut off.
  - **Once at the limit, the Edit refuses any character insertion**
    via WM_CHAR. But Delete and Backspace still work because they
    *reduce* length. Selection-replace partially worked: the
    Delete portion succeeded, the Insert silently failed.
  - When the user pressed Ctrl+S, save read back the truncated
    text, JSON parse produced an incomplete object, and our
    consistency check caught "no sections array" — exactly what
    the reporter saw.
  - `EM_SETLIMITTEXT` is now called immediately after
    `CreateWindowExW` to raise the limit to `0x7FFFFFFE`. Loading
    keeps full content, typing works.
- **Crash on closing the editor after editing + clicking "No"
  on the save prompt.** Mismatched A/W subclass install/restore:
  `AddJSONTab` used `SetWindowLongPtrW` to install our subclass,
  but `ClearAllTabs` was using the ANSI `SetWindowLongPtr` to
  restore the original. Win32 tracks proc A/W status separately
  per window, and the mismatch caused message conversion chaos
  during `WM_NCDESTROY` — taking the host with it. Both paths
  now consistently use the W variant.
- **Mojibake in error dialogs.** "TBL Plugin â€" consistency
  check" and similar — em-dash characters (UTF-8) were going
  through ANSI `MessageBoxA`, where they got reinterpreted as
  cp1252. Replaced with ASCII hyphens. Same applied to several
  other MessageBoxA captions throughout `tbl_wlx.pas`.

### Notes
- The previous v1.3.20–v1.3.23 fixes (Unicode Edit, focus, F-key
  forwarding, WM_GETDLGCODE, manual WM_CHAR generation) are
  retained but mostly redundant with this release. They were
  trying to work around a host-pump issue that turned out to be
  the Edit's text-length limit. The Unicode-Edit fix is still
  needed for non-ASCII characters; everything else is harmless
  bonus robustness.
- This explains why v1.3.20 / .21 / .22 fixes appeared to do
  nothing: the keystrokes were arriving correctly, the focus was
  correct, the message routing was correct — Win32 simply refused
  to insert any character because the Edit was at its capacity.

## v1.3.23 (2026-04)

### Fixed
- **JSON tab typing actually works now.** Diagnosis: in TC Lister
  plugin context, the host's message pump apparently doesn't run
  `TranslateMessage` on `WM_KEYDOWN` events for our subclassed
  Edit, so the standard `WM_KEYDOWN → WM_CHAR` chain that all
  Win32 Edit controls rely on for character entry was broken.
  The reason Delete and Backspace still worked: those are handled
  in the Edit's `WM_KEYDOWN` directly, not via `WM_CHAR`. Same
  for selection-replace via "type to overwrite selection" — the
  WM_KEYDOWN clears the selection but the inserted character
  never arrives.
- **The fix:** in `JSONEditSubclassProc`, after our usual handling
  of F-keys and Ctrl+S/F, we now call a small helper
  `GenerateCharFromKey` that uses Win32's `ToUnicode` to translate
  the virtual-key + scan-code + keyboard state into the actual
  characters, then `SendMessage(WM_CHAR)` directly into the same
  Edit. This bypasses the host pump's `TranslateMessage` entirely.
  Pure modifier keys, function keys, and Ctrl+letter combos are
  excluded (they're handled by the default WM_KEYDOWN path).

### Notes
- This is a workaround for a host-pump quirk, not a "right" Win32
  pattern. The tradeoff is acceptable: the Edit is fully editable,
  IME / dead keys / accented characters work via `ToUnicode`'s
  built-in keyboard layout handling (it returns 1 or 2 chars
  depending on input).
- Read-only mode is checked before generating the WM_CHAR — in RO
  mode we let the default proc handle the keystroke (which beeps).

## v1.3.22 (2026-04)

### Fixed
- **JSON tab editable in EDIT mode (third try; this should be the
  real fix).** Root cause was Total Commander's main message loop
  calling `IsDialogMessage` on the Lister window. `IsDialogMessage`
  asks the focused control "what keys do you want?" via
  `WM_GETDLGCODE`. Our subclassed Edit was passing this through to
  the default Edit handler — which apparently doesn't return enough
  flags in TC's plugin context. Result: keystrokes got eaten as
  dialog navigation before reaching the Edit's `WM_CHAR` pipeline.
  `JSONEditSubclassProc` now returns `DLGC_WANTALLKEYS |
  DLGC_WANTCHARS | DLGC_WANTARROWS | DLGC_HASSETSEL | DLGC_WANTTAB`
  unconditionally, which tells `IsDialogMessage` "hands off, give
  me everything." Same handler also added on the tab-host wndproc
  for completeness.
- **Click-to-focus on the JSON Edit.** `WM_LBUTTONDOWN` /
  `WM_LBUTTONDBLCLK` in the subclass now explicitly call
  `SetFocus(Wnd)` before falling through to the default handler,
  belt-and-suspenders against any host that might steal focus.
- **`SetWindowLongPtrW` subclass install with A fallback.** Defensive:
  if the W variant returns 0 (failure indicator on first install),
  we retry with `SetWindowLongPtr`. Same for `GetWindowLongPtrW`.
  On 64-bit Windows both variants should work for Edit instances,
  but the fallback removes one possible failure mode.

### Notes
- The previous v1.3.20 / v1.3.21 fixes (focus-after-toggle and
  Unicode Edit creation) are still needed. v1.3.22 adds the missing
  third piece (`WM_GETDLGCODE`) that Win32 host integrations
  generally require.
- If typing into the JSON tab still doesn't work after this
  release, please send a screenshot showing the status strip
  (RO vs EDIT MODE), the file path, and what TC version you're
  on — there's a small chance TC has changed its message-pump
  behaviour in a way that needs further accommodation.

## v1.3.21 (2026-04)

### Fixed
- **JSON tab now displays non-ASCII characters correctly.** Names
  like `René`, `Gerard Dantès`, `Ärioch` were showing up as
  `Renã©`, `Gerard DantÃ¨s`, `Ãrioch` because the Edit control
  was created via the ANSI `CreateWindowEx` path, which interprets
  the UTF-8 bytes of the JSON text as cp1252. The Edit is now
  created via `CreateWindowExW`, text is sent via `SendMessageW`
  with proper UTF-8 → UTF-16 conversion, and `viewerwin`'s
  text-IO helpers (`SetViewerText` / `GetViewerText` / `ViewerFind`)
  now use the W variants throughout.
- **JSON tab editable after F4 (definitive fix).** v1.3.20's
  `SetFocus` after the toggle still wasn't reliable. Now we call
  `ShowTabAt(St, St^.Active)` after the toggle, which re-shows
  the active child + sets focus + does the size/position dance
  that ensures keystroke routing works. F4 → click in JSON Edit
  area → typing now works.
- **Search scope: only the active tab.** Previously F3 / Shift+F7
  would wrap through every tab in the tab-host (e.g. search in
  ShopInfo would jump to ShopItem after running out of matches).
  Now search stays within whatever tab the user is currently
  looking at — matches the standard "find in this view" mental
  model. Scope-by-tab also makes the JSON tab's Backwards search
  work as expected.

### Notes
- The Unicode-Edit conversion is fully transparent. JSON serialized
  by FormatJSON is UTF-8 on disk and in memory, and gets converted
  to UTF-16 only at the boundary with the Edit control. Round-trip
  byte-stability is unchanged: the editor's bytes-out match the
  bytes-in on save when no character changes are made.
- The grid (ListView) tabs were already Unicode-aware via
  `CCM_SETUNICODEFORMAT` and `LVN_GETDISPINFOW` since v1.3.13.
  Only the JSON tab was missed.

## v1.3.20 (2026-04)

### Added
- **Click a column header to sort by that column.** First click sorts
  ascending; clicking the same header again toggles to descending;
  clicking a different header switches to that column (ascending).
  Numeric-looking values are compared as numbers; everything else
  uses case-insensitive string compare. Empty cells sort last in
  both directions. Works for both top-level grids and nested-array
  sub-grids.
- **`testgridsort` regression** added to the smoke-test suite,
  exercising the same sort algorithm against the shared `gridmodel`
  on Linux. Suite is now **15 pass / 0 fail**.

### Fixed
- **JSON tab not editable after F4.** When the user pressed F4 to
  toggle into edit mode, then clicked the JSON tab, the text was
  white (= edit mode) but typing did nothing. Root cause: focus
  was on the tab strip / mode label after the F4 toggle, not on
  the now-editable JSON Edit. `DoToggleEditMode` now explicitly
  `SetFocus`es the active tab's child control after applying the
  edit-mode UI changes, so keystrokes route correctly.

## v1.3.19 (2026-04)

### Fixed
- **Mojibake `â€¦` on the "Export current TBL as JSON…" button.**
  The horizontal-ellipsis character (`…`, UTF-8 `E2 80 A6`) was
  going through `CreateWindowExA` to an ANSI BUTTON, which
  interpreted the bytes as cp1252. Replaced with three ASCII dots.
- **Shift+F7 (find next) now works from inside sub-grid popups.**
  `GridSubclassProc` previously skipped F3/F7/Ctrl+F forwarding
  when `IsSubGrid` was true (to avoid sending key events out of
  the popup), but TC's standard "find next" shortcut needs to
  reach the Lister parent regardless. Sub-grids now forward via
  `ParentHost` so the search dialog opens / continues normally.
- **Config tab forwards F3/F7/Ctrl+F/Esc/F4 to TC.** The Config
  panel is a custom child window class — pressing search keys
  while it had focus (e.g. on a button or combobox) would consume
  the event silently. Added explicit `WM_KEYDOWN` forwarding to
  the Lister parent.

### Notes on JSON tab editability
- The JSON tab IS editable when in EDIT MODE (`F4` toggles).
  Default state on open is read-only (`READ-ONLY` shown in the
  status strip). If you can't type into the JSON Edit, press F4
  first — the strip should turn red and read `EDIT MODE`. If F4
  has no effect, it usually means focus is on a non-subclassed
  control; click into the JSON Edit area first, then F4.

## v1.3.18 (2026-04)

### Added
- **`build.sh` now auto-bootstraps missing Win64 cross units.** On
  AlmaLinux/RHEL/Fedora and other distributions that don't ship
  Win64 RTL with FPC, the script now builds the necessary units
  (RTL + winunits-base + objpas extras) on first run instead of
  requiring a manual setup procedure. Subsequent builds reuse the
  bootstrapped units.
- **Auto-detection of FPC install layouts.** `build.sh` now finds
  the FPC lib dir automatically across:
  - `/opt/fpc-<ver>/lib/fpc/<ver>/` (manual upstream tarball install)
  - `/usr/lib/fpc/<ver>/` (RPM/DNF builds)
  - `/usr/lib/x86_64-linux-gnu/fpc/<ver>/` (Debian multi-arch)
  - `/usr/local/lib/fpc/<ver>/`
  - Override via `FPC_LIB` env var if non-standard.
- **`BUILD.md`** rewritten as a step-by-step guide with verbatim
  tested commands for both Debian/Ubuntu (one apt line) and
  AlmaLinux 8/9 (~10 commands; tarball + EPEL mingw + samplecfg
  + bootstrap). Includes a troubleshooting section for the common
  failure modes.

### Notes
- The Debian/Ubuntu flow (`apt install fpc fp-units-fcl
  fp-compiler-source gcc-mingw-w64-x86-64`) is still the easiest
  path. Bootstrap auto-detection is invisible there because Debian
  ships pre-built Win64 units in the package.
- AlmaLinux first build needs to be run as `sudo ./build.sh` (or
  the unit dirs need to be pre-`chown`ed) because the bootstrap
  writes into the FPC install tree. Subsequent builds work as a
  normal user.

## v1.3.17 (2026-04)

### Added
- **Export current TBL as JSON…** button in the Config tab. Opens a
  Save File dialog (suggested filename is the source TBL's basename
  with `.json` extension). Writes the same content the JSON tab
  displays (with the header comment block).
- **JSON ↔ grid auto-sync.** After any successful save, the plugin
  rebuilds every tab from the model. Edits made in JSON now show up
  in grid tabs immediately; edits made in grids show up in the JSON
  tab. Active tab index is preserved across the rebuild.
- **JSON tab marks the file dirty on edit.** Previously only grid
  cell commits set the dirty flag; typing in JSON didn't. F2 reload
  now correctly prompts to save unsaved JSON changes.

### Fixed
- **Pre-save consistency check** for the JSON path. Before letting
  `FromJSON` touch the model, the parsed JSON must have:
  - a `sections` array that is actually a JSON array
  - the same number of sections as the original
  - matching section names (renaming sections breaks the writer's
    schema/section mapping)
  Failing any check pops a clear MessageBox and aborts the save —
  no partial write to the file.

## v1.3.16 (2026-04)

### Fixed
- **Esc inside sub-grid popup now reliably closes it.** v1.3.13's
  fix routed Esc through `DispatchMessage` to the focused control's
  WndProc, which worked when focus was on the sub-grid itself but
  failed when focus had drifted to a non-grid child (column header,
  the popup chrome, etc.) or when the focus chain was disrupted by
  earlier interactions. The popup's modal message loop now intercepts
  `WM_KEYDOWN VK_ESCAPE` directly:
  - If an inline cell-edit overlay is visible → dispatch normally so
    `OverlayEditProc` cancels the edit.
  - Otherwise → unconditionally `PostMessage(PopupWnd, WM_CLOSE)`,
    closing the popup regardless of which child has focus.
- **Mojibake `â€"` in the status strip.** The em-dash separator
  (`—`, UTF-8 `E2 80 94`) was sent through `SendMessageA(WM_SETTEXT)`
  to an ANSI STATIC control, which interpreted the bytes as cp1252.
  Replaced with ASCII `|` so the strip renders correctly without
  needing a Unicode-flavor STATIC.

### Changed
- **Mode strip color scheme swapped.** Read-only is now neutral
  (system button-face grey, blends with the rest of the chrome) and
  Edit mode is the highlighted state (pale red background, dark red
  text) — because edit mode is where accidental keystrokes can
  corrupt the file. Read-only is the safe default and shouldn't
  scream for attention.

## v1.3.15 (2026-04)

### Added
- **Array fields are now editable in the grid.** Previously the
  grid showed `[1, 2, 3]` for u8/u16/u32-array fields but
  double-click only beeped — you had to drop into the JSON tab to
  edit them. The inline overlay now accepts:
  - `[1, 2, 3]` — JSON-array notation (with or without brackets,
    with or without spaces)
  - `1, 2, 3`   — bare comma-separated
  - `[]` / empty — clears the array
  Each item must parse as the column's primitive type (integer or
  float); a non-numeric token rejects the whole edit and leaves
  the row unchanged.
- **Status strip showing edit-mode state at the top of the host.**
  A 22-pixel-tall label sits above the tab control:
  - **EDIT MODE** — pale-green background, dark-green text
  - **READ-ONLY** — pale-red background, dark-red text
  Updates instantly on F4 toggle.

### Fixed
- **Editing column 0 (the leftmost column) no longer hides the
  rest of the row's cells.** `LVM_GETSUBITEMRECT` with `LVIR_BOUNDS`
  returns the *entire row's* rect when called for subitem 0 (a
  Win32 ListView quirk), so the floating Edit overlay covered all
  cells in the row instead of just the first one. Fixed by using
  `LVIR_LABEL` for column 0 and `LVIR_BOUNDS` for the rest.

## v1.3.14 (2026-04)

### Added
- **Sub-grid (nested-struct popup) position and size are now also
  remembered between sessions.** Same convention as the main
  Lister window: gated by `RememberWindowSize`, persisted in
  `tbl_wlx.ini` under the `[TBL_WLX]` section as `LastSubX`,
  `LastSubY`, `LastSubW`, `LastSubH`. Captured when the popup
  closes (Esc, ✕, after editing); restored when next double-click
  on a `[N rows]` cell opens a popup. If the saved values are
  missing or out of sane bounds (off-screen, degenerate), the
  plugin falls back to the v1.3.x default — popup placed 50px
  offset from the parent grid, sized 700×400.

### Notes
- `RememberWindowSize=0` (or unsetting it via the Config tab)
  also stops capturing/restoring sub-grid geometry; the popup
  always opens at the default offset/size.
- `MaximizeOnOpen` is *only* about the main Lister window — sub-
  grids are never auto-maximized.

## v1.3.13 (2026-04)

### Fixed
- **Esc inside sub-grid popup actually works now.** v1.3.12's Esc
  handling was correct in `GridSubclassProc` (it would post
  `WM_CLOSE` to the popup), but the keystroke never reached our
  subclass — `IsDialogMessage()` in the sub-grid's modal message
  loop was swallowing `VK_ESCAPE` and converting it to
  `WM_COMMAND IDCANCEL` on the popup window, which we don't
  handle. Effectively, Esc was dispatched to a black hole.

  Fix: the message loop in `OpenSubGrid` now bypasses
  `IsDialogMessage` for `WM_KEYDOWN VK_ESCAPE` and calls
  `TranslateMessage`/`DispatchMessage` directly, so Esc reaches
  the focused control's WndProc:
  - During inline cell edit: `OverlayEditProc` cancels the edit
  - On the grid (no active edit): `GridSubclassProc` posts
    `WM_CLOSE` to the popup, closing it
  - Other dialog navigation keys (Tab, Enter, arrow keys) still
    go through `IsDialogMessage` as before.

## v1.3.12 (2026-04)

### Fixed
- **Sub-grid (nested struct popup) now opens in read-only mode too.**
  Previously, double-clicking a `[N rows]` cell in RO mode beeped
  and refused — now it opens the popup so you can *view* the
  nested rows. Cell editing inside the popup remains gated by the
  parent instance's edit-mode flag (the sub-grid walks back to the
  original tab-host through `SubGridFindHost` to read it live).
- **Esc inside a sub-grid popup closes the popup, not the whole
  Lister.** Previously Esc forwarded to TC's parent regardless of
  context. Now `GridSubclassProc` checks `IsSubGrid` + `PopupWnd`
  on the grid state and posts `WM_CLOSE` to the popup if it's a
  sub-grid; top-level grids still forward to TC as before.
- **Sub-grid popup title no longer shows mojibake.** The `Format`
  string for the title contained an em-dash (`—`, UTF-8 bytes
  `E2 80 94`) and the column DisplayName may itself be UTF-8.
  Creating the popup via `CreateWindowExA` interpreted those bytes
  as cp1252 — title showed `effects â€" row 4 (6 nested rows)`.
  Fix: `UTF8Decode` the title and use `CreateWindowExW`.

### Added
- **Config tab gained more controls and read-only fields:**
  - **Open INI in editor** button — launches Notepad (or whatever
    is registered for `.ini`) on the active INI file.
  - **INI file path** — read-only label showing where settings
    actually live (handy when TC's `wincmd.ini` is in a non-default
    location).
  - **Last window state** — read-only label showing the last
    captured `LastWinX/Y/W/H` and the `LastWinMax` flag, so you can
    confirm window-position memory is actually capturing values.

### Sub-grid behavior summary
| Action               | RO mode               | Edit mode             |
|----------------------|-----------------------|-----------------------|
| Open sub-grid (dbl)  | ✅ opens for viewing  | ✅ opens              |
| Edit cell in sub-grid| beeps, refuses        | ✅ inline edit        |
| Esc in sub-grid      | closes popup          | closes popup          |
| Esc in top-level grid| closes Lister (TC)    | closes Lister (TC)    |

## v1.3.11 (2026-04)

### Fixed
- **UTF-8 mojibake in grid cells.** TBL files store strings as UTF-8
  (Falcom convention), but the grid was registered as an ANSI
  control, so non-ASCII characters rendered as cp1250/cp1252
  garbage — `Dantès` showed as `DantÃ¨s`, `René` as `RenÃ©`,
  `◆3D Avatar` as `â—†3D Avatar`, etc.
  
  Fix: the grid now runs in Unicode mode
  (`CCM_SETUNICODEFORMAT, 1`), column headers use
  `LVM_INSERTCOLUMNW` with UTF-16 caption text, and the
  `LVN_GETDISPINFOW` handler decodes UTF-8 cell text to UTF-16
  before writing to the control's WCHAR buffer. Cell editing also
  switched to Unicode (Edit overlay created with
  `CreateWindowExW`, text round-tripped via `UTF8Decode` /
  `UTF8Encode` on edit/commit).

### Added
- **Config tab.** A new tab labeled **Config** is appended after
  the JSON tab, with a GUI for the `[TBL_WLX]` INI section so you
  don't have to edit `tbl_wlx.ini` by hand:
  - **Preferred game** — combobox: `(auto-detect)`, Kuro1, Kuro2,
    Sora1, Ys_X, Kai
  - **Default edit mode** — checkbox (skip the F4 toggle on open)
  - **Remember window position and size between sessions** —
    checkbox
  - **Always maximize Lister on open** — checkbox
  - **Save** button — writes current values to disk and shows the
    INI path in the status line
  - **Reset to defaults** button — populates the controls with the
    factory defaults (you must click Save afterwards to persist)

## v1.3.10 (2026-04)

### Fixed
- **Find dialog no longer erases the grid background.** When TC's
  Find dialog opened (F3 / F7 / Ctrl+F), the entire grid + tabs
  were briefly painted white/grey behind the dialog, and sometimes
  stayed that way after the dialog was dismissed. Two compounding
  bugs:
  - The tab-host window class was registered with
    `hbrBackground = COLOR_BTNFACE+1`, so every `WM_ERASEBKGND`
    filled the whole client area with grey *before* the children
    got a chance to paint. The dialog opening triggered an erase,
    showing grey for one frame, hiding the grid.
  - Even after the dialog was dismissed, the LVS_OWNERDATA grid's
    cached cell-text replies were sometimes invalidated; only the
    focused/selected row repainted, leaving the rest blank.

  Fix: window class now uses `hbrBackground = 0` (no fill — children
  fully cover the client area), `WM_ERASEBKGND` handler returns 1
  (handled, don't fill), and `WM_PAINT` on the host invalidates the
  active tab's child so the next paint cycle re-queries every
  visible cell from `LVN_GETDISPINFO`.

## v1.3.9 (2026-04)

### Fixed
- **Crash on first F3 of a session**. The window-state restore from
  v1.3.7 called `SetWindowPos` / `ShowWindow(SW_MAXIMIZE)` on TC's
  Lister parent *during* `ListLoad`, which reentrantly fired
  `WM_SHOWWINDOW` into TC while it was still in the middle of its
  plugin-loading state machine. On some configurations this corrupted
  TC's internal state and crashed the whole TC process.
  
  Fix: window-state restore is now scheduled via `SetTimer(100ms)`
  on the plugin's tab-host, so it runs *after* `ListLoad` returns
  and TC has finished its plugin-loading dance. The `WM_TIMER`
  handler in `TabHostWndProc` calls `KillTimer` first to ensure
  the apply runs only once, then invokes `ApplyWindowStateNow`
  inside a `try/except` for extra safety.

- **`MaximizeOnOpen` / `LastWinMax` now use `IsZoomed` guard** before
  calling `ShowWindow(SW_MAXIMIZE)`. If the window is already
  maximized (e.g. TC's own "Save Position" already restored it),
  we skip the call entirely so we don't trigger redundant resize
  notifications.

### Behavior notes (search dialog)

If the user reports that "F7 / Ctrl+F sometimes opens TC's standard
Find dialog" (with checkboxes for whole words, backwards search,
match case, and hex search) — that is the **expected** behavior. WLX
plugins forward F-keys to TC's Lister, which then opens its built-in
Find dialog. Our plugin doesn't ship a custom search UI; instead we
implement `ListSearchText` and let TC drive.

## v1.3.8 (2026-04)

### Fixed
- **F3 / F7 / Ctrl+F now actually open the search dialog.**
  Previously the keystrokes were swallowed by whichever child
  control had focus (grid, JSON Edit) and never reached Total
  Commander, so the only way to start a search was via
  *Edit → Find* in the menu. The grid, JSON-Edit, and tab-host
  subclass procs now forward F3 / F7 / Ctrl+F to the TC Lister
  parent the same way Esc and F4 are forwarded.
- **Grid search no longer leaves the view in a "single visible row,
  rest blank" state.** Two compounding bugs:
  - The search switched tabs *after* `SetItemState` /
    `EnsureVisible` fired on the (still-hidden) target grid.
    `LVS_OWNERDATA` ListViews don't repaint cells that weren't
    queried while the control was visible, so on tab activation
    only the focused/selected row painted.
  - Even with the right ordering, the post-`SelectTabAt` paint
    relied on Windows' lazy invalidation, which sometimes left
    cached rows blank.
  Fix: `SelectTabAt` now does an explicit
  `InvalidateRect(child, nil, TRUE) + UpdateWindow(child)` after
  showing the new tab, and the grid-search hit handler does the
  same on the grid before calling `SetFocus`. The search call site
  in `DoSearch` also switches tabs *before* running the search,
  not after.

## v1.3.7 (2026-04)

### Added
- **Grid cell search.** F3/F7 now scans cells in the active grid tab
  (and continues into other tabs if no hit there). When a match is
  found, the plugin selects the row, scrolls it into view, and
  switches the active tab if the hit was on a different tab.
  Previously, F3 only worked inside the JSON tab — search on a grid
  tab silently fell through.
- **Window position / size memory.** The plugin now persists the
  Lister window's last position and size to `tbl_wlx.ini` on close,
  and restores them next time the plugin opens a TBL file. Maximized
  state is preserved separately so unmaximizing later gives a sane
  size.
- **`MaximizeOnOpen=1`** INI flag. Add to `[TBL_WLX]` to always open
  the Lister maximized, regardless of the saved size.

### INI keys (under `[TBL_WLX]`)
| Key                 | Default | Description                          |
|---------------------|--------:|--------------------------------------|
| `RememberWindowSize`|       1 | Restore last position+size on open   |
| `MaximizeOnOpen`    |       0 | Always maximize on open              |
| `LastWinX/Y/W/H`    |      -1 | Auto-updated on close (don't edit)   |
| `LastWinMax`        |       0 | Auto-updated on close (don't edit)   |

### Note about TC's built-in "Save Position"
Total Commander's Lister has its own *Options → Save position* menu
entry that does roughly the same thing. If you've already used that,
you can leave the new INI defaults alone or set
`RememberWindowSize=0` to disable the plugin-side persistence and
let TC handle it. The two systems don't fight, but TC's saved
position will win on the very first open before our INI restore
kicks in.

### Search semantics
- Plain text substring; case-insensitive by default (TC's *Match
  case* checkbox toggles).
- Wraps around: starts from the active tab+row, runs forward through
  remaining tabs, then wraps to tab 0 and continues until back at the
  start.
- Non-text fields (numbers, arrays, nested-summary `[N rows]`) are
  matched as their displayed text — so searching `42` finds rows
  whose any cell prints `42`.

## v1.3.6 (2026-04)

### Fixed
- **Esc key now closes the plugin window**. Previously, Esc was
  swallowed by whichever child control had focus (the grid, JSON
  Edit, or sub-grid Edit) and never reached Total Commander, so the
  Lister window stayed open. Now all three of our subclassed window
  procs forward Esc to the TC parent window via
  `PostMessage(parent, WM_KEYDOWN, VK_ESCAPE)`, which TC interprets
  as "close Lister".
- Esc on the JSON tab no longer triggers the standard Edit-control
  beep (`WM_CHAR` with `0x1B` is now swallowed alongside the keydown
  forward).

### Behavior notes
- Esc on a sub-grid popup still closes the popup (not the whole
  Lister) — that's existing behavior, intentional.
- During inline cell editing, Esc still cancels the edit (handled
  by `OverlayEditProc` before the new top-level forward).

## v1.3.5 (2026-04)

### Added
- **`DefaultEditMode` INI setting**. Add `DefaultEditMode=1` under
  `[TBL_WLX]` in your `tbl_wlx.ini` to make every newly opened TBL
  start in edit mode (skipping the F4 step). Default remains `0`
  (read-only). Useful if you primarily use the plugin to edit, not
  to view.

### Changed
- **F4 toggle is no longer a popup.** It now plays distinct beeps
  (info pitch for ON, warning pitch for OFF) instead of opening a
  modal dialog after each press. This is much less intrusive when
  you toggle modes frequently. The JSON tab's read-only state still
  changes visibly so you can confirm the mode switched.

## v1.3.4 (2026-04)

### Added
- **Read-only by default + F4 to toggle edit mode**. The plugin now
  opens every file in **read-only mode** when invoked from F3 (the
  Total Commander Lister). Press **F4 inside the plugin window** to
  toggle to edit mode (and F4 again to flip back).
- In read-only mode:
  - Double-click on a cell beeps and refuses (no inline editor opens)
  - The JSON tab's text area is disabled (read-only) — you can still
    select and copy, but not type
  - Ctrl+S in the JSON tab is a no-op (beep)
  - Closing the window does **not** show a save prompt
- In edit mode, all editing works as before (cell editing, sub-grid
  popups, JSON editing, Ctrl+S, save-on-close prompt).

### Note about TC F4 vs the plugin's F4
Total Commander's own F4 key opens the *external editor* configured
in `wincmd.ini` (`[Configuration] Editor=`); it does **not** invoke
WLX plugins. To get edit mode for a TBL file:
- Press F3 (TC) → plugin opens in read-only mode
- Press F4 (inside the plugin) → flip to edit mode
- OR: set `DefaultEditMode=1` in `tbl_wlx.ini` to skip the F4 step
  (added in v1.3.5)

## v1.3.3 (2026-04)

### Fixed
- **Plugin no longer claims unrelated files** (`.md`, `.ini`, `.inf`,
  etc.). The previous detect string used `FIND("#TBL")` which scans
  the first 8 KB of the file, so any random text file mentioning
  `#TBL` anywhere in its content was wrongly matched. The new detect
  string uses **only** exact matches:
  - file extension is `.tbl`, OR
  - the file's first 4 bytes are exactly `#TBL` (plain TBL), OR
  - the file's first 2 bytes are `F9 BA` (CLE encrypted), OR
  - the file's first 2 bytes are `D9 BA` (CLE encrypted+compressed)

### Important: existing installations need a one-time fix

If you installed v1.3.0 / v1.3.1 / v1.3.2 (or installed manually
through Configuration → Plugins → Lister WLX → Add), Total Commander
saved the **old** detect string into `wincmd.ini` and won't update
it just because you install a newer DLL. To reset:

**Option A (recommended): reinstall via the auto-installer.** Open
`tbl_wlx_v1.3.4_plugin.zip` from inside Total Commander, click Yes on
the install dialog. TC overwrites both the DLL and the `wincmd.ini`
detect string entry.

**Option B: manual edit.** Open `wincmd.ini` (Configuration →
Options → Configuration → "Open in editor"), find your `[ListerPlugins]`
section, locate the `<n>_detect=...` line that mentions
`tbl_wlx.wlx64`, and replace its value with:

```
EXT="TBL" | ([0]=35 & [1]=84 & [2]=66 & [3]=76) | ([0]=249 & [1]=186) | ([0]=217 & [1]=186)
```

Save, restart TC.

**Option C: remove + re-add.** In TC: Configuration → Options →
Plugins → Lister (WLX) → Configure → select the existing TBL plugin →
Remove. Then either re-run the installer ZIP, or click Add and pick
`tbl_wlx.wlx64` again.

## v1.3.2 (2026-04)

### Fixed
- **Crash on close**: Total Commander would crash when closing the
  Lister window in some cases. Root cause: the overlay Edit's
  subclassed window proc dereferenced freed grid state (`St^`)
  during `WM_NCDESTROY` after `ClearAllTabs` had already disposed
  the state record. The subclass procs are now hardened to handle
  a nil state, and `DestroyGridState` explicitly unsubclasses the
  Edit before disposing state. `ClearAllTabs` similarly unsubclasses
  the JSON-tab Edit before destroying it.
- Managed-type fields (`Cols`, `Rows`, `Caption`) are now explicitly
  nilled before `Dispose` to avoid double-finalize on shared
  dynamic-array data when the same `Cols` array is held by both a
  `TGridState` and its parent `TTabEntry`.
- `ListCloseWindow` now guards `DestroyWindow` with `IsWindow` and
  wraps each teardown step in its own `try/except`.

## v1.3.1 (2026-04)

### Fixed
- **Plugin DLL renamed from `tbl_wlx.dll` to `tbl_wlx.wlx64`**.
  Total Commander only treats files with `.wlx`/`.wlx64` extensions
  as Lister plugins; the previous `.dll` name caused TC's plugin
  installer to skip auto-detection.
- `pluginst.inf` updated to point at `tbl_wlx.wlx64`.
- Manual install: pick the `.wlx64` file (not a `.dll`) when adding
  the plugin via Configuration → Options → Plugins.

## v1.3 (2026-04)

### Added
- F2 reload now functional (re-reads file from disk, asks before
  discarding unsaved changes)
- INI settings persistence (`[TBL_WLX] PreferredGame=...`)
- TC plugin auto-installer manifest (`pluginst.inf`)
- Crash-safety: every `stdcall` entry point wrapped in `try/except`
- Memory leak audit (HeapTrc): 0 leaks on happy path and error path
- Fuzz hardening: bounds check on `SecStart + SecLen*SecCount`
  prevents OOM on malformed section directories
- `build.sh` / `run-tests.sh` reproducibility scripts
- `TROUBLESHOOTING.md`

### Changed
- (Internal) Removed dead `tbllib.pas` from the eArmada8-based
  prototype. All file I/O lives in `tblfile.pas` now.

## v1.2 (2026-04)

### Added
- Tabbed view: one tab per TBL section + a JSON tab at the end
- Per-section grid view (Win32 ListView, virtual mode)
- Inline cell edit overlay (double-click → Edit → Enter/Escape)
- Sub-grid dialog for nested-struct fields (modal popup)
- Tab strip at top of viewer (`SysTabControl32`)

### Changed
- `gridmodel`: nested struct fields now render as a single
  `[N rows]` summary cell instead of inline-expanding into N×K
  columns. Cleaner UX for sections like `ItemTableData.effects`.
- DLL grew from ~520 KB to ~725 KB due to grid + tab UI

## v1.1 (2026-04)

### Added
- Editable JSON view (`ES_READONLY` removed)
- Ctrl+S in the JSON edit triggers Save
- `EM_SETMODIFY` / `EM_GETMODIFY` dirty tracking
- Close-prompt for unsaved changes
- `StripHeaderComment` strips informational `//` lines on save

## v1.0 (2026-04)

### Added
- Initial WLX Lister plugin for Total Commander
- Read-only JSON view of decoded `#TBL` files
- 11 standard WLX entry points
- Schema DB driven by KuroTools' 282-header / 346-variant set
- Auto-detect CLE wrap (Blowfish-CTR + ZSTD)
- Verbatim raw passthrough for sections without a schema
- Round-trip parity: 408/411 bit-identical, 411/411 functionally
  identical against KuroTools Python `json2tbl`
