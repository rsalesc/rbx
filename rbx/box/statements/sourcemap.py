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
from jinja2.lexer import TOKEN_DATA, Token, TokenStream

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
        self._sources: Dict[str, pathlib.Path] = {}

    def mount(self, staged_dir: PathLike, source_dir: PathLike) -> None:
        self._mounts.append((_key(staged_dir), _key(source_dir)))
        # Deepest first, so `.problems/A/` beats the chrome mounted at the root.
        # Stable, so among equals the first registered wins.
        self._mounts.sort(key=lambda mount: len(mount[0].parts), reverse=True)

    def alias(self, staged: PathLike, source: PathLike) -> None:
        self._aliases[_key(staged)] = _key(source)

    def source(self, path: PathLike) -> None:
        try:
            text = pathlib.Path(path).read_text()
        except (OSError, UnicodeDecodeError):
            return
        self._sources.setdefault(text, _key(path))

    def resolve(self, staged: PathLike) -> Optional[pathlib.Path]:
        key = _key(staged)
        if key in self._aliases:
            return self._aliases[key]
        if key.name.startswith(SCRATCH_PREFIX):
            try:
                return self._sources.get(key.read_text())
            except (OSError, UnicodeDecodeError):
                return None
        for staged_dir, source_dir in self._mounts:
            try:
                relative = key.relative_to(staged_dir)
            except ValueError:
                continue
            candidate = source_dir / relative
            if candidate.is_file():
                return candidate
        return None


class SourceTracker:
    """The source map of one statement build: tag ids, and the line origins of
    every file :meth:`emit` wrote."""

    def __init__(self, origins: Optional[Origins] = None) -> None:
        self.origins = origins or Origins()
        self._ids: Dict[Optional[pathlib.Path], int] = {}
        self._paths: List[Optional[pathlib.Path]] = []
        self._lines: Dict[pathlib.Path, List[Optional[SourcePos]]] = {}
        self._text: Dict[pathlib.Path, List[str]] = {}

    def intern(self, origin: Optional[pathlib.Path]) -> int:
        if origin not in self._ids:
            self._ids[origin] = len(self._paths)
            self._paths.append(origin)
        return self._ids[origin]

    def emit(self, path: PathLike, text: str) -> str:
        """Strip the tags from ``text``, which is about to be written to
        ``path``, remembering where each of its lines came from."""
        lines: List[str] = []
        positions: List[Optional[SourcePos]] = []
        current: Optional[SourcePos] = None
        for raw in text.split('\n'):
            tags = _TAG.findall(raw)
            if tags:
                origin_id, line = tags[-1]
                origin = self._paths[int(origin_id)]
                current = SourcePos(origin, int(line)) if origin is not None else None
            positions.append(current)
            lines.append(_TAG.sub('', raw))
        self._lines[_key(path)] = positions
        self._text[_key(path)] = lines
        return '\n'.join(lines)

    def find_excerpt(
        self, path: PathLike, line: int, before: str, after: str
    ) -> Optional[int]:
        """The line of an emitted file that holds a piece of text TeX printed,
        split at the point it stopped -- the nearest at or above ``line``, since
        TeX expands text after reading it.

        Matched without whitespace, which TeX re-spaces when it prints tokens
        (a control word is always shown followed by a space).

        The text before the stop usually spans many lines -- TeX prints up to
        a few hundred characters of the argument, and truncates the start with
        `...` -- so it is matched by its **longest suffix found on one line**:
        that suffix is the error line's own text up to the offending token.
        Any shorter suffix is found wherever a longer one is, so the longest is
        well defined. What follows the stop only breaks ties, by its longest
        prefix continuing the match on the same line: it may hold tokens TeX
        inserted itself (a `\\par` for a blank line) and never appear at all.
        """
        text = self._text.get(_key(path))
        if text is None:
            return None
        squashed = [_squash(raw) for raw in text]
        head, tail = _squash(before), _squash(after)

        def holding(needle: str, among: Iterable[int]) -> List[int]:
            return [i for i in among if needle in squashed[i]]

        everywhere = range(len(squashed))
        for size in range(len(head), _EXCERPT_MIN_CHARS - 1, -1):
            suffix = head[-size:]
            hits = holding(suffix, everywhere)
            if hits:
                break
        else:
            return None
        for size in range(len(tail), 0, -1):
            narrowed = holding(suffix + tail[:size], hits)
            if narrowed:
                hits = narrowed
                break
        above = [hit + 1 for hit in hits if hit + 1 <= line]
        return above[-1] if above else hits[0] + 1

    def locate(self, path: PathLike, line: int) -> Optional[SourcePos]:
        """The source position of ``line`` of a file pdflatex read.

        A file written through :meth:`emit` answers from its line map; one
        copied into the overlay verbatim (a setter's ``\\input``) is the same
        line of its origin; anything else (a system ``.sty``) is unknown."""
        key = _key(path)
        if key in self._lines:
            positions = self._lines[key]
            if not positions:
                return None
            return positions[min(max(line, 1), len(positions)) - 1]
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


def _squash(text: str) -> str:
    return _WHITESPACE.sub('', text)


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


class LineTagExtension(jinja2.ext.Extension):
    """Tags each content line of a template's literal text with its origin."""

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
        for token in stream:
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


def extensions() -> List[type]:
    """The Jinja extensions a statement render needs right now."""
    return [LineTagExtension] if current() is not None else []
