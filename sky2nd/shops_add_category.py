#!/usr/bin/env python3
"""
shops_add_category.py - put a whole category of items on sale in a shop.

Reads the item table, picks the items you want - every costume, every
accessory, or a hand-picked subset - and writes a .kurodlc.json that holds
nothing but a ShopItem section.  Run kurodlc_make_tbls.py afterwards and the
items can be bought in the game.

Run it with no arguments for a guided, keyboard-driven wizard, or pass options
to use it from the command line or a batch file.  See --help for everything.

Part of the KuroDLCTools toolkit.
"""

import argparse
import contextlib
import glob
import io
import json
import os
import sys

try:
    from kurodlc_lib import kuro_tables
    HAS_TBL_LIB = True
    MISSING_LIB = ''
except ImportError as e:
    HAS_TBL_LIB = False
    MISSING_LIB = str(e)

try:
    from p3a_lib import p3a_class
    HAS_P3A_LIB = True
except ImportError:
    HAS_P3A_LIB = False

try:
    from sky_pac_lib import (find_sky_pac_archives, extract_table_from_pac,
                             is_pac_file)
    HAS_PAC = True
except ImportError:
    HAS_PAC = False

    def find_sky_pac_archives(base_dir='.', table_name=None):
        return []

    def extract_table_from_pac(pac_file, table_name, out_file, quiet=False):
        return False

    def is_pac_file(path):
        try:
            with open(path, 'rb') as f:
                return f.read(4) == b'FPAC'
        except (OSError, IOError):
            return False

try:
    from kurodlc_game_profiles import (get_profile, resolve_game_id, GAME_IDS,
                                       detect_game_from_item_entry,
                                       chr_restrict_value, DEFAULT_GAME)
    HAS_PROFILES = True
except ImportError:
    HAS_PROFILES = False
    DEFAULT_GAME = 'kuro'
    GAME_IDS = []

    def chr_restrict_value(value, default=65535):
        if isinstance(value, list):
            return value[0] if value else default
        return default if value is None else value

try:
    from kurodlc_tui import (pick, confirm, ask_text, has_tui, Option, colour,
                             clear_screen, BOLD, DIM, CYAN, GREEN, YELLOW, RED)
    HAS_TUI_LIB = True
except ImportError:
    HAS_TUI_LIB = False

    def has_tui():
        return False

    def colour(text, *codes):
        return text

    BOLD = DIM = CYAN = GREEN = YELLOW = RED = ''


VERSION = '2.2'
NO_RESTRICTION = 65535


def out(text=''):
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or 'ascii'
        print(text.encode(enc, 'replace').decode(enc, 'replace'))


# ===========================================================================
# Reading the tables
# ===========================================================================

def detect_sources(base_name):
    """Available sources for t_<name>, in the toolkit's usual priority order."""
    sources = []
    if os.path.exists('{}.json'.format(base_name)):
        sources.append(('json', '{}.json'.format(base_name)))
    if os.path.exists('{}.tbl.original'.format(base_name)):
        sources.append(('original', '{}.tbl.original'.format(base_name)))
    if os.path.exists('{}.tbl'.format(base_name)):
        sources.append(('tbl', '{}.tbl'.format(base_name)))
    if os.path.exists('script_en.p3a'):
        sources.append(('p3a', 'script_en.p3a'))
    if os.path.exists('script_eng.p3a'):
        sources.append(('p3a', 'script_eng.p3a'))
    if os.path.exists('zzz_combined_tables.p3a'):
        sources.append(('zzz', 'zzz_combined_tables.p3a'))
    # Trails in the Sky keeps its tables in .pac archives (table_en.pac and
    # friends), next to the script or in pac/steam/.
    for pac_path in find_sky_pac_archives('.', '{}.tbl'.format(base_name)):
        sources.append(('p3a', pac_path))
    return sources


def source_label(stype, path, base_name):
    if stype in ('p3a', 'zzz'):
        return "{0}  (extract {1}.tbl)".format(path, base_name)
    return path


def select_source_numbered(sources, base_name):
    """Plain numbered prompt, used when the arrow-key list is not available."""
    out("\nMultiple data sources detected. Select source to use:")
    for i, (stype, path) in enumerate(sources, 1):
        out("  {0}) {1}".format(i, source_label(stype, path, base_name)))
    while True:
        try:
            choice = input("\nEnter choice [1-{}]: ".format(len(sources))).strip()
            index = int(choice)
            if 1 <= index <= len(sources):
                return sources[index - 1]
            out("Invalid choice. Please enter a number between 1 and {}.".format(
                len(sources)))
        except ValueError:
            out("Invalid input. Please enter a number.")
        except (EOFError, KeyboardInterrupt):
            out("\n\nOperation cancelled by user.")
            sys.exit(0)


