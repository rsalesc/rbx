"""The testrun cache: a re-run of `rbx time --runner moj` costs no judge time.

`rbx time` is a command a setter runs *again* -- tweak a solution, re-estimate,
look at the table once more -- and every re-run used to re-submit every solution,
including the ones whose source had not changed by a byte. A testrun occupies a
shared two-judge park for as long as the solution takes on every test, so that is
not a small waste.

What these tests are really about is the **key**: a hit has to be provably the
same measurement, not merely a similar one. So they change one thing at a time --
a solution's source, the cap in the uploaded package, the run-level verdict -- and
assert exactly which submissions the next run makes.

Nothing here touches the network: `FakeJudge` from `test_run_solution.py` is the
same fake the rest of the runner's tests drive.
"""

import asyncio
import json
import pathlib
from typing import Dict, List, Optional, Tuple

import pytest

from rbx.box.runners.moj import runner as runner_module
from rbx.box.runners.moj.runner import MojRunner, MojRunnerError
from rbx.box.schema import ExpectedOutcome
from tests.rbx.box.packaging.moj.conftest import build_entries, minimal_package
from tests.rbx.box.runners.moj.test_run_solution import (
    SAMPLE_NAMES,
    FakeJudge,
    _compile_error,
    _test,
)
from tests.rbx.box.runners.moj.test_runner import _context

pytestmark = pytest.mark.shared_cache


# What every solution in this file is measured as, unless a test says otherwise.
# The names are the ones `MojPackager` gives the `samples` entries, spelled out
# rather than re-derived -- see `test_run_solution.py`.
def _all_accepted() -> List:
    return [_test(SAMPLE_NAMES[0], 'AC', 0.1), _test(SAMPLE_NAMES[1], 'AC', 0.2)]


@pytest.fixture(autouse=True)
def _instant_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_module, 'CALIBRATION_POLL_INTERVAL_SECONDS', 0)
    monkeypatch.setattr(runner_module, 'TESTRUN_POLL_INTERVAL_SECONDS', 0)


def _session(
    testing_pkg,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    solutions: Optional[List[Tuple[str, ExpectedOutcome]]] = None,
) -> FakeJudge:
    """A package and a judge that survive several `rbx time` runs.

    The point of every test here is what the *second* run does, so the fake is
    built once and kept: its `submissions` list is the whole assertion.
    """
    minimal_package(testing_pkg)
    for path, _ in solutions or []:
        if path != 'sol.cpp':
            testing_pkg.add_solution(path, outcome='wrong-answer').write_text(
                'int main(){}\n'
            )
    fake = FakeJudge(tmp_path / 'snapshots').install(monkeypatch)
    for path, _ in solutions or [('sol.cpp', ExpectedOutcome.ACCEPTED)]:
        fake.results[path] = _all_accepted()
    return fake


async def _time(fake: FakeJudge, ctx) -> Dict[str, List]:
    """One whole `rbx time` run: prepare, then every solution to completion."""
    runner = MojRunner()
    await runner.prepare(ctx)
    evaluations = {}
    for solution in ctx.skeleton.solutions:
        deferreds = runner.run_solution(solution, ctx.skeleton.entries, ctx)
        evaluations[str(solution.path)] = [await deferred() for deferred in deferreds]
    await runner.close()
    return evaluations


def _dump(evaluations: Dict[str, List]) -> Dict[str, List[dict]]:
    return {
        path: [evaluation.model_dump(mode='json') for evaluation in evals]
        for path, evals in evaluations.items()
    }


def _submitted(fake: FakeJudge) -> List[str]:
    return [filename for _, _, filename, _ in fake.submissions]


# -- the hit ---------------------------------------------------------------------


async def test_a_second_run_over_an_unchanged_package_submits_nothing(
    testing_pkg, tmp_path, monkeypatch
):
    """THE test. Nothing changed, so nothing is measured again."""
    fake = _session(testing_pkg, tmp_path, monkeypatch)
    ctx = _context(tmp_path, entries=build_entries(tmp_path, ['samples']))

    await _time(fake, ctx)
    assert _submitted(fake) == ['sol.cpp']

    await _time(fake, ctx)

    assert _submitted(fake) == ['sol.cpp']


