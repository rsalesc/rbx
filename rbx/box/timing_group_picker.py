from typing import Callable, Dict, List, Optional

from prompt_toolkit.formatted_text import AnyFormattedText
from pydantic import BaseModel

from rbx.box import timing_groups
from rbx.box.environment import LanguageGroupFallback


class GroupAssignment(BaseModel):
    numbers: Dict[str, int]
    relatives: Dict[str, LanguageGroupFallback] = {}


LEGEND_LINES = [
    'Assign each language to a time-limit bucket:',
    '',
    '  [N] grouped    shares one estimated limit with same-numbered langs',
    '  [X] singleton  its own estimated limit',
    '  [ ] leftover   pooled with all other unmarked langs (default)',
    '',
    '↑/↓ or k/j move · 1-9 group · space/tab [X]/[ ] · 0 leftover'
    ' · r derive limit from a group · R reset to env · enter confirm · q cancel',
]

# Number of extra lines the inline relative editor draws under the cursor row.
EDITOR_HEIGHT = 3


class GroupPickerState:
    def __init__(
        self,
        languages: List[str],
        default_number: Dict[str, int],
        relatives: Optional[Dict[str, LanguageGroupFallback]] = None,
    ):
        self.languages: List[str] = list(languages)
        self.numbers: Dict[str, int] = {
            lang: int(default_number.get(lang, 0)) for lang in self.languages
        }
        self.cursor: int = 0
        # Set once the user confirms; suppresses the live preview on the final
        # paint so only the official table (printed afterwards) remains.
        self.done: bool = False
        # Forced relative specs keyed by group-key (see timing_groups.group_key).
        self.relatives: Dict[str, LanguageGroupFallback] = dict(relatives or {})
        self._initial_numbers = dict(self.numbers)
        self._initial_relatives = dict(self.relatives)
        # Edit-mode scratch state for the relative-spec editor.
        self.editing = False
        self._edit_ref: Optional[str] = None
        self._edit_a: str = ''
        self._edit_b: str = ''
        self._edit_field: str = 'ref'
        self._edit_error: str = ''

    def group_key(self, lang: str) -> str:
        return timing_groups.group_key(self.numbers[lang], lang)

    def current_lang(self) -> Optional[str]:
        return self.languages[self.cursor] if self.languages else None

    def reference_options(self) -> List[Optional[str]]:
        """None (base estimate) + one representative language per OTHER group,
        in language order."""
        own = self.group_key(self.current_lang())
        opts: List[Optional[str]] = [None]
        seen: set = set()
        for lang in self.languages:
            key = self.group_key(lang)
            if key == own or key in seen:
                continue
            seen.add(key)
            opts.append(lang)
        return opts

    def start_edit(self) -> None:
        if not self.languages:
            return
        existing = self.relatives.get(self.group_key(self.current_lang()))
        self.editing = True
        self._edit_field = 'ref'
        self._edit_error = ''
        self._edit_ref = existing.relativeTo if existing else None
        self._edit_a = str(existing.multiplier) if existing else '1.0'
        self._edit_b = (
            str(existing.increment)
            if existing and existing.increment is not None
            else ''
        )

    @property
    def edit_ref(self) -> Optional[str]:
        """The reference language currently selected in the inline editor."""
        return self._edit_ref

    def set_ref(self, ref: Optional[str]) -> None:
        self._edit_ref = ref

    def cycle_ref(self, delta: int) -> None:
        opts = self.reference_options()
        try:
            i = opts.index(self._edit_ref)
        except ValueError:
            i = 0
        self._edit_ref = opts[(i + delta) % len(opts)]

    def set_a(self, text: str) -> None:
        self._edit_a = text

    def set_b(self, text: str) -> None:
        self._edit_b = text

    @property
    def edit_a(self) -> str:
        return self._edit_a

    @property
    def edit_b(self) -> str:
        return self._edit_b

    def edit_tab(self) -> None:
        order = ['ref', 'a', 'b']
        self._edit_field = order[(order.index(self._edit_field) + 1) % len(order)]

    @property
    def edit_field(self) -> str:
        return self._edit_field

    @property
    def edit_error(self) -> str:
        return self._edit_error

    def _accepts_char(self, buf: str, data: str) -> bool:
        """Whether ``data`` is a valid next character for the focused field.
        Multiplier accepts digits and a single decimal point; increment accepts
        digits only."""
        if self._edit_field == 'a':
            return data.isdigit() or (data == '.' and '.' not in buf)
        return data.isdigit()  # 'b'

    def edit_key(self, data: str) -> None:
        """Route a raw key press to the focused editor field, ignoring any
        character that would make the multiplier/increment non-numeric."""
        if self._edit_field == 'ref':
            return  # ref is changed via cycle_ref / edit_tab, not typed
        buf = self._edit_a if self._edit_field == 'a' else self._edit_b
        if data == '\x7f' or data == '\b':  # backspace
            buf = buf[:-1]
        elif self._accepts_char(buf, data):
            buf += data
        else:
            return  # reject invalid character; leave the buffer untouched
        if self._edit_field == 'a':
            self._edit_a = buf
        else:
            self._edit_b = buf
        self._edit_error = ''  # any successful edit clears a stale error

    def commit_edit(self) -> bool:
        try:
            a = float(self._edit_a)
        except ValueError:
            self._edit_error = 'multiplier must be a number greater than 0'
            return False
        if a <= 0:
            self._edit_error = 'multiplier must be greater than 0'
            return False
        b: Optional[int] = None
        if self._edit_b.strip():
            try:
                b = int(self._edit_b)
            except ValueError:
                self._edit_error = 'increment must be a whole number of milliseconds'
                return False
        self.relatives[self.group_key(self.current_lang())] = LanguageGroupFallback(
            relativeTo=self._edit_ref, multiplier=a, increment=b
        )
        self._edit_error = ''
        self.editing = False
        return True

    def cancel_edit(self) -> None:
        self.editing = False

    def clear_relative(self) -> None:
        self.relatives.pop(self.group_key(self.current_lang()), None)
        self.editing = False

    def reset_to_initial(self) -> None:
        self.numbers = dict(self._initial_numbers)
        self.relatives = dict(self._initial_relatives)
        self.editing = False

    def prune_relatives(self) -> Dict[str, LanguageGroupFallback]:
        live = {self.group_key(lang) for lang in self.languages}
        return {k: v for k, v in self.relatives.items() if k in live}

    def preview_text(self, preview):
        """The live preview's content, or empty once the picker is confirmed."""
        if self.done or preview is None:
            return ''
        return preview(self.assignment(), self.prune_relatives())

    def move(self, delta: int) -> None:
        if not self.languages:
            return
        self.cursor = max(0, min(len(self.languages) - 1, self.cursor + delta))

    def set_group(self, number: int) -> None:
        if self.languages:
            self.numbers[self.languages[self.cursor]] = number

    def toggle_singleton(self) -> None:
        if not self.languages:
            return
        lang = self.languages[self.cursor]
        # toggle between singleton (-1) and unbucketed (0); a numbered language
        # goes to singleton on the first press.
        self.numbers[lang] = 0 if self.numbers.get(lang, 0) == -1 else -1

    def assignment(self) -> Dict[str, int]:
        return dict(self.numbers)

    def _relative_suffix(self, lang: str) -> str:
        spec = self.relatives.get(self.group_key(lang))
        if spec is None:
            return ''
        ref = spec.relativeTo if spec.relativeTo is not None else 'base'
        suffix = f'  → {ref} ×{spec.multiplier:g}'
        if spec.increment:
            suffix += f' +{spec.increment}'
        return suffix

    def _editor_fragments(self):
        ref = self._edit_ref if self._edit_ref is not None else 'base estimate'
        increment = self._edit_b if self._edit_b else '0'
        fields = [
            ('reference', ref, 'ref'),
            ('multiplier', self._edit_a, 'a'),
            ('increment', increment, 'b'),
        ]
        # Field row: the focused field is marked with a pointer and highlighted,
        # so it is clear which of reference/multiplier/increment is being edited.
        frags = [('class:editor', '      ')]
        for idx, (label, value, key) in enumerate(fields):
            if idx:
                frags.append(('class:editor', '    '))
            focused = self._edit_field == key
            marker = '▸ ' if focused else '  '
            field_style = 'class:editor-focus' if focused else 'class:editor'
            frags.append((field_style, f'{marker}{label}: [{value}]'))
        frags.append(('class:editor', '\n'))
        # Explain what the parameters mean and how the limit is computed.
        frags.append(
            (
                'class:editor-hint',
                '      time limit = multiplier × reference + increment\n',
            )
        )
        frags.append(
            (
                'class:editor-hint',
                '      Tab: switch field · ←/→ or h/l: change reference · '
                'enter: ok · esc: cancel · c: clear\n',
            )
        )
        if self._edit_error:
            frags.append(('class:editor-error', f'      ⚠ {self._edit_error}\n'))
        return frags

    def editor_height(self) -> int:
        """Number of lines the inline editor draws (grows for an error line)."""
        return EDITOR_HEIGHT + (1 if self._edit_error else 0)

    def render_fragments(self):
        """prompt_toolkit formatted-text fragments: list of (style, text)."""
        fragments = []
        for i, lang in enumerate(self.languages):
            number = self.numbers[lang]
            if number > 0:
                box = str(number)
            elif number < 0:
                box = 'X'
            else:
                box = ' '
            selected = i == self.cursor
            pointer = '❯ ' if selected else '  '
            row_style = 'class:current' if selected else 'class:row'
            box_style = 'class:box-current' if selected else 'class:box'
            fragments.append((row_style, pointer))
            fragments.append((box_style, f'[{box}] '))
            fragments.append((row_style, lang))
            fragments.append(('class:relative', self._relative_suffix(lang)))
            fragments.append((row_style, '\n'))
            if i == self.cursor and self.editing:
                fragments.extend(self._editor_fragments())
        return fragments


