r"""The macro definitions TeX actually ran, read back from the demacro compile.

A static read of the sources cannot tell which of several definitions of a name
is the one in effect (#1007). A contest's ``icpclang.sty`` defines one string
table per language, each a macro whose body ``\def``\ s the strings, and runs
only the one the package option selects through
``\csname icpcstrings@\icpclang\endcsname``. Read statically, every table's
``\def\strOutputdescline`` is a definition, and the last one -- Spanish -- won,
so an English statement exported to MOJ shipped a Spanish sentence.

So the demacro compile (``render.compile_pdf(..., demacro=True)``) is asked:

1. The static pass (:mod:`rbx.box.statements.processing.demacro_utils`) still finds the
   *names*, and stays the fallback for anything TeX cannot answer.
2. :func:`inject_dump_hook` adds, right after ``\documentclass``, an
   ``\AtEndDocument`` hook that writes ``\meaning`` of each name to
   :data:`DUMP_FILE`, one per line. It writes nothing on the page, and only in
   the main job: TikZ externalization re-runs the document once per figure
   under another ``\jobname``, and those runs leave the file alone.
3. :func:`resolve` parses each ``macro:<parameters>-><body>`` and lets it
   override the static definition.

What ``\meaning`` prints is detokenized: every control word is followed by a
space (``\textbf {x}``), the parameter character of a nested definition is
doubled (``\def \inner ##1{##1}``), and comments are gone. :func:`_normalize`
drops the spaces TeX would skip anyway, so the body reads as the setter wrote
it. Indirections are followed one level: a ``\newcommand`` with an optional
argument is ``\@protected@testopt \foo \\foo {default}``, the real body being
``\\foo``'s; a ``\DeclareRobustCommand`` is ``\protect \foo␣``, the body being
the one of the macro named ``foo`` plus a space. Both are dumped on the TeX
side, so no second compile is needed.

A name TeX cannot answer for -- undefined when the document ends (typical of a
problem's ``defs`` block, which the template opens inside a group), or bound to
something other than a macro -- keeps its static definition. That is silent when
the static answer is unambiguous, and a warning when it is not: when the name
had several definitions in different scopes (#1007's option C), or when the one
picked sits in another macro's body or a package option's code, which may never
have run.
"""

import pathlib
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

from rbx import console
from rbx.box.statements.processing import tex_scan
from rbx.box.statements.processing.demacro_utils import (
    MacroDef,
    MacroDefinitions,
    collect_macro_definitions_from_text,
)

#: Written next to ``statement.tex`` by the main pdflatex job.
DUMP_FILE = 'macros.meaning'

_HEADER = 'RBX-MACRO-MEANINGS 1'
_FOOTER = 'RBX-MACRO-MEANINGS-END'

# The control sequences dumped for one name: the macro itself, then the inner
# macro an optional argument hides behind (`\\foo`), the one a robust command
# hides behind (`\foo␣`), and both at once (`\\foo␣`).
_OUTER = 'N'
_OPTIONAL = 'I'
_ROBUST = 'R'
_ROBUST_OPTIONAL = 'RI'
_KINDS = (_OUTER, _OPTIONAL, _ROBUST, _ROBUST_OPTIONAL)

# Names the hook can spell inside `\csname`: control words only.
_NAME_RE = re.compile(r'[A-Za-z@]+')

# The main job's name: `latex.Latex.build_pdf` compiles `statement.tex`.
_MAIN_JOB = 'statement'