def extract_from_archive(archive, table_name, out_file):
    """Pull one .tbl out of a .p3a or a Sky .pac."""
    if is_pac_file(archive):
        return extract_table_from_pac(archive, table_name, out_file, quiet=True)
    if not HAS_P3A_LIB:
        out("p3a_lib.py is missing - cannot read {}".format(archive))
        return False
    try:
        p3a = p3a_class()
        with open(archive, 'rb') as p3a.f:
            _headers, entries, p3a_dict = p3a.read_p3a_toc()
            for entry in entries:
                if os.path.basename(entry['name']) == table_name:
                    with open(out_file, 'wb') as f:
                        f.write(p3a.read_file(entry, p3a_dict))
                    return True
    except Exception as e:
        out("Error reading {0}: {1}".format(archive, e))
    return False


def load_from_json(json_file, section):
    """Read a section out of a KuroTools-style .json."""
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        out("Error loading {0}: {1}".format(json_file, e))
        return None
    if isinstance(data, dict):
        if isinstance(data.get('data'), list):          # {"data": [{"name":..}]}
            for part in data['data']:
                if part.get('name') == section:
                    return part.get('data', [])
        if isinstance(data.get(section), list):         # {"ItemTableData": [...]}
            return data[section]
    return None


def read_sections(prefix, sections, source_type, source_path):
    """Read several sections of t_<prefix> from one source in one go."""
    if source_type == 'json':
        path = source_path or '{}.json'.format(prefix)
        if not os.path.exists(path):
            return None, None
        return {name: load_from_json(path, name) for name in sections}, path

    if source_type in ('tbl', 'original'):
        path = '{0}.tbl{1}'.format(prefix, '.original' if source_type == 'original' else '')
        if not os.path.exists(path):
            return None, None
        table = kuro_tables().read_table(path)
        if not isinstance(table, dict):
            return None, None
        return {name: table.get(name) for name in sections}, path

    temp = '{}.tbl.tmp'.format(prefix)
    if not extract_from_archive(source_path, '{}.tbl'.format(prefix), temp):
        return None, None
    try:
        table = kuro_tables().read_table(temp)
        if not isinstance(table, dict):
            return None, None
        return {name: table.get(name) for name in sections}, source_path
    finally:
        if os.path.exists(temp):
            os.remove(temp)


def choose_source(base_name, forced_type, interactive, strict=True, use_tui=False):
    """Pick the source for a table, asking when there is a real choice."""
    sources = detect_sources(base_name)
    if not sources:
        return None, None
    if forced_type:
        matching = [s for s in sources if s[0] == forced_type]
        if matching:
            return matching[0]
        if strict:
            out("No {0} source found for {1}. Available: {2}".format(
                forced_type, base_name, ", ".join(sorted({s[0] for s in sources}))))
            sys.exit(2)
        return None, None
    if len(sources) == 1 or not interactive:
        return sources[0]
    if use_tui:
        options = [Option(s, source_label(s[0], s[1], base_name)) for s in sources]
        return pick("Where should {}.tbl be read from?".format(base_name), options,
                    subtitle="Several copies were found. Pick one.")
    if not sys.stdin.isatty():
        return sources[0]
    return select_source_numbered(sources, base_name)


def load_optional(prefix, section, preferred_type):
    """One section of an optional table, quietly.

    Tries a source of the same kind as the item table first, then every other
    copy found. Returns (rows, source) or (None, None); never asks and never
    fails - these tables only make the labels nicer.
    """
    sources = detect_sources(prefix)
    sources.sort(key=lambda s: s[0] != preferred_type)
    for stype, spath in sources:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                sections, used = read_sections(prefix, [section], stype, spath)
        except Exception:
            continue
        if sections and sections.get(section):
            return sections[section], used
    return None, None


# ===========================================================================
# The data model
# ===========================================================================

