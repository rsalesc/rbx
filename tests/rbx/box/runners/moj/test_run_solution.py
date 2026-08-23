"""`MojRunner.run_solution`: turning one testrun into one evaluation per testcase.

Nothing here touches the network. `FakeMoj` from `test_runner.py` -- the fake the
`prepare` tests already drive -- is extended with the two calls this half of the
runner makes, `cli.testrun` and `cli.testrun_status`, rather than replaced by a
second fake with its own conventions.

The judge these tests imitate is the one the **live probe** found
(`docs/plans/2026-08-21-moj-probe-notes.md`), not the one the design doc imagined.
In particular it returns its `tests` array in whatever order it pleases, because
the real one does: tests run in parallel across the park and come back as they
finish.
"""

import asyncio
import gc
import pathlib
import re
from typing import Dict, List, Optional, Tuple

import pytest

from rbx import utils
from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.runners.moj import cli
from rbx.box.runners.moj import runner as runner_module
from rbx.box.runners.moj.runner import MojRunner, MojRunnerError
from rbx.box.schema import ExpectedOutcome, Testcase
from rbx.box.testcase_schema import TestcaseEntry
from rbx.grading.steps import Outcome
from tests.rbx.box.packaging.moj.conftest import build_entries, minimal_package
from tests.rbx.box.runners.moj.test_runner import FakeMoj, _context

pytestmark = pytest.mark.shared_cache

# The names `MojPackager` gives the entries `build_entries` produces, spelled out
# rather than re-derived from the packager. Re-deriving them would make the
# pairing tests agree with whatever the naming happens to be, which is exactly
# what they exist to catch: these are what the *uploaded package* calls its files,
# and what the judge therefore reports back.
SAMPLE_NAMES = ('sample001', 'sample002')
MAIN_NAMES = ('t00_main_001', 't00_main_002')
BETA_NAMES = ('t00_beta_001', 't00_beta_002')


def subgrouped_entries(tmp_path: pathlib.Path) -> List[GenerationTestcaseEntry]:
    """Two samples, plus one `beta` group split into the subgroups `one` and `two`.

    Built by hand rather than through `build_entries`, and shaped to match
    `testcase_extractors._explore_subgroup` exactly, because the shape *is* the
    test: `group_entry` is `(top-level group, per-subgroup index)` and that index
    **restarts at 0 for each subgroup**, so `beta/one`'s first testcase and
    `beta/two`'s first testcase are both `beta/0`. Only `subgroup_entry` carries
    the full path that tells them apart.

    Every fixture in this file used to go through `build_entries`, which produces
    no subgroups at all -- which is precisely how a key that collides on every
    subgrouped problem got all the way through review.
    """
    entries = build_entries(tmp_path, ['samples'])
    group_dir = tmp_path / 'built' / 'beta'
    group_dir.mkdir(parents=True, exist_ok=True)

    for subgroup_index, subgroup in enumerate(['one', 'two'], start=1):
        # `_copied_to`'s naming: `<subgroup index>-<subgroup name>-<index>`.
        stem = f'{subgroup_index}-{subgroup}-000'
        input_path = group_dir / f'{stem}.in'
        output_path = group_dir / f'{stem}.out'
        input_path.write_text(f'beta {subgroup}\n')
        output_path.write_text('42\n')
        entries.append(
            GenerationTestcaseEntry(
                # The colliding half.
                group_entry=TestcaseEntry(group='beta', index=0),
                # The half that does not collide.
                subgroup_entry=TestcaseEntry(group=f'beta/{subgroup}', index=0),
                metadata=GenerationMetadata(
                    copied_to=Testcase(inputPath=input_path, outputPath=output_path)
                ),
            )
        )
    return entries


# Rich highlights numbers and parentheses in bold, so what lands on stdout carries
# escape codes the message does not. Assertions read the plain text.
_ANSI = re.compile(r'\x1b\[[0-9;]*m')


class RecordingProgress:
    """Just enough `StatusProgress` to see what the runner says, and when."""

    def __init__(self):
        self.updates: List[str] = []

    def update(self, text: str) -> None:
        self.updates.append(text)


class FakeJudge(FakeMoj):
    """`FakeMoj`, plus a judge that accepts testruns and answers about them.

    `results` is keyed by the **basename of the submitted file**, which is how the
    real server tells submissions apart too (`moj testrun` sends
    `filename: basename(sol)`).
    """

    def __init__(self, snapshots: pathlib.Path, **kwargs):
        super().__init__(snapshots, **kwargs)
        # solution filename -> the `tests` array to answer with, in the order the
        # judge chooses to report it.
        self.results: Dict[str, List[cli.TestrunTest]] = {}
        # solution filename -> the *whole* finished status to answer with, for the
        # shapes `results` cannot express: a run that failed as a whole and never
        # entered the testset carries a verdict and a `total_tests`, and those two
        # fields are the entire difference between "never ran" and "ran, reported
        # fewer". Takes precedence over `results` when set.
        self.statuses: Dict[str, cli.TestrunStatus] = {}
        # How many `testrun-status` calls a run answers `queued` to before it is
        # `done`. `None` never finishes -- the judge that died silently.
        self.polls_until_done: int = 1
        # When set, every `testrun-status` blocks on it. Holds runs in flight, so
        # the concurrency cap is observable.
        self.hold: Optional[asyncio.Event] = None

        self.submissions: List[Tuple[str, str, str, bytes]] = []
        self.status_calls: List[str] = []
        self.inflight = 0
        self.max_inflight = 0

    def install(self, monkeypatch: pytest.MonkeyPatch) -> 'FakeJudge':
        super().install(monkeypatch)
        monkeypatch.setattr(cli, 'testrun', self.testrun)
        monkeypatch.setattr(cli, 'testrun_status', self.testrun_status)
        return self

    async def testrun(self, ref, solution) -> str:
        path = pathlib.Path(solution)
        # A 32-character hex digest, which is what the probe saw four times out of
        # four -- not a number, which is what the design doc had assumed.
        run = f'{len(self.submissions):032x}'
        self.submissions.append((run, str(ref), path.name, path.read_bytes()))
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        return run

    async def testrun_status(self, run: str) -> cli.TestrunStatus:
        self.status_calls.append(run)
        if self.hold is not None:
            await self.hold.wait()
        polls = self.status_calls.count(run)
        if self.polls_until_done is None or polls < self.polls_until_done:
            # No `tests` key at all while queued, exactly as the probe saw.
            return cli.TestrunStatus(status='queued')
        self.inflight -= 1
        filename = self.filename_of(run)
        if filename in self.statuses:
            return self.statuses[filename]
        return cli.TestrunStatus(status='done', tests=self.results[filename])

    def filename_of(self, run: str) -> str:
        for submitted, _, filename, _ in self.submissions:
            if submitted == run:
                return filename
        raise AssertionError(f'no such run: {run}')


