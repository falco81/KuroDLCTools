#!/usr/bin/env python3
"""
kurodlc_game_profiles.py - per-game table layouts for the KuroDLC toolkit

The DLC tables have a different shape in every game.  The differences that
matter when *generating* entries are:

  ItemTableData
    Kuro 1 / 2 / Kai   248 bytes, chr_restrict = number, patk/pdef/matk/mdef,
                       costume category 17
    Trails in the Sky
      1st Chapter      232 bytes, chr_restrict = number, item_icon/element,
                       costume category 15
      2nd Chapter      256 bytes, chr_restrict = LIST, three extra fields
                       (unk0 after chr_restrict, unk1 after float3,
                       unk2 after price), costume category 15
    Ys X               176 bytes, entirely different field set

  DLCTableData
    Kuro 1 / Sky 1st   88 bytes  (extra unk2, unk3, unk4, unk_arr, unk5)
    Kuro 2 / Sky 2nd   64 bytes
    Kyoto Xanadu       72 bytes  (extra desc2)

  CostumeParam / ShopItem
    identical in Kuro 1 / 2 and both Sky chapters

Every script that creates entries or interprets category numbers should ask
this module rather than hardcoding one game's layout.

Detection order used by the scripts:
  1. an explicit --game flag
  2. the entry length of ItemTableData in the loaded .tbl (exact)
  3. the field names of an existing entry (.json / .kurodlc.json)

Part of the KuroDLC Modding Toolkit.
"""

import copy

__all__ = [
    'GAME_IDS', 'GAME_ALIASES', 'PROFILES', 'DEFAULT_GAME',
    'get_profile', 'resolve_game_id', 'describe_games',
    'detect_game_from_item_length', 'detect_game_from_item_entry',
    'detect_game_from_tables', 'detect_game_from_kurodlc',
    'make_item_template', 'make_dlc_template', 'make_costume_template',
    'make_shop_template', 'normalize_chr_restrict', 'chr_restrict_value',
    'coerce_entry_to_profile', 'convert_item_entry', 'migrate_kurodlc',
]

DEFAULT_GAME = 'kuro'

GAME_IDS = ['kuro', 'sky1st', 'sky2nd', 'ysx']

# Accepted spellings for --game
GAME_ALIASES = {
    'kuro': 'kuro', 'kuro1': 'kuro', 'kuro2': 'kuro', 'kai': 'kuro',
    'daybreak': 'kuro', 'daybreak2': 'kuro', 'ed9': 'kuro',
    'sky': 'sky1st', 'sky1': 'sky1st', 'sky1st': 'sky1st', 'fc': 'sky1st',
    'sky_1st': 'sky1st', 'sky-1st': 'sky1st', '1st': 'sky1st',
    'sky2': 'sky2nd', 'sky2nd': 'sky2nd', 'sc': 'sky2nd',
    'sky_2nd': 'sky2nd', 'sky-2nd': 'sky2nd', '2nd': 'sky2nd',
    'ys': 'ysx', 'ysx': 'ysx', 'ys_x': 'ysx', 'ys-x': 'ysx',
}

# ---------------------------------------------------------------------------
# Item entry templates.  Field order follows the schema so generated .json
# files read the same way as the ones produced by kuro_dlc_tool.
# ---------------------------------------------------------------------------

_EFFECT_FIELDS = {}
for _i in range(1, 6):
    _EFFECT_FIELDS['eff{}_id'.format(_i)] = 0
    for _j in range(3):
        _EFFECT_FIELDS['eff{}_{}'.format(_i, _j)] = 0


def _kuro_item_template():
    entry = {
        "id": 0, "chr_restrict": 0, "flags": "", "unk_txt": "1",
        "category": 17, "subcategory": 16,
        "unk0": 0, "unk1": 0, "unk2": 0, "unk3": 0, "unk4": 0,
    }
    entry.update(copy.deepcopy(_EFFECT_FIELDS))
    entry.update({
        "unk5": 0,
        "hp": 0, "ep": 0, "patk": 0, "pdef": 0, "matk": 0, "mdef": 0,
        "str": 0, "def": 0, "ats": 0, "adf": 0, "agl": 0, "dex": 0,
        "hit": 0, "eva": 0, "meva": 0, "crit": 0, "spd": 0, "mov": 0,
        "stack_size": 1, "price": 100, "anim": "", "name": "", "desc": "",
        "unk6": 0, "unk7": 0, "unk8": 0, "unk9": 0,
    })
    return entry


