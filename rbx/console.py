import io
import sys
from typing import Optional

import rich
import rich.markup
from rich.console import Console
from rich.text import Span, Text, TextType
from rich.theme import Theme

theme = Theme(
    {
        # Normal.
        'default': 'bright_white',
        'rbx': 'bold italic yellow',
        'info': 'bright_black',
        'hilite': 'color(243)',
        'status': 'bright_white',
        'bstatus': 'bold bright_white',
        'item': 'bold blue',
        'error': 'bold red',
        'success': 'bold green',
        'lnumber': 'dim cyan',
        'warning': 'bold yellow',
        # Inverted.
        'istatus': 'bold black on bright_white',
        'isuccess': 'bold white on green',
        'ierror': 'bold white on red',
        'iwarning': 'bold white on yellow',
    }
)
console = Console(theme=theme, style='info', highlight=False)
stderr_console = Console(theme=theme, style='info', highlight=False, stderr=True)


def new_console():
    return Console(theme=theme, style='info', highlight=False)


def capture_ansi(renderable, width: Optional[int] = None) -> str:
    """Render a rich renderable (or markup string) to an ANSI string using the
    project theme, suitable for embedding in a prompt_toolkit ``ANSI`` fragment."""
    buf = io.StringIO()
    cap = Console(
        theme=theme,
        style='info',
        highlight=False,
        file=buf,
        force_terminal=True,
        color_system='standard',
        width=width,
    )
    cap.print(renderable)
    return buf.getvalue()


def multiline_prompt(text: str) -> str:
    console.print(f'{text} (Ctrl-D to finish):\n')
    lines = sys.stdin.readlines()
    console.print()
    return ''.join(lines)


def render_from(r: rich.console.RenderableType) -> str:
    with console.capture() as capture:
        console.print(r)
    return capture.get()


def render_from_markup(markup: str) -> str:
    return render_from(rich.markup.render(markup))


def expand_markup(text: TextType) -> Text:
    if isinstance(text, str):
        styled_text = Text.from_markup(text)
    else:
        styled_text = text.copy()

    # We manually link the theme styles to the text object
    styled_text.spans = [_expand_span(span) for span in styled_text.spans]
    return styled_text


def _expand_span(span: Span) -> Span:
    if isinstance(span.style, str) and span.style in theme.styles:
        return Span(span.start, span.end, style=theme.styles[span.style])
    return span
