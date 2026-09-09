"""The on-disk state the detectors run over.

`rbx issues` is meant to be instant -- it computes nothing, it reads what the
last run already wrote. So this module reads the package cache and nothing else:
no package is loaded, no testcases are extracted, no sandbox is touched. Two
steps go past the two YAML files -- `size_stderr_artifacts`, which `stat()`s the
`.err` files already sitting in the runs dir, and `locate_sanitizer_logs`, which
looks for the sanitizer output beside it. Both live here rather than in the
detectors that need them so the detectors stay pure over the state they are
given.

That is also why it does not import `rbx.box.solutions` to parse `skeleton.yml`.
That module is thousands of lines and pulls in most of the box, and paying for
it would defeat the point of a command that only reads two YAML files. Instead
`SkeletonView` below picks out the handful of skeleton fields the detectors
actually need; Pydantic ignores the rest. `skeleton_view_test.py` pins the two
together so the narrow read cannot silently drift from the real model.
"""

import pathlib
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel

from rbx.box import run_report
from rbx.box.compilation_findings import SolutionCompilation
from rbx.box.sanitizers import warning_stack

SKELETON_FILENAME = 'skeleton.yml'

# Where the sanitizer logs sit, relative to the runs dir. Beside it rather than
# inside it because the run writes them through `warning_stack`, whose home is
# the package cache dir -- of which the runs dir is another child.
SANITIZER_LOGS_DIR = pathlib.Path('..') / warning_stack.WARNINGS_DIR_NAME

# Stderr artifacts that belong to something other than the solution. A
# communication run writes the interactor's stderr beside the solution's, and
# every run may keep the checker's; both end in `.err` and neither says anything
# about how noisy the *solution* is.
_NON_SOLUTION_STDERR_SUFFIXES = ('.checker.err', '.int.err')


class UnsupportedReportVersion(Exception):
    """The report on disk is newer than this rbx knows how to read.

    Raised rather than tolerated: `run_report` states the rule -- a reader that
    meets a version it does not know must ignore the report rather than guess --
    and for this command guessing would mean reporting verdicts that may not
    mean what they used to.
    """

    def __init__(self, found: int):
        super().__init__(
            f'The run report on disk is version {found}, but this rbx only '
            f'understands up to {run_report.REPORT_VERSION}. Upgrade rbx, or '
            f're-run to regenerate it.'
        )
        self.found = found


class SkeletonView(BaseModel):
    """The slice of `skeleton.yml` the detectors read.

    Deliberately narrow. Every field here has to keep meaning exactly what
    `solutions.SolutionReportSkeleton` means by it, so add to it only when a
    detector genuinely needs the field.
    """

    compilation: List[SolutionCompilation] = []


class StderrArtifact(BaseModel):
    """The largest stderr one solution's run wrote, and how large it was."""

    # Relative to the runs dir, e.g. `0/main/001.err`.
    path: pathlib.Path
    size: int  # bytes


class RunState(BaseModel):
    """One package's last run, as the detectors see it."""

    report: run_report.RunReport
    skeleton: SkeletonView
    runs_dir: pathlib.Path
    # The noisiest stderr artifact per solution index, when the solution wrote
    # one at all. Sized here rather than in the detector so the detectors stay
    # pure over the state they are handed -- see `size_stderr_artifacts`.
    stderr: Dict[int, StderrArtifact] = {}
    # The kept sanitizer output per solution path, for the solutions that have
    # one on disk. Located here rather than in the detector for the reason the
    # stderr sizes are -- see `locate_sanitizer_logs`.
    sanitizer_logs: Dict[str, pathlib.Path] = {}
    # `report.yml`'s mtime, as a POSIX timestamp. When the run happened, near
    # enough: the report is rewritten as each solution lands, so it is stamped
    # at the end of the run rather than the start.
    ran_at: float


