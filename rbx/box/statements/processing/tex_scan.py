r"""A minimal TeX scanner, for the places rbx reads TeX by position.

TexSoup is a structural parser, and the structure it builds is good enough to
*find* things. It is not good enough to reproduce them: printing a soup back is
not byte-identical (``\def\foo#1{...}`` comes back as ``\def\foo{#1}{...}``,
which TeX reads as something else entirely), its argument parser gives up on a
comment or an optional argument separated by spaces (``\newcommand{\x} % ...``
on one line and the body on the next), and it splits ``\icpcstrings@en`` into
``\icpcstrings`` plus the text ``@en``. So every edit rbx makes to a setter's
TeX is a splice at a position, and the extents it splices are read here, with
TeX's own rules: a control word is a run of letters, a comment runs to the end
of the line, braces balance, and an escaped brace does not count.

``@`` is read as a letter everywhere. That is TeX's rule inside a package and
after ``\makeatletter`` -- exactly where macro names carry one -- and in a
document it only matters to a control word immediately followed by ``@``,
which a statement does not write.

Sourcemap tags (:mod:`rbx.box.statements.sourcemap`) lead every content line of
a rendered block; they are skipped wherever blank space is.

A leaf module: the standard library only.
"""

import dataclasses
import re
from typing import List, Optional, Tuple

# `sourcemap.TAG_OPEN <id>:<line> sourcemap.TAG_CLOSE`, spelled out to keep this
# a leaf. Invisible to TeX: `sourcemap.emit` strips it before anything compiles.
TAG_RE = re.compile('\ue000\\d+:\\d+\ue001')

# Environments whose body TeX does not tokenize: nothing inside one is a command.
VERBATIM_ENVIRONMENTS = frozenset(
    {'verbatim', 'verbatim*', 'lstlisting', 'minted', 'spverbatim', 'comment'}
)


def is_letter(ch: str) -> bool:
    return ch == '@' or ('a' <= ch <= 'z') or ('A' <= ch <= 'Z')


def strip_tags(text: str) -> str:
    return TAG_RE.sub('', text)


def skip_comment(text: str, i: int) -> int:
    """``text[i]`` is ``%``: the index just past the end of its line."""
    end = text.find('\n', i)
    return len(text) if end < 0 else end + 1


def read_control_sequence(text: str, i: int) -> Tuple[str, int]:
    """``text[i]`` is a backslash: the control sequence's name and the index
    just past it. A control word is a run of letters; anything else is a
    one-character control symbol (``\\,``, ``\\\\``, ``\\{``)."""
    j = i + 1
    if j >= len(text):
        return '', j
    if not is_letter(text[j]):
        return text[j], j + 1
    while j < len(text) and is_letter(text[j]):
        j += 1
    return text[i + 1 : j], j


def skip_blanks(text: str, i: int, *, newlines: bool = True) -> int:
    """Skip spaces, comments and sourcemap tags. With ``newlines`` unset, stop
    at a line break (but still skip a comment, which eats its own)."""
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in ' \t' or (newlines and ch in '\r\n'):
            i += 1
        elif ch == '%':
            i = skip_comment(text, i)
        elif ch == '\ue000':
            match = TAG_RE.match(text, i)
            if match is None:
                return i
            i = match.end()
        else:
            return i
    return i


def read_group(text: str, i: int, open_ch: str = '{') -> Optional[int]:
    """``text[i]`` opens a group: the index just past its closing delimiter, or
    ``None`` when it never closes.

    ``open_ch`` is ``{`` or ``[``. A ``[...]`` group is TeX's optional argument:
    it ends at the first ``]`` outside braces, so ``[\\textbf{]}]`` is one
    group. Comments and escaped delimiters never count."""
    depth = 0
    j = i
    n = len(text)
    while j < n:
        ch = text[j]
        if ch == '\\':
            _, j = read_control_sequence(text, j)
            continue
        if ch == '%':
            j = skip_comment(text, j)
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if open_ch == '{' and depth == 0:
                return j + 1
            if depth < 0:
                return None
        elif open_ch == '[' and ch == ']' and depth == 0:
            return j + 1
        j += 1
    return None


def read_argument(text: str, i: int) -> Optional[Tuple[str, int, int]]:
    """Read one undelimited macro argument starting at ``i``, the way TeX does:
    blanks are skipped, then a braced group (its contents are the argument) or
    a single token.

    Returns ``(argument, start, end)``, ``start`` being where the argument's
    first character is (past any blanks), or ``None`` at the end of the text or
    on an unbalanced group. A paragraph break ends the search too: TeX would
    hand ``\\par`` to the macro, which no statement means."""
    j = skip_blanks(text, i, newlines=False)
    if j < len(text) and text[j] in '\r\n':
        k = j + 1
        k = skip_blanks(text, k, newlines=False)
        if k < len(text) and text[k] in '\r\n':
            return None
        j = k
    if j >= len(text):
        return None
    ch = text[j]
    if ch == '{':
        end = read_group(text, j)
        if end is None:
            return None
        return text[j + 1 : end - 1], j, end
    if ch == '\\':
        _, end = read_control_sequence(text, j)
        return text[j:end], j, end
    if ch == '}':
        return None
    return ch, j, j + 1