async def test_a_hit_produces_exactly_the_evaluations_a_miss_did(
    testing_pkg, tmp_path, monkeypatch
):
    """The cache may change how long a run takes and nothing else.

    Every field of every `Evaluation` -- the outcome, the timing, the checker
    message, the artifact path -- has to come out the same, because the estimate
    `rbx time` writes into a limits profile is computed from exactly these. A
    cache that changed one of them would move a time limit, silently, depending
    on whether the setter had run the command before.
    """
    fake = _session(testing_pkg, tmp_path, monkeypatch)
    ctx = _context(tmp_path, entries=build_entries(tmp_path, ['samples']))
    fake.results['sol.cpp'] = [
        _test(SAMPLE_NAMES[0], 'TLE', 2.81),
        _test(SAMPLE_NAMES[1], 'WA', 0.2),
    ]

    missed = await _time(fake, ctx)
    hit = await _time(fake, ctx)

    assert _dump(hit) == _dump(missed)


async def test_the_cache_lives_in_the_disposable_problem_cache(
    testing_pkg, tmp_path, monkeypatch
):
    """Losing it must cost a redundant testrun, never a wrong measurement.

    Same place, and for the same reason, as `prepare`'s upload record: what a
    judge park answered at a moment is an observation this machine made, not part
    of the package. It must never be committed.
    """
    fake = _session(testing_pkg, tmp_path, monkeypatch)
    ctx = _context(tmp_path, entries=build_entries(tmp_path, ['samples']))

    await _time(fake, ctx)

    entries = list(
        (testing_pkg.root / '.rbx' / runner_module.TESTRUN_CACHE_DIR_NAME).glob(
            '*.json'
        )
    )
    assert len(entries) == 1
    # The judge's own answer, stored whole: the run-level verdict included, so a
    # cached entry can be checked on the way back in exactly as a fresh one is.
    payload = json.loads(entries[0].read_text())
    assert payload['run'] == fake.submissions[0][0]
    assert [test['name'] for test in payload['status']['tests']] == list(SAMPLE_NAMES)


# -- the miss --------------------------------------------------------------------


async def test_a_changed_solution_is_the_only_one_measured_again(
    testing_pkg, tmp_path, monkeypatch
):
    """THE other test. The key is the *amalgamated bytes*, per solution.

    `other.cpp` is edited and `sol.cpp` is not, so the judge sees one submission
    and not two. Note which solution is edited: the model solution is shipped
    *inside* the probe package, so editing it would move the package fingerprint
    too and invalidate everything -- which is right, and is the next test.
    """
    solutions = [
        ('sol.cpp', ExpectedOutcome.ACCEPTED),
        ('other.cpp', ExpectedOutcome.WRONG_ANSWER),
    ]
    fake = _session(testing_pkg, tmp_path, monkeypatch, solutions=solutions)
    ctx = _context(
        tmp_path, entries=build_entries(tmp_path, ['samples']), solutions=solutions
    )

    await _time(fake, ctx)
    assert sorted(_submitted(fake)) == ['other.cpp', 'sol.cpp']

    (testing_pkg.root / 'other.cpp').write_text('int main(){ return 0; }\n')
    await _time(fake, ctx)

    assert _submitted(fake) == ['sol.cpp', 'other.cpp', 'other.cpp']


async def test_a_changed_package_invalidates_every_solution(
    testing_pkg, tmp_path, monkeypatch
):
    """The cap is *in* the package, so a new cap is a new measurement of everything.

    `TLOVERRIDE` is emitted into the package's `conf`, which is what
    `_directory_fingerprint` hashes -- so it needs no term of its own in the key,
    and phase 2 (which re-uploads at `timeLimitToTle x TL`) misses on every
    solution by construction. Timings taken under a 2.5s cap are not timings
    under a 4s one: a solution that was killed at the first cap may finish under
    the second.
    """
    solutions = [
        ('sol.cpp', ExpectedOutcome.ACCEPTED),
        ('other.cpp', ExpectedOutcome.WRONG_ANSWER),
    ]
    fake = _session(testing_pkg, tmp_path, monkeypatch, solutions=solutions)

    await _time(
        fake,
        _context(
            tmp_path,
            entries=build_entries(tmp_path, ['samples']),
            solutions=solutions,
            timelimit_override=2500,
        ),
    )
    await _time(
        fake,
        _context(
            tmp_path,
            entries=build_entries(tmp_path, ['samples']),
            solutions=solutions,
            timelimit_override=4000,
        ),
    )

    assert len(fake.uploads) == 2
    assert _submitted(fake) == ['sol.cpp', 'other.cpp', 'sol.cpp', 'other.cpp']


