"""Where each line of a generated statement came from (#909).

A statement reaches pdflatex after two Jinja renders -- the setter's ``.rbx.tex``
block by block, then the template that splices the rendered blocks in -- and
neither keeps line numbers. This module carries them through.

**Tagging.** :class:`LineTagExtension` rewrites the Jinja token stream so every
source line with content starts with an invisible tag, ``U+E000 <id>:<line>
U+E001``. The tag is plain template *data*, so Jinja moves it wherever it moves
the line: into a block, through a loop or a conditional, into a template via
``\\VAR{problem.blocks.legend}``. Ids rather than paths, so a ``{% filter upper
%}`` cannot damage one; content lines only, so a whitespace-only block stays
falsy.

**Emitting.** Rendered TeX never reaches disk with tags in it: whoever writes it
into the overlay passes it through :func:`emit`, which strips the tags and
records, for that file, the source position of every line (the last tag on the
line, else the line above's).

**Provenance.** The overlay is a copy, so a tag first names an overlay file.
:class:`Origins` maps it back to the file the setter edits.

Tagging is only on inside :func:`tracking`, which only the statement builds
enter. Outside it every function here is a no-op, so nothing else that renders
a template -- ``rbx vars``, the editor's var hints -- ever sees a tag.

A leaf module (Jinja and the stdlib only): see
``docs/plans/2026-10-15-statement-preview-design.md``.
"""

import contextlib
import contextvars
import dataclasses
import os
import pathlib
import re
import types
from typing import Dict, Iterable, Iterator, List, Optional, Tuple, Union

import jinja2
import jinja2.ext
from jinja2.lexer import (
    TOKEN_ASSIGN,
    TOKEN_BLOCK_BEGIN,
    TOKEN_BLOCK_END,
    TOKEN_COMMA,
    TOKEN_DATA,
    TOKEN_INTEGER,
    TOKEN_LINESTATEMENT_BEGIN,
    TOKEN_LINESTATEMENT_END,
    TOKEN_LPAREN,
    TOKEN_NAME,
    TOKEN_PIPE,
    TOKEN_RPAREN,
    TOKEN_VARIABLE_BEGIN,
    TOKEN_VARIABLE_END,
    Token,
    TokenStream,
)

TAG_OPEN = ''
TAG_CLOSE = ''
_TAG = re.compile(f'{TAG_OPEN}(\\d+):(\\d+){TAG_CLOSE}')

# `render.render_jinja` and friends write the content they render to a scratch
# file named like this before Jinja loads it; it is never the setter's file.
SCRATCH_PREFIX = '__'

PathLike = Union[str, os.PathLike]


def _key(path: PathLike) -> pathlib.Path:
    """One spelling per file: pdflatex, Jinja's loader and the stager each name
    the same file differently (relative to a cwd, joined onto a search path, or
    through a symlinked temp dir)."""
    return pathlib.Path(os.path.realpath(path))


@dataclasses.dataclass(frozen=True)
class SourcePos:
    path: pathlib.Path
    line: int  # 1-based


class Origins:
    """Maps a file in the build overlay back to the file it was staged from.

    - a **mount** says an overlay directory mirrors a source directory (the
      contest chrome, a problem's statement directory);
    - an **alias** names one staged file's origin (a template copied in by its
      basename);
    - a **source** is a file whose *content* may be rendered from a scratch
      file, so the scratch file is matched back to it by content.
    """

    def __init__(self) -> None:
        self._mounts: List[Tuple[pathlib.Path, pathlib.Path]] = []
        self._aliases: Dict[pathlib.Path, pathlib.Path] = {}
        # Keyed by content and by the directory the scratch copy is rendered
        # in: two problems of a contest may ship byte-identical statements.
        self._sources: Dict[Tuple[Optional[pathlib.Path], str], pathlib.Path] = {}

    def mount(self, staged_dir: PathLike, source_dir: PathLike) -> None:
        self._mounts.append((_key(staged_dir), _key(source_dir)))
        # Deepest first, so `.problems/A/` beats the chrome mounted at the root.
        # Stable, so among equals the first registered wins.
        self._mounts.sort(key=lambda mount: len(mount[0].parts), reverse=True)

    def alias(self, staged: PathLike, source: PathLike) -> None:
        self._aliases[_key(staged)] = _key(source)

    def source(self, path: PathLike, rendered_in: Optional[PathLike] = None) -> None:
        """``path``'s content may be rendered from a scratch file -- in
        ``rendered_in`` when given, which tells apart two sources with the same
        text (identical statements of two problems in a contest)."""
        try:
            text = pathlib.Path(path).read_text()
        except (OSError, UnicodeDecodeError):
            return
        where = _key(rendered_in) if rendered_in is not None else None
        self._sources.setdefault((where, text), _key(path))

    def resolve(self, staged: PathLike) -> Optional[pathlib.Path]:
        key = _key(staged)
        if key in self._aliases:
            return self._aliases[key]
        if key.name.startswith(SCRATCH_PREFIX):
            try:
                text = key.read_text()
            except (OSError, UnicodeDecodeError):
                return None
            return self._sources.get((key.parent, text)) or self._sources.get(
                (None, text)
            )
        for staged_dir, source_dir in self._mounts:
            try:
                relative = key.relative_to(staged_dir)
            except ValueError:
                continue
            candidate = source_dir / relative
            if candidate.is_file():
                return candidate
        return None