class GameData(object):
    """Everything the script needs, read once."""

    def __init__(self):
        self.items = []             # ItemTableData
        self.item_source = ''
        self.shop_items = []        # ShopItem
        self.shop_names = {}        # shop id -> name
        self.shop_source = ''
        self.game_id = DEFAULT_GAME
        self.already = {}           # shop id -> set of item ids on sale
        self.from_mods = 0          # entries contributed by .kurodlc.json files
        # Optional, only for nicer labels - nothing depends on them:
        self.kind_names = {}        # subcategory -> name   (t_item ItemKindParam2)
        self.help_names = {}        # category -> name      (t_itemhelp ItemKindHelpData)
        self.char_names = {}        # character id -> name  (t_name NameTableData)
        self.name_sources = []      # what the names were read from, for display

    @property
    def game_name(self):
        return get_profile(self.game_id)['name'] if HAS_PROFILES else 'unknown game'

    def _profile_category_names(self):
        return dict(get_profile(self.game_id)['category_names']) if HAS_PROFILES else {}

    def _real_category_names(self):
        """Category names the game's own tables give, where they give one."""
        real = {cat: name for cat, name in self.help_names.items() if name}
        if not self.kind_names:
            return real
        per_category = {}
        for item in self.items:
            cat, sub = item.get('category'), item.get('subcategory')
            counts = per_category.setdefault(cat, {})
            counts[sub] = counts.get(sub, 0) + 1
        for cat, counts in per_category.items():
            if cat in real:
                continue
            names = []
            for sub in sorted(counts, key=lambda s: -counts[s]):
                name = self.kind_names.get(sub)
                if name and name != 'None' and name not in names:
                    names.append(name)
            if names:
                real[cat] = ', '.join(names[:3]) + (', ...' if len(names) > 3 else '')
        return real

    def category_names(self):
        """Best available name per category.

        The game's own name is used when it tells the categories apart. Where
        several categories share one (in Sky, costumes, hair colours and costume
        accessories are all "Costumes"), the toolkit's name for the category is
        used instead, and a name that is then shown twice gets the game's name
        added, e.g. "Accessories (Costumes)" next to the equipment "Accessories".
        """
        profile = self._profile_category_names()
        real = self._real_category_names()
        uses = {}
        for name in real.values():
            uses[name] = uses.get(name, 0) + 1
        names = {}
        for cat in set(real) | set(profile):
            if cat in real and (uses[real[cat]] == 1 or cat not in profile):
                names[cat] = real[cat]
            else:
                names[cat] = profile[cat]
        shown = {}
        for name in names.values():
            shown[name] = shown.get(name, 0) + 1
        for cat, name in list(names.items()):
            if shown[name] > 1 and cat in profile and name == profile[cat] \
                    and cat in real and real[cat] != name:
                names[cat] = '{0} ({1})'.format(name, real[cat])
        return names

    def type_to_category(self):
        return dict(get_profile(self.game_id)['categories']) if HAS_PROFILES else {}


def load_game_data(source_type, source_path, forced_game, output_to_ignore,
                   interactive=False, use_tui=False):
    """Read t_item and t_shop and work out what the shops already sell."""
    data = GameData()

    sections, data.item_source = read_sections(
        't_item', ['ItemTableData', 'ItemKindParam2'], source_type, source_path)
    if not sections or not sections.get('ItemTableData'):
        return None
    data.items = sections['ItemTableData']
    for kind in sections.get('ItemKindParam2') or []:
        if isinstance(kind, dict) and kind.get('value'):
            data.kind_names[kind.get('id')] = kind['value']
    if data.kind_names:
        data.name_sources.append('item kinds: {}'.format(data.item_source))

    # Names for the labels. Optional: missing or unreadable tables are ignored.
    help_rows, help_source = load_optional('t_itemhelp', 'ItemKindHelpData', source_type)
    for row in help_rows or []:
        cat, name = row.get('category_id'), row.get('text2')
        if cat is not None and name and cat not in data.help_names:
            data.help_names[cat] = name
    if data.help_names:
        data.name_sources.append('categories: {}'.format(help_source))

    name_rows, name_source = load_optional('t_name', 'NameTableData', source_type)
    for row in name_rows or []:
        chr_id, name = row.get('character_id'), row.get('name')
        if chr_id is not None and name and chr_id not in data.char_names:
            data.char_names[chr_id] = name
    if data.char_names:
        data.name_sources.append('characters: {}'.format(name_source))

    if forced_game:
        data.game_id = forced_game
    elif HAS_PROFILES:
        for item in data.items:
            detected = detect_game_from_item_entry(item)
            if detected:
                data.game_id = detected
                break

    # t_shop from the same kind of source when it has one, else from whatever
    # t_shop does have - so both tables normally come from the same place.
    shop_type, shop_path = choose_source('t_shop', source_type, interactive=False,
                                         strict=False)
    if shop_type is None:
        shop_type, shop_path = choose_source('t_shop', None, interactive=interactive,
                                             use_tui=use_tui)
    if shop_type is not None:
        shop_sections, data.shop_source = read_sections(
            't_shop', ['ShopItem', 'ShopInfo'], shop_type, shop_path)
        if shop_sections:
            data.shop_items = shop_sections.get('ShopItem') or []
            for info in shop_sections.get('ShopInfo') or []:
                data.shop_names[info.get('id')] = info.get('shop_name') or ''

    for entry in data.shop_items:
        data.already.setdefault(entry.get('shop_id'), set()).add(entry.get('item_id'))

    # The .kurodlc.json files here will be merged into the tables as well, so
    # what they put on sale counts as sold already. The file about to be
    # written is left out, so regenerating it works.
    target = os.path.abspath(output_to_ignore) if output_to_ignore else None
    for path in sorted(glob.glob('*.kurodlc.json')):
        if target and os.path.abspath(path) == target:
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                mod = json.loads(f.read())
        except (OSError, ValueError):
            continue
        for entry in mod.get('ShopItem') or []:
            if isinstance(entry, dict) and 'shop_id' in entry and 'item_id' in entry:
                data.already.setdefault(entry['shop_id'], set()).add(entry['item_id'])
                data.from_mods += 1
    return data


