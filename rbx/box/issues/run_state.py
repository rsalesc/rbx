"""The on-disk state the detectors run over.

`rbx issues` is meant to be instant -- it computes nothing, it reads what the
last run already wrote. So this module reads `.rbx/runs` and nothing else: no
package is loaded, no testcases are extracted, no sandbox is touched.

That is also why it does not import `rbx.box.solutions` to parse `skeleton.yml`.
That module is thousands of lines and pulls in most of the box, and paying for
it would defeat the point of a command that only reads two YAML files. Instead
`SkeletonView` below picks out the handful of skeleton fields the detectors
actually need; Pydantic ignores the rest. `skeleton_view_test.py` pins the two
together so the narrow read cannot silently drift from the real model.
"""

import pathlib
from typing import List, Optional

import yaml
from pydantic import BaseModel

from rbx.box import run_report
from rbx.box.compilation_findings import SolutionCompilation

SKELETON_FILENAME = 'skeleton.yml'


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


class RunState(BaseModel):
    """One package's last run, as the detectors see it."""

    report: run_report.RunReport
    skeleton: SkeletonView
    runs_dir: pathlib.Path
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
        ran_at=run_report.report_path(runs_dir).stat().st_mtime,
    )
