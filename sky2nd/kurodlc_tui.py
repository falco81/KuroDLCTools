#!/usr/bin/env python3
"""
kurodlc_tui.py - a small keyboard-driven text UI for the KuroDLC toolkit.

Gives the scripts a scrolling list that is driven with the arrow keys: move
with Up/Down, page with PgUp/PgDn, tick items with Space, confirm with Enter,
step back with Esc or Backspace.  On top of that it offers live filtering,
wildcard selection and the usual select-all / none / invert.

It has no third-party dependencies.  Colours go through colorama when it is
installed, which is what makes them work in the old Windows console; without it
the output is plain text.  Raw keys come from msvcrt on Windows and from
termios on everything else, so no curses is needed.

Using it
--------
    from kurodlc_tui import pick, confirm, ask_text, has_tui

    chosen = pick("Pick shops", options, multi=True)     # -> list of values
    if confirm("Write the file?", default=True):
        ...

`options` is a list of Option objects, or of (value, label) pairs, or of plain
strings.  `pick` returns the chosen value (or a list of them when multi=True),
or None when the user backed out with Esc.

Part of the KuroDLCTools toolkit.
"""

import fnmatch
import os
import shutil
import sys

__all__ = ['Option', 'pick', 'confirm', 'ask_text', 'message', 'has_tui',
           'clear_screen', 'colour',
           'BOLD', 'DIM', 'CYAN', 'GREEN', 'YELLOW', 'RED', 'MAGENTA']

# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------

def _enable_windows_ansi():
    """Switch the Windows 10+ console to native ANSI (virtual terminal) mode."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if mode.value & 0x0004:
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


# On Windows 10+ the console is put into native ANSI mode first. colorama is
# only asked to help when that fails (older consoles): its init() replaces
# stdout with a converter that turns every escape sequence into a separate
# console call, which is slow and makes a redrawn list flicker.
_NATIVE_ANSI = os.name != 'nt' or _enable_windows_ansi()
HAS_COLORAMA = False
try:
    import colorama
    HAS_COLORAMA = True
    if os.name == 'nt' and not _NATIVE_ANSI:
        if hasattr(colorama, 'just_fix_windows_console'):
            colorama.just_fix_windows_console()
            _NATIVE_ANSI = _enable_windows_ansi()
        if not _NATIVE_ANSI:
            colorama.init()
except Exception:
    pass

_NO_COLOUR = (os.environ.get('NO_COLOR') is not None
              or os.environ.get('KURODLC_NO_COLOR') is not None)

BOLD, DIM = '\033[1m', '\033[2m'
CYAN, GREEN, YELLOW = '\033[36m', '\033[32m', '\033[33m'
RED, MAGENTA, RESET = '\033[31m', '\033[35m', '\033[0m'
REVERSE = '\033[7m'


def _ansi_ok():
    """Can the console take cursor movement? (Colour is decided separately.)"""
    if not sys.stdout.isatty():
        return False
    return _NATIVE_ANSI or HAS_COLORAMA


_ANSI = _ansi_ok()
# NO_COLOR turns colour off but keeps the cursor control, so the lists still
# redraw in place.
_USE_COLOUR = _ANSI and not _NO_COLOUR


def colour(text, *codes):
    """Wrap text in ANSI codes, or return it untouched when colour is off."""
    if not _USE_COLOUR or not codes:
        return text
    return ''.join(codes) + text + RESET


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _write(text):
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or 'ascii'
        sys.stdout.write(text.encode(enc, 'replace').decode(enc, 'replace'))
    sys.stdout.flush()


def _safe(text):
    """Text the current console can actually print."""
    enc = sys.stdout.encoding or 'utf-8'
    try:
        text.encode(enc)
        return text
    except (UnicodeEncodeError, LookupError):
        return text.encode(enc, 'replace').decode(enc, 'replace')


def _clear():
    _write('\033[H\033[2J' if _ANSI else '\n' * 3)


def clear_screen():
    """Wipe the console, e.g. before printing a final result."""
    _clear()


def _hide_cursor():
    if _ANSI and _NATIVE_ANSI:        # colorama's converter cannot do this one
        _write('\033[?25l')


def _show_cursor():
    if _ANSI and _NATIVE_ANSI:
        _write('\033[?25h')


class _Screen(object):
    """Draws whole frames without flicker.

    The screen is never blanked between frames. Each frame is compared with
    the previous one and only the lines that changed are rewritten - moving
    the cursor one row touches two list lines and the counter - and the whole
    update goes out in a single write. Terminals that support synchronised
    output (Windows Terminal, most modern Linux ones) are also asked to show
    the update at once; the rest ignore that request.
    """

    def __init__(self):
        self.previous = None
        self.size = None

    def invalidate(self):
        """Forget what is on screen; the next frame is drawn in full."""
        self.previous = None

    def draw(self, lines):
        if not _ANSI:
            _write('\n' * 2 + '\n'.join(lines) + '\n')
            return
        size = shutil.get_terminal_size((80, 24))
        if size != self.size:
            self.size, self.previous = size, None
        sync = _NATIVE_ANSI            # colorama's converter would print it
        parts = ['\033[?2026h'] if sync else []
        if self.previous is None:
            parts.append('\033[H\033[2J')
            old = []
        else:
            old = self.previous
        for row, line in enumerate(lines):
            if row < len(old) and old[row] == line:
                continue
            parts.append('\033[{0};1H{1}\033[0m\033[K'.format(row + 1, line))
        if len(old) > len(lines):
            parts.append('\033[{0};1H\033[J'.format(len(lines) + 1))
        if sync:
            parts.append('\033[?2026l')
        _write(''.join(parts))
        self.previous = list(lines)

    def park(self):
        """Put the cursor on the line under the frame, for whatever follows."""
        if _ANSI and self.previous is not None:
            _write('\033[{};1H'.format(len(self.previous) + 1))


def message(lines):
    """Print a block of lines, encoding-safe."""
    for line in (lines if isinstance(lines, (list, tuple)) else [lines]):
        _write(_safe(str(line)) + '\n')


# ---------------------------------------------------------------------------
# Keyboard
# ---------------------------------------------------------------------------

UP, DOWN, LEFT, RIGHT = 'UP', 'DOWN', 'LEFT', 'RIGHT'
PGUP, PGDN, HOME, END = 'PGUP', 'PGDN', 'HOME', 'END'
ENTER, ESC, BACKSPACE, SPACE, TAB = 'ENTER', 'ESC', 'BACKSPACE', 'SPACE', 'TAB'


def has_tui():
    """True when the console can run the interactive list."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    if os.name == 'nt':
        try:
            import msvcrt          # noqa: F401
            return True
        except ImportError:
            return False
    try:
        import termios             # noqa: F401
        import tty                 # noqa: F401
        return True
    except ImportError:
        return False