def _sky1st_item_template():
    entry = {
        "id": 0, "chr_restrict": 0, "flags": "", "unk_txt": "2",
        "category": 15, "subcategory": 16,
        "item_icon": 0, "effect_icon": 0, "element": 0,
        "int1": 0, "float1": 0, "float2": 0,
    }
    entry.update(copy.deepcopy(_EFFECT_FIELDS))
    entry.update({
        "float3": 0,
        "hp": 0, "ep": 0, "str": 0, "def": 0, "ats": 0, "adf": 0,
        "agl": 0, "dex": 0, "hit": 0, "eva": 0, "aev": 0, "crit": 0,
        "spd": 0, "mov": 0,
        "stack_size": 1, "price": 100, "anim": "", "name": "", "desc": "",
        "unk6": 0, "unk7": 0, "unk8": 0, "unk9": 0,
    })
    return entry


def _sky2nd_item_template():
    entry = {
        "id": 0, "chr_restrict": [0], "unk0": 0, "flags": "", "unk_txt": "2",
        "category": 15, "subcategory": 16,
        "item_icon": 0, "effect_icon": 0, "element": 0,
        "int1": 0, "float1": 0, "float2": 0,
    }
    entry.update(copy.deepcopy(_EFFECT_FIELDS))
    entry.update({
        "float3": 0, "unk1": 0,
        "hp": 0, "ep": 0, "str": 0, "def": 0, "ats": 0, "adf": 0,
        "agl": 0, "dex": 0, "hit": 0, "eva": 0, "aev": 0, "crit": 0,
        "spd": 0, "mov": 0,
        "stack_size": 1, "price": 100, "unk2": 0,
        "anim": "", "name": "", "desc": "",
        "unk6": 0, "unk7": 0, "unk8": 0, "unk9": 0,
    })
    return entry


_DLC_TEMPLATE_SHORT = {          # Kuro 2 / Sky 2nd Chapter (64 bytes)
    "id": 0, "sort_id": 0, "items": [], "unk0": 0, "quantity": [],
    "unk1": 0, "name": "", "desc": "", "unk_txt": "",
}

_DLC_TEMPLATE_LONG = {           # Kuro 1 / Sky 1st Chapter (88 bytes)
    "id": 0, "sort_id": 0, "items": [], "unk0": 0, "quantity": [],
    "unk1": 0, "name": "", "desc": "", "unk_txt": "",
    "unk2": 0, "unk3": 1, "unk4": 0, "unk_arr": [], "unk5": 0,
}

_COSTUME_TEMPLATE = {
    "char_restrict": 0, "type": 0, "item_id": 0, "unk0": 0, "unk_txt0": "",
    "mdl_name": "", "unk1": 0, "unk2": 0, "attach_name": "",
    "unk_txt1": "", "unk_txt2": "",
}

_SHOP_TEMPLATE = {
    "shop_id": 0, "item_id": 0, "unknown": 1, "start_scena_flags": [],
    "empty1": 0, "end_scena_flags": [], "int2": 0,
}


PROFILES = {
    'kuro': {
        'id': 'kuro',
        'name': 'Kuro no Kiseki / Daybreak / Kai (ED9)',
        'item_entry_length': 248,
        'dlc_entry_lengths': [88, 64],       # Kuro 1 = 88, Kuro 2 / Kai = 64
        'dlc_template_default': 'long',
        'chr_restrict_is_list': False,
        'item_template': _kuro_item_template,
        'categories': {'costume': 17, 'hair': 18, 'accessory': 19, 'orbment': 24},
        'costume_subcategory': 16,
        'category_names': {17: 'Costumes', 18: 'Hair color',
                           19: 'Accessories', 24: 'ARCUS covers'},
        'max_item_id': 5000,
    },
    'sky1st': {
        'id': 'sky1st',
        'name': 'Trails in the Sky 1st Chapter',
        'item_entry_length': 232,
        'dlc_entry_lengths': [88],
        'dlc_template_default': 'long',
        'chr_restrict_is_list': False,
        'item_template': _sky1st_item_template,
        'categories': {'costume': 15, 'hair': 16, 'accessory': 17, 'orbment': 19},
        'costume_subcategory': 16,
        'category_names': {15: 'Costumes', 16: 'Hair color',
                           17: 'Accessories', 19: 'Orbment covers'},
        'max_item_id': 5000,
    },
    'sky2nd': {
        'id': 'sky2nd',
        'name': 'Trails in the Sky 2nd Chapter',
        'item_entry_length': 256,
        'dlc_entry_lengths': [64],
        'dlc_template_default': 'short',
        'chr_restrict_is_list': True,
        'item_template': _sky2nd_item_template,
        'categories': {'costume': 15, 'hair': 16, 'accessory': 17, 'orbment': 19},
        'costume_subcategory': 16,
        'category_names': {15: 'Costumes', 16: 'Hair color',
                           17: 'Accessories', 19: 'Orbment covers'},
        'max_item_id': 5000,
    },
    'ysx': {
        'id': 'ysx',
        'name': 'Ys X: Nordics',
        'item_entry_length': 176,
        'dlc_entry_lengths': [64],
        'dlc_template_default': 'short',
        'chr_restrict_is_list': False,
        'item_template': None,               # Ys X uses its own generator
        'categories': {'costume': 0},
        'costume_subcategory': 0,
        'category_names': {},
        'max_item_id': 5000,
    },
}

