"""The stress session rbx publishes for other tools to read.

`rbx stress` used to keep its report in memory and leave only the bare inputs
of its findings on disk, so anything outside Python that wanted to show a stress
session -- the VS Code extension -- would have had to parse terminal output.
This module is the on-disk form of that session: a versioned manifest at
`.rbx/runs/.stress/stress.yml`, plus one directory per finding. See
docs/plans/2026-10-15-vscode-stress-design.md.

    .rbx/runs/.stress/
      stress.yml
      findings/<k>/input.in             # k from 1
      findings/<k>/input.ans            # the reference answer, when one was made
      findings/<k>/<sol>.out|.err|.eval # <sol> indexes `solutions`

A solution's artifacts in a finding are its *last* run in that iteration (a
finder can run one solution several times, against different checkers), while
its entry in `results` carries the *worst* outcome across all those runs.

Like `run_report.py`, it is a published contract:

- **Structured, never rendered.** Enum values, seconds, bytes, milliseconds.
- **Versioned.** Bump `STRESS_MANIFEST_VERSION` when a change would make an
  older reader misread the file. Readers ignore versions they do not know.
"""

import datetime
import enum
import pathlib
from typing import List, Optional

import yaml
from pydantic import BaseModel

from rbx import utils
from rbx.box import package
from rbx.box.schema import GeneratorCall
from rbx.grading.steps import Outcome

# Adding an optional field is not a reason to bump: an older reader drops what
# it does not know and reads everything else exactly as before.
STRESS_MANIFEST_VERSION = 1

MANIFEST_FILENAME = 'stress.yml'
FINDING_INPUT_FILENAME = 'input.in'
FINDING_ANSWER_FILENAME = 'input.ans'


class StressState(str, enum.Enum):
    RUNNING = 'running'
    DONE = 'done'
    INTERRUPTED = 'interrupted'
    FAILED = 'failed'


class StressSpec(BaseModel):
    """What the stress session was asked to do."""

    # The declared stress this session runs, if any.
    name: Optional[str]
    # The generator expression, unexpanded. Absent when fuzzing.
    generator: Optional[str]
    finder: str
    # The testgroups being fuzzed: `[]` means every group, `None` no fuzzing.
    fuzz: Optional[List[str]] = None
    slowest: bool = False
    timeout: int  # seconds
    findingsLimit: int
    # The effective time limit (ms) the solutions ran under, before any double
    # TL is applied; `None` when they ran unlimited (`--slowest`).
    timelimit: Optional[int] = None
    doubleTL: bool = False


class StressSolutionResult(BaseModel):
    """How one solution fared on a finding."""

    # Index into `StressManifest.solutions`; also the artifact file stem.
    solution: int
    # The worst outcome across every finder call on this solution.
    outcome: Outcome
    time: Optional[float] = None  # seconds
    memory: Optional[int] = None  # bytes


class StressFindingEntry(BaseModel):
    # From 1; also the directory name under `findings/`.
    index: int
    # The expanded call, with its seed: re-running it reproduces the input.
    generator: GeneratorCall
    duration: Optional[int] = None  # milliseconds
    # One per solution the finder expression evaluated.
    results: List[StressSolutionResult] = []


class StressManifest(BaseModel):
    version: int = STRESS_MANIFEST_VERSION
    state: StressState
    spec: StressSpec
    startedAt: datetime.datetime
    elapsed: float = 0  # seconds
    executed: int = 0
    skipped: int = 0
    # The solutions involved, in order; artifact file names use the index. It
    # includes the reference solution when the finder needs expected answers,
    # which then has artifacts in each finding but possibly no `results` entry.
    solutions: List[str]
    findings: List[StressFindingEntry] = []


def stress_dir() -> pathlib.Path:
    return package.get_problem_runs_dir() / '.stress'


def manifest_path() -> pathlib.Path:
    return stress_dir() / MANIFEST_FILENAME


def findings_dir() -> pathlib.Path:
    return stress_dir() / 'findings'


def finding_dir(index: int) -> pathlib.Path:
    return findings_dir() / str(index)


def finding_input_path(index: int) -> pathlib.Path:
    return finding_dir(index) / FINDING_INPUT_FILENAME


def finding_answer_path(index: int) -> pathlib.Path:
    return finding_dir(index) / FINDING_ANSWER_FILENAME


def write_manifest(
    manifest: StressManifest, path: Optional[pathlib.Path] = None
) -> None:
    """Write the manifest atomically.

    It is rewritten while the extension may be reading it, and a half-written
    file can still parse. `None` fields are kept: `fuzz: null` and `fuzz: []`
    mean different things.
    """
    utils.write_text_atomic(
        path or manifest_path(),
        yaml.safe_dump(
            manifest.model_dump(mode='json'),
            sort_keys=False,
            allow_unicode=True,
        ),
    )


def read_manifest(path: Optional[pathlib.Path] = None) -> Optional[StressManifest]:
    """The latest session's manifest, or `None` when there is no usable one."""
    path = path or manifest_path()
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            return None
        if data.get('version') != STRESS_MANIFEST_VERSION:
            return None
        return StressManifest.model_validate(data)
    except Exception:
        return None


# The manifest of the session this process started and has not finished yet.
_open_session: Optional[pathlib.Path] = None


def begin_session(path: pathlib.Path) -> None:
    global _open_session
    _open_session = path


def end_session() -> None:
    global _open_session
    _open_session = None


def finish_open_session(exit_status: str) -> None:
    """Stamp a session this process left `running` as over.

    Called from `rbx.box.main` on the way out of the process, as a backstop for
    whatever got past `run_stress`'s own bookkeeping (a second Ctrl-C, a hard
    abort). `exit_status` is a `run_report.ExitStatus` value: `interrupted`
    becomes `interrupted`, anything else `failed` -- a session still `running`
    at a clean exit did not finish properly either.

    Never raises: this runs on the way out of a process that may already be
    failing.
    """
    path = _open_session
    end_session()
    if path is None:
        return
    try:
        manifest = read_manifest(path)
        if manifest is None or manifest.state != StressState.RUNNING:
            return
        manifest.state = (
            StressState.INTERRUPTED
            if exit_status == 'interrupted'
            else StressState.FAILED
        )
        write_manifest(manifest, path)
    except Exception:
        return