def _load_yaml(path: pathlib.Path) -> Optional[dict]:
    """Parse a YAML mapping, or None when it is missing or unusable.

    A half-written or corrupt artifact reads as absent on purpose. The report is
    rewritten whole on every solution, so catching it mid-write is a real
    possibility, and "no run to show" is a far better answer to that than a
    traceback.
    """
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _is_solution_stderr(path: pathlib.Path) -> bool:
    name = path.name
    if not name.endswith('.err'):
        return False
    return not any(name.endswith(suffix) for suffix in _NON_SOLUTION_STDERR_SUFFIXES)


def size_stderr_artifacts(
    runs_dir: pathlib.Path, indices: List[int]
) -> Dict[int, StderrArtifact]:
    """The noisiest stderr each of `indices` wrote, by `stat()`-ing the runs dir.

    The one place `rbx issues` looks at the run beyond its two YAML files. It is
    done here, eagerly, rather than inside the detector: a detector that stats
    is a detector that needs a populated directory tree to test, which is
    exactly the coupling the detectors were pulled out of the issue stack to
    escape. The cost is a `stat()` per testcase artifact, which is the same
    order as reading the report itself.

    Only the indices the report names are walked, so a stale directory left by a
    longer previous run is never sized.
    """
    sizes: Dict[int, StderrArtifact] = {}
    for index in indices:
        solution_dir = runs_dir / str(index)
        if not solution_dir.is_dir():
            continue
        largest: Optional[StderrArtifact] = None
        for path in solution_dir.rglob('*.err'):
            if not _is_solution_stderr(path):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                # A run cleaned up underneath us reads as no artifact at all,
                # for the same reason a half-written report reads as no run.
                continue
            if largest is None or size > largest.size:
                largest = StderrArtifact(path=path.relative_to(runs_dir), size=size)
        if largest is not None:
            sizes[index] = largest
    return sizes


def locate_sanitizer_logs(
    runs_dir: pathlib.Path, paths: List[str]
) -> Dict[str, pathlib.Path]:
    """The kept sanitizer output for each of `paths` that still has one.

    `report.yml` records only *that* a sanitizer fired, so the log has to be
    found by name -- which `warning_stack.sanitizer_log_name` answers, so the
    reader cannot drift from the writer that put it there.

    Like `size_stderr_artifacts` this happens here, eagerly, rather than inside
    the detector: a detector that stats is a detector that needs a populated
    directory to test.

    Only the paths the caller names are looked up, and a missing log is simply
    absent -- `warning_stack` clears its directory at the start of every process
    that writes one, so a `rbx compile` between the run and the read leaves the
    report's flag standing with no file behind it.
    """
    logs: Dict[str, pathlib.Path] = {}
    for path in paths:
        relative = SANITIZER_LOGS_DIR / warning_stack.sanitizer_log_name(
            pathlib.Path(path)
        )
        if (runs_dir / relative).is_file():
            logs[path] = relative
    return logs


def load_run_state(runs_dir: pathlib.Path) -> Optional[RunState]:
    """The last run in `runs_dir`, or None when there was not one.

    None means "never run", which is a state worth reporting rather than an
    error: a problem nobody has run is exactly what a contest-wide view needs to
    call out.
    """
    report_data = _load_yaml(run_report.report_path(runs_dir))
    if report_data is None:
        return None

    version = report_data.get('version', run_report.REPORT_VERSION)
    if isinstance(version, int) and version > run_report.REPORT_VERSION:
        raise UnsupportedReportVersion(version)

    report = run_report.RunReport.model_validate(report_data)

    # The skeleton is optional in a way the report is not: it is written first,
    # so a report can never outlive it, but treating a missing one as fatal
    # would turn a partially cleaned `.rbx` into a crash. The detectors that
    # read it simply find nothing.
    skeleton_data = _load_yaml(runs_dir / SKELETON_FILENAME) or {}

    return RunState(
        report=report,
        skeleton=SkeletonView.model_validate(skeleton_data),
        runs_dir=runs_dir,
        stderr=size_stderr_artifacts(
            runs_dir, [solution.index for solution in report.solutions]
        ),
        sanitizer_logs=locate_sanitizer_logs(
            runs_dir,
            [
                solution.path
                for solution in report.solutions
                if solution.sanitizerWarnings
            ],
        ),
        ran_at=run_report.report_path(runs_dir).stat().st_mtime,
    )
