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
import pathlib
from typing import Dict, List, Optional, Tuple

import pytest

from rbx.box.runners.moj import cli
from rbx.box.runners.moj import runner as runner_module
from rbx.box.runners.moj.runner import MojRunner, MojRunnerError
from rbx.box.schema import ExpectedOutcome
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
        return cli.TestrunStatus(
            status='done', tests=self.results[self.filename_of(run)]
        )

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
        entries=build_entries(tmp_path, groups or ['samples', 'main']),
        solutions=solutions,
    )
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
    assert [e.result.outcome for e in evals] == [Outcome.ACCEPTED, Outcome.ACCEPTED]


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


async def test_run_solution_queues_every_solution_before_the_first_is_awaited(
    testing_pkg, tmp_path, monkeypatch
):
    """The reason the submission is a background task.

    `_produce_solution_items` builds every solution's deferreds synchronously,
    before a single one resolves. If `run_solution` submitted lazily, the second
    solution would only reach the judge once the first had been judged in full --
    which is the serialization the whole remote-runner design exists to avoid.
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

    # Let the background tasks run. Both reach the judge; neither deferred has
    # been touched.
    for _ in range(10):
        await asyncio.sleep(0)
    assert [filename for _, _, filename, _ in fake.submissions] == [
        'sol.cpp',
        'other.cpp',
    ]
    assert [deferred.peek() for deferred in second] == [None, None]

    fake.hold.set()
    assert len(await _gather(first)) == 2
    assert len(await _gather(second)) == 2


async def test_no_more_than_two_testruns_are_in_flight_at_once(
    testing_pkg, tmp_path, monkeypatch
):
    """The judge park is shared -- two judges, everyone else's submissions too.

    A timing session that dispatched every solution at once would be a denial of
    service on the park it is measuring, and would measure a park it had itself
    made slow.
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