_WINDOWS_EXTENDED = {'H': UP, 'P': DOWN, 'K': LEFT, 'M': RIGHT,
                     'G': HOME, 'O': END, 'I': PGUP, 'Q': PGDN, 'S': 'DELETE'}
_CSI = {'A': UP, 'B': DOWN, 'C': RIGHT, 'D': LEFT, 'H': HOME, 'F': END,
        '5~': PGUP, '6~': PGDN, '1~': HOME, '4~': END, '3~': 'DELETE'}


class KeyReader(object):
    """Raw keyboard input for as long as the widget needs it.

    The terminal is switched to raw mode once, when the widget starts, and put
    back when it ends.  Doing it per keypress leaves the console echoing
    between reads, which corrupts both the display and the input.  Reads go
    through os.read rather than sys.stdin, because the buffered text wrapper
    does not play well with raw mode.
    """

    def __init__(self):
        self._fd = None
        self._saved = None

    # -- terminal mode --------------------------------------------------
    def __enter__(self):
        self._enter_raw()
        return self

    def __exit__(self, *exc):
        self._leave_raw()
        return False

    def _enter_raw(self):
        if os.name == 'nt':
            return
        import termios
        import tty
        self._fd = sys.stdin.fileno()
        self._saved = termios.tcgetattr(self._fd)
        tty.setraw(self._fd)

    def _leave_raw(self):
        if os.name == 'nt' or self._saved is None:
            return
        import termios
        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
        self._saved = None

    def suspend(self):
        """Hand the terminal back so input() can be used normally."""
        self._leave_raw()

    def resume(self):
        """Take the terminal again after suspend()."""
        if self._saved is None:
            self._enter_raw()

    # -- reading ---------------------------------------------------------
    def key(self):
        """Block for one keypress and return its name or character."""
        if os.name == 'nt':
            return self._key_windows()
        return self._key_posix()

    @staticmethod
    def _key_windows():
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ('\x00', '\xe0'):                   # an extended key follows
            return _WINDOWS_EXTENDED.get(msvcrt.getwch(), '')
        if ch == '\r':
            return ENTER
        if ch == '\x1b':
            return ESC
        if ch == '\x08':
            return BACKSPACE
        if ch == '\t':
            return TAB
        if ch == ' ':
            return SPACE
        if ch == '\x03':
            raise KeyboardInterrupt
        return ch

    def _key_posix(self):
        import select

        fd = self._fd if self._fd is not None else sys.stdin.fileno()

        def read_byte(timeout=None):
            if timeout is not None and not select.select([fd], [], [], timeout)[0]:
                return ''
            data = os.read(fd, 1)
            return data.decode('utf-8', 'replace') if data else ''

        ch = read_byte()
        if ch == '':
            return ESC
        if ch == '\x1b':
            # A bare Esc or the start of a CSI sequence; a short wait tells
            # them apart without swallowing a real Esc.
            nxt = read_byte(0.05)
            if nxt not in ('[', 'O'):
                return ESC
            seq = ''
            while True:
                part = read_byte(0.05)
                if not part:
                    break
                seq += part
                if part.isalpha() or part == '~':
                    break
            return _CSI.get(seq, '')
        if ch in ('\r', '\n'):
            return ENTER
        if ch in ('\x7f', '\x08'):
            return BACKSPACE
        if ch == '\t':
            return TAB
        if ch == ' ':
            return SPACE
        if ch == '\x03':
            raise KeyboardInterrupt
        # UTF-8 continuation bytes, so accented characters survive the filter.
        if ord(ch[0]) >= 0x80 if ch else False:
            extra = 0
            first = ord(ch[0])
            if first >= 0xF0:
                extra = 3
            elif first >= 0xE0:
                extra = 2
            elif first >= 0xC0:
                extra = 1
            raw = ch.encode('utf-8', 'surrogateescape')[:1]
            for _ in range(extra):
                more = os.read(fd, 1)
                if not more:
                    break
                raw += more
            return raw.decode('utf-8', 'replace')
        return ch