def is_hidden(item):
    """Costume-viewer entries for NPCs and enemies, not meant to be obtained."""
    return 'T' in (item.get('flags') or '')


def restrict_list(item):
    value = item.get('chr_restrict')
    return value if isinstance(value, list) else [value]


def filter_items(items, category, char=None, name=None, price=0,
                 include_hidden=False):
    """Items of a category, narrowed down. Returns (chosen, hidden_left_out)."""
    chosen, hidden = [], 0
    for item in items:
        if item.get('category') != category:
            continue
        if char is not None and char not in restrict_list(item):
            continue
        if name and name.lower() not in (item.get('name') or '').lower():
            continue
        if price and item.get('price', 0) > price:
            continue
        if not include_hidden and is_hidden(item):
            hidden += 1
            continue
        chosen.append(item)
    return chosen, hidden


def build_entries(items, shops, already, keep_existing=False):
    """ShopItem entries for every item in every shop.

    Returns (entries, added_per_shop, skipped_per_shop).
    """
    entries, added, skipped = [], {}, {}
    for shop in shops:
        sold = already.get(shop, set())
        for item in items:
            if not keep_existing and item['id'] in sold:
                skipped[shop] = skipped.get(shop, 0) + 1
                continue
            entries.append({
                "shop_id": shop,
                "item_id": item['id'],
                "unknown": 1,
                "start_scena_flags": [],
                "empty1": 0,
                "end_scena_flags": [],
                "int2": 0,
            })
            added[shop] = added.get(shop, 0) + 1
    return entries, added, skipped


def normalise_output(path):
    if not path.endswith('.kurodlc.json'):
        path = os.path.splitext(path)[0] + '.kurodlc.json'
    return path


def write_output(path, entries):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(json.dumps({"ShopItem": entries}, indent=4, ensure_ascii=False))


def character_ids(item):
    return [c for c in restrict_list(item) if c not in (NO_RESTRICTION, None)]


def character_label(item, char_names=None):
    """'Estelle' when t_name was found, 'char 0' when it was not, '' for anyone."""
    names = char_names or {}
    return ', '.join(names.get(c) or 'char {}'.format(c) for c in character_ids(item))


def resolve_character(value, char_names):
    """--char takes an id or a name. Returns (id, error message)."""
    text = str(value).strip()
    if text.isdigit():
        return int(text), None
    if not char_names:
        return None, ("--char {} needs t_name (t_name.tbl, .json or an archive) to "
                      "look the name up; give the character id instead.".format(text))
    wanted = text.lower()
    exact = sorted(c for c, n in char_names.items() if n.lower() == wanted)
    if len(exact) >= 1:
        return exact[0], None
    partial = sorted(c for c, n in char_names.items() if wanted in n.lower())
    if len(partial) == 1:
        return partial[0], None
    if not partial:
        return None, "No character called '{}' in t_name.".format(text)
    listed = ', '.join('{0} {1}'.format(c, char_names[c]) for c in partial[:12])
    return None, "'{0}' matches several characters: {1}{2}. Be more specific or use the id.".format(
        text, listed, ', ...' if len(partial) > 12 else '')


# ===========================================================================
# The wizard
# ===========================================================================