def skip_verb(text: str, i: int) -> int:
    """``i`` is just past ``\\verb`` (or ``\\verb*``): the index past its
    argument, delimited by the first character after it."""
    if i < len(text) and text[i] == '*':
        i += 1
    if i >= len(text):
        return i
    end = text.find(text[i], i + 1)
    newline = text.find('\n', i + 1)
    if end < 0 or (0 <= newline < end):
        return i + 1
    return end + 1


def read_environment_name(text: str, i: int) -> Optional[Tuple[str, int]]:
    """``i`` is just past ``\\begin`` or ``\\end``: the environment's name and
    the index past its ``{...}``."""
    j = skip_blanks(text, i)
    if j >= len(text) or text[j] != '{':
        return None
    end = read_group(text, j)
    if end is None:
        return None
    return text[j + 1 : end - 1].strip(), end


def find_environment_end(text: str, i: int, env: str) -> Optional[int]:
    """``i`` is anywhere inside an ``env`` environment's body: the index just
    past the ``\\end{env}`` closing it, counting nested ``env``s."""
    depth = 1
    j = i
    n = len(text)
    while j < n:
        ch = text[j]
        if ch == '%':
            j = skip_comment(text, j)
            continue
        if ch != '\\':
            j += 1
            continue
        name, k = read_control_sequence(text, j)
        if name == 'verb':
            j = skip_verb(text, k)
            continue
        if name in ('begin', 'end'):
            parsed = read_environment_name(text, k)
            if parsed is not None:
                inner, k = parsed
                if inner == env:
                    depth += 1 if name == 'begin' else -1
                    if depth == 0:
                        return k
                elif name == 'begin' and inner in VERBATIM_ENVIRONMENTS:
                    end = find_environment_end(text, k, inner)
                    k = n if end is None else end
        j = k
    return None


def skip_verbatim(text: str, name: str, i: int) -> Optional[int]:
    """When the control word ``name`` (ending just before ``i``) opens a region
    TeX does not tokenize, the index past it; otherwise ``None``."""
    if name == 'verb':
        return skip_verb(text, i)
    if name == 'begin':
        parsed = read_environment_name(text, i)
        if parsed is not None and parsed[0] in VERBATIM_ENVIRONMENTS:
            end = find_environment_end(text, parsed[1], parsed[0])
            return len(text) if end is None else end
    return None


# --- Definitions ---------------------------------------------------------------

# `\newcommand`-shaped: `{\name}` or `\name`, `[<n>]`, `[<default>]`, `{body}`.
NEWCOMMAND_LIKE = frozenset(
    {'newcommand', 'renewcommand', 'providecommand', 'DeclareRobustCommand'}
)
# `\def`-shaped: `\name`, a parameter text, `{body}`.
DEF_LIKE = frozenset({'def', 'gdef', 'edef', 'xdef'})
# `\newenvironment{name}[<n>][<default>]{begin}{end}`.
ENVIRONMENT_LIKE = frozenset({'newenvironment', 'renewenvironment'})

# Primitives that build a name rather than being one: `\expandafter\def\csname
# foo\endcsname{...}` defines `\foo`, which a static read cannot name.
_NOT_A_NAME = frozenset({'csname', 'expandafter', 'noexpand'})

# A parameter (`#1`, or `##1` one body deep); `\#` is a character, not one.
_PARAM_RE = re.compile(r'\\.|#+(\d)')


@dataclasses.dataclass(frozen=True)
class Definition:
    """One macro definition's extent in the text it was read from."""

    name: str
    n_args: int
    default: Optional[str]
    body_start: int  # the body's first character, past its `{`
    body_end: int  # the body's closing `}`

    def body(self, text: str) -> str:
        return text[self.body_start : self.body_end]


def _read_defined_name(text: str, i: int) -> Optional[Tuple[str, int]]:
    """The name a definition command defines, written ``{\\name}`` or
    ``\\name``, and the index past it."""
    j = skip_blanks(text, i)
    if j >= len(text):
        return None
    if text[j] == '{':
        end = read_group(text, j)
        if end is None:
            return None
        inner = strip_tags(text[j + 1 : end - 1]).strip()
        if not inner.startswith('\\'):
            return None
        name, k = read_control_sequence(inner, 0)
        if inner[k:].strip():
            return None
        return name, end
    if text[j] == '\\':
        return read_control_sequence(text, j)
    return None