@dataclasses.dataclass(frozen=True)
class Excerpt:
    """Where a piece of text TeX printed was found in an emitted file."""

    line: int  # 1-based
    column: int  # 0-based, just past the point TeX stopped
    # Where the token TeX stopped on begins: the error is that token's, and a
    # control word glued to the next text (`\\badBody` + `Given`) may start
    # in one origin and end in another.
    start: int
    # How many (non-whitespace) characters of the printed text matched: the
    # evidence behind the match, to choose between several printed texts.
    score: int


# A line's origins, as `(column, origin)` segments: a line can hold template
# text and then a spliced block, or the end of an included file and then the
# includer's next line.
Segments = List[Tuple[int, Optional[SourcePos]]]


class SourceTracker:
    """The source map of one statement build: tag ids, and the line origins of
    every file :meth:`emit` wrote."""

    def __init__(self, origins: Optional[Origins] = None) -> None:
        self.origins = origins or Origins()
        self._ids: Dict[Optional[pathlib.Path], int] = {}
        self._paths: List[Optional[pathlib.Path]] = []
        self._lines: Dict[pathlib.Path, List[Segments]] = {}
        self._text: Dict[pathlib.Path, List[str]] = {}

    def intern(self, origin: Optional[pathlib.Path]) -> int:
        if origin not in self._ids:
            self._ids[origin] = len(self._paths)
            self._paths.append(origin)
        return self._ids[origin]

    def emit(self, path: PathLike, text: str) -> str:
        """Strip the tags from ``text``, which is about to be written to
        ``path``, remembering where each of its lines came from: each tag starts
        a segment there, and text before a line's first tag continues the
        previous line's last segment."""
        lines: List[str] = []
        segments: List[Segments] = []
        current: Optional[SourcePos] = None
        for raw in text.split('\n'):
            clean: List[str] = []
            line_segments: Segments = []
            column = 0
            position = 0
            for match in _TAG.finditer(raw):
                piece = raw[position : match.start()]
                clean.append(piece)
                column += len(piece)
                position = match.end()
                if not line_segments and column > 0:
                    line_segments.append((0, current))
                origin = self._paths[int(match.group(1))]
                current = (
                    SourcePos(origin, int(match.group(2)))
                    if origin is not None
                    else None
                )
                if line_segments and line_segments[-1][0] == column:
                    line_segments[-1] = (column, current)
                else:
                    line_segments.append((column, current))
            clean.append(raw[position:])
            if not line_segments:
                line_segments.append((0, current))
            lines.append(''.join(clean))
            segments.append(line_segments)
        self._lines[_key(path)] = segments
        self._text[_key(path)] = lines
        return '\n'.join(lines)

    def find_excerpt(
        self,
        path: PathLike,
        line: int,
        before: str,
        after: str,
        only_line: bool = False,
    ) -> Optional[Excerpt]:
        """Where in an emitted file a piece of text TeX printed sits, split at
        the point it stopped.

        Matched without whitespace, which TeX re-spaces when it prints tokens
        (a control word is always shown followed by a space).

        The text before the stop usually spans many lines -- TeX prints up to
        a few hundred characters of it, truncating the start with `...` -- so
        it is matched by its **longest suffix found on one line**: the error
        line's own text up to the offending token. Several lines may hold that
        suffix (a phrase used twice); each is scored by how far the rest of the
        text keeps matching backwards over the lines above it, so the one
        whose surroundings TeX printed wins. What follows the stop breaks the
        remaining ties -- it may hold tokens TeX inserted itself (a `\\par` for a
        blank line) and never appear at all -- and then the nearest line at or
        above ``line``, since TeX expands text after reading it.

        ``only_line`` restricts the search to ``line``, to find the column of a
        stop TeX already located.
        """
        text = self._text.get(_key(path))
        if text is None:
            return None
        squashed = [_squash(raw) for raw in text]
        head = _squash(before[3:] if before.startswith('...') else before)
        tail = _squash(after)
        # A `\\par` at the break is TeX's (a blank line ended the paragraph
        # there); no source line holds it.
        while head.endswith(_PAR):
            head = head[: -len(_PAR)]
        while tail.startswith(_PAR):
            tail = tail[len(_PAR) :]
        scope = (
            [line - 1]
            if only_line and 0 < line <= len(squashed)
            else range(len(squashed))
        )

        size = 0
        hits: List[int] = []
        for size in range(len(head), _EXCERPT_MIN_CHARS - 1, -1):
            hits = [i for i in scope if head[-size:] in squashed[i]]
            if hits:
                break
        if not hits:
            # The line TeX stopped on may be too short to match on its own (a
            # paragraph ending in `b`): match across it and the line above, and
            # keep the lines where the match ends.
            return self._find_across(text, squashed, head, line, scope)
        suffix = head[-size:]

        def backwards(i: int) -> int:
            # Only a match that starts its line can continue onto the line above.
            if not squashed[i].startswith(suffix):
                return 0
            rest, j, score = head[:-size], i - 1, 0
            while rest and j >= 0:
                above = squashed[j]
                if not above:
                    # A blank line is a paragraph break, printed as `\par`.
                    if rest.endswith(_PAR):
                        rest = rest[: -len(_PAR)]
                elif rest.endswith(above):
                    rest, score = rest[: -len(above)], score + len(above)
                else:
                    score += len(os.path.commonprefix([rest[::-1], above[::-1]]))
                    break
                j -= 1
            return score

        def forwards(i: int) -> int:
            at = squashed[i].rfind(suffix) + len(suffix)
            return len(os.path.commonprefix([tail, squashed[i][at:]]))

        def rank(i: int) -> Tuple[int, int, int]:
            nearest = i - line if i <= line - 1 else -len(squashed) - i
            return (backwards(i), forwards(i), nearest)

        best = max(hits, key=rank)
        end = squashed[best].rfind(suffix) + len(suffix)
        word = _CONTROL_WORD_END.search(suffix)
        token = len(word.group(0)) if word is not None else 1
        return Excerpt(
            line=best + 1,
            column=_column(text[best], end),
            score=size + backwards(best),
            start=_column(text[best], end - token + 1) - 1,
        )

    def _find_across(
        self,
        text: List[str],
        squashed: List[str],
        head: str,
        line: int,
        scope: Iterable[int],
    ) -> Optional[Excerpt]:
        """:meth:`find_excerpt` for a stop at the end of a short line: the
        longest suffix of ``head`` that runs from the line above into one line
        and ends there."""
        for size in range(len(head), _EXCERPT_MIN_CHARS - 1, -1):
            suffix = head[-size:]
            hits = [
                i
                for i in scope
                if i > 0
                and squashed[i]
                and (squashed[i - 1] + squashed[i]).endswith(suffix)
                and len(suffix) > len(squashed[i])
            ]
            if hits:
                above = [i for i in hits if i <= line - 1]
                best = above[-1] if above else hits[0]
                end = len(squashed[best])
                return Excerpt(
                    line=best + 1,
                    column=_column(text[best], end),
                    score=size,
                    start=_column(text[best], 1) - 1,
                )
        return None

    def text_of(self, path: PathLike, line: int) -> Optional[str]:
        """Line ``line`` of an emitted file, as pdflatex read it."""
        text = self._text.get(_key(path))
        if text is None or not 0 < line <= len(text):
            return None
        return text[line - 1]

    def locate(
        self, path: PathLike, line: int, column: Optional[int] = None
    ) -> Optional[SourcePos]:
        """The source position of ``line`` of a file pdflatex read.

        A file written through :meth:`emit` answers from its line map -- the
        segment holding ``column``, or the line's last segment when the
        column is unknown; one
        copied into the overlay verbatim (a setter's ``\\input``) is the same
        line of its origin; anything else (a system ``.sty``) is unknown."""
        key = _key(path)
        if key in self._lines:
            lines = self._lines[key]
            if not lines:
                return None
            segments = lines[min(max(line, 1), len(lines)) - 1]
            if column is None:
                return segments[-1][1]
            at = max(column, 0)
            found = segments[0][1]
            for start, pos in segments:
                if start <= at:
                    found = pos
            return found
        origin = self.origins.resolve(key)
        return SourcePos(origin, line) if origin is not None else None

    def locate_template_error(self, exc: BaseException) -> Optional[SourcePos]:
        """Where a Jinja error happened, in the setter's files.

        A syntax error says so itself. A runtime one (an undefined variable)
        does not, but its traceback runs through the compiled template, and the
        template knows which of its lines a frame was executing. The innermost
        frame that maps to a source file wins; the error may arrive wrapped (as
        ``typer.Abort`` ``from`` it), so the whole cause chain is searched.
        """
        for err in _chain(exc):
            if isinstance(err, jinja2.TemplateSyntaxError) and err.filename:
                origin = self.origins.resolve(err.filename)
                if origin is not None:
                    return SourcePos(origin, err.lineno)
            found = None
            for filename, line in _template_frames(err.__traceback__):
                origin = self.origins.resolve(filename)
                if origin is not None:
                    found = SourcePos(origin, line)
            if found is not None:
                return found
        return None


