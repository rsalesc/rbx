"""The run summary rbx publishes for other tools to read.

`rbx run` already decides every solution's verdict and score, in
`solutions.get_solution_outcome_report`, and then throws the answer away: the
report is rendered to the console and never persisted. Anything else that wants
to show a run -- the VS Code extension today -- has had to re-derive all of it
from the raw `.eval` artifacts, which means re-implementing outcome ranking,
expectation matching and dependency-gated scoring in another language, with
nothing to catch the two copies drifting apart.

This module is the on-disk form of that answer. See
docs/plans/2026-08-16-run-report-artifact-design.md.

Two deliberate constraints:

- **Structured, not rendered.** Enum values, seconds, bytes, integers. Turning
  `accepted` into `AC` or `0.008` into `8 ms` is the client's business, and a
  client with a different surface may reasonably render it differently.
- **Lean.** `SolutionOutcomeReport` embeds the solution, its limits and every
  evaluation. Those either already live on disk (`.eval` files) or are internal
  shape that must not harden into an external contract.
"""

import pathlib
from typing import Dict, Iterable, List, Optional, Set, Tuple, TypeVar

import yaml
from pydantic import BaseModel

from rbx.box.schema import ExpectedOutcome
from rbx.grading.steps import Evaluation, Outcome

# Bump when a change would make an older reader misread the file. A reader that
# meets a version it does not know must ignore the report rather than guess --
# showing a run without aggregates is recoverable, showing wrong verdicts is not.
#
# Adding an optional field is not such a change: an older reader drops what it
# does not know and reads everything else exactly as before. Bumping for it
# would instead make every existing reader ignore the whole file.
REPORT_VERSION = 1

REPORT_FILENAME = 'report.yml'

_T = TypeVar('_T', float, int)


class RunGroupReport(BaseModel):
    """How one testcase group fared, for one solution."""

    name: str
    # Worst verdict in the group. Absent when nothing in it has been evaluated,
    # which is what an in-flight or interrupted run looks like.
    outcome: Optional[Outcome] = None
    # Only set when the solution declares an `outcomePerGroup` covering it.
    expectedOutcome: Optional[ExpectedOutcome] = None
    matchesExpectation: bool = True
    score: int = 0
    maxScore: int = 0
    # Max, not sum or mean: the slowest testcase is the one judged against the
    # time limit, and the only one worth a glance.
    maxTime: Optional[float] = None  # seconds
    maxMemory: Optional[int] = None  # bytes
    # The double-TL facts for this group alone. See `RunSolutionReport` for what
    # they mean; they are published per group as well because the console names
    # the groups a warning came from, and a client with only the aggregate would
    # have to guess.
    runUnderDoubleTl: bool = False
    doubleTlVerdicts: List[Outcome] = []
    # The verdicts a soft TLE hid in this group that no expectation accepts.
    #
    # Under `-v4` a solution is judged at 2x its time limit and reported TLE the
    # moment it crosses 1x; the verdict it would have got is kept alongside, in
    # each evaluation's `no_tle_outcome`. A client showing per-testcase rows can
    # read that field itself, but it cannot tell which of those verdicts are
    # worth showing -- that needs `ExpectedOutcome.match` against both this
    # group's declaration and the solution's, and reimplementing that matcher is
    # exactly the drift this module exists to prevent.
    #
    # So rbx answers instead, and a client shows a testcase's `no_tle_outcome`
    # only when it appears here. ACCEPTED never does: a correct answer under a
    # soft TLE is the good case, already reported by `runUnderDoubleTl`.
    unexpectedNoTleVerdicts: List[Outcome] = []


