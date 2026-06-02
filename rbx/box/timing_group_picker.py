from typing import Dict, List, Optional


class GroupPickerState:
    def __init__(self, languages: List[str], default_number: Dict[str, int]):
        self.languages: List[str] = list(languages)
        self.numbers: Dict[str, int] = {
            lang: int(default_number.get(lang, 0)) for lang in self.languages
        }
        self.cursor: int = 0

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
            fragments.append((row_style, f'{lang}\n'))
        return fragments


async def prompt_group_assignment(
    languages: List[str],
    default_number: Dict[str, int],
    input=None,
    output=None,
) -> Optional[Dict[str, int]]:
    """Interactive single-screen group picker. Returns {language: group_number}
    where N>=1 is a shared group, 0 is unbucketed (leftover), and -1 is a
    singleton (own group); or None if cancelled."""
    if not languages:
        return {}

    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    state = GroupPickerState(languages, default_number)

    header = FormattedTextControl(
        lambda: [
            (
                'class:header',
                'Assign each language to a group (same number = shared time limit).\n',
            ),
            (
                'class:hint',
                '↑/↓ or j/k move · 1-9 set group · space/tab toggle '
                'singleton [X] / unbucketed [ ] · 0 clear · Enter confirm · '
                'q cancel\n',
            ),
        ]
    )
    body = FormattedTextControl(
        state.render_fragments, focusable=True, show_cursor=False
    )

    kb = KeyBindings()

    @kb.add('up')
    @kb.add('k')
    def _(event):
        state.move(-1)

    @kb.add('down')
    @kb.add('j')
    def _(event):
        state.move(1)

    for _digit in '123456789':

        @kb.add(_digit)
        def _(event, _digit=_digit):
            state.set_group(int(_digit))

    @kb.add('0')
    def _(event):
        # explicit clear to unbucketed
        state.set_group(0)

    @kb.add('space')
    @kb.add('tab')
    def _(event):
        state.toggle_singleton()

    @kb.add('enter')
    def _(event):
        event.app.exit(result=state.assignment())

    @kb.add('c-c')
    @kb.add('q')
    def _(event):
        event.app.exit(result=None)

    layout = Layout(
        HSplit(
            [
                Window(content=header, height=2, always_hide_cursor=True),
                Window(
                    content=body,
                    height=len(state.languages),
                    always_hide_cursor=True,
                ),
            ]
        )
    )
    style = Style.from_dict(
        {
            'header': 'bold',
            'hint': 'ansibrightblack',
            'current': 'bold reverse',
            'row': '',
            'box-current': 'ansiyellow bold',
            'box': 'ansiyellow',
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
