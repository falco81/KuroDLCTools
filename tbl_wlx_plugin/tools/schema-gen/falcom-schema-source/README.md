# FalcomSchema source

Original schema data from
[Trails-Research-Group/FalcomSchema](https://github.com/Trails-Research-Group/FalcomSchema)
— 226 schema files in the FalcomSchema's typed format covering Daybreak 1,
Daybreak 2, and Ys X.

## Folders

- `common/` — 2 shared types (Effect, StatArrayDaybreak) referenced by
  the per-game schemas via `ref_<Name>`.
- `ed9_Daybreak1/` — 113 schemas for Trails through Daybreak.
- `ed9_Daybreak2/` — 74 schemas for Trails through Daybreak II.
- `ys_X/` — 39 schemas for Ys X Nordics.

## Format

Each file is a JSON object:

```json
{
    "version": 1,
    "schema": {
        "field_name": "type",
        ...
    }
}
```

### Type vocabulary

| Type | Meaning | Bytes |
|------|---------|------:|
| `u8`, `s8` | Unsigned/signed byte | 1 |
| `u16`, `s16` | Unsigned/signed short | 2 |
| `u32`, `s32` | Unsigned/signed int | 4 |
| `u64`, `s64` | Unsigned/signed long | 8 |
| `f32` | Float | 4 |
| `ptr_str_utf8` | Pointer to NUL-terminated UTF-8 string | 8 |
| `ptr_str_latin1` | Pointer to NUL-terminated Latin-1 string | 8 |
| `arr_u8`, `arr_u16`, `arr_u32` | Pointer (8) + count (4) array | 12 |
| `dN` (e.g. `d8`) | N raw bytes | N |
| `ref_<Name>` | Inline of common schema `<Name>` | varies |
| `{"repeat": N, "type": T}` | N copies of T | N × sizeof(T) |
| `{"type": T}` (no `repeat`) | Single inline of T | sizeof(T) |

## Integration into plugin

The plugin does NOT load these files directly. Instead, an offline
converter (in our `generate_schemas_v2.py` family) reads each file
and emits a KuroTools-compatible variant in `schemas/headers/<Section>.json`
under the `FALCOMSCHEMA_Daybreak1`, `FALCOMSCHEMA_Daybreak2`,
or `FALCOMSCHEMA_Ys_X` platform key.

Conversion rules:

| FalcomSchema | KuroTools (plugin) |
|---|---|
| `u8`, `u16`, `u32`, `u64`, `f32`, `s8`, `s16`, `s32`, `s64` | `ubyte`, `ushort`, `uint`, `ulong`, `float`, `byte`, `short`, `int`, `long` |
| `ptr_str_utf8`, `ptr_str_latin1` | `toffset` |
| `arr_u8`, `arr_u16`, `arr_u32` | `u8array`, `u16array`, `u32array` |
| `dN` | N × `ubyte` (with `_b0`, `_b1`, ... suffix) |
| `ref_<Name>` | Inline of common's fields, prefixed with field name |
| `{"repeat": N, "type": T}` | N expansions with `_0`, `_1`, ... suffix |

The plugin's variant-selection logic picks the FalcomSchema variant
when `PreferGame` matches (e.g. `Kuro2` for Daybreak II). For Daybreak 2
and Ys X, FalcomSchema sizes match real TBL entry lengths 100% of the
time (74/74 and 39/39 sections respectively).

## License

FalcomSchema is © Trails-Research-Group. See `LICENSE_FalcomSchema`
for the original license.