@pytest.fixture(autouse=True)
def _instant_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never really wait three seconds between polls."""
    monkeypatch.setattr(runner_module, 'CALIBRATION_POLL_INTERVAL_SECONDS', 0)
    monkeypatch.setattr(runner_module, 'TESTRUN_POLL_INTERVAL_SECONDS', 0)


def _test(name: str, code: str, time: Optional[float]) -> cli.TestrunTest:
    return cli.TestrunTest(name=name, code=code, time=time, tl=1.0)


async def _prepared(
    testing_pkg,
    tmp_path,
    monkeypatch,
    groups: Optional[List[str]] = None,
    solutions=None,
    entries: Optional[List[GenerationTestcaseEntry]] = None,
    progress: Optional[RecordingProgress] = None,
):
    """A runner that has already uploaded and calibrated, and its fake judge."""
    minimal_package(testing_pkg)
    # Every solution the run measures has to exist on disk: `run_solution`
    # amalgamates it before submitting, the same way the packager does for the one
    # it ships, because MOJ compiles a submission from a single file.
    for path, outcome in solutions or []:
        if path != 'sol.cpp':
            testing_pkg.add_solution(path, outcome=outcome).write_text('int main(){}\n')
    fake = FakeJudge(tmp_path / 'snapshots').install(monkeypatch)
    ctx = _context(
        tmp_path,
        entries=entries
        if entries is not None
        else build_entries(tmp_path, groups or ['samples', 'main']),
        solutions=solutions,
    )
    ctx.progress = progress
    runner = MojRunner()
    await runner.prepare(ctx)
    return runner, fake, ctx


async def _run(runner: MojRunner, ctx, solution_index: int = 0):
    """Run one solution to completion and return its evaluations, in entry order."""
    solution = ctx.skeleton.solutions[solution_index]
    deferreds = runner.run_solution(solution, ctx.skeleton.entries, ctx)
    return [await deferred() for deferred in deferreds]


# -- pairing, which is the whole point -----------------------------------------


async def test_results_are_paired_by_name_even_when_the_judge_shuffles_them(
    testing_pkg, tmp_path, monkeypatch
):
    """THE test. The real `tests` array is not ordered.

    An AC run in the live probe began `['t01_handmade_002', 'sample2',
    't01_handmade_001']` -- not lexicographic, not authored order -- because the
    park runs tests in parallel and returns them as they finish. Pairing by
    position would misattribute essentially every timing, and would do it
    silently: every number still looks like a plausible time for *some* test.

    So the judge here answers in an order that shares no position with the
    entries, and every testcase carries a distinct time and a distinct verdict.
    """
    runner, fake, ctx = await _prepared(testing_pkg, tmp_path, monkeypatch)
    fake.results['sol.cpp'] = [
        _test(MAIN_NAMES[1], 'TLE', 4.0),
        _test(SAMPLE_NAMES[1], 'WA', 2.0),
        _test(MAIN_NAMES[0], 'RE', 3.0),
        _test(SAMPLE_NAMES[0], 'AC', 1.0),
    ]

    evals = await _run(runner, ctx)

    # Entry order is samples[0], samples[1], main[0], main[1].
    assert [e.log.time for e in evals] == [1.0, 2.0, 3.0, 4.0]
    assert [e.result.outcome for e in evals] == [
        Outcome.ACCEPTED,
        Outcome.WRONG_ANSWER,
        Outcome.RUNTIME_ERROR,
        Outcome.TIME_LIMIT_EXCEEDED,
    ]


async def test_a_subgrouped_problem_prepares_at_all(testing_pkg, tmp_path, monkeypatch):
    """Two subgroups of one group both start at index 0. Keying on `group_entry`
    made them collide, and the duplicate guard then refused from inside
    `prepare()` -- so `rbx time --runner moj` was dead on arrival for every
    problem using subgroups, before a single byte was uploaded, with a message
    telling the setter it was an rbx bug and nothing to do about it.

    Reaching an upload at all is the assertion.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, entries=subgrouped_entries(tmp_path)
    )

    assert len(fake.uploads) == 1
    assert runner is not None


async def test_subgroups_of_one_group_are_paired_apart(
    testing_pkg, tmp_path, monkeypatch
):
    """And the two colliding entries get *their own* results, not each other's.

    `beta/one/0` and `beta/two/0` are both `beta/0` at the `group_entry` level, so
    a key that cannot tell them apart would either refuse (the bug as it was) or,
    if the duplicate guard were removed, hand both testcases one timing. The judge
    reports them out of order here, as it really does.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, entries=subgrouped_entries(tmp_path)
    )
    fake.results['sol.cpp'] = [
        _test(BETA_NAMES[1], 'TLE', 4.0),
        _test(SAMPLE_NAMES[0], 'AC', 1.0),
        _test(BETA_NAMES[0], 'WA', 3.0),
        _test(SAMPLE_NAMES[1], 'AC', 2.0),
    ]

    evals = await _run(runner, ctx)

    # Entry order is samples[0], samples[1], beta/one[0], beta/two[0].
    assert [e.log.time for e in evals] == [1.0, 2.0, 3.0, 4.0]
    assert [e.result.outcome for e in evals] == [
        Outcome.ACCEPTED,
        Outcome.ACCEPTED,
        Outcome.WRONG_ANSWER,
        Outcome.TIME_LIMIT_EXCEEDED,
    ]
    # Two distinct `.eval` artifacts, not one written twice: both entries report
    # `beta/0`, so the on-disk path has to come from the built input file.
    paths = {e.log.eval_absolute_path for e in evals}
    assert len(paths) == 4


async def test_every_observed_code_maps_to_the_matching_outcome(
    testing_pkg, tmp_path, monkeypatch
):
    """`AC` / `WA` / `RE` / `TLE` are the four codes a real testrun has produced."""
    runner, fake, ctx = await _prepared(testing_pkg, tmp_path, monkeypatch)
    names = [*SAMPLE_NAMES, *MAIN_NAMES]
    fake.results['sol.cpp'] = [
        _test(name, code, 0.5) for name, code in zip(names, ['AC', 'WA', 'RE', 'TLE'])
    ]

    evals = await _run(runner, ctx)

    assert [e.result.outcome for e in evals] == [
        Outcome.ACCEPTED,
        Outcome.WRONG_ANSWER,
        Outcome.RUNTIME_ERROR,
        Outcome.TIME_LIMIT_EXCEEDED,
    ]


async def test_a_tle_keeps_the_time_it_really_took(testing_pkg, tmp_path, monkeypatch):
    """MOJ reports a TLE's real time, not the limit: 2.81s against a 0.614s `tl`.

    How far over the cap a solution ran is exactly what phase 2 measures, so it
    must not be clamped on the way in.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.results['sol.cpp'] = [
        cli.TestrunTest(name=SAMPLE_NAMES[0], code='TLE', time=2.81, tl=0.614),
        _test(SAMPLE_NAMES[1], 'AC', 0.1),
    ]

    evals = await _run(runner, ctx)

    assert evals[0].log.time == 2.81