# Item entry length -> game id.  Exact and unambiguous, so this is the
# preferred detection route whenever a .tbl was read.
_LENGTH_TO_GAME = {248: 'kuro', 232: 'sky1st', 256: 'sky2nd', 176: 'ysx'}


def resolve_game_id(value):
    """Map a user-supplied game name to a profile id, or None if unknown."""
    if not value:
        return None
    return GAME_ALIASES.get(str(value).strip().lower().replace(' ', ''))


def get_profile(game_id):
    """Return the profile dict for `game_id` (falls back to Kuro)."""
    return PROFILES.get(resolve_game_id(game_id) or game_id, PROFILES[DEFAULT_GAME])


def describe_games():
    """One line per supported game, for --help output."""
    return "\n".join("  {:<7} {}".format(gid, PROFILES[gid]['name']) for gid in GAME_IDS)


def detect_game_from_item_length(entry_length):
    """Detect the game from the ItemTableData entry length of a .tbl."""
    return _LENGTH_TO_GAME.get(entry_length)


def detect_game_from_item_entry(entry):
    """Detect the game from the field names of one ItemTableData entry."""
    if not isinstance(entry, dict):
        return None
    keys = set(entry.keys())
    if 'obtain_type' in keys or 'short_desc' in keys:
        return 'ysx'
    if 'patk' in keys or 'meva' in keys:
        return 'kuro'
    if 'item_icon' in keys or 'aev' in keys:
        # Both Sky chapters.  2nd Chapter adds unk0 / unk1 / unk2 and stores
        # chr_restrict as a list.
        if 'unk0' in keys or 'unk1' in keys or 'unk2' in keys:
            return 'sky2nd'
        if isinstance(entry.get('chr_restrict'), list):
            return 'sky2nd'
        return 'sky1st'
    return None


def detect_game_from_tables(schema_dict):
    """Detect the game from a kuro_tables().schema_dict (name -> entry length)."""
    if not schema_dict:
        return None
    game = detect_game_from_item_length(schema_dict.get('ItemTableData'))
    if game:
        return game
    # No t_item around: fall back to the DLC table, which at least separates
    # the 64-byte games (Kuro 2 / Sky 2nd) from the 88-byte ones.
    dlc_len = schema_dict.get('DLCTableData')
    if dlc_len == 88:
        return None       # Kuro 1 or Sky 1st - ambiguous, let the caller ask
    return None


def detect_game_from_kurodlc(data):
    """Detect the game from an already loaded .kurodlc.json structure."""
    if not isinstance(data, dict):
        return None
    items = data.get('ItemTableData') or []
    for entry in items:
        game = detect_game_from_item_entry(entry)
        if game:
            return game
    # Nothing but a DLC section: the long form is Kuro 1 / Sky 1st.
    for entry in data.get('DLCTableData') or []:
        if isinstance(entry, dict) and 'unk_arr' in entry:
            return None
    return None


def dlc_template_is_long(game_id, dlc_entry_length=None):
    """True if DLCTableData needs the five extra Kuro 1 / Sky 1st fields."""
    if dlc_entry_length == 88:
        return True
    if dlc_entry_length == 64:
        return False
    return get_profile(game_id)['dlc_template_default'] == 'long'


def make_item_template(game_id):
    """A fresh ItemTableData entry with this game's field set."""
    profile = get_profile(game_id)
    factory = profile['item_template']
    if factory is None:
        return None
    return factory()


def make_dlc_template(game_id, dlc_entry_length=None):
    """A fresh DLCTableData entry with this game's field set."""
    long_form = dlc_template_is_long(game_id, dlc_entry_length)
    return copy.deepcopy(_DLC_TEMPLATE_LONG if long_form else _DLC_TEMPLATE_SHORT)


def make_costume_template(game_id=None):
    """A fresh CostumeParam entry (identical in Kuro and both Sky chapters)."""
    return copy.deepcopy(_COSTUME_TEMPLATE)


