import dataclasses
import os
import pathlib
import re
import subprocess
from typing import List, Optional, Tuple

import chardet
import typer

from rbx import tooling

MAX_PDFLATEX_RUNS = 3


def should_rerun(logs: str) -> bool:
    logs = logs.lower()
    for line in logs.splitlines():
        if 'rerun to get cross-references right' in line:
            return True
        if 'rerun' in line and 'warning' in line:
            return True
    return False


def decode_latex_output(output: bytes) -> str:
    # Latex output can be tricky with decoding
    encoding = chardet.detect(output)['encoding'] or 'utf-8'
    return output.decode(encoding)


Excerpt = Tuple[str, str]


@dataclasses.dataclass(frozen=True)
class LatexError:
    """One error pdflatex reported, located in the file *it* read."""

    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    # What TeX was reading when it stopped, as it printed it.
    context: Optional[str] = None
    # The text of every context level that can hold source text -- a macro
    # argument (`<argument>`), a macro body (`\foo #1->...`) -- innermost
    # first, each split where TeX stopped. A macro often stores its argument
    # and expands it later (`\inputdesc{...}`, `\includeProblem{..}{<body>}` in
    # the bundled preset), so `line` names where it was *expanded* -- often
    # `\end{document}` -- while these texts still say which line wrote it.
    excerpts: Tuple[Excerpt, ...] = ()
    # The `l.<n>` line TeX was reading, split the same way.
    reading: Optional[Excerpt] = None


# `-file-line-error` turns every `! <message>` into `<file>:<line>: <message>`.
_LOCATED = re.compile(r'^((?:[A-Za-z]:)?[^:]+):(\d+): (.*)$')
_READING = re.compile(r'^l\.\d+ (.*)$')
# A macro body level: `\name<parameter text>->`, the body after the arrow.
_MACRO_BODY = re.compile(r'^\\\S+.*?->(.*)$')
_ARGUMENT = '<argument> '
# The context of one error never runs this long; a bound, not a format rule.
_CONTEXT_LIMIT = 2000
# Not errors of their own: the trailers TeX prints after a fatal one.
_TRAILERS = ('Emergency stop.', '==>')


def _clean(text: str) -> str:
    return text.replace('^^M', '')


def _context_after(
    lines: List[str], index: int
) -> Tuple[Tuple[Excerpt, ...], Optional[Excerpt], int]:
    """The context levels under an error, down to its `l.<n>` line, and the
    index of the line after them.

    TeX prints each level as two lines: the text up to where it stopped, then,
    indented to that column, the rest. Levels that are TeX's own bookkeeping
    (`<inserted text>`, `<to be read again>`, ...) hold no source and are
    skipped. A level is printed verbatim, so a macro body may itself hold a
    line that starts with `! ` (LaTeX's own error macros do): only the next
    located error ends the context, never one of those."""
    excerpts: List[Excerpt] = []
    j = index + 1
    stop = min(len(lines), index + 1 + _CONTEXT_LIMIT)
    while j < stop:
        raw = lines[j]
        if _LOCATED.match(raw):
            break
        if not raw or raw[0].isspace() or raw.startswith('! '):
            j += 1
            continue
        has_after = j + 1 < len(lines) and lines[j + 1][:1].isspace()
        after = lines[j + 1].strip() if has_after else ''
        reading = _READING.match(raw)
        if reading is not None:
            end = j + 2 if has_after else j + 1
            return tuple(excerpts), (_clean(reading.group(1)), _clean(after)), end
        body = _MACRO_BODY.match(raw)
        if raw.startswith(_ARGUMENT):
            excerpts.append((_clean(raw[len(_ARGUMENT) :]), _clean(after)))
        elif body is not None:
            excerpts.append((_clean(body.group(1)), _clean(after)))
        j += 2 if has_after else 1
    return tuple(excerpts), None, j


def _joined(excerpt: Optional[Excerpt]) -> Optional[str]:
    """One excerpt as one line of text. The two halves are joined with a space:
    TeX drops the space after a control word where it breaks the line, and
    `\badcmd` + `here` must not read as `\badcmdhere`."""
    if excerpt is None:
        return None
    text = ' '.join(part.strip() for part in excerpt if part.strip())
    return text or None


