# Falcom enum reference

Enum value definitions extracted from
[FalcomToolsCollection](https://github.com/aviniumau/FalcomToolsCollection)
(Sky FC/SC/THIRD era), useful as documentation when interpreting
integer fields in TBL data.

## Caveat: era-specific values

These enums originate from Sky trilogy code (Falcom PC originals,
~2004-2007). Modern Falcom games (Daybreak, Daybreak II, Beyond Horizon,
Ys X) likely **share many of these values** because Falcom maintains
internal consistency, but **not all** values are guaranteed to map
across eras.

## Extracted enums

| Enum | Source | Values | Used by |
|------|--------|-------:|---------|
| `EffectEnum` | Shared/EffectEnum.cs | 106 | Item/Skill effect IDs (Effect.effect_id field) |
| `ElementEnum` | Shared/ElementEnum.cs | 8 | EARTH=1, WATER=2, FIRE=3, WIND=4, SPACE=5, MIRAGE=6, TIME=7 |
| `AbilityFlagEnum` | Shared/AbilityFlagEnum.cs | 17 | 16-bit flags on skills (HEAL, HITS_ENEMY, MAGIC, etc.) |
| `AiType` | MS_Converter/AIType.cs | 6 | Monster AI behavior type |
| `StatusResistanceEnum` | MS_Converter/StatusResistanceEnum.cs | 33 | Resistance bitfield |
| `Gender` | MS_Converter/GenderEnum.cs | 2 | MALE=0, FEMALE=1 |

## Programmatic access

`enums.json` contains all 172 (name → integer) mappings in a single
JSON file. A future plugin enhancement could load this and offer
human-readable display in the grid (e.g. show "FIRE" instead of "3"
for an `element_id` field).

## Element values quick reference

Used in many TBL fields (item/skill/orbment elements):

| ID | Element | Notes |
|---:|---------|-------|
| 0 | NONE    | |
| 1 | EARTH   | |
| 2 | WATER   | |
| 3 | FIRE    | |
| 4 | WIND    | |
| 5 | SPACE   | (was 5, not 6) |
| 6 | MIRAGE  | |
| 7 | TIME    | (was 7, not 5) |

This mapping has been verified consistent from Sky to current Trails
games per community reverse engineering.