async def test_bumping_the_cache_version_invalidates_every_entry(
    testing_pkg, tmp_path, monkeypatch
):
    """The version is *in* the key, so an old entry is unreachable, not wrong.

    That is what a bump is for: a change in what an entry means costs one
    redundant testrun per solution and needs no migration and no deletion pass.
    """
    fake = _session(testing_pkg, tmp_path, monkeypatch)
    ctx = _context(tmp_path, entries=build_entries(tmp_path, ['samples']))

    await _time(fake, ctx)
    monkeypatch.setattr(
        runner_module, 'TESTRUN_CACHE_VERSION', runner_module.TESTRUN_CACHE_VERSION + 1
    )
    await _time(fake, ctx)

    assert _submitted(fake) == ['sol.cpp', 'sol.cpp']


async def test_an_entry_that_parses_but_is_not_the_right_shape_reads_as_a_miss(
    testing_pkg, tmp_path, monkeypatch
):
    """Valid JSON is not a valid measurement.

    A file rbx wrote in some other version, or something that landed under this
    name by accident, must send the run back to the judge rather than resolve
    into whatever it happens to coerce to.
    """
    fake = _session(testing_pkg, tmp_path, monkeypatch)
    ctx = _context(tmp_path, entries=build_entries(tmp_path, ['samples']))

    await _time(fake, ctx)
    for entry in (
        testing_pkg.root / '.rbx' / runner_module.TESTRUN_CACHE_DIR_NAME
    ).glob('*.json'):
        entry.write_text(json.dumps({'run': 'abc', 'status': ['done']}))

    await _time(fake, ctx)

    assert _submitted(fake) == ['sol.cpp', 'sol.cpp']


async def test_an_unreadable_entry_reads_as_a_miss(testing_pkg, tmp_path, monkeypatch):
    """Half a file is not half a measurement.

    Anything that does not parse into the shape it was written in has to re-run,
    because the alternative is feeding a time limit off bytes nobody can vouch
    for.
    """
    fake = _session(testing_pkg, tmp_path, monkeypatch)
    ctx = _context(tmp_path, entries=build_entries(tmp_path, ['samples']))

    await _time(fake, ctx)
    for entry in (
        testing_pkg.root / '.rbx' / runner_module.TESTRUN_CACHE_DIR_NAME
    ).glob('*.json'):
        entry.write_text('{"run": "abc", "stat')

    await _time(fake, ctx)

    assert _submitted(fake) == ['sol.cpp', 'sol.cpp']


# -- what may never be cached ----------------------------------------------------


async def test_a_run_level_failure_is_never_cached(testing_pkg, tmp_path, monkeypatch):
    """THE constraint. A cached `Compilation Error` would be maddening.

    The setter reads "it did not build on the judge", fixes the code, runs again
    -- and a cache that remembered the failure would tell them the same thing
    forever, with no submission to show for it. So a run that never entered the
    testset is not a measurement and is not written down; the very next run
    submits again.
    """
    fake = _session(testing_pkg, tmp_path, monkeypatch)
    ctx = _context(tmp_path, entries=build_entries(tmp_path, ['samples']))
    fake.statuses['sol.cpp'] = _compile_error()

    with pytest.raises(MojRunnerError):
        await _time(fake, ctx)

    # The setter fixes it. (The source did not have to change for the judge to
    # answer differently -- a compile error can be the package's own compile
    # script -- so this run has the same key as the failed one, deliberately.)
    fake.statuses.clear()
    await _time(fake, ctx)

    assert _submitted(fake) == ['sol.cpp', 'sol.cpp']