# Shorter than this, a suffix like `\\x` would match lines by accident.
_EXCERPT_MIN_CHARS = 4
_WHITESPACE = re.compile(r'\s+')
_PAR = '\\par'
# A control word at the very end of a printed text: the token TeX stopped on.
_CONTROL_WORD_END = re.compile(r'\\[A-Za-z@]+$')


def _squash(text: str) -> str:
    return _WHITESPACE.sub('', text)


def _column(raw: str, squashed_end: int) -> int:
    """The column in ``raw`` just past its ``squashed_end``-th non-whitespace
    character."""
    seen = 0
    for column, char in enumerate(raw):
        if not char.isspace():
            seen += 1
            if seen == squashed_end:
                return column + 1
    return len(raw)


def _chain(exc: BaseException) -> Iterator[BaseException]:
    seen = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _template_frames(
    tb: Optional[types.TracebackType],
) -> Iterator[Tuple[str, int]]:
    """``(template filename, template line)`` for each template frame, outermost
    first. A frame of a compiled template carries the template, which maps the
    Python line back; a frame Jinja already rewrote (``Template.render`` does)
    carries the template line itself, under the template's filename."""
    while tb is not None:
        frame = tb.tb_frame
        template = frame.f_globals.get('__jinja_template__')
        if template is not None and template.filename:
            yield template.filename, template.get_corresponding_lineno(tb.tb_lineno)
        elif not frame.f_code.co_filename.endswith('.py'):
            yield frame.f_code.co_filename, tb.tb_lineno
        tb = tb.tb_next