async def test_an_unknown_code_fails_loudly_and_names_it(
    testing_pkg, tmp_path, monkeypatch
):
    """`MLE`/`OLE`/`PE`/`CE`/`JE` were never provoked, so they are not mapped.

    A code guessed into a plausible `Outcome` corrupts the time-limit estimate
    with nothing in the report to say so -- an unmapped slow solution silently
    changes the number rbx writes into the limits profile. Refusing names the
    code, so the fix is a one-line table entry rather than an investigation.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.results['sol.cpp'] = [
        _test(SAMPLE_NAMES[0], 'AC', 0.1),
        _test(SAMPLE_NAMES[1], 'MLE', 0.2),
    ]

    with pytest.raises(MojRunnerError) as exc:
        await _run(runner, ctx)

    message = str(exc.value)
    assert 'MLE' in message
    assert '2026-08-21-moj-probe-notes' in message
    # Plain text: `main.py` bare-prints `str(e)`.
    assert '[item]' not in message and '[error]' not in message


async def test_an_unknown_code_fails_every_testcase_of_that_solution(
    testing_pkg, tmp_path, monkeypatch
):
    """Including the ones the judge did understand, and the ones before it.

    Checking codes per-slice instead would let the entries preceding the unknown
    one resolve into a report that looks complete and is missing a verdict.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.results['sol.cpp'] = [
        _test(SAMPLE_NAMES[0], 'AC', 0.1),
        _test(SAMPLE_NAMES[1], 'JE', 0.2),
    ]

    deferreds = runner.run_solution(
        ctx.skeleton.solutions[0], ctx.skeleton.entries, ctx
    )

    with pytest.raises(MojRunnerError):
        await deferreds[0]()


# -- what the judge did not say ------------------------------------------------


async def test_a_testcase_the_judge_never_reported_is_unmeasured_not_instant(
    testing_pkg, tmp_path, monkeypatch
):
    """A missing name must not read as a testcase that ran in no time at all.

    A probe package suppresses `STOPWHEN_*` so this should not happen, but the
    probe watched a failing run come back with 4 tests out of 72 against a problem
    that had them on, so it is a shape the judge really produces. The reported
    tests keep their real verdicts; the unreported one is SKIPPED with no timing,
    which is the one outcome that cannot be mistaken for a verdict about the
    solution and which never masks a real one.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.results['sol.cpp'] = [_test(SAMPLE_NAMES[0], 'WA', 0.7)]

    evals = await _run(runner, ctx)

    assert evals[0].result.outcome == Outcome.WRONG_ANSWER
    assert evals[0].log.time == 0.7
    assert evals[1].result.outcome == Outcome.SKIPPED
    assert evals[1].log.time is None
    # And the estimate is not built on a number nobody measured.
    assert evals[1].log.wall_time is None
    assert evals[1].log.memory is None


async def test_memory_and_artifacts_degrade_to_unmeasured_rather_than_zero(
    testing_pkg, tmp_path, monkeypatch
):
    """`RunnerCapabilities` says MOJ reports neither. The evaluations must agree.

    A 0 would read as a measurement, and an empty `.out` would claim the solution
    printed nothing. Only the `.eval` is written, which is the precedent
    `_record_skipped_evaluation` set; the log viewer renders the rest as
    "(does not exist)".
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.results['sol.cpp'] = [
        _test(SAMPLE_NAMES[0], 'AC', 0.1),
        _test(SAMPLE_NAMES[1], 'AC', 0.2),
    ]

    evals = await _run(runner, ctx)

    assert [e.log.memory for e in evals] == [None, None]
    assert [e.log.wall_time for e in evals] == [None, None]

    eval_path = evals[0].log.eval_absolute_path
    assert eval_path is not None and eval_path.is_file()
    for suffix in ('.out', '.err', '.log'):
        assert not eval_path.with_suffix(suffix).exists()
    # It says where the verdict came from: MOJ never hands back the checker's own
    # words, and an empty message would read as a checker that had nothing to say.
    assert 'MOJ' in evals[0].result.message


