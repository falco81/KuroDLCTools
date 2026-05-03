# KuroTools modding guide

The PDF in this folder is the original KuroTools modding guide written
by Twn (with tools by Twn, SoftBrilliant, hell259), explaining how the
TBL and DAT formats work for Kuro no Kiseki PC.

It documents the same TBL format we handle in this plugin:
- Header section: 80 bytes per entry (64-byte name + CRC32 + start_offset
  + entry_length + entry_count)
- Entry data follows immediately after the headers
- Pointer fields (`toffset`) reference NUL-terminated UTF-8 strings in
  data2 (after all entry rows).

## Confirmed semantic field names (from PDF examples)

The PDF shows decompiled JSON examples that confirm field naming
conventions used in our schemas. These align with KuroTools' published
schemas — none introduces *new* schema definitions, but they all
validate that our integrated set is correct.

### t_npc_<map>.tbl — NpcTableData
```
char_id, start_scena_flag, int1, end_scena_flag, int2, map, X, Y, Z,
orientation_angle, range_interaction, int (=character_id), flt7..flt10,
text1, talk_setting_function, first_animation_function, int3, int4,
talk_function, text2, int5..int8
```

### t_name.tbl — NameTableData
```
character_id, name, texture, face, model, long1, text1, text2,
long2, text3, text4
```

### t_achievement.tbl — AchievementTableData
```
achievement_category, achievement_id, achievement_objective_1,
achievement_objective_param_1, arr1, short1, short2, int1, int2,
long1, flag, achievement_name, achievement_description
```

(matches our FALCOM_PS4 / Kuro1 schema exactly)

### t_item.tbl — ItemTableData
```
id, character_restriction, text1, text2, ..., stack_size, price,
animation, name, description, data
```

## Schema variants explained

Per the PDF: schema name like `FALCOM_PS4` corresponds to a **specific
version** of a header. Multiple versions can exist because games/ports
add fields between releases. Example from the guide:

> CLE port adds new data to the t_quest table; this is why there is a
> `CLE_PC` version of the QuestTitle header, and also a `FALCOM_PS4` one.

Our plugin's variant-selection logic (`FindVariant` in `tblschemas.pas`)
implements this:
1. Among all variants whose `Size == EntryLength`, pick the one whose
   `GameTag == PreferGame` if user has set a game preference.
2. Otherwise pick the first size-matching variant.

The PDF confirms this strategy is correct.