def getkey():
    """One keypress, entering and leaving raw mode around it.

    Convenient for a single prompt; widgets should hold a KeyReader open
    instead, so the console is not switched back and forth between keys.
    """
    with KeyReader() as reader:
        return reader.key()


# ---------------------------------------------------------------------------
# The list widget
# ---------------------------------------------------------------------------

class Option(object):
    """One row: the value handed back, what is shown, and optional extras."""

    def __init__(self, value, label, detail='', tag='', searchable=None):
        self.value = value
        self.label = label
        self.detail = detail          # dimmed, right of the label
        self.tag = tag                # short marker, e.g. "already sold"
        self.searchable = searchable if searchable is not None else \
            '{0} {1} {2}'.format(label, detail, tag)


def _as_options(items):
    result = []
    for item in items:
        if isinstance(item, Option):
            result.append(item)
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            result.append(Option(item[0], str(item[1]),
                                 str(item[2]) if len(item) > 2 else ''))
        else:
            result.append(Option(item, str(item)))
    return result


def _matches(option, needle):
    """Does this row match what was typed?

    Plain text is a substring search over the whole row - label, detail and
    tag.  Text containing * or ? is a wildcard pattern matched against the
    label alone, shell style and anchored at both ends, so `Estelle*` means
    "starts with Estelle" and `*Swimsuit*` means "contains Swimsuit".
    """
    if not needle:
        return True
    needle = needle.lower()
    if '*' in needle or '?' in needle:
        return fnmatch.fnmatch(option.label.lower(), needle)
    return needle in option.searchable.lower()