def inject_dump_hook(tex: str, names: Iterable[str]) -> str:
    """``tex`` with the dump hook for ``names`` injected after ``\\documentclass``.

    The hook allocates its ``\\write`` stream only when the document ends, and
    only when one is free (TeX has 16), so a document that uses them all --
    whenever it allocates them -- compiles as before, just without a dump.
    One name per line: the list may be long, and TeX reads a line into a fixed
    buffer."""
    from rbx.box.statements.processing.texsoup_utils import inject_in_preamble_text

    calls = ''.join(
        f'\\rbx@dumpmeaning{{{name}}}%\n'
        for name in sorted(set(names))
        if _NAME_RE.fullmatch(name)
    )
    hook = (
        '\\makeatletter\n'
        '\\def\\rbx@dumpcs#1#2{\\ifcsname#2\\endcsname'
        '\\immediate\\write\\rbx@meaningdump'
        '{#1:\\expandafter\\meaning\\csname#2\\endcsname}\\fi}%\n'
        f'\\def\\rbx@dumpmeaning#1{{\\rbx@dumpcs{{{_OUTER}:#1}}{{#1}}%\n'
        f'\\rbx@dumpcs{{{_OPTIONAL}:#1}}{{\\@backslashchar#1}}%\n'
        f'\\rbx@dumpcs{{{_ROBUST}:#1}}{{#1\\space}}%\n'
        f'\\rbx@dumpcs{{{_ROBUST_OPTIONAL}:#1}}{{\\@backslashchar#1\\space}}}}%\n'
        '\\AtEndDocument{%\n'
        '\\edef\\rbx@thisjob{\\jobname}%\n'
        f'\\edef\\rbx@mainjob{{\\detokenize{{{_MAIN_JOB}}}}}%\n'
        '\\ifx\\rbx@thisjob\\rbx@mainjob\n'
        # `\count17` is the kernel's last allocated `\write`.
        '\\ifnum\\count17<15 %\n'
        '\\newwrite\\rbx@meaningdump\n'
        '\\begingroup\\newlinechar=-1 \\escapechar=92 %\n'
        f'\\immediate\\openout\\rbx@meaningdump={DUMP_FILE}\\relax\n'
        f'\\immediate\\write\\rbx@meaningdump{{{_HEADER}}}%\n'
        f'{calls}'
        f'\\immediate\\write\\rbx@meaningdump{{{_FOOTER}}}%\n'
        '\\immediate\\closeout\\rbx@meaningdump\n'
        '\\endgroup\n'
        '\\fi\n'
        '\\fi}%\n'
        '\\makeatother\n'
    )
    return inject_in_preamble_text(tex, hook)


# `^^xx` (a byte in hex) or `^^C` (a control character, C = byte + 64; `^^?`
# is 127): how TeX prints a byte it deems unprintable.
_HEX_ESCAPE_RE = re.compile(rb'\^\^([0-9a-f]{2}|[@-_?])')


def _unescape_byte(match: 're.Match[bytes]') -> bytes:
    code = match.group(1)
    if len(code) == 2:
        return bytes([int(code, 16)])
    return bytes([(code[0] + 64) % 128])