async def test_a_verdict_rbx_could_not_read_is_never_cached(
    testing_pkg, tmp_path, monkeypatch
):
    """The same rule, for the other thing the runner refuses to interpret.

    An unrecognised per-test code fails the whole solution by name so the fix is
    a one-line table entry. Caching the response would mean the fix appeared to
    do nothing until the cache was cleared.
    """
    fake = _session(testing_pkg, tmp_path, monkeypatch)
    ctx = _context(tmp_path, entries=build_entries(tmp_path, ['samples']))
    fake.results['sol.cpp'] = [
        _test(SAMPLE_NAMES[0], 'AC', 0.1),
        _test(SAMPLE_NAMES[1], 'MLE', 0.2),
    ]

    with pytest.raises(MojRunnerError):
        await _time(fake, ctx)

    fake.results['sol.cpp'] = _all_accepted()
    await _time(fake, ctx)

    assert _submitted(fake) == ['sol.cpp', 'sol.cpp']


async def test_a_solution_that_failed_the_judges_verdict_is_still_cached(
    testing_pkg, tmp_path, monkeypatch
):
    """ "Do not cache a failure" means a run rbx could not read, not a bad verdict.

    A WA, an RE or a TLE is a legitimate, reproducible measurement -- phase 2
    exists to measure exactly the solutions that are supposed to fail, and their
    timings are as real as an accepted solution's. Refusing to cache them would
    re-submit, on every re-run, the slowest solutions in the package: the very
    ones that cost the park the most.
    """
    fake = _session(testing_pkg, tmp_path, monkeypatch)
    ctx = _context(tmp_path, entries=build_entries(tmp_path, ['samples']))
    fake.results['sol.cpp'] = [
        _test(SAMPLE_NAMES[0], 'TLE', 9.9),
        _test(SAMPLE_NAMES[1], 'WA', 0.2),
    ]

    await _time(fake, ctx)
    await _time(fake, ctx)

    assert _submitted(fake) == ['sol.cpp']


# -- how a hit is dispatched -----------------------------------------------------


async def test_a_hit_does_not_queue_behind_the_testruns_in_flight(
    testing_pkg, tmp_path, monkeypatch
):
    """The cache is consulted before the concurrency slot, not inside it.

    A hit costs one file read and no judge time at all, so making it wait for the
    slot that bounds how much of the shared park rbx occupies would serialize free
    work behind expensive work -- a run whose solutions all hit would take as long
    as whatever was already queued. That matters more, not less, now the cap is
    one: the hit would otherwise wait out every miss ahead of it.

    `sol.cpp` is deliberately last, so the slot is taken by a solution the judge is
    still chewing on by the time its turn comes.
    """
    solutions = [
        ('other.cpp', ExpectedOutcome.WRONG_ANSWER),
        ('third.cpp', ExpectedOutcome.WRONG_ANSWER),
        ('sol.cpp', ExpectedOutcome.ACCEPTED),
    ]
    fake = _session(testing_pkg, tmp_path, monkeypatch, solutions=solutions)
    ctx = _context(
        tmp_path, entries=build_entries(tmp_path, ['samples']), solutions=solutions
    )

    await _time(fake, ctx)

    # Only `sol.cpp` still hits.
    for path in ('other.cpp', 'third.cpp'):
        (testing_pkg.root / path).write_text('int main(){ return 0; }\n')

    runner = MojRunner()
    await runner.prepare(ctx)
    # The judge answers nobody until this is set, so the slot stays occupied.
    fake.hold = asyncio.Event()
    batches = [
        runner.run_solution(solution, ctx.skeleton.entries, ctx)
        for solution in ctx.skeleton.solutions
    ]

    cached = [
        # A bound, so that the failure is a failing test rather than a hung suite.
        await asyncio.wait_for(deferred(), timeout=5)
        for deferred in batches[2]
    ]

    assert len(cached) == 2
    # The hit resolved while a real testrun was still in flight and unanswered --
    # that is the whole claim -- and never went back to the judge itself.
    submitted_this_run = _submitted(fake)[3:]
    assert submitted_this_run, 'a miss should have been dispatched'
    assert 'sol.cpp' not in submitted_this_run
    assert set(submitted_this_run) <= {'other.cpp', 'third.cpp'}

    fake.hold.set()
    await runner.close()