def make_shop_template(game_id=None):
    """A fresh ShopItem entry (identical in Kuro and both Sky chapters)."""
    return copy.deepcopy(_SHOP_TEMPLATE)


def normalize_chr_restrict(value, game_id):
    """Return `value` in the form this game's ItemTableData expects.

    Sky 2nd Chapter stores chr_restrict as a list of character ids, every
    other game as a single number.
    """
    wants_list = get_profile(game_id)['chr_restrict_is_list']
    if wants_list:
        if isinstance(value, list):
            return list(value)
        return [] if value is None else [value]
    if isinstance(value, list):
        return value[0] if value else 65535
    return 65535 if value is None else value


def chr_restrict_value(value, default=65535):
    """Read a chr_restrict field of any game as one number (for display).

    Sky 2nd Chapter's list form collapses to its first entry; an empty list
    means "no restriction" and yields `default`.
    """
    if isinstance(value, list):
        return value[0] if value else default
    return default if value is None else value


def coerce_entry_to_profile(entry, game_id, section='ItemTableData'):
    """Reshape one entry to this game's field set.

    Missing fields are filled from the template, unknown fields are dropped and
    chr_restrict is converted between the number and list forms.  Used when an
    entry is copied from a file made for a different game.
    """
    if section == 'ItemTableData':
        template = make_item_template(game_id)
    elif section == 'DLCTableData':
        template = make_dlc_template(game_id)
    elif section == 'CostumeParam':
        template = make_costume_template(game_id)
    elif section == 'ShopItem':
        template = make_shop_template(game_id)
    else:
        return copy.deepcopy(entry)
    if template is None:
        return copy.deepcopy(entry)
    result = {}
    for key, default in template.items():
        result[key] = copy.deepcopy(entry[key]) if key in entry else copy.deepcopy(default)
    if section == 'ItemTableData' and 'chr_restrict' in result:
        result['chr_restrict'] = normalize_chr_restrict(result['chr_restrict'], game_id)
    return result


def _item_type_of_category(game_id, category):
    """'costume', 'hair'... for a category number of this game, or None."""
    for type_name, number in get_profile(game_id)['categories'].items():
        if number == category:
            return type_name
    return None


def convert_item_entry(entry, source_game, target_game):
    """An ItemTableData entry of one game rewritten for another.

    Fields are matched by name (missing ones come from the target template,
    unknown ones are dropped), chr_restrict switches between the number and
    list forms, and the category follows the item type: a Kuro costume
    (category 17) becomes a Sky costume (15), a Sky accessory (17) a Kuro one
    (19). The subcategory is 16 for costume items in every game and is kept.
    """
    result = coerce_entry_to_profile(entry, target_game, 'ItemTableData')
    if source_game and source_game != target_game and 'category' in entry:
        item_type = _item_type_of_category(source_game, entry['category'])
        target_categories = get_profile(target_game)['categories']
        if item_type in target_categories:
            result['category'] = target_categories[item_type]
    return result


def _dlc_is_long(entry):
    return isinstance(entry, dict) and any(
        key in entry for key in ('unk2', 'unk3', 'unk4', 'unk_arr', 'unk5'))


def migrate_kurodlc(data, target_game, dlc_entry_length=None):
    """Bring every entry of a loaded .kurodlc.json to target_game's layout.

    Changes `data` in place and returns {section: number of entries changed}
    plus 'from' -> the games the converted ItemTableData entries came from.
    Entries already in the target layout are left exactly as they are, so it
    is safe to run on a file that is partly or wholly converted.
    """
    report = {'ItemTableData': 0, 'DLCTableData': 0, 'from': set()}
    if make_item_template(target_game) is None:
        return report                       # no generator for this game (Ys X)
    items = data.get('ItemTableData') or []
    for index, entry in enumerate(items):
        if not isinstance(entry, dict):
            continue
        source = detect_game_from_item_entry(entry)
        if source is None or source == target_game:
            continue
        items[index] = convert_item_entry(entry, source, target_game)
        report['ItemTableData'] += 1
        report['from'].add(source)
    want_long = dlc_template_is_long(target_game, dlc_entry_length)
    dlc = data.get('DLCTableData') or []
    for index, entry in enumerate(dlc):
        if not isinstance(entry, dict) or _dlc_is_long(entry) == want_long:
            continue
        template = make_dlc_template(target_game, dlc_entry_length)
        dlc[index] = {key: copy.deepcopy(entry[key]) if key in entry
                      else copy.deepcopy(default) for key, default in template.items()}
        report['DLCTableData'] += 1
    return report