def read_dump(path: pathlib.Path) -> Optional[Dict[str, Dict[str, str]]]:
    """``{name: {kind: meaning}}`` from a dump file, or ``None`` when there is
    none or it is incomplete (the compile died before the end of the document).

    A name missing from the result was undefined when the document ended."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    # pdfTeX prints a byte it deems unprintable as `^^xx`; TeX Live's default
    # tables print UTF-8 as is, but not every installation does.
    raw = _HEX_ESCAPE_RE.sub(_unescape_byte, raw)
    lines = raw.decode('utf-8', errors='replace').split('\n')
    while lines and not lines[-1]:
        lines.pop()
    if not lines or lines[0] != _HEADER or lines[-1] != _FOOTER:
        return None

    dump: Dict[str, Dict[str, str]] = {}
    last: Optional[Tuple[str, str]] = None
    for line in lines[1:-1]:
        kind, sep, rest = line.partition(':')
        name, sep2, meaning = rest.partition(':')
        if sep and sep2 and kind in _KINDS and _NAME_RE.fullmatch(name):
            dump.setdefault(name, {})[kind] = meaning
            last = (name, kind)
        elif last is not None:
            # A body holding the `\newlinechar` character broke its line.
            dump[last[0]][last[1]] += '\n' + line
    return dump


_MEANING_RE = re.compile(
    r'(?P<prefixes>(?:\\(?:protected|long|outer) ?)*)macro:'
    r'(?P<params>(?:\[#1\])?(?:#[1-9])*)->(?P<body>.*)\Z',
    re.DOTALL,
)


def _normalize(meaning: str) -> str:
    r"""Undo ``\meaning``'s detokenization where TeX would not see a difference:
    the space it prints after every control word goes, unless a letter follows
    (``\textbf {x}`` -> ``\textbf{x}``, ``\foo bar`` stays)."""
    out: List[str] = []
    i = 0
    n = len(meaning)
    while i < n:
        ch = meaning[i]
        if ch != '\\':
            out.append(ch)
            i += 1
            continue
        name, j = tex_scan.read_control_sequence(meaning, i)
        out.append(meaning[i:j])
        is_word = len(name) > 0 and tex_scan.is_letter(name[0])
        if is_word and j < n and meaning[j] == ' ':
            if j + 1 < n and tex_scan.is_letter(meaning[j + 1]):
                out.append(' ')
            j += 1
        i = j
    return ''.join(out)


def _strip_braces(text: str) -> Optional[str]:
    text = text.strip()
    if not text.startswith('{'):
        return None
    end = tex_scan.read_group(text, 0)
    if end != len(text):
        return None
    return text[1:-1]


def _parse(meaning: Optional[str]) -> Optional[Tuple[str, str]]:
    """``(params, body)`` of a macro's meaning, or ``None`` for anything else
    (undefined, a primitive, a ``\\let`` to a non-macro, delimited parameters)."""
    if meaning is None:
        return None
    match = _MEANING_RE.match(meaning)
    if match is None:
        return None
    return match.group('params'), match.group('body')


def _unwrap_optional(body: str, name: str) -> Optional[str]:
    r"""The default of ``\@protected@testopt \name \\name {default}`` (or the
    older ``\@testopt \\name {default}``), when ``body`` is that."""
    escaped = re.escape(name)
    match = re.match(
        rf'\\@protected@testopt \\{escaped} +\\\\{escaped} +(?P<d>\{{.*\}}) *\Z'
        rf'|\\@testopt \\\\{escaped} +(?P<d2>\{{.*\}}) *\Z',
        body,
        re.DOTALL,
    )
    if match is None:
        return None
    return _strip_braces(match.group('d') or match.group('d2') or '')


def _is_robust_wrapper(body: str, name: str) -> bool:
    return re.fullmatch(rf'\\protect \\{re.escape(name)}  ', body) is not None


def macro_from_meaning(
    name: str, entries: Dict[str, str], source_file: Optional[str] = None
) -> Optional[MacroDef]:
    """The definition ``\\meaning`` reports for ``name``, or ``None`` when it is
    not one rbx can expand."""
    outer, optional = _OUTER, _OPTIONAL
    parsed = _parse(entries.get(outer))
    if parsed is not None and _is_robust_wrapper(parsed[1], name):
        outer, optional = _ROBUST, _ROBUST_OPTIONAL
        parsed = _parse(entries.get(outer))
    if parsed is None:
        return None
    params, body = parsed

    # Robust commands are `\foo␣`: the inner name carries the space.
    inner_name = name + ' ' if outer == _ROBUST else name
    default = _unwrap_optional(body, inner_name)
    if default is not None:
        inner = _parse(entries.get(optional))
        if inner is None or not inner[0].startswith('[#1]'):
            return None
        params, body = inner
    elif params.startswith('['):
        return None

    return MacroDef(
        name=name,
        n_args=params.count('#'),
        default=_normalize(default) if default is not None else None,
        body=_normalize(body),
        source_file=source_file,
    )


def _origin(macro: MacroDef) -> str:
    return pathlib.Path(macro.source_file).name if macro.source_file else 'unknown'


def _used_names(document: str) -> Set[str]:
    """The control words ``document`` uses outside definition bodies: what a
    wrong static definition could actually reach."""
    bodies = tex_scan.definition_bodies(document)
    used: Set[str] = set()
    i = 0
    n = len(document)
    while i < n:
        ch = document[i]
        if ch == '%':
            i = tex_scan.skip_comment(document, i)
            continue
        if ch != '\\':
            i += 1
            continue
        name, j = tex_scan.read_control_sequence(document, i)
        if not tex_scan.within(i, bodies):
            used.add(name)
        i = j
    return used


def body_definitions(
    document: str, base_dir: pathlib.Path, source_file: Optional[pathlib.Path] = None
) -> MacroDefinitions:
    """The names the body of ``document`` defines at its top level (directly or
    in a file it inputs there), outside any other macro's body.

    TeX's end-of-document meaning is no authority on these: the template runs
    the blocks inside a group, so a block's ``\\renewcommand{\\vec}`` is gone by
    the end and ``\\meaning`` reports the kernel's ``\\vec``. The definition the
    block text sees is the one written right there."""
    begin = tex_scan.find_begin_document(document)
    if begin is None:
        return MacroDefinitions()
    defined = collect_macro_definitions_from_text(
        document[begin:], base_dir=base_dir, source_file=source_file
    )
    return defined.select(lambda name: defined.nested_in(name) is None)


def resolve(
    static: MacroDefinitions,
    dump: Optional[Dict[str, Dict[str, str]]],
    document: Optional[str] = None,
    body: Optional[MacroDefinitions] = None,
) -> MacroDefinitions:
    """The definitions ``macros.json`` should hold: each name's run-time
    definition from ``dump`` where TeX gave one, its static one otherwise.

    Falling back is silent when the static answer is unambiguous: a name that
    is undefined when the document ends is, overwhelmingly, one the problem's
    ``defs`` block (or a file it inputs) defines inside the template's group,
    and that definition is right there in the source. It is a warning when the
    name had several definitions in different scopes, or when the one picked
    sits in another macro's body (or a package option's code), which may never
    have run -- and, given the compiled ``document``, only for names it uses:
    a package's internal helper going unread harms nothing.

    A name ``body`` defines (see :func:`body_definitions`) takes that
    definition, whatever TeX says."""
    body = body if body is not None else MacroDefinitions()
    resolved = MacroDefinitions()
    doubtful: List[str] = []
    used = _used_names(document) if document is not None else None
    for name in static:
        macro = static.get(name)
        assert macro is not None
        runtime = None
        written = body.get(name)
        if written is not None:
            resolved.add(written)
            continue
        if dump is not None and _NAME_RE.fullmatch(name):
            runtime = macro_from_meaning(name, dump.get(name, {}), macro.source_file)
        if runtime is not None:
            resolved.add(runtime)
            continue

        nested_in = static.nested_in(name)
        resolved.add(macro, nested_in=nested_in)
        conflicts = static.conflicts(name)
        if used is not None and name not in used:
            continue
        if conflicts:
            others = ', '.join(sorted({_origin(other) for other in conflicts}))
            picked = f', the one inside \\{nested_in}' if nested_in else ''
            doubtful.append(
                f'\\{name}: picked {_origin(macro)}{picked}; also defined '
                f'differently in {others}'
            )
        elif nested_in is not None:
            doubtful.append(
                f'\\{name}: defined inside \\{nested_in} ({_origin(macro)}), '
                'which may never have run'
            )

    if doubtful:
        why = (
            'TeX did not report the definitions in effect'
            if dump is None
            else 'TeX did not report a usable definition for them'
        )
        console.console.print(
            f'[warning]Exporting the static definitions of {len(doubtful)} '
            f'macro(s), which may not be the ones the PDF used ({why}):[/warning]'
        )
        for line in doubtful:
            console.console.print(f'[warning]  {line}[/warning]')
    return resolved