def parse_errors(log: str) -> List[LatexError]:
    """The errors in a pdflatex log produced with `-file-line-error`.

    Two shapes need care. An error raised while TeX prompts for a file (a
    missing package) prints as a bare `! LaTeX Error: ...`, and only the
    `Emergency stop.` that follows it carries a location -- which is handed to
    it. And the fatal-error trailers are noise, not more errors.
    """
    errors: List[LatexError] = []
    lines = log.splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index]
        match = _LOCATED.match(raw)
        if raw.startswith('! '):
            file, line, message = None, None, raw[2:].strip()
        elif match is not None:
            file, line = match.group(1), int(match.group(2))
            message = match.group(3).strip()
        else:
            index += 1
            continue
        excerpts, reading, index = _context_after(lines, index)
        if message.startswith(_TRAILERS):
            last = errors[-1] if errors else None
            if last is not None and last.file is None and file is not None:
                errors[-1] = dataclasses.replace(
                    last,
                    file=file,
                    line=line,
                    excerpts=last.excerpts or excerpts,
                    reading=last.reading or reading,
                    context=last.context or _joined(reading),
                )
            if last is not None or not message.startswith('Emergency'):
                continue
        context = _joined(excerpts[0] if excerpts else reading)
        errors.append(LatexError(message, file, line, context, excerpts, reading))
    return list(dict.fromkeys(errors))


class LatexCompilationError(typer.Exit):
    """pdflatex failed; carries what it said, so a caller can say where."""

    def __init__(self, errors: List[LatexError], log: str, cwd: pathlib.Path):
        super().__init__(1)
        self.errors = errors
        self.log = log
        # Where pdflatex ran: the paths in `errors` are relative to it.
        self.cwd = cwd


@dataclasses.dataclass
class LatexResult:
    result: subprocess.CompletedProcess[bytes]
    pdf: Optional[bytes]


class Latex:
    def __init__(self, latex: str):
        self.latex = latex

    def build_pdf(self, temp_dir: pathlib.Path) -> LatexResult:
        tooling.PDFLATEX.ensure()

        temp_path = pathlib.Path('statement.tex')
        output_path = temp_path.with_suffix('.pdf')
        args = [
            'pdflatex',
            '-shell-escape',
            '-interaction',
            'nonstopmode',
            # `<file>:<line>: <message>` instead of a bare `! <message>`, so an
            # error can be traced back to its source (`parse_errors`).
            '-file-line-error',
            f'-jobname={temp_path.stem}',
            # Every context level, not only the innermost and outermost: the
            # source text of an error inside a stored macro argument is in a
            # level in between (see `LatexError.excerpts`).
            f'\\errorcontextlines=1000\\input{{{temp_path}}}',
        ]

        (temp_dir / temp_path).write_text(self.latex)

        completed = subprocess.run(
            args, capture_output=True, cwd=temp_dir, env=_unwrapped_log_env()
        )
        if completed.returncode != 0 or not (temp_dir / output_path).exists():
            return LatexResult(result=completed, pdf=None)

        return LatexResult(result=completed, pdf=(temp_dir / output_path).read_bytes())


def _unwrapped_log_env() -> dict:
    """TeX wraps its log at 79 columns by default, which splits long paths and
    messages across lines. TeX Live reads these from the environment."""
    return {
        **os.environ,
        'max_print_line': '10000',
        'error_line': '254',
        'half_error_line': '238',
    }


def install_tex_packages(path: pathlib.Path, cwd: pathlib.Path):
    # `is_available`, not `ensure`: texliveonfly is a best-effort convenience, and a
    # machine with a complete TeX Live install never needs it. Its absence is not an
    # error, so it stays a silent no-op.
    if not tooling.TEXLIVEONFLY.is_available():
        return
    subprocess.run(
        ['texliveonfly', path],
        cwd=cwd,
    )