async def test_the_missing_testcase_warning_is_said_once_per_testrun(
    testing_pkg, tmp_path, monkeypatch, capsys
):
    """Once per solution, and from the consumer's own thread of control.

    It used to be printed by the background polling task, which owns nothing: the
    reporter has the console at that moment and is printing another solution's
    results. Emitting it where the report awaits the result puts it in the run's
    own output, in order -- and the `warned` flag is what keeps N deferreds over
    one testrun from saying it N times.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.results['sol.cpp'] = [_test(SAMPLE_NAMES[0], 'AC', 0.1)]

    deferreds = runner.run_solution(
        ctx.skeleton.solutions[0], ctx.skeleton.entries, ctx
    )
    # Nothing said while it is merely in flight.
    for _ in range(10):
        await asyncio.sleep(0)
    assert 'reported no result' not in capsys.readouterr().out

    for deferred in deferreds:
        await deferred()

    out = _ANSI.sub('', capsys.readouterr().out)
    assert out.count('reported no result') == 1
    assert '1 of 2 testcases of sol.cpp' in out


# -- a run that never ran at all -----------------------------------------------
#
# The first end-to-end `rbx time --runner moj` submitted solutions that did not
# build on the judge. Every one came back `{"status": "done", "verdict_canon":
# "Compilation Error", "correct": 0, "total_tests": 0, "tests": []}`, and rbx
# reported it as six testcases going unmeasured -- true, and no help at all to
# someone whose real problem was a compiler error they were never shown.


def _compile_error() -> cli.TestrunStatus:
    """The finished status the live end-to-end run actually received."""
    return cli.TestrunStatus(
        status='done',
        verdict='Compilation Error',
        verdict_canon='Compilation Error',
        correct=0,
        total_tests=0,
        tests=[],
    )


async def test_a_compile_error_names_the_verdict_and_the_report_command(
    testing_pkg, tmp_path, monkeypatch
):
    """The two things the setter needs: what happened, and how to read the log.

    Naming the verdict is what turns "6 of 6 testcases unmeasured" into "it did
    not compile"; quoting `moj testrun-status <run> --report ...` with the real
    run id in it is what turns that into a fix, because the compiler's own output
    lives in that report and nowhere rbx can reach.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.statuses['sol.cpp'] = _compile_error()

    with pytest.raises(MojRunnerError) as exc:
        await _run(runner, ctx)

    message = str(exc.value)
    assert 'Compilation Error' in message
    # The real run id, not a placeholder: it is a 32-character digest nobody is
    # going to reconstruct from memory.
    run = fake.submissions[0][0]
    assert f'moj testrun-status {run} --report' in message
    assert 'did not build on the judge' in message
    # Plain text: `main.py` bare-prints `str(e)`.
    assert '[item]' not in message and '[error]' not in message


async def test_a_compile_error_is_not_reported_as_unmeasured_testcases(
    testing_pkg, tmp_path, monkeypatch, capsys
):
    """The old message must not survive alongside the new one.

    "MOJ reported no result for 2 of 2 testcases" is what this run used to say,
    and it is a description of the symptom that quietly implies the cause is
    somewhere in the testset. Nothing about the testcases was wrong.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.statuses['sol.cpp'] = _compile_error()

    with pytest.raises(MojRunnerError):
        await _run(runner, ctx)

    assert 'reported no result' not in _ANSI.sub('', capsys.readouterr().out)


async def test_a_compile_error_fails_every_testcase_of_that_solution(
    testing_pkg, tmp_path, monkeypatch
):
    """Not one `SKIPPED` evaluation is produced, and the first deferred already
    raises.

    Degrading per testcase would hand the estimator a solution whose every
    testcase is "unmeasured" -- a shape it is entitled to carry on from, since
    that is exactly what a legitimately truncated run looks like. The estimate
    would then be built from fewer solutions than the setter asked for, with
    nothing in the report saying which ones dropped out. The run that found this
    bug did stop in the end, but on `Failed to run ACCEPTED solutions`, which is
    an accident of that package's expectations rather than a decision.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.statuses['sol.cpp'] = _compile_error()

    deferreds = runner.run_solution(
        ctx.skeleton.solutions[0], ctx.skeleton.entries, ctx
    )

    for deferred in deferreds:
        with pytest.raises(MojRunnerError):
            await deferred()


async def test_a_run_level_failure_with_no_verdict_at_all_still_says_so(
    testing_pkg, tmp_path, monkeypatch
):
    """`verdict_canon` is not guaranteed -- an older server has only `verdict`,
    and a run can carry neither.

    The failure is detected from the shape of the response, not from the verdict
    vocabulary (only five spellings of which have ever been seen), so a nameless
    one is still refused. It just cannot say what to call it.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.statuses['sol.cpp'] = cli.TestrunStatus(status='done', total_tests=0, tests=[])

    with pytest.raises(MojRunnerError) as exc:
        await _run(runner, ctx)

    message = str(exc.value)
    assert 'without running a single testcase' in message
    assert f'moj testrun-status {fake.submissions[0][0]} --report' in message


async def test_a_truncated_run_with_no_entries_still_degrades_per_testcase(
    testing_pkg, tmp_path, monkeypatch, capsys
):
    """THE discriminator test. Zero entries is not the same as never having run.

    `STOPWHEN_*` breaks out of the judge's loop at the first bad verdict, and the
    probe watched that return 4 tests out of 72. A problem whose *first* test
    fails can return none at all -- and that is still a run that entered the
    testset, which `total_tests` reports as 72 either way. Keying the new failure
    on `len(tests) == 0` would call this a build failure and refuse, replacing one
    wrong diagnosis with another.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.statuses['sol.cpp'] = cli.TestrunStatus(
        status='done',
        verdict='Wrong Answer,0p',
        verdict_canon='Wrong Answer',
        correct=0,
        # The judge set out to run both, and said so.
        total_tests=2,
        tests=[],
    )

    evals = await _run(runner, ctx)

    assert [e.result.outcome for e in evals] == [Outcome.SKIPPED, Outcome.SKIPPED]
    assert [e.log.time for e in evals] == [None, None]
    out = _ANSI.sub('', capsys.readouterr().out)
    assert '2 of 2 testcases of sol.cpp' in out


async def test_the_background_polling_never_writes_the_status_line(
    testing_pkg, tmp_path, monkeypatch
):
    """Up to `MAX_INFLIGHT_TESTRUNS` tasks poll at once, on their own schedule.

    They share the `StatusProgress` the reporter is driving, so a poll writing to
    it makes the status line flip between two solutions -- and keep flipping after
    the reporter has moved on to printing the first one's results.

    This is about the *console*, and stays true now that polls report themselves
    on the board: a board write lands in the polled solution's own slot, and the
    reporter draws only the slot it is blocked on, so nothing a non-awaited task
    learns can reach the display. See
    `test_a_poll_writes_to_its_own_slot_and_no_other` for that half.
    """
    progress = RecordingProgress()
    runner, fake, ctx = await _prepared(
        testing_pkg,
        tmp_path,
        monkeypatch,
        groups=['samples'],
        solutions=[
            ('sol.cpp', ExpectedOutcome.ACCEPTED),
            ('other.cpp', ExpectedOutcome.WRONG_ANSWER),
        ],
        progress=progress,
    )
    for filename in ('sol.cpp', 'other.cpp'):
        fake.results[filename] = [
            _test(SAMPLE_NAMES[0], 'AC', 0.1),
            _test(SAMPLE_NAMES[1], 'AC', 0.2),
        ]
    fake.polls_until_done = 5

    first = runner.run_solution(ctx.skeleton.solutions[0], ctx.skeleton.entries, ctx)
    runner.run_solution(ctx.skeleton.solutions[1], ctx.skeleton.entries, ctx)

    await _gather(first)

    # While the report was waiting on `sol.cpp`, `other.cpp` was being polled
    # throughout -- and never got a word in.
    assert progress.updates
    assert not any('other.cpp' in update for update in progress.updates)