class RunSolutionReport(BaseModel):
    path: str
    # Position in `skeleton.solutions`, which is also the directory name under
    # `.rbx/runs/`. Clients resolve artifact paths with it.
    index: int
    expectedOutcome: ExpectedOutcome
    outcome: Optional[Outcome] = None
    # `SolutionOutcomeStatus`, as its value.
    status: str
    # `status == OK`, hoisted out so a client need not learn the status values
    # to answer the only question most of them ask.
    matchesExpectation: bool = True
    # Whether the *pooled* `outcome` layer held on its own.
    #
    # Published apart from `matchesExpectation` because that one is the
    # aggregate of two independent layers, and a client that has only the
    # aggregate cannot tell which of them it is allowed to blame. A solution
    # declaring `outcome: incorrect` with an `outcomePerGroup` can fail only
    # the per-group layer while the pooled `incorrect` it names was in fact
    # met -- saying "expected INCORRECT, got WA" there accuses an expectation
    # that held. `get_verdict_markup` draws exactly this distinction for the
    # console, and had the only copy of it.
    pooledMatchesExpectation: bool = True
    score: int = 0
    maxScore: int = 0
    maxTime: Optional[float] = None
    maxMemory: Optional[int] = None
    failedGroups: List[str] = []
    # The `[min, max]` score range declared for this solution, when one was.
    # Without it a client meeting `status == UNEXPECTED_SCORE` knows a solution
    # is wrong but has nothing to say about how.
    expectedScore: Optional[Tuple[int, int]] = None
    # Whether a solution declared slow only timed out *within* double TL.
    #
    # Published because it is a warning about a run that otherwise passed:
    # `status` is OK and `matchesExpectation` is true, so a client reading only
    # those draws a clean row for a solution whose slowness the testset does not
    # actually prove. Under `-v4` (the default) rbx runs at 2x the time limit
    # and rewrites an over-TL run to TLE, so a solution declared TLE that fits
    # inside that doubled window is borderline, not decisively slow.
    #
    # `get_verdict_markup_with_warnings` prints exactly this, and had the only
    # copy of it.
    runUnderDoubleTl: bool = False
    # The verdicts a solution declared slow would have had *without* the time
    # limit -- it finished inside double TL, but wrongly.
    #
    # Independent of `runUnderDoubleTl` rather than an alternative to it: both
    # are unions over the pooled layer and every group, so two different groups
    # can each contribute one fact. Gating one on the other is how the second
    # was lost entirely (#607).
    #
    # A sorted list rather than a set: YAML has no set, and the console sorts
    # these for display anyway.
    doubleTlVerdicts: List[Outcome] = []
    groups: List[RunGroupReport] = []


class RunReport(BaseModel):
    version: int = REPORT_VERSION
    solutions: List[RunSolutionReport] = []


def _max_of(values: Iterable[Optional[_T]]) -> Optional[_T]:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _sorted_outcomes(outcomes: Iterable[Outcome]) -> List[Outcome]:
    """A set of verdicts, in the order the console prints them.

    Sorted by name rather than by badness: `get_verdict_markup_with_warnings`
    sorts these the same way, and a client showing them beside the console
    should not have to explain why the two orders differ.
    """
    return sorted(outcomes, key=lambda outcome: outcome.name)


def _no_tle_verdicts_in(evals: List[Evaluation]) -> Set[Outcome]:
    """The verdicts a soft TLE actually hid among these evaluations.

    The set a group is judged against comes from whichever expectation layer
    covers it, and the pooled layer covers the *whole solution*: without this
    intersection a group whose testcases all ran clean inherits a verdict hidden
    three groups away and claims it as its own. A client reading the group row
    would then say a testcase hid something when none of them did.
    """
    return {
        eval.result.no_tle_outcome
        for eval in evals
        if eval.result.no_tle_outcome is not None
    }


def _worst_outcome(evals: List[Evaluation]) -> Optional[Outcome]:
    # `Outcome.worst_outcome` is a `max`, so it raises on an empty iterable.
    if not evals:
        return None
    return Outcome.worst_outcome(eval.result.outcome for eval in evals)


def _evals_per_group(evals: List[Evaluation], skeleton) -> Dict[str, List[Evaluation]]:
    # Imported here rather than at module scope: `solutions` is a heavy module
    # and imports this one, so a top-level import would be circular.
    from rbx.box.solutions import _get_evals_per_group  # noqa: SLF001

    return _get_evals_per_group(evals, skeleton)