def run_wizard(forced_game=None):
    """Guided, keyboard-driven mode. Esc steps back; Esc on the first step quits."""
    if not HAS_TUI_LIB:
        out("kurodlc_tui.py is missing - the wizard needs it. Use the command-line")
        out("options instead; see --help.")
        return 2
    if not HAS_TBL_LIB:
        out("kurodlc_lib.py is missing: {}".format(MISSING_LIB))
        return 2

    # ---- data source (asked once, before the wizard proper) -------------
    source_type, source_path = choose_source('t_item', None, interactive=True,
                                             use_tui=True)
    if source_type is None:
        if not detect_sources('t_item'):
            out("No item table found. Looked for:")
            out("  t_item.json, t_item.tbl.original, t_item.tbl,")
            out("  script_en.p3a / script_eng.p3a, zzz_combined_tables.p3a,")
            out("  and the game's .pac archives (here or in pac/steam).")
            return 2
        out("Cancelled.")
        return 0

    out(colour("Reading {} ...".format(source_path), DIM))
    data = load_game_data(source_type, source_path, forced_game,
                          output_to_ignore=None, interactive=True, use_tui=True)
    if data is None:
        out("Could not read ItemTableData from {}.".format(source_path))
        return 2

    state = {'category': None, 'type_name': None, 'shops': [], 'items': None,
             'output': None, 'keep_existing': False}
    step = 0

    while True:
        # ---- 1. what kind of item ------------------------------------------
        if step == 0:
            state['category'] = pick_category(data)
            if state['category'] is None:
                clear_screen()
                out("Cancelled.")
                return 0
            state['type_name'] = category_type_name(data, state['category'])
            state['items'] = None                  # a new category resets the picks
            step = 1

        # ---- 2. which shops -------------------------------------------------
        elif step == 1:
            if not data.shop_names:
                out(colour("No shop table found - cannot continue.", RED))
                return 2
            shops = pick_shops(data, state['category'], state['shops'])
            if shops is None:
                step = 0
                continue
            state['shops'] = shops
            step = 2

        # ---- 3. which items ---------------------------------------------------
        elif step == 2:
            items = pick_items(data, state['category'], state['shops'],
                               state['items'])
            if items is None:
                step = 1
                continue
            state['items'] = items
            step = 3

        # ---- 4. output file ---------------------------------------------------
        elif step == 3:
            default = state['output'] or '{}_shop.kurodlc.json'.format(state['type_name'])
            choice = pick("Where should the result go?", [
                Option('default', 'Write {}'.format(default)),
                Option('other', 'Choose another file name...'),
            ], subtitle="Esc goes back to the item list.")
            if choice is None:
                step = 2
                continue
            if choice == 'other':
                name = ask_text("File name", default)
                state['output'] = normalise_output(name or default)
            else:
                state['output'] = normalise_output(default)
            step = 4

        # ---- 5. summary and write -----------------------------------------------
        elif step == 4:
            result = confirm_and_write(data, state)
            if result is None:
                step = 3
                continue
            return result


def category_type_name(data, category):
    for name, number in data.type_to_category().items():
        if number == category:
            return name
    return 'category{}'.format(category)


def pick_category(data):
    counts = {}
    hidden = {}
    for item in data.items:
        cat = item.get('category')
        counts[cat] = counts.get(cat, 0) + 1
        if is_hidden(item):
            hidden[cat] = hidden.get(cat, 0) + 1

    names = data.category_names()
    # The categories this toolkit is built for come first, the rest after.
    known = set(data.type_to_category().values())
    options = []
    for cat in sorted(counts, key=lambda c: (c not in known, c)):
        label = names.get(cat, 'Category {}'.format(cat))
        detail = '{} item(s)'.format(counts[cat])
        if hidden.get(cat):
            detail += ', {} unobtainable'.format(hidden[cat])
        options.append(Option(cat, '{0:>3}  {1}'.format(cat, label), detail=detail))

    subtitle = '{0}  -  read from {1}'.format(data.game_name, data.item_source)
    if data.name_sources:
        subtitle += '\nNames: ' + '; '.join(data.name_sources)
    else:
        subtitle += '\nNo name tables found - generic category names are shown.'
    return pick("What do you want to put on sale?", options, subtitle=subtitle)


def pick_shops(data, category, preselected):
    wanted = {item['id'] for item in data.items if item.get('category') == category}
    options = []
    for shop_id in sorted(data.shop_names):
        name = data.shop_names[shop_id] or '(no name)'
        sold = data.already.get(shop_id, set())
        overlap = len(wanted & sold)
        detail = 'sells {} item(s)'.format(len(sold))
        if overlap:
            detail += ', {} of this kind already'.format(overlap)
        tag = 'test shop' if name.startswith('◆') else ''
        options.append(Option(shop_id, '{0:>4}  {1}'.format(shop_id, name),
                              detail=detail, tag=tag))
    return pick("Which shop(s) should sell them?", options, multi=True,
                preselected=preselected,
                subtitle="Space ticks a shop. / filters, * ticks by pattern "
                         "(e.g. *Arms*).")