# -- the bounded wait ----------------------------------------------------------


async def test_a_testrun_that_never_finishes_stops_instead_of_hanging(
    testing_pkg, tmp_path, monkeypatch
):
    """No terminal failure status was ever observed, so "not done" is forever."""
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    monkeypatch.setattr(runner_module, 'TESTRUN_POLL_ATTEMPTS', 4)
    fake.polls_until_done = None

    with pytest.raises(MojRunnerError) as exc:
        await _run(runner, ctx)

    assert len(fake.status_calls) == 4
    # Says how to look at it, and that nothing on the server needs cleaning up.
    assert 'testrun-status' in str(exc.value)


async def test_a_testrun_that_finishes_late_is_still_waited_for(
    testing_pkg, tmp_path, monkeypatch
):
    """The bound must not degenerate into "poll once and give up"."""
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    monkeypatch.setattr(runner_module, 'TESTRUN_POLL_ATTEMPTS', 4)
    fake.polls_until_done = 3
    fake.results['sol.cpp'] = [
        _test(SAMPLE_NAMES[0], 'AC', 0.1),
        _test(SAMPLE_NAMES[1], 'AC', 0.2),
    ]

    evals = await _run(runner, ctx)

    assert len(fake.status_calls) == 3
    assert [e.result.outcome for e in evals] == [Outcome.ACCEPTED] * len(evals)


# -- how the work is dispatched ------------------------------------------------


async def test_the_whole_testset_is_one_submission(testing_pkg, tmp_path, monkeypatch):
    """One solution is one testrun, however many testcases it has.

    `Deferred` memoizes each deferred's *own* result and nothing else, so N
    deferreds over one submission is only true if the runner holds the job.
    """
    runner, fake, ctx = await _prepared(testing_pkg, tmp_path, monkeypatch)
    fake.results['sol.cpp'] = [
        _test(name, 'AC', 0.1) for name in (*SAMPLE_NAMES, *MAIN_NAMES)
    ]

    evals = await _run(runner, ctx)

    assert len(evals) == 4
    assert len(fake.submissions) == 1


async def test_the_first_testrun_starts_before_any_deferred_is_awaited(
    testing_pkg, tmp_path, monkeypatch
):
    """Why the submission is a background task rather than a lazy coroutine.

    `_produce_solution_items` builds every solution's deferreds synchronously,
    before a single one resolves. If `run_solution` submitted lazily, nothing would
    reach the judge until the report began consuming, and the judge would sit idle
    through the build and the report's own setup.

    With `MAX_INFLIGHT_TESTRUNS = 1` the second solution deliberately waits its
    turn -- see the next test for what still has to be true of it.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg,
        tmp_path,
        monkeypatch,
        groups=['samples'],
        solutions=[
            ('sol.cpp', ExpectedOutcome.ACCEPTED),
            ('other.cpp', ExpectedOutcome.WRONG_ANSWER),
        ],
    )
    for filename in ('sol.cpp', 'other.cpp'):
        fake.results[filename] = [
            _test(SAMPLE_NAMES[0], 'AC', 0.1),
            _test(SAMPLE_NAMES[1], 'AC', 0.2),
        ]
    fake.hold = asyncio.Event()

    first = runner.run_solution(ctx.skeleton.solutions[0], ctx.skeleton.entries, ctx)
    second = runner.run_solution(ctx.skeleton.solutions[1], ctx.skeleton.entries, ctx)

    # Not one call has been awaited yet: `run_solution` must not block.
    assert fake.submissions == []
    assert [deferred.peek() for deferred in first] == [None, None]

    for _ in range(10):
        await asyncio.sleep(0)

    # The first is on the judge with nothing awaited; the second holds behind the
    # cap rather than adding to the account's queue.
    assert [filename for _, _, filename, _ in fake.submissions] == ['sol.cpp']
    assert [deferred.peek() for deferred in second] == [None, None]

    fake.hold.set()
    assert len(await _gather(first)) == 2
    assert len(await _gather(second)) == 2


async def test_the_next_testrun_starts_without_the_report_consuming_the_previous(
    testing_pkg, tmp_path, monkeypatch
):
    """What the cap does *not* cost.

    Serialising testruns would be much worse if the next one only left once the
    report had rendered the last: every gap would carry the report's own work. The
    queue is the runner's, so the moment one testrun finishes the next is
    dispatched, whether or not anybody has looked at the result yet.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg,
        tmp_path,
        monkeypatch,
        groups=['samples'],
        solutions=[
            ('sol.cpp', ExpectedOutcome.ACCEPTED),
            ('other.cpp', ExpectedOutcome.WRONG_ANSWER),
        ],
    )
    for filename in ('sol.cpp', 'other.cpp'):
        fake.results[filename] = [
            _test(SAMPLE_NAMES[0], 'AC', 0.1),
            _test(SAMPLE_NAMES[1], 'AC', 0.2),
        ]

    first = runner.run_solution(ctx.skeleton.solutions[0], ctx.skeleton.entries, ctx)
    runner.run_solution(ctx.skeleton.solutions[1], ctx.skeleton.entries, ctx)

    for _ in range(30):
        await asyncio.sleep(0)

    # Both have been to the judge, and `first`'s deferreds were never awaited, so
    # the second did not wait on the report.
    assert [filename for _, _, filename, _ in fake.submissions] == [
        'sol.cpp',
        'other.cpp',
    ]
    assert [deferred.peek() for deferred in first] == [None, None]


