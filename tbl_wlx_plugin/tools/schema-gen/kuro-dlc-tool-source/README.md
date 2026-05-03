# kuro_dlc_tool source schemas

Reference data from [eArmada8's kuro_dlc_tool](https://github.com/eArmada8/kuro_dlc_tool)
project. The `kurodlc_schema.json` file contains 39 schema definitions
for various TBL sections in a different format than KuroTools.

Key benefits over KuroTools schemas:
- **Better field names**: `id`, `sort_id`, `name`, `desc`, `items`,
  `quantity` instead of generic `int1`, `arr1`, `text1`.
- **Additional variants**: e.g. DLCTableData has a Kuro 1 variant
  (88 bytes) that KuroTools doesn't ship.
- **Multiple platform coverage**: Kuro 1, Kuro 2, Sky 1st, Ys X, Kai.

## Conversion

The plugin's schemas/headers/ directory has been auto-merged with these
schemas:
- 13 sections enriched with better field names from kuro_dlc_tool
- 26 new variants added (different game / size combinations)

The conversion is done by parsing kuro_dlc_tool's Python `struct` format
strings (`<2IQ2IQ2I3Q...`) and value type codes (`n`=number, `a`=u32array,
`b`=u16array, `t`=toffset).

See `kurodlc_schema.json` for the original data.

## License

kuro_dlc_tool is GPL-3.0 licensed (see `LICENSE_kdt`). Used here as a
data source under the same license.