def pick(title, items, multi=False, preselected=None, subtitle='',
         empty_ok=False, page_hint=True):
    """Show a list and let the user choose.

    Returns the chosen value, or a list of values when multi=True, or None if
    the user pressed Esc.  With multi=True an empty selection is refused unless
    empty_ok is set.
    """
    options = _as_options(items)
    if not options:
        return [] if multi else None

    selected = set()
    if preselected:
        wanted = set(preselected)
        for index, option in enumerate(options):
            if option.value in wanted:
                selected.add(index)

    needle = ''
    typing = False            # True while the filter box has focus
    cursor = 0
    top = 0
    status = ''

    def visible_indexes():
        return [i for i, option in enumerate(options) if _matches(option, needle)]

    _hide_cursor()
    screen = _Screen()
    reader = KeyReader()
    reader.__enter__()
    try:
        while True:
            shown = visible_indexes()
            if not shown:
                cursor, top = 0, 0
            else:
                cursor = max(0, min(cursor, len(shown) - 1))

            size = shutil.get_terminal_size((80, 24))
            width = max(40, min(size.columns, 200)) - 1
            subtitle_lines = subtitle.splitlines() if subtitle else []
            # Title, blank, counter, filter, keys, status, and the subtitle.
            chrome = 7 + len(subtitle_lines) + (1 if multi else 0)
            body_height = max(3, size.lines - chrome)
            if cursor < top:
                top = cursor
            if cursor >= top + body_height:
                top = cursor - body_height + 1
            top = max(0, min(top, max(0, len(shown) - body_height)))

            lines = []
            lines.append(colour(_safe(title)[:width], BOLD, CYAN))
            for sub in subtitle_lines:
                lines.append(colour(_safe(sub)[:width], DIM))
            lines.append('')

            for position in range(top, min(top + body_height, len(shown))):
                index = shown[position]
                option = options[index]
                mark = ''
                if multi:
                    mark = '[x] ' if index in selected else '[ ] '
                text = '{0}{1}'.format(mark, _safe(option.label))
                if option.detail:
                    text += '  ' + _safe(option.detail)
                if option.tag:
                    text += '  ' + _safe(option.tag)
                text = text[:width - 2]
                if position == cursor:
                    lines.append(colour('>' + text.ljust(width - 2), REVERSE))
                else:
                    if multi and index in selected:
                        lines.append(' ' + colour(text, GREEN))
                    else:
                        lines.append(' ' + text)

            for _ in range(body_height - (min(top + body_height, len(shown)) - top)):
                lines.append('')

            lines.append('')
            counter = '{0}/{1}'.format(cursor + 1 if shown else 0, len(shown))
            if len(shown) != len(options):
                counter += ' of {}'.format(len(options))
            if multi:
                counter += '   ticked: {}'.format(len(selected))
            lines.append(colour(counter[:width], DIM))

            box = needle if (needle or typing) else ''
            filter_line = 'Filter: ' + box + ('_' if typing else '')
            lines.append(colour(_safe(filter_line)[-width:], YELLOW if typing else DIM))

            if page_hint:
                if typing:
                    keys = 'type to filter   Enter accept   Esc clear'
                elif multi:
                    keys = ('Space tick   Enter confirm   / filter   '
                            '* pattern   a all   n none   i invert   Esc back')
                else:
                    keys = 'Enter choose   / filter   Esc back'
                lines.append(colour(keys[:width], DIM))

            if status:
                lines.append(colour(_safe(status)[:width], MAGENTA))

            screen.draw(lines)
            status = ''

            key = reader.key()

            # ---- filter box has focus ------------------------------------
            if typing:
                if key == ENTER:
                    typing = False
                elif key == ESC:
                    needle, typing = '', False
                elif key == BACKSPACE:
                    needle = needle[:-1]
                elif isinstance(key, str) and len(key) == 1 and key.isprintable():
                    needle += key
                elif key == SPACE:
                    needle += ' '
                cursor = 0
                continue

            # ---- navigation ----------------------------------------------
            if key == UP:
                cursor -= 1
                if cursor < 0:
                    cursor = len(shown) - 1 if shown else 0
            elif key == DOWN:
                cursor += 1
                if cursor >= len(shown):
                    cursor = 0
            elif key == PGUP:
                cursor = max(0, cursor - body_height)
            elif key == PGDN:
                cursor = min(len(shown) - 1, cursor + body_height) if shown else 0
            elif key == HOME:
                cursor = 0
            elif key == END:
                cursor = len(shown) - 1 if shown else 0
            elif key == '/':
                typing = True
            elif key in (ESC, BACKSPACE):
                if needle:
                    needle, cursor = '', 0        # first Esc clears the filter
                else:
                    return None
            elif key == ENTER:
                if multi:
                    if not selected and not empty_ok:
                        status = 'Nothing ticked. Space ticks a row, a ticks all.'
                        continue
                    return [options[i].value for i in sorted(selected)]
                if shown:
                    return options[shown[cursor]].value

            # ---- multi-select actions ------------------------------------
            elif multi and key == SPACE:
                if shown:
                    index = shown[cursor]
                    selected.discard(index) if index in selected else selected.add(index)
                    cursor = min(cursor + 1, len(shown) - 1)
            elif multi and key in ('a', 'A'):
                selected.update(shown)
                status = 'Ticked {} shown row(s).'.format(len(shown))
            elif multi and key in ('n', 'N'):
                for index in shown:
                    selected.discard(index)
                status = 'Unticked the shown rows.'
            elif multi and key in ('i', 'I'):
                for index in shown:
                    selected.discard(index) if index in selected else selected.add(index)
                status = 'Inverted the shown rows.'
            elif multi and key == '*':
                screen.park()
                pattern = _prompt_inline(reader,
                                         'Pattern (e.g. Estelle*, *Swimsuit*): ')
                screen.invalidate()
                if pattern:
                    hits = [i for i, option in enumerate(options)
                            if _matches(option, pattern)]
                    selected.update(hits)
                    status = 'Pattern matched {} row(s).'.format(len(hits))
            elif multi and key in ('-', '_'):
                screen.park()
                pattern = _prompt_inline(reader, 'Pattern to untick: ')
                screen.invalidate()
                if pattern:
                    hits = [i for i, option in enumerate(options)
                            if _matches(option, pattern)]
                    for index in hits:
                        selected.discard(index)
                    status = 'Unticked {} row(s).'.format(len(hits))
    finally:
        screen.park()
        reader.__exit__(None, None, None)
        _show_cursor()