async def test_no_more_testruns_are_in_flight_than_the_cap_allows(
    testing_pkg, tmp_path, monkeypatch
):
    """Asserted against the cap itself, so it survives the cap changing.

    The park is shared -- two judges, and everyone else's submissions -- so a
    session that dispatched every solution at once would be a denial of service on
    the park it is measuring, and would measure a park it had itself made slow.
    MOJ enforces its own limit too, refusing with 429 past a few queued per
    account.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg,
        tmp_path,
        monkeypatch,
        groups=['samples'],
        solutions=[
            ('sol.cpp', ExpectedOutcome.ACCEPTED),
            ('other.cpp', ExpectedOutcome.WRONG_ANSWER),
            ('third.cpp', ExpectedOutcome.WRONG_ANSWER),
        ],
    )
    for filename in ('sol.cpp', 'other.cpp', 'third.cpp'):
        fake.results[filename] = [
            _test(SAMPLE_NAMES[0], 'AC', 0.1),
            _test(SAMPLE_NAMES[1], 'AC', 0.2),
        ]
    fake.hold = asyncio.Event()

    batches = [
        runner.run_solution(solution, ctx.skeleton.entries, ctx)
        for solution in ctx.skeleton.solutions
    ]

    for _ in range(20):
        await asyncio.sleep(0)
    # The third solution has not been dispatched at all: its slot is taken.
    assert len(fake.submissions) == runner_module.MAX_INFLIGHT_TESTRUNS
    assert fake.max_inflight == runner_module.MAX_INFLIGHT_TESTRUNS

    fake.hold.set()
    for batch in batches:
        assert len(await _gather(batch)) == 2
    # And the third one really did run once a slot came free.
    assert len(fake.submissions) == 3
    assert fake.max_inflight == runner_module.MAX_INFLIGHT_TESTRUNS


async def test_a_solution_nobody_waits_for_does_not_haunt_the_run_later(
    testing_pkg, tmp_path, monkeypatch
):
    """Every solution is dispatched up front; the report stops at the first failure.

    So solutions 2..N can end up with a task nobody ever awaits. A failed task
    whose exception was never retrieved prints its traceback out of the garbage
    collector, long after, attached to nothing the setter did -- and retrieving it
    must not swallow it either, or the deferred that *does* get awaited would
    silently succeed.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg,
        tmp_path,
        monkeypatch,
        groups=['samples'],
        solutions=[
            ('sol.cpp', ExpectedOutcome.ACCEPTED),
            ('other.cpp', ExpectedOutcome.WRONG_ANSWER),
        ],
    )
    fake.results['sol.cpp'] = [
        _test(SAMPLE_NAMES[0], 'AC', 0.1),
        _test(SAMPLE_NAMES[1], 'AC', 0.2),
    ]
    # The abandoned one fails, which is the case that leaves a trace.
    fake.results['other.cpp'] = [_test(SAMPLE_NAMES[0], 'MLE', 0.1)]

    first = runner.run_solution(ctx.skeleton.solutions[0], ctx.skeleton.entries, ctx)
    abandoned = runner.run_solution(
        ctx.skeleton.solutions[1], ctx.skeleton.entries, ctx
    )

    # Only the first solution's results are ever consumed.
    await _gather(first)
    for _ in range(20):
        await asyncio.sleep(0)

    job = runner._jobs[1]  # noqa: SLF001
    assert job.done()
    # Retrieved, so nothing surfaces later...
    assert isinstance(job.exception(), MojRunnerError)
    # ...and still raised for anyone who does come asking.
    with pytest.raises(MojRunnerError):
        await abandoned[0]()


async def test_an_abandoned_failure_is_not_reported_out_of_the_garbage_collector(
    testing_pkg, tmp_path, monkeypatch
):
    """The other half: nothing surfaces once the task is collected.

    asyncio reports an unretrieved task exception from `Task.__del__`, through the
    loop's exception handler -- so the way to see the difference is to drop every
    reference and collect. With the failure retrieved, the handler is never
    reached; without, the setter gets a traceback at an unrelated moment.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg,
        tmp_path,
        monkeypatch,
        groups=['samples'],
        solutions=[('sol.cpp', ExpectedOutcome.ACCEPTED)],
    )
    fake.results['sol.cpp'] = [_test(SAMPLE_NAMES[0], 'MLE', 0.1)]

    loop = asyncio.get_running_loop()
    reported: List[dict] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: reported.append(context))
    try:
        deferreds = runner.run_solution(
            ctx.skeleton.solutions[0], ctx.skeleton.entries, ctx
        )
        for _ in range(20):
            await asyncio.sleep(0)
        assert runner._jobs[0].done()  # noqa: SLF001

        # Nobody ever awaited a deferred; now let go of everything.
        del deferreds
        runner._jobs.clear()  # noqa: SLF001
        gc.collect()
        await asyncio.sleep(0)

        assert reported == []
    finally:
        loop.set_exception_handler(previous)


async def test_the_submitted_file_keeps_the_solutions_extension(
    testing_pkg, tmp_path, monkeypatch
):
    """MOJ picks the language off `basename(sol)`, which `moj testrun` sends.

    An amalgamated Python solution written to `solution.cpp` would be compiled as
    C++ on the judge.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.results['sol.cpp'] = [
        _test(SAMPLE_NAMES[0], 'AC', 0.1),
        _test(SAMPLE_NAMES[1], 'AC', 0.2),
    ]

    await _run(runner, ctx)

    _, ref, filename, content = fake.submissions[0]
    assert filename == 'sol.cpp'
    # Submitted against the problem `prepare` bound, not a directory that has
    # since been deleted.
    assert ref.startswith('alice#rbxt-')
    assert content


async def test_running_before_preparing_says_so_rather_than_crashing(
    testing_pkg, tmp_path, monkeypatch
):
    """`prepare` is what settles the remote problem and the testcase names.

    Neither is something to re-derive on the spot: the names have to be the ones
    the *uploaded* package used.
    """
    minimal_package(testing_pkg)
    FakeJudge(tmp_path / 'snapshots').install(monkeypatch)
    ctx = _context(tmp_path, entries=build_entries(tmp_path, ['samples']))

    with pytest.raises(MojRunnerError) as exc:
        MojRunner().run_solution(ctx.skeleton.solutions[0], ctx.skeleton.entries, ctx)

    assert 'prepare' in str(exc.value)


