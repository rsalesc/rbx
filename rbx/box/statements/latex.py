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


@dataclasses.dataclass(frozen=True)
class LatexError:
    """One error pdflatex reported, located in the file *it* read."""

    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    # The source text TeX was reading when it stopped: the macro argument it
    # was expanding when there was one, else its `l.<n>` line.
    context: Optional[str] = None
    # The macro argument the error happened in, split where TeX stopped. An
    # argument is often stored and expanded later (`\inputdesc{...}` in the
    # bundled preset), so `line` names where it was *expanded* -- often
    # `\end{document}` -- while this text is still the line that holds it.
    argument: Optional[Tuple[str, str]] = None


# `-file-line-error` turns every `! <message>` into `<file>:<line>: <message>`.
_LOCATED = re.compile(r'^((?:[A-Za-z]:)?[^:]+):(\d+): (.*)$')
_CONTEXT = re.compile(r'^l\.\d+ (.*)$')
_ARGUMENT = '<argument> '
_CONTEXT_LOOKAHEAD = 8


def _broken(lines: List[str], j: int, before: str) -> Tuple[str, str]:
    """TeX shows the text it was reading as `<before>` on one line and, on the
    next, `<after>` -- the point where it stopped is the line break."""
    after = lines[j + 1].strip() if j + 1 < len(lines) else ''
    return before.replace('^^M', ''), after.replace('^^M', '')


def _context_after(
    lines: List[str], index: int
) -> Tuple[Optional[str], Optional[Tuple[str, str]]]:
    """The `l.<n>` text, and the `<argument>` text when TeX shows one, from the
    few lines under an error."""
    argument = None
    for j in range(index + 1, min(index + 1 + _CONTEXT_LOOKAHEAD, len(lines))):
        if lines[j].startswith(_ARGUMENT) and argument is None:
            argument = _broken(lines, j, lines[j][len(_ARGUMENT) :])
            continue
        match = _CONTEXT.match(lines[j])
        if match is None:
            continue
        if argument is not None:
            text = (argument[0] + argument[1]).strip()
        else:
            text = ''.join(_broken(lines, j, match.group(1))).strip()
        return text or None, argument
    return None, argument


def parse_errors(log: str) -> List[LatexError]:
    """The errors in a pdflatex log produced with `-file-line-error`.

    Two shapes need care. An error raised while TeX prompts for a file (a
    missing package) prints as a bare `! LaTeX Error: ...`, and only the
    `Emergency stop.` that follows it carries a location -- which is handed to
    it. And the fatal-error trailer is noise, not another error.
    """
    errors: List[LatexError] = []
    lines = log.splitlines()
    for index, raw in enumerate(lines):
        if raw.startswith('! '):
            context, argument = _context_after(lines, index)
            errors.append(
                LatexError(raw[2:].strip(), context=context, argument=argument)
            )
            continue
        match = _LOCATED.match(raw)
        if match is None:
            continue
        file, line, message = match.group(1), int(match.group(2)), match.group(3)
        message = message.strip()
        if message.startswith('==>'):
            continue
        context, argument = _context_after(lines, index)
        if message == 'Emergency stop.' and errors:
            last = errors[-1]
            if last.file is None:
                errors[-1] = dataclasses.replace(
                    last,
                    file=file,
                    line=line,
                    context=last.context or context,
                    argument=last.argument or argument,
                )
            continue
        errors.append(LatexError(message, file, line, context, argument))
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
            str(temp_path),
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