def _is_markdown(path: Optional[PathLike]) -> bool:
    return path is not None and pathlib.Path(path).suffix.lower() == '.md'


def _tag(origin_id: int, line: int) -> str:
    return f'{TAG_OPEN}{origin_id}:{line}{TAG_CLOSE}'


# Statements whose body Jinja captures as a string for the template to compute
# with (`set x` ... `endset`, a macro, a call block, a filter block): tags in
# there would change what `|int`, `|length` or `== "..."` see.
_CAPTURES = {
    'macro': 'endmacro',
    'call': 'endcall',
    'filter': 'endfilter',
    'set': 'endset',
}
_STATEMENT_BEGIN = (TOKEN_BLOCK_BEGIN, TOKEN_LINESTATEMENT_BEGIN)
_STATEMENT_END = (TOKEN_BLOCK_END, TOKEN_LINESTATEMENT_END)
_LINE_TAG_FILTER = '_rbx_line_tag'


def _line_tag(value: object, origin_id: int, line: int) -> str:
    """The `\\VAR{...}` that starts a source line, tagged -- only when it renders
    something, so a block holding nothing but an empty one stays empty."""
    text = str(value)
    return _tag(origin_id, line) + text if text.strip() else text


class LineTagExtension(jinja2.ext.Extension):
    """Tags each content line of a template's literal text with its origin."""

    def __init__(self, environment: jinja2.Environment) -> None:
        super().__init__(environment)
        environment.filters[_LINE_TAG_FILTER] = _line_tag

    def filter_stream(self, stream: TokenStream) -> Iterator[Token]:
        tracker = current()
        if tracker is None:
            yield from stream
            return
        origin = tracker.origins.resolve(stream.filename) if stream.filename else None
        if _is_markdown(stream.filename) or _is_markdown(origin):
            # Markdown is converted by pandoc before it is ever TeX, and a tag
            # at the start of a line would stop `# heading` or `- item` from
            # being syntax. Its errors are pandoc's, not pdflatex's, anyway.
            yield from stream
            return
        origin_id = tracker.intern(origin)
        last_tagged = 0
        capturing: List[str] = []  # the end tags of the captures we are inside
        tokens = iter(stream)
        for token in tokens:
            if token.type in _STATEMENT_BEGIN:
                statement = [token, *_until(tokens, _STATEMENT_END)]
                _track_captures(statement, capturing)
                yield from statement
                continue
            if capturing:
                yield token
                continue
            if token.type == TOKEN_VARIABLE_BEGIN and token.lineno != last_tagged:
                # A line that starts with a `\VAR{...}` has no literal text to
                # carry its tag; the value carries it instead. Not counted as
                # tagged: the value may render empty.
                yield from _wrap_variable(token, tokens, origin_id)
                continue
            if token.type != TOKEN_DATA:
                yield token
                continue
            out: List[str] = []
            line = token.lineno
            for index, piece in enumerate(token.value.split('\n')):
                if index:
                    out.append('\n')
                    line += 1
                # Once per source line: data resuming after a `\VAR{}` on the
                # same line is still that line.
                if line != last_tagged and piece.strip():
                    out.append(_tag(origin_id, line))
                    last_tagged = line
                out.append(piece)
            yield Token(token.lineno, TOKEN_DATA, ''.join(out))