def _read_signature(text: str, j: int) -> Optional[Tuple[int, Optional[str], int]]:
    """``[<n>][<default>]`` at ``j`` (both optional): the arity, the default
    and the index of what follows."""
    n_args = 0
    default: Optional[str] = None
    j = skip_blanks(text, j)
    if j < len(text) and text[j] == '[':
        end = read_group(text, j, '[')
        if end is None:
            return None
        try:
            n_args = int(strip_tags(text[j + 1 : end - 1]).strip())
        except ValueError:
            pass
        j = skip_blanks(text, end)
        if j < len(text) and text[j] == '[':
            end = read_group(text, j, '[')
            if end is None:
                return None
            default = text[j + 1 : end - 1]
            j = skip_blanks(text, end)
    return n_args, default, j


def parse_definition(text: str, command: str, i: int) -> Optional[Definition]:
    """The definition made by the control word ``command``, whose name ends
    just before ``i``; ``None`` when ``command`` defines nothing this module can
    read (or is not a definition command at all).

    For ``\\def`` the parameter text runs up to the body's opening brace, and
    its ``#<n>`` count is the arity (``##<n>`` inside another macro's body,
    where TeX doubles the parameter character)."""
    n = len(text)
    if command in NEWCOMMAND_LIKE:
        if i < n and text[i] == '*':
            i += 1
        named = _read_defined_name(text, i)
        if named is None:
            return None
        name, j = named
        signature = _read_signature(text, j)
        if signature is None:
            return None
        n_args, default, j = signature
    elif command in DEF_LIKE:
        j = skip_blanks(text, i)
        if j >= n or text[j] != '\\':
            return None
        name, j = read_control_sequence(text, j)
        k = j
        while k < n and text[k] != '{':
            if text[k] == '\\':
                _, k = read_control_sequence(text, k)
            elif text[k] == '%':
                k = skip_comment(text, k)
            elif text[k] == '}':
                return None
            else:
                k += 1
        n_args = len(set(filter(None, _PARAM_RE.findall(strip_tags(text[j:k])))))
        default = None
        j = k
    else:
        return None

    if not name or name in _NOT_A_NAME or j >= n or text[j] != '{':
        return None
    end = read_group(text, j)
    if end is None:
        return None
    return Definition(name, n_args, default, body_start=j + 1, body_end=end - 1)


def _environment_bodies(text: str, i: int) -> List[Tuple[int, int]]:
    """``i`` is just past ``\\newenvironment``: the spans of its begin and end
    code."""
    if i < len(text) and text[i] == '*':
        i += 1
    j = skip_blanks(text, i)
    if j >= len(text) or text[j] != '{':
        return []
    end = read_group(text, j)
    if end is None:
        return []
    signature = _read_signature(text, end)
    if signature is None:
        return []
    j = signature[2]
    spans: List[Tuple[int, int]] = []
    for _ in range(2):
        j = skip_blanks(text, j)
        if j >= len(text) or text[j] != '{':
            break
        end = read_group(text, j)
        if end is None:
            break
        spans.append((j + 1, end - 1))
        j = end
    return spans


def definition_bodies(text: str) -> List[Tuple[int, int]]:
    """The spans of every definition body in ``text``, nested ones included:
    what is inside one is drawn or typeset where the macro is used, not there."""
    spans: List[Tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '%':
            i = skip_comment(text, i)
            continue
        if ch != '\\':
            i += 1
            continue
        name, j = read_control_sequence(text, i)
        skipped = skip_verbatim(text, name, j)
        if skipped is not None:
            i = skipped
            continue
        if name in ENVIRONMENT_LIKE:
            spans.extend(_environment_bodies(text, j))
        else:
            definition = parse_definition(text, name, j)
            if definition is not None:
                spans.append((definition.body_start, definition.body_end))
        # Bodies are scanned too, so nested definitions are found.
        i = j
    return spans


def within(position: int, spans: List[Tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def verbatim_spans(text: str) -> List[Tuple[int, int]]:
    """The spans of ``text`` TeX does not tokenize: ``\\verb`` arguments and
    verbatim-like environments, delimiters included."""
    spans: List[Tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '%':
            i = skip_comment(text, i)
            continue
        if ch != '\\':
            i += 1
            continue
        name, j = read_control_sequence(text, i)
        skipped = skip_verbatim(text, name, j)
        if skipped is not None:
            spans.append((i, skipped))
            i = skipped
            continue
        i = j
    return spans


def find_begin_document(text: str) -> Optional[int]:
    """Where ``\\begin{document}`` starts in ``text``, outside comments."""
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '%':
            i = skip_comment(text, i)
            continue
        if ch != '\\':
            i += 1
            continue
        name, j = read_control_sequence(text, i)
        if name == 'begin':
            parsed = read_environment_name(text, j)
            if parsed is not None and parsed[0] == 'document':
                return i
        skipped = skip_verbatim(text, name, j)
        i = j if skipped is None else skipped
    return None
