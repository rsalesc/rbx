"""The external command-line tools rbx shells out to, and how to explain a
missing one.

rbx depends on several binaries it does not ship -- pdflatex, pandoc, poppler --
and every call site used to have its own story for a missing one: an inline
``command_exists`` plus an ad-hoc console error, a silent no-op, or a bare
``OSError`` from deep inside a library. A setter hitting the third one learns
nothing about what to install.

An ``ExternalTool`` carries the explanation *with* the tool: what rbx needs it
for, and the command that installs it on the running platform. ``ensure()``
turns a missing binary into that message plus a clean ``typer.Exit``, and
``run()`` calls ``ensure()`` first so a ``FileNotFoundError`` can never escape
into the middle of a packaging run.
"""

import dataclasses
import subprocess
import sys
from typing import Any, Dict, List

import typer

from rbx import console
from rbx.utils import command_exists


@dataclasses.dataclass(frozen=True)
class ExternalTool:
    """One external binary rbx may invoke.

    ``probe_flags`` is what makes the availability check cheap and side-effect
    free (``pdflatex -v`` rather than a real compile). ``purpose`` and
    ``install_hints`` exist purely for the failure path: they are what turns
    "command not found" into something the setter can act on.

    Frozen, and the mutable fields are never mutated -- a registry entry is
    shared by every call site, so a mutation would leak across them.
    """

    name: str
    executable: str
    purpose: str
    probe_flags: List[str] = dataclasses.field(default_factory=list)
    install_hints: Dict[str, str] = dataclasses.field(default_factory=dict)

    def is_available(self) -> bool:
        """Whether the binary can be invoked. Use this for a genuinely optional
        tool; use ``ensure()`` when rbx cannot proceed without it."""
        return command_exists(self.executable, flags=list(self.probe_flags) or None)

    def ensure(self) -> None:
        """Return quietly when the tool is there, otherwise explain and exit.

        The hint is looked up by ``sys.platform``; an unknown platform still gets
        the name and the purpose, which is the part that cannot be guessed.
        """
        if self.is_available():
            return
        console.console.print(
            f'[error][item]{self.executable}[/item] not found, but rbx needs it '
            f'for {self.purpose}.[/error]'
        )
        hint = self.install_hints.get(sys.platform)
        if hint is not None:
            console.console.print(f'Install it with: [item]{hint}[/item]')
        else:
            console.console.print(
                f'Please install [item]{self.name}[/item] and try again.'
            )
        raise typer.Exit(1)

    def run(self, args: List[str], **kwargs: Any) -> 'subprocess.CompletedProcess':
        """Invoke the tool, after ``ensure()``.

        The ``ensure()`` is the whole point: without it a missing binary surfaces
        as a ``FileNotFoundError`` traceback from wherever rbx happened to be,
        instead of a message naming what to install.
        """
        self.ensure()
        return subprocess.run([self.executable, *args], **kwargs)


PDFLATEX = ExternalTool(
    name='TeX Live',
    executable='pdflatex',
    purpose='compiling statements to PDF',
    probe_flags=['-v'],
    install_hints={
        'darwin': 'brew install --cask mactex-no-gui',
        'linux': 'apt install texlive-full',
    },
)

TEXLIVEONFLY = ExternalTool(
    name='texliveonfly',
    executable='texliveonfly',
    purpose='installing missing TeX packages on demand',
    install_hints={
        'darwin': 'pip install texliveonfly',
        'linux': 'apt install texlive-extra-utils',
    },
)

PANDOC = ExternalTool(
    name='pandoc',
    executable='pandoc',
    purpose='converting statements between markup formats',
    probe_flags=['-v'],
    install_hints={
        'darwin': 'brew install pandoc',
        'linux': 'apt install pandoc',
    },
)

PDFTOPPM = ExternalTool(
    name='poppler',
    executable='pdftoppm',
    purpose='rasterizing PDF statement figures',
    probe_flags=['-v'],
    install_hints={
        'darwin': 'brew install poppler',
        'linux': 'apt install poppler-utils',
    },
)
