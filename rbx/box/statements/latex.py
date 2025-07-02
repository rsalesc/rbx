import dataclasses
import pathlib
import subprocess
from typing import Optional

import chardet

from rbx.utils import command_exists

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


@dataclasses.dataclass
class LatexResult:
    result: subprocess.CompletedProcess[bytes]
    pdf: Optional[bytes]


class Latex:
    def __init__(self, latex: str):
        self.latex = latex

    def build_pdf(self, temp_dir: pathlib.Path) -> LatexResult:
        temp_path = temp_dir / 'statement.tex'
        output_path = temp_path.with_suffix('.pdf')
        args = ['pdflatex', '-interaction', 'nonstopmode', str(temp_path)]
        temp_path.write_text(self.latex)

        completed = subprocess.run(args, timeout=15, capture_output=True, cwd=temp_dir)
        if completed.returncode != 0 or not output_path.exists():
            return LatexResult(result=completed, pdf=None)

        return LatexResult(result=completed, pdf=output_path.read_bytes())


def install_tex_packages(path: pathlib.Path, cwd: pathlib.Path):
    if not command_exists('texliveonfly'):
        return
    subprocess.run(
        ['texliveonfly', path],
        cwd=cwd,
    )