def pick_items(data, category, shops, preselected):
    items = [item for item in data.items if item.get('category') == category]
    shop_sets = [data.already.get(shop, set()) for shop in shops]

    options, default_pick = [], []
    for item in items:
        sold_in = sum(1 for sold in shop_sets if item['id'] in sold)
        tags = []
        if is_hidden(item):
            tags.append('unobtainable')
        if sold_in == len(shops) and shops:
            tags.append('sold in all chosen shops')
        elif sold_in:
            tags.append('sold in {0}/{1}'.format(sold_in, len(shops)))
        who = character_label(item, data.char_names)
        detail = '{0:>6} mira'.format(item.get('price', 0))
        if who:
            detail += '  ' + who
        options.append(Option(item['id'],
                              '{0:>5}  {1}'.format(item['id'], item.get('name') or ''),
                              detail=detail, tag=' '.join('[{}]'.format(t) for t in tags),
                              searchable='{0} {1} {2}'.format(
                                  item.get('name') or '', item['id'], who)))
        # Ticked by default: everything obtainable that is not on sale yet.
        if not is_hidden(item) and sold_in < len(shops):
            default_pick.append(item['id'])

    chosen = pick("Which items? ({} in this category)".format(len(items)), options,
                  multi=True,
                  preselected=preselected if preselected is not None else default_pick,
                  subtitle="Ticked: everything obtainable that is not on sale yet. "
                           "* ticks by pattern, - unticks by pattern." +
                           ("\n/ also finds characters: /Estelle shows her items."
                            if data.char_names else ""))
    if chosen is None:
        return None
    wanted = set(chosen)
    return [item for item in items if item['id'] in wanted]


def confirm_and_write(data, state):
    """Show what will happen and write it. None means 'go back'."""
    entries, added, skipped = build_entries(state['items'], state['shops'],
                                            data.already, state['keep_existing'])
    lines = []
    for shop in state['shops']:
        name = data.shop_names.get(shop, '')
        line = '  shop {0:>4}  {1:<34} +{2}'.format(shop, name[:34], added.get(shop, 0))
        if skipped.get(shop):
            line += '  ({} already on sale, skipped)'.format(skipped[shop])
        lines.append(line)

    options = [Option('write', 'Write {0}  ({1} entries)'.format(
        state['output'], len(entries)))]
    if not entries:
        options = [Option('back', 'Nothing to add - go back')]
    options.append(Option('back', 'Go back and change something'))
    options.append(Option('quit', 'Quit without writing'))

    choice = pick("Ready", options,
                  subtitle="{0} item(s) in {1} shop(s):\n{2}".format(
                      len(state['items']), len(state['shops']), '\n'.join(lines)))
    if choice in (None, 'back'):
        return None
    if choice == 'quit':
        clear_screen()
        out("Nothing written.")
        return 0

    if os.path.exists(state['output']):
        if not confirm("{} exists. Overwrite it?".format(state['output']), default=False):
            return None
    write_output(state['output'], entries)
    clear_screen()
    out(colour("Written: {0}  ({1} entries)".format(state['output'], len(entries)),
               GREEN, BOLD))
    for line in lines:
        out(line)
    out("")
    out("Next: run kurodlc_make_tbls.py to build the tables.")
    return 0


# ===========================================================================
# Command line
# ===========================================================================

HELP_DESCRIPTION = """\
Put a whole category of items on sale in one or more shops.

Reads the game's item table, picks the items you ask for and writes a
.kurodlc.json containing only a ShopItem section. Build the tables with
kurodlc_make_tbls.py afterwards and the items can be bought in the game.

Run with NO arguments to get a guided wizard driven by the keyboard. Pass any
option to use the command line instead, which suits batch files."""