def _until(tokens: Iterator[Token], ends: Tuple[str, ...]) -> List[Token]:
    taken: List[Token] = []
    for token in tokens:
        taken.append(token)
        if token.type in ends:
            break
    return taken


def _track_captures(statement: List[Token], capturing: List[str]) -> None:
    names = [token.value for token in statement if token.type == TOKEN_NAME]
    if not names:
        return
    keyword = names[0]
    if capturing and keyword == capturing[-1]:
        capturing.pop()
        return
    if keyword in _CAPTURES:
        # `set x = value` assigns; only a bare `set x` captures a body.
        if keyword == 'set' and any(token.type == TOKEN_ASSIGN for token in statement):
            return
        capturing.append(_CAPTURES[keyword])


def _wrap_variable(
    begin: Token, tokens: Iterator[Token], origin_id: int
) -> Iterator[Token]:
    """`\\VAR{expr}` -> `\\VAR{(expr)|_rbx_line_tag(id, line)}`."""
    line = begin.lineno
    body = _until(tokens, (TOKEN_VARIABLE_END,))
    end = body.pop() if body and body[-1].type == TOKEN_VARIABLE_END else None
    last = body[-1].lineno if body else line
    yield begin
    yield Token(line, TOKEN_LPAREN, '(')
    yield from body
    yield Token(last, TOKEN_RPAREN, ')')
    yield Token(last, TOKEN_PIPE, '|')
    yield Token(last, TOKEN_NAME, _LINE_TAG_FILTER)
    yield Token(last, TOKEN_LPAREN, '(')
    yield Token(last, TOKEN_INTEGER, origin_id)
    yield Token(last, TOKEN_COMMA, ',')
    yield Token(last, TOKEN_INTEGER, line)
    yield Token(last, TOKEN_RPAREN, ')')
    if end is not None:
        yield end


_current: contextvars.ContextVar[Optional[SourceTracker]] = contextvars.ContextVar(
    'rbx_statement_sourcemap', default=None
)


def current() -> Optional[SourceTracker]:
    return _current.get()


@contextlib.contextmanager
def tracking(origins: Optional[Origins] = None) -> Iterator[SourceTracker]:
    """Tag every template rendered inside the block, and collect the map."""
    tracker = SourceTracker(origins)
    token = _current.set(tracker)
    try:
        yield tracker
    finally:
        _current.reset(token)


def strip(text: str) -> str:
    return _TAG.sub('', text) if TAG_OPEN in text else text


def emit(path: PathLike, text: str) -> str:
    """Tag-free ``text`` for writing to ``path``; recorded when tracking."""
    tracker = current()
    if tracker is None:
        return strip(text)
    return tracker.emit(path, text)


def verbatim(text: str, origin: PathLike) -> str:
    """``text``, read from ``origin`` and handed to pdflatex as is (a static
    `tex` statement), tagged line for line so its errors map back too."""
    tracker = current()
    if tracker is None:
        return text
    origin_id = tracker.intern(_key(origin))
    return '\n'.join(
        _tag(origin_id, number) + raw if raw.strip() else raw
        for number, raw in enumerate(text.split('\n'), start=1)
    )


def unlocated(text: str) -> str:
    """``text`` marked as coming from nowhere a setter can edit -- a block
    pandoc wrote -- so its lines do not inherit the origin of the template
    line before them."""
    tracker = current()
    if tracker is None:
        return text
    origin_id = tracker.intern(None)
    return '\n'.join(
        _tag(origin_id, 0) + raw if raw.strip() else raw for raw in text.split('\n')
    )


def extensions() -> List[type]:
    """The Jinja extensions a statement render needs right now."""
    return [LineTagExtension] if current() is not None else []