async def test_no_entries_means_no_submission(testing_pkg, tmp_path, monkeypatch):
    """A solution with nothing to run must not queue a testrun -- nor a task.

    A task nobody awaits whose body raises prints its traceback out of the garbage
    collector, at a moment unrelated to anything the setter did.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )

    assert runner.run_solution(ctx.skeleton.solutions[0], [], ctx) == []
    for _ in range(10):
        await asyncio.sleep(0)
    assert fake.submissions == []


async def _gather(deferreds):
    return [await deferred() for deferred in deferreds]


_ORDER_SOLUTIONS = [
    ('sol.cpp', ExpectedOutcome.ACCEPTED),
    ('b.cpp', ExpectedOutcome.WRONG_ANSWER),
    ('c.cpp', ExpectedOutcome.WRONG_ANSWER),
    ('d.cpp', ExpectedOutcome.WRONG_ANSWER),
    ('e.cpp', ExpectedOutcome.WRONG_ANSWER),
]


async def _run_every_solution_in_order(runner, ctx):
    """Drive the runner the way `_produce_solution_items` and the report do.

    Every solution queued synchronously first, then consumed one at a time in
    solution order.
    """
    deferreds = [
        runner.run_solution(solution, ctx.skeleton.entries[:1], ctx)
        for solution in ctx.skeleton.solutions
    ]
    for group in deferreds:
        for deferred in group:
            await deferred()


async def test_solutions_reach_the_judge_in_the_order_the_report_reads_them(
    testing_pkg, tmp_path, monkeypatch
):
    """More solutions than slots, and the queue must not reorder them.

    With a concurrency cap, only the first `MAX_INFLIGHT_TESTRUNS` submit
    immediately and the rest wait on the semaphore. A setter reading the report
    top to bottom is watching solutions resolve in package order, so a queue that
    handed slots out in some other order would have the report waiting on a
    solution the judge had not started while a later one was already done.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg,
        tmp_path,
        monkeypatch,
        groups=['samples'],
        solutions=_ORDER_SOLUTIONS,
    )
    for filename, _ in _ORDER_SOLUTIONS:
        fake.results[filename] = [_test(SAMPLE_NAMES[0], 'AC', 0.1)]

    await _run_every_solution_in_order(runner, ctx)

    assert [name for (_run, _ref, name, _content) in fake.submissions] == [
        solution.path.name for solution in ctx.skeleton.solutions
    ]


async def test_one_slow_solution_does_not_let_the_queue_behind_it_jump_ahead(
    testing_pkg, tmp_path, monkeypatch
):
    """The case that would expose a non-FIFO queue.

    `asyncio.Semaphore` wakes waiters in arrival order, so a job that holds its
    slot for many loop turns delays everything behind it without reordering it.
    Pinned because the guarantee is the event loop's, not ours, and a future
    rewrite (a pool, a `gather`, a retry that re-acquires) could quietly lose it.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg,
        tmp_path,
        monkeypatch,
        groups=['samples'],
        solutions=_ORDER_SOLUTIONS,
    )
    for filename, _ in _ORDER_SOLUTIONS:
        fake.results[filename] = [_test(SAMPLE_NAMES[0], 'AC', 0.1)]

    original = fake.testrun_status

    async def hold_b_cpp(run):
        entry = next((s for s in fake.submissions if s[0] == run), None)
        if entry is not None and entry[2] == 'b.cpp':
            for _ in range(50):
                await asyncio.sleep(0)
        return await original(run)

    fake.testrun_status = hold_b_cpp

    await _run_every_solution_in_order(runner, ctx)

    assert [name for (_run, _ref, name, _content) in fake.submissions] == [
        solution.path.name for solution in ctx.skeleton.solutions
    ]


async def test_a_full_queue_is_waited_out_rather_than_failing_the_run(
    testing_pkg, tmp_path, monkeypatch
):
    """MOJ caps queued testruns per account; waiting is the only recovery.

    The quota is not something rbx can avoid by dispatching less -- an interrupted
    run leaves its testruns going on the judge, and a second session holds slots
    too -- and `moj` exposes nothing that cancels one. So a 429 must be sat out,
    not reported as a failed solution.
    """
    runner, fake, ctx = await _prepared(testing_pkg, tmp_path, monkeypatch)
    fake.results['sol.cpp'] = [
        _test(name, 'AC', 0.1) for name in (*SAMPLE_NAMES, *MAIN_NAMES)
    ]

    monkeypatch.setattr(runner_module, 'QUEUE_FULL_INTERVAL_SECONDS', 0)
    original = fake.testrun
    refusals = {'left': 3}

    async def refuse_then_accept(ref, solution):
        if refusals['left'] > 0:
            refusals['left'] -= 1
            raise cli.MojQueueFullError('moj: ... na fila ... (429)')
        return await original(ref, solution)

    fake.testrun = refuse_then_accept
    monkeypatch.setattr(cli, 'testrun', fake.testrun)

    evals = await _run(runner, ctx)

    assert refusals['left'] == 0
    assert evals
    assert all(e.result.outcome == Outcome.ACCEPTED for e in evals)


async def test_a_queue_that_never_drains_says_it_cannot_be_cancelled(
    testing_pkg, tmp_path, monkeypatch
):
    """Bounded, like every other wait here, and actionable when it gives up.

    Nothing rbx can do clears the queue, so the message has to send the setter to
    `moj status` rather than suggesting a retry that would fail the same way.
    """
    runner, fake, ctx = await _prepared(testing_pkg, tmp_path, monkeypatch)
    fake.results['sol.cpp'] = [_test(name, 'AC', 0.1) for name in SAMPLE_NAMES]

    monkeypatch.setattr(runner_module, 'QUEUE_FULL_INTERVAL_SECONDS', 0)
    monkeypatch.setattr(runner_module, 'QUEUE_FULL_ATTEMPTS', 3)

    attempts = {'n': 0}

    async def always_refuse(ref, solution):
        attempts['n'] += 1
        raise cli.MojQueueFullError('moj: ... na fila ... (429)')

    monkeypatch.setattr(cli, 'testrun', always_refuse)

    with pytest.raises(runner_module.MojRunnerError) as exc_info:
        await _run(runner, ctx)

    assert attempts['n'] == 3, 'the wait must be bounded'
    message = str(exc_info.value)
    assert 'cannot be cancelled' in message
    assert 'moj status' in message
    assert '[item]' not in message


# -- what the runner puts on the board -----------------------------------------


def _chips(ctx, solution_path: str) -> List[str]:
    return [chip.text for chip in ctx.progress_board.get(solution_path)]


async def test_a_queued_solution_says_so_before_it_is_submitted(
    testing_pkg, tmp_path, monkeypatch
):
    """A solution the report has not reached is accounted for, not blank.

    `run_solution` returns without awaiting -- that is the point of the seam --
    so every solution is queued while the report is still printing the first. A
    blank header for the other nine reads as nothing happening, which is the
    opposite of the truth.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )

    runner.run_solution(ctx.skeleton.solutions[0], ctx.skeleton.entries, ctx)

    # Synchronously, before a single turn of the loop has run the task.
    assert _chips(ctx, 'sol.cpp') == [f'moj {runner._moj_id}', 'waiting for a slot']  # noqa: SLF001