def _prompt_inline(reader, prompt):
    """Ask for a line of text in the middle of a widget.

    The terminal goes back to its normal mode for the duration, so the user
    gets echo and line editing, then raw mode is taken again.
    """
    reader.suspend()
    _show_cursor()
    try:
        _write('\n' + colour(prompt, YELLOW))
        return _read_line()
    finally:
        _hide_cursor()
        reader.resume()


def _read_line():
    """Read a line with the terminal back in its normal mode."""
    try:
        return input().strip()
    except (EOFError, KeyboardInterrupt):
        return ''


# ---------------------------------------------------------------------------
# Small prompts
# ---------------------------------------------------------------------------

def confirm(question, default=True):
    """Yes/no. Esc counts as no. Returns the answer."""
    if not has_tui():
        suffix = ' [Y/n]: ' if default else ' [y/N]: '
        answer = input(question + suffix).strip().lower()
        if not answer:
            return default
        return answer in ('y', 'yes')

    choice = pick(question, [
        Option(True, 'Yes'),
        Option(False, 'No'),
    ], subtitle='Enter to choose, Esc to go back', page_hint=False)
    return default if choice is None else choice


def ask_text(prompt, default=''):
    """One line of text. Empty input keeps the default."""
    shown = '{0} [{1}]: '.format(prompt, default) if default else '{}: '.format(prompt)
    _write(colour(_safe(shown), YELLOW))
    answer = _read_line()
    return answer or default


if __name__ == '__main__':
    # A quick self-test: python kurodlc_tui.py
    if not has_tui():
        message("This console cannot run the interactive list.")
        sys.exit(1)
    demo = [Option(i, 'Item {}'.format(i), detail='id {}'.format(1000 + i))
            for i in range(1, 60)]
    chosen = pick('Demo - tick a few', demo, multi=True,
                  subtitle='Arrows move, Space ticks, Enter confirms, Esc backs out')
    _clear()
    message('Chosen: {}'.format(chosen))
