from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from rich.containers import Lines
from rich.segment import Segment
from rich.text import Text

if TYPE_CHECKING:
    from rich.console import Console, ConsoleOptions


class CroppedText:
    """Wraps a Rich Text renderable and crops it to a maximum number of rendered lines.

    Horizontal wrapping/overflow is handled by the wrapped Text as usual.
    This wrapper only adds vertical cropping on top.

    Args:
        text: The Text renderable to crop.
        max_lines: Maximum number of rendered lines to show.
        overflow: How to handle vertical overflow:
            - "crop": Discard lines beyond max_lines.
            - "ellipsis": Show max_lines-1 content lines + an ellipsis line.
            - "fold": Same as "crop".
            - "ignore": No vertical cropping.
        footer: Optional Text shown below the content only when cropping occurs.
            Does not count towards max_lines.
    """

    def __init__(
        self,
        text: Text,
        max_lines: int,
        overflow: str = 'ellipsis',
        footer: Text | None = None,
    ) -> None:
        self.text = text
        self.max_lines = max_lines
        self.overflow = overflow
        self.footer = footer

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> Iterable[Segment]:
        text = self.text
        tab_size: int = console.tab_size if text.tab_size is None else text.tab_size
        justify = text.justify or options.justify or 'left'
        overflow = text.overflow or options.overflow or 'fold'
        no_wrap = (
            text.no_wrap if text.no_wrap is not None else (options.no_wrap or False)
        )

        lines = text.wrap(
            console,
            options.max_width,
            justify=justify,
            overflow=overflow,
            tab_size=tab_size or 8,
            no_wrap=no_wrap,
        )

        cropped = False
        if self.overflow != 'ignore' and len(lines) > self.max_lines:
            cropped = True
            if self.overflow == 'ellipsis' and self.max_lines > 0:
                cut = lines[: self.max_lines - 1]
                ellipsis_line = Text(
                    '...',
                    style='bold red',
                    justify=justify,
                    overflow=overflow,
                    end='',
                )
                ellipsis_line.truncate(options.max_width, overflow=overflow)
                cut.append(ellipsis_line)
                lines = Lines(cut)
            else:
                lines = Lines(lines[: self.max_lines])

        result: list[Text] = list(lines)
        if cropped and self.footer is not None:
            footer_lines = list(
                self.footer.wrap(
                    console,
                    options.max_width,
                    justify=self.footer.justify or justify,
                    overflow=self.footer.overflow or overflow,
                    tab_size=tab_size or 8,
                    no_wrap=no_wrap,
                )
            )
            result.extend(footer_lines)

        all_lines = Text('\n').join(result)
        yield from all_lines.render(console, end=text.end)