HELP_EPILOG = """\
INTERACTIVE MODE
  Start the script without arguments (or with -i). It reads the tables, then
  walks you through four screens: what kind of item, which shop(s), which
  items, and where to write the result. Every screen is a list:

    Up / Down          move                PgUp / PgDn  page
    Home / End         first / last row    Enter        confirm
    Space              tick / untick       Esc, Bksp    go back one screen
    /                  filter the list as you type (Enter keeps it, Esc clears)
    *                  tick every row matching a pattern
    -                  untick every row matching a pattern
    a / n / i          tick all / none / invert  (acts on the rows shown)

  Plain text filters by substring over the whole row. Text with * or ? is a
  wildcard pattern, matched against the name and anchored at both ends:
    Estelle*           names starting with "Estelle"
    *Swimsuit*         names containing "Swimsuit"
    Item 1?            "Item 10" to "Item 19"

  The item screen starts with every obtainable item that is not on sale yet
  already ticked, so Enter alone is usually right.

NAMES
  Only t_item and t_shop are needed. When more tables are found - in the
  same places as t_item - the lists show real names instead of bare numbers:
    t_item  ItemKindParam2     in-game item kinds  (Costumes, Orbment Covers...)
    t_itemhelp                 category names, where the game has the table
    t_name  NameTableData      character names: "Estelle" instead of "char 0"
  Where the game gives several categories the same name (in Trails in the Sky,
  costumes, hair colours and costume accessories are all "Costumes"), the
  toolkit's own name is used. With t_name present, --char also takes a name
  and the item filter finds items by character.

DATA SOURCES
  Found automatically, in this order:
    t_item.json, t_item.tbl.original, t_item.tbl,
    script_en.p3a / script_eng.p3a, zzz_combined_tables.p3a,
    and the game's .pac archives (Trails in the Sky), here or in pac/steam.
  When several are present you are asked which to use; t_shop is then read
  from the same kind of source. --source forces one, --no-interactive takes
  the first. A Trails in the Sky .pac counts as --source p3a.

WHAT IS SKIPPED
  - Items the chosen shop already sells.
  - Items the other .kurodlc.json files in this folder already put on sale
    there, so running the script twice never lists anything twice.
  - Items marked unobtainable (the costume-viewer models for NPCs and
    enemies), unless --include-hidden is given.

ITEM TYPES
  --type accepts: costume, hair, accessory, orbment. The category numbers
  behind them differ per game (a costume is 15 in Trails in the Sky and 17 in
  Kuro), so they are resolved from the tables that are present. --category
  takes a raw number instead.

EXAMPLES
  Guided wizard:
    python shops_add_category.py

  Every costume on sale in Rinon's General Goods (shop 22):
    python shops_add_category.py --type costume --shop 22

  Look first, write nothing:
    python shops_add_category.py --type costume --list

  Estelle's costumes only, in two shops, to a file of your choosing
  (--char Estelle works as well when t_name is present):
    python shops_add_category.py --type costume --char 0 --shop 22 --shop 28 -o EstelleCostumes.kurodlc.json

  Only names containing "Cheerful", costing at most 5000:
    python shops_add_category.py --type costume --name Cheerful --price 5000 --shop 22

  Every accessory, read from the game's archive, no questions asked:
    python shops_add_category.py --type accessory --shop 74 --source p3a --no-interactive

  Each example is one line, so it pastes as-is into cmd, PowerShell or bash.

  Then build the tables:
    python kurodlc_make_tbls.py

EXIT CODES
  0  done (or nothing to do)     1  nothing matched     2  error / bad input

Requires kurodlc_lib.py and kurodlc_schema.json; kurodlc_tui.py for the
wizard; p3a_lib.py for .p3a archives and sky_pac_lib.py for .pac ones.
Colours use colorama when installed (python -m pip install colorama); set
NO_COLOR to turn them off."""


def build_parser():
    parser = argparse.ArgumentParser(
        prog='shops_add_category.py',
        description=HELP_DESCRIPTION,
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)

    what = parser.add_argument_group('what to sell')
    what.add_argument('--type', metavar='NAME',
                      help="costume, hair, accessory or orbment")
    what.add_argument('--category', type=int, metavar='N',
                      help="raw category number, instead of --type")
    what.add_argument('--char', metavar='N|NAME',
                      help="only items for one character: an id, or a name "
                           "when t_name is present (e.g. Estelle)")
    what.add_argument('--name', metavar='TEXT',
                      help="only items whose name contains TEXT (case-insensitive)")
    what.add_argument('--price', type=int, default=0, metavar='N',
                      help="only items costing at most N (0 = no limit)")
    what.add_argument('--include-hidden', action='store_true',
                      help="also the entries marked unobtainable")

    where = parser.add_argument_group('where to sell it')
    where.add_argument('--shop', action='append', type=int, default=[], metavar='N',
                       help="shop id to sell in; repeat for several")
    where.add_argument('--keep-existing', action='store_true',
                       help="do not skip what the shop already sells "
                            "(creates duplicates)")

    output = parser.add_argument_group('output')
    output.add_argument('-o', '--output', metavar='FILE',
                        help="output file (default: <type>_shop.kurodlc.json)")
    output.add_argument('--list', action='store_true',
                        help="print what would be added, write nothing")

    source = parser.add_argument_group('data source')
    source.add_argument('--source', metavar='TYPE',
                        choices=['json', 'original', 'tbl', 'p3a', 'zzz'],
                        help="force a source: json, original, tbl, p3a, zzz")
    source.add_argument('--no-interactive', action='store_true',
                        help="never ask; take the first source found")
    source.add_argument('--game', metavar='NAME',
                        help="kuro, sky1st, sky2nd or ysx, if detection is wrong")

    mode = parser.add_argument_group('mode')
    mode.add_argument('-i', '--interactive', action='store_true',
                      help="start the guided wizard")
    mode.add_argument('--version', action='version',
                      version='%(prog)s {}'.format(VERSION))
    return parser