def build_solution_report(
    index: int,
    skeleton,
    report,
) -> RunSolutionReport:
    """Project the internal outcome report onto the published shape.

    Every decision here is *read off* `report`, never recomputed. The scores
    come from `gotScorePerGroup`, which has already applied the `_check_deps`
    dependency gate; the expectation results come from `perGroup`. Recomputing
    any of it would reintroduce exactly the divergence this module exists to
    remove.

    `report.perGroup` holds only the groups that carry an expectation *and*
    were evaluated, so the group list is driven by the skeleton instead -- a
    client needs a row per group either way.
    """
    evals_per_group = _evals_per_group(report.evals, skeleton)

    groups = []
    for group in skeleton.groups:
        group_evals = evals_per_group.get(group.name, [])
        per_group = report.perGroup.get(group.name)
        groups.append(
            RunGroupReport(
                name=group.name,
                outcome=_worst_outcome(group_evals),
                expectedOutcome=per_group.expectedOutcome if per_group else None,
                matchesExpectation=per_group.status.ok() if per_group else True,
                score=report.gotScorePerGroup.get(group.name, 0),
                maxScore=group.score,
                maxTime=_max_of(eval.log.time for eval in group_evals),
                maxMemory=_max_of(eval.log.memory for eval in group_evals),
                runUnderDoubleTl=per_group.runUnderDoubleTl if per_group else False,
                doubleTlVerdicts=_sorted_outcomes(
                    per_group.doubleTlVerdicts if per_group else set()
                ),
                unexpectedNoTleVerdicts=_sorted_outcomes(
                    _no_tle_verdicts_in(group_evals)
                    & (
                        per_group.unexpectedNoTleVerdicts
                        if per_group
                        else report.unexpectedNoTleVerdicts
                    )
                ),
            )
        )

    return RunSolutionReport(
        path=str(report.solution.path),
        index=index,
        expectedOutcome=report.expectedOutcome,
        # Worst verdict observed, not `report.gotVerdicts`: that set holds only
        # the verdicts that *offended* the expectation, so it is empty on a
        # solution that behaved exactly as declared.
        outcome=_worst_outcome(report.evals),
        status=report.status.value,
        matchesExpectation=report.status.ok(),
        pooledMatchesExpectation=report.pooledStatus.ok(),
        score=report.gotScore,
        maxScore=report.maxScore,
        maxTime=_max_of(eval.log.time for eval in report.evals),
        maxMemory=_max_of(eval.log.memory for eval in report.evals),
        failedGroups=report.failedGroups,
        expectedScore=report.expectedScore,
        runUnderDoubleTl=report.runUnderDoubleTl,
        doubleTlVerdicts=_sorted_outcomes(report.doubleTlVerdicts),
        groups=groups,
    )


def report_path(runs_dir: pathlib.Path) -> pathlib.Path:
    return runs_dir / REPORT_FILENAME


def write_report(path: pathlib.Path, report: RunReport) -> None:
    """Write the report as plain YAML.

    Not `utils.model_to_yaml`: that stamps a `$schema` header pointing at a
    published schema, and no schema is published for this model. It also drops
    unset fields, which would make a client's parsing depend on which defaults
    happened to be explicit at the call site.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            report.model_dump(mode='json', exclude_none=True),
            sort_keys=False,
            allow_unicode=True,
        )
    )


def clear_report(runs_dir: pathlib.Path) -> None:
    """Drop a previous run's report.

    Called when a new skeleton is written, which is what marks a new run.
    Without this, an interrupted run would leave the last run's verdicts on
    disk and a client could not tell a stale report from a current one.
    """
    report_path(runs_dir).unlink(missing_ok=True)


class RunReportWriter:
    """Accumulates solution reports, rewriting the file as each one lands.

    Rewritten whole rather than appended: the file is a few KB, and a reader
    that treats a missing or unparseable file as "no aggregates yet" tolerates
    being caught mid-write.
    """

    def __init__(self, runs_dir: pathlib.Path):
        self._path = report_path(runs_dir)
        self._report = RunReport()

    def add(self, entry: RunSolutionReport) -> None:
        self._report.solutions.append(entry)
        write_report(self._path, self._report)