async def prompt_group_assignment(
    languages: List[str],
    default_number: Dict[str, int],
    relatives: Optional[Dict[str, LanguageGroupFallback]] = None,
    input=None,
    output=None,
    preview: Optional[Callable[..., AnyFormattedText]] = None,
) -> Optional[GroupAssignment]:
    """Interactive single-screen group picker. Returns a ``GroupAssignment``
    whose ``numbers`` maps {language: group_number} (N>=1 shared group, 0
    unbucketed/leftover, -1 singleton) and whose ``relatives`` carries any
    forced-relative specs; or None if cancelled."""
    if not languages:
        return GroupAssignment(numbers={}, relatives={})

    from prompt_toolkit.application import Application
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    state = GroupPickerState(languages, default_number, relatives=relatives)

    def _header_fragments():
        fragments = []
        last = len(LEGEND_LINES) - 1
        for i, line in enumerate(LEGEND_LINES):
            if i == 0:
                style = 'class:header'
            elif i == last:
                style = 'class:hint'
            else:
                style = 'class:legend'
            fragments.append((style, line + '\n'))
        return fragments

    header = FormattedTextControl(_header_fragments)
    body = FormattedTextControl(
        state.render_fragments, focusable=True, show_cursor=False
    )

    kb = KeyBindings()

    editing = Condition(lambda: state.editing)
    not_editing = ~editing

    @kb.add('up', filter=not_editing)
    @kb.add('k', filter=not_editing)
    def _(event):
        state.move(-1)

    @kb.add('down', filter=not_editing)
    @kb.add('j', filter=not_editing)
    def _(event):
        state.move(1)

    for _digit in '123456789':

        @kb.add(_digit, filter=not_editing)
        def _(event, _digit=_digit):
            state.set_group(int(_digit))

    @kb.add('0', filter=not_editing)
    def _(event):
        # explicit clear to unbucketed
        state.set_group(0)

    @kb.add('space', filter=not_editing)
    @kb.add('tab', filter=not_editing)
    def _(event):
        state.toggle_singleton()

    @kb.add('r', filter=not_editing)
    def _(event):
        state.start_edit()

    @kb.add('R', filter=not_editing)
    def _(event):
        state.reset_to_initial()

    @kb.add('enter', filter=not_editing)
    def _(event):
        # Hide the live preview on the final paint; the official table is
        # printed by the caller right after the picker returns.
        state.done = True
        event.app.exit(
            result=GroupAssignment(
                numbers=state.assignment(),
                relatives=state.prune_relatives(),
            )
        )

    @kb.add('c-c', filter=not_editing)
    @kb.add('q', filter=not_editing)
    def _(event):
        event.app.exit(result=None)

    # Edit-mode bindings: active only while the inline relative editor is open.
    @kb.add('tab', filter=editing)
    def _(event):
        state.edit_tab()

    # Left/right (and vim h/l) cycle the reference group regardless of which
    # field is focused; Tab switches the focused field.
    @kb.add('left', filter=editing)
    @kb.add('h', filter=editing)
    def _(event):
        state.cycle_ref(-1)

    @kb.add('right', filter=editing)
    @kb.add('l', filter=editing)
    def _(event):
        state.cycle_ref(1)

    @kb.add('enter', filter=editing)
    def _(event):
        # commit_edit flips editing=False on success; stay editing if invalid.
        state.commit_edit()

    @kb.add('escape', filter=editing)
    def _(event):
        state.cancel_edit()

    @kb.add('c', filter=editing)
    def _(event):
        state.clear_relative()

    @kb.add('<any>', filter=editing)
    def _(event):
        state.edit_key(event.data)

    def _body_height():
        # Grow to fit the inline editor's extra lines while it is open.
        return len(state.languages) + (state.editor_height() if state.editing else 0)

    windows = [
        Window(content=header, height=len(LEGEND_LINES), always_hide_cursor=True),
        Window(content=body, height=_body_height, always_hide_cursor=True),
    ]
    if preview is not None:

        def _preview_fragments():
            return state.preview_text(preview)

        windows.append(
            Window(
                content=FormattedTextControl(_preview_fragments),
                always_hide_cursor=True,
                dont_extend_height=True,
            )
        )
    layout = Layout(HSplit(windows))
    style = Style.from_dict(
        {
            'header': 'bold',
            'hint': 'ansibrightblack',
            'legend': '',
            'current': 'bold reverse',
            'row': '',
            'box-current': 'ansiyellow bold',
            'box': 'ansiyellow',
            'editor': 'ansicyan',
            'editor-focus': 'ansicyan bold reverse',
            'editor-hint': 'ansibrightblack',
            'editor-error': 'ansired bold',
            'relative': 'ansigreen',
        }
    )
    app = Application(
        layout=layout,
        key_bindings=kb,
        style=style,
        full_screen=False,
        input=input,
        output=output,
    )
    return await app.run_async()