def run_cli(args):
    if not HAS_TBL_LIB:
        out("kurodlc_lib.py is missing: {}".format(MISSING_LIB))
        return 2
    if args.type is None and args.category is None:
        out("Say what to put on sale: --type costume, or --category 15.")
        out("Run without arguments for the guided wizard, or see --help.")
        return 2
    if not args.shop and not args.list:
        out("Say where to sell it: --shop 22. Use --list to only look.")
        return 2

    forced_game = None
    if args.game:
        forced_game = resolve_game_id(args.game) if HAS_PROFILES else None
        if forced_game is None:
            out("Unknown game '{0}'. Known: {1}".format(args.game, ", ".join(GAME_IDS)))
            return 2

    interactive = not args.no_interactive
    source_type, source_path = choose_source('t_item', args.source, interactive)
    if source_type is None:
        out("No t_item source found. Looked for:")
        out("  t_item.json, t_item.tbl.original, t_item.tbl,")
        out("  script_en.p3a / script_eng.p3a, zzz_combined_tables.p3a,")
        out("  and the game's .pac archives (here or in pac/steam).")
        return 2

    data = load_game_data(source_type, source_path, forced_game, args.output,
                          interactive=interactive)
    if data is None:
        out("Could not read ItemTableData from {}.".format(source_path))
        return 2

    if args.category is not None:
        category = args.category
        type_name = 'category{}'.format(category)
    else:
        type_name = args.type.strip().lower()
        categories = data.type_to_category()
        if type_name not in categories:
            out("Unknown type '{0}'. Known for {1}: {2}".format(
                args.type, data.game_name, ", ".join(categories) or '(none)'))
            return 2
        category = categories[type_name]

    out("Items:  {0} ({1})".format(data.item_source, data.game_name))
    out("Kind:   {0}, category {1}".format(type_name, category))
    if data.shop_source:
        out("Shops:  {}".format(data.shop_source))
    if data.from_mods:
        out("Mods:   {} shop entry(s) in the .kurodlc.json files here".format(
            data.from_mods))
    for shop in args.shop:
        if data.shop_names and shop not in data.shop_names:
            out("[!] shop {} does not exist in this game".format(shop))

    char = None
    if args.char is not None:
        char, problem = resolve_character(args.char, data.char_names)
        if problem:
            out(problem)
            return 2
        out("Char:   {0}{1}".format(char, "  ({})".format(data.char_names[char])
                                    if char in data.char_names else ""))

    chosen, hidden = filter_items(data.items, category, char, args.name,
                                  args.price, args.include_hidden)
    if not chosen:
        out("\nNothing matched.")
        return 1

    out("")
    out("Matched {0} item(s){1}".format(
        len(chosen), ", {} unobtainable one(s) left out".format(hidden) if hidden else ""))

    if args.list or not args.shop:
        out("")
        for item in chosen:
            who = character_label(item, data.char_names)
            out("  {0:>5}  {1:<44} {2:>7}{3}".format(
                item['id'], (item.get('name') or '')[:44], item.get('price', 0),
                '  [{}]'.format(who) if who else ''))
        if not args.shop:
            out("\nAdd --shop N to put these on sale.")
            return 0

    entries, added, skipped = build_entries(chosen, args.shop, data.already,
                                            args.keep_existing)
    for shop in args.shop:
        out("  shop {0:>4} {1:<34} +{2} item(s){3}".format(
            shop, data.shop_names.get(shop, '')[:34], added.get(shop, 0),
            ", {} already sold".format(skipped[shop]) if shop in skipped else ""))

    if not entries:
        out("\nEverything is on sale already - nothing to write.")
        return 0
    if args.list:
        out("\n[LIST] Nothing written. Drop --list to write the file.")
        return 0

    output = normalise_output(args.output or '{}_shop.kurodlc.json'.format(type_name))
    if os.path.exists(output) and interactive and sys.stdin.isatty():
        answer = input("{} exists. Overwrite? [y/N]: ".format(output)).strip().lower()
        if answer not in ('y', 'yes'):
            out("Nothing written.")
            return 0
    write_output(output, entries)
    out("")
    out("Written: {0}  ({1} entries)".format(output, len(entries)))
    out("Now run kurodlc_make_tbls.py to build the tables.")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(argv)

    wizard = args.interactive or not argv
    if wizard:
        if not has_tui():
            if not argv:
                # Piped or redirected: the wizard cannot run, so show how to use
                # the command line instead of hanging on a prompt.
                parser.print_help()
                return 2
            out("The wizard needs an interactive console. Use the options instead;")
            out("see --help.")
            return 2
        forced_game = resolve_game_id(args.game) if (args.game and HAS_PROFILES) else None
        return run_wizard(forced_game)
    return run_cli(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        out("\nCancelled.")
        sys.exit(130)
    except BrokenPipeError:            # output piped into head / more
        try:
            sys.stdout = open(os.devnull, 'w')
        except OSError:
            pass
        sys.exit(0)
