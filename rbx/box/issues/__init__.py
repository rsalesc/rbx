"""What the last run revealed.

`rbx summary` answers what a problem *is*; this answers what running it turned
up. Both questions were previously answerable only by reading a run scroll past,
because the accumulated issues lived in a contextvar stack that was rendered at
process exit and then lost.

Here they are derived instead: a registry of pure detectors over the artifacts
`.rbx/runs` already holds. Nothing new is written, so there is no staleness to
reason about and no second copy of the truth to drift -- and `rbx run`'s own
post-run section calls the same detectors on the same files, so it can never
word a finding differently from a later `rbx issues`.

Callers import from here, never from a submodule.

See docs/plans/2026-08-31-issues-view-design.md.
"""

from rbx.box.issues.config_detectors import CONFIG_DETECTORS, detect_all_config
from rbx.box.issues.config_state import ConfigState, collect_config_state
from rbx.box.issues.contest import build_report, collect_contest_rows
from rbx.box.issues.detectors import DETECTORS, detect_all
from rbx.box.issues.rendering import (
    IssuesFormat,
    contest_to_json,
    explain,
    print_contest_report,
    print_report,
    severity_marker,
    summarize,
    to_json,
)
from rbx.box.issues.run_state import (
    RunState,
    UnsupportedReportVersion,
    load_run_state,
)
from rbx.box.issues.schema import (
    ISSUES_FORMAT_VERSION,
    ContestIssueRow,
    Issue,
    IssueFamily,
    IssueReport,
    IssueSeverity,
)

__all__ = [
    'CONFIG_DETECTORS',
    'DETECTORS',
    'ISSUES_FORMAT_VERSION',
    'ConfigState',
    'ContestIssueRow',
    'Issue',
    'IssueFamily',
    'IssueReport',
    'IssueSeverity',
    'IssuesFormat',
    'RunState',
    'UnsupportedReportVersion',
    'build_report',
    'collect_config_state',
    'collect_contest_rows',
    'contest_to_json',
    'detect_all',
    'detect_all_config',
    'explain',
    'load_run_state',
    'print_contest_report',
    'print_report',
    'severity_marker',
    'summarize',
    'to_json',
]