async def test_the_board_names_the_testrun_once_it_is_submitted(
    testing_pkg, tmp_path, monkeypatch
):
    """The testrun id is the one thing that makes the rest of the line
    actionable: it is what `moj testrun-status <run>` takes."""
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.results['sol.cpp'] = [
        _test(SAMPLE_NAMES[0], 'AC', 0.1),
        _test(SAMPLE_NAMES[1], 'AC', 0.2),
    ]
    fake.polls_until_done = 3

    seen: List[List[str]] = []
    original = runner._wait_for_testrun  # noqa: SLF001

    async def watching(run, solution, board, since):
        status = await original(run, solution, board, since)
        seen.append([chip.text for chip in board.get(str(solution.path))])
        return status

    monkeypatch.setattr(runner, '_wait_for_testrun', watching)
    await _run(runner, ctx)

    assert seen, 'the wait was never entered'
    assert any(text.startswith('testrun ') for text in seen[0])


async def test_every_poll_repaints_the_solution_it_is_waiting_on(
    testing_pkg, tmp_path, monkeypatch
):
    """This is the slow half of a remote run and the half a setter wants moving.

    The judge's own state word goes on the board on each poll, so a run that is
    queued behind the park looks different from one that is being judged.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.results['sol.cpp'] = [
        _test(SAMPLE_NAMES[0], 'AC', 0.1),
        _test(SAMPLE_NAMES[1], 'AC', 0.2),
    ]
    fake.polls_until_done = 3

    seen: List[List[str]] = []
    original = runner_module.cli.testrun_status

    async def watching(run):
        status = await original(run)
        seen.append([chip.text for chip in ctx.progress_board.get('sol.cpp')])
        return status

    monkeypatch.setattr(runner_module.cli, 'testrun_status', watching)
    await _run(runner, ctx)

    # By the last poll the board is describing this testrun, not the queue.
    assert any(any(text.startswith('testrun ') for text in chips) for chips in seen[1:])


async def test_a_finished_solution_keeps_the_testrun_on_its_header(
    testing_pkg, tmp_path, monkeypatch
):
    """The slot is left holding `done`, not emptied.

    The reporter rebuilds its block on every drawn frame, so the last frame --
    the one `Live.stop()` freezes into scrollback, and the only one a
    non-terminal console emits at all -- shows whatever the board holds then.
    Clearing it would drop the testrun id out of the permanent record and out of
    every `--share` report, which is exactly where it is worth having.

    Nothing stale survives, because `_submit_and_poll` overwrites the slot with
    `done` before any deferred can resolve.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg, tmp_path, monkeypatch, groups=['samples']
    )
    fake.results['sol.cpp'] = [
        _test(SAMPLE_NAMES[0], 'AC', 0.1),
        _test(SAMPLE_NAMES[1], 'AC', 0.2),
    ]

    await _run(runner, ctx)

    chips = _chips(ctx, 'sol.cpp')
    assert any(text.startswith('testrun ') for text in chips)
    assert 'done' in chips
    # ...and nothing left over from while it was still running.
    assert 'waiting for a slot' not in chips
    assert 'submitted' not in chips


async def test_a_poll_writes_to_its_own_slot_and_no_other(
    testing_pkg, tmp_path, monkeypatch
):
    """The rule that lets a background task say anything at all.

    Up to `MAX_INFLIGHT_TESTRUNS` tasks poll at once, long after the call that
    created them returned. Printing from one would make the display flip between
    solutions; a board write cannot, because the reporter draws only the slot it
    is blocked on. Pinned here from the writing end: `other.cpp` being polled
    throughout never touches `sol.cpp`'s slot.
    """
    runner, fake, ctx = await _prepared(
        testing_pkg,
        tmp_path,
        monkeypatch,
        groups=['samples'],
        solutions=[
            ('sol.cpp', ExpectedOutcome.ACCEPTED),
            ('other.cpp', ExpectedOutcome.WRONG_ANSWER),
        ],
    )
    for filename in ('sol.cpp', 'other.cpp'):
        fake.results[filename] = [
            _test(SAMPLE_NAMES[0], 'AC', 0.1),
            _test(SAMPLE_NAMES[1], 'AC', 0.2),
        ]
    fake.polls_until_done = 5

    first = runner.run_solution(ctx.skeleton.solutions[0], ctx.skeleton.entries, ctx)
    runner.run_solution(ctx.skeleton.solutions[1], ctx.skeleton.entries, ctx)

    await _gather(first)

    # `sol.cpp` is finished; `other.cpp` kept its own slot the whole time, and
    # never appeared in `sol.cpp`'s.
    assert 'done' in _chips(ctx, 'sol.cpp')
    assert _chips(ctx, 'other.cpp')
    assert not any('other' in text for text in _chips(ctx, 'sol.cpp'))


def test_poll_chips_say_only_what_the_judge_reported(testing_pkg):
    """A `0/0` on a run that has not started would read as a lost testset.

    The state word is always answered; the counts and the host are reported by
    some responses and not others, so they are added when present rather than
    defaulted.
    """
    runner = MojRunner()
    runner._moj_id = 'alice#rbxt-x'  # noqa: SLF001
    since = utils.Elapsed()

    bare = runner._poll_chips(  # noqa: SLF001
        '4821', cli.TestrunStatus(status='queued'), since
    )
    texts = [chip.text for chip in bare]
    assert 'queued' in texts
    assert not any('/' in text and 'ok' in text for text in texts)

    full = runner._poll_chips(  # noqa: SLF001
        '4821',
        cli.TestrunStatus(
            status='running', correct=12, total_tests=72, host='judge-sp1'
        ),
        since,
    )
    texts = [chip.text for chip in full]
    assert 'running' in texts
    assert 'judge-sp1' in texts
    # `correct`, not "tests run": MOJ reports how many passed, and calling that
    # progress would show a solution expected to fail stuck at 0 while it works.
    assert '12/72 ok' in texts


def test_the_host_is_read_off_a_status_that_carries_one():
    """The live probe came back `host: judge-sp1`.

    Optional because nothing guarantees every response carries it -- a park with
    one judge may well never send it -- and `extra='ignore'` means a missing field
    is not an error.
    """
    assert cli.TestrunStatus(status='done', host='judge-sp1').host == 'judge-sp1'
    assert cli.TestrunStatus(status='done').host is None
