"""The judgement cache: a re-run of `rbx time --runner domjudge` costs no judging.

`rbx time` is a command a setter runs *again* -- tweak a solution, re-estimate,
look at the table once more -- and every re-run used to re-stage the whole package
and re-submit every solution, including the ones whose source had not changed by a
byte. A submission occupies the judgehost for as long as the solution takes on
every test, and `MAX_INFLIGHT_SUBMISSIONS = 1` makes that strictly serial, so that
is not a small waste.

What these tests are really about is the **key**: a hit has to be provably the
same measurement, not merely a similar one. So they change one thing at a time --
a solution's source, the limit pinned in the package, the verdict the judge
reports -- and assert exactly which submissions and uploads the next run makes.

Nothing here touches the network; `FakeApi` from `conftest.py` is the whole judge.
"""

import asyncio
import json
import pathlib
from typing import Dict, List

import pytest

from rbx.box.runners.base import RunPurpose
from rbx.box.runners.domjudge import runner as runner_module
from rbx.box.runners.domjudge.runner import DomjudgeRunner, DomjudgeRunnerError
from rbx.box.schema import ExpectedOutcome
from tests.rbx.box.runners.domjudge.conftest import (
    FakeApi,
    build_entries,
    context,
    minimal_package,
    run,
    time_run,
)

pytestmark = pytest.mark.shared_cache

TWO_SOLUTIONS = [
    ('sol.cpp', ExpectedOutcome.ACCEPTED),
    ('other.cpp', ExpectedOutcome.WRONG_ANSWER),
]


@pytest.fixture(autouse=True)
def _instant_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_module, 'JUDGEMENT_POLL_INTERVAL_SECONDS', 0)


def _cache_dir(testing_pkg) -> pathlib.Path:
    return testing_pkg.root / '.rbx' / runner_module.JUDGEMENT_CACHE_DIR_NAME


def _entries(testing_pkg) -> List[pathlib.Path]:
    directory = _cache_dir(testing_pkg)
    return sorted(directory.glob('*.json')) if directory.is_dir() else []


def _dump(evaluations: Dict[str, List]) -> Dict[str, List[dict]]:
    return {
        path: [evaluation.model_dump(mode='json') for evaluation in evals]
        for path, evals in evaluations.items()
    }


# -- the hit ---------------------------------------------------------------------


async def test_a_second_run_over_an_unchanged_package_submits_nothing(
    testing_pkg, tmp_path, monkeypatch
):
    """THE test. Nothing changed, so nothing is judged again."""
    minimal_package(testing_pkg)
    fake = FakeApi().install(monkeypatch)
    ctx = context(tmp_path)

    await time_run(ctx)
    assert fake.submitted == ['sol.cpp']

    await time_run(ctx)

    assert fake.submitted == ['sol.cpp']


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
    minimal_package(testing_pkg)
    fake = FakeApi().install(monkeypatch)
    fake.results['sol.cpp'] = [run(1, 'TLE', 2.81), run(2, 'WA', 0.2)]
    ctx = context(tmp_path)

    missed = await time_run(ctx)
    hit = await time_run(ctx)

    assert _dump(hit) == _dump(missed)


async def test_a_testcase_the_judge_never_reported_stays_unreported_on_a_hit(
    testing_pkg, tmp_path, monkeypatch
):
    """A partial judging is remembered as partial, not completed by the cache.

    A run list short of the testset resolves the missing testcases as SKIPPED,
    and the entry stores the judge's own answer rather than the derivation -- so
    a hit re-derives the same shortfall instead of inventing results for the
    testcases nobody measured.
    """
    minimal_package(testing_pkg)
    fake = FakeApi().install(monkeypatch)
    fake.results['sol.cpp'] = [run(1, 'AC', 0.1)]
    ctx = context(tmp_path)

    missed = await time_run(ctx)
    hit = await time_run(ctx)

    assert fake.submitted == ['sol.cpp']
    assert _dump(hit) == _dump(missed)
    assert hit['sol.cpp'][1].result.outcome.name == 'SKIPPED'


async def test_the_cache_lives_in_the_disposable_problem_cache(
    testing_pkg, tmp_path, monkeypatch
):
    """Losing it must cost a redundant submission, never a wrong measurement.

    Same place, and for the same reason, as `prepare`'s upload record: what a
    judgehost answered at a moment is an observation this machine made, not part
    of the package. It must never be committed.
    """
    minimal_package(testing_pkg)
    fake = FakeApi().install(monkeypatch)
    ctx = context(tmp_path)

    await time_run(ctx)

    entries = _entries(testing_pkg)
    assert len(entries) == 1
    # The judge's own answer, stored whole -- the judgement and the runs, rather
    # than the evaluations derived from them, so a hit re-derives against
    # whatever the current run asks for.
    payload = json.loads(entries[0].read_text())
    assert payload['submission'] == fake.submissions[0][0]
    assert [item['ordinal'] for item in payload['runs']] == [1, 2]
    assert payload['judgement']['judgement_type_id'] == 'AC'


# -- the miss --------------------------------------------------------------------


async def test_a_changed_solution_is_the_only_one_measured_again(
    testing_pkg, tmp_path, monkeypatch
):
    """THE other test. The key is the *amalgamated bytes*, per solution."""
    minimal_package(testing_pkg, solutions=TWO_SOLUTIONS)
    fake = FakeApi().install(monkeypatch)
    ctx = context(tmp_path, solutions=TWO_SOLUTIONS)

    await time_run(ctx)
    assert sorted(fake.submitted) == ['other.cpp', 'sol.cpp']

    (testing_pkg.root / 'other.cpp').write_text('int main(){ return 1; }\n')
    await time_run(ctx)

    assert fake.submitted == ['sol.cpp', 'other.cpp', 'other.cpp']


async def test_editing_the_model_solution_invalidates_only_itself(
    testing_pkg, tmp_path, monkeypatch
):
    """The difference from MOJ, and it is a real one.

    A MOJ probe ships its solutions inside the package, so editing any of them
    moves the package fingerprint and invalidates every other solution's timing.
    A DOMjudge probe deliberately ships **no** submissions -- DOMjudge would judge
    them for real and race the measured runs -- so the model solution is nothing
    but another submission here, and editing it costs one re-measurement rather
    than all of them.
    """
    minimal_package(testing_pkg, solutions=TWO_SOLUTIONS)
    fake = FakeApi().install(monkeypatch)
    ctx = context(tmp_path, solutions=TWO_SOLUTIONS)

    await time_run(ctx)
    (testing_pkg.root / 'sol.cpp').write_text('int main(){ return 2; }\n')
    await time_run(ctx)

    assert fake.submitted == ['sol.cpp', 'other.cpp', 'sol.cpp']
    # And the package itself did not move, so nothing was re-uploaded either.
    assert len(fake.uploads) == 1


async def test_a_changed_limit_invalidates_every_solution(
    testing_pkg, tmp_path, monkeypatch
):
    """The limit is *in* the package, so a new limit is a new measurement of
    everything.

    It is written into `domjudge-problem.ini`, which the package fingerprint
    covers -- so it needs no term of its own in the key, and the validation phase
    (which re-stages at `timeLimitToTle x TL`) misses on every solution by
    construction. Timings taken under a 2.5s kill are not timings under a 4s one:
    a solution killed at the first limit may finish under the second.
    """
    minimal_package(testing_pkg, solutions=TWO_SOLUTIONS)
    fake = FakeApi().install(monkeypatch)

    await time_run(context(tmp_path, solutions=TWO_SOLUTIONS, timelimit_override=2500))
    await time_run(context(tmp_path, solutions=TWO_SOLUTIONS, timelimit_override=4000))

    assert len(fake.uploads) == 2
    assert fake.submitted == ['sol.cpp', 'other.cpp', 'sol.cpp', 'other.cpp']


async def test_the_two_phases_do_not_share_entries(testing_pkg, tmp_path, monkeypatch):
    """Estimation and validation stage different problems, so they key apart.

    They pin different limits and live under different `rbxt-` ids by design; an
    entry from one must never answer for the other even when the bytes submitted
    are identical.
    """
    minimal_package(testing_pkg)
    fake = FakeApi().install(monkeypatch)

    await time_run(context(tmp_path, timelimit_override=2500))
    await time_run(
        context(tmp_path, timelimit_override=2500, purpose=RunPurpose.VALIDATION)
    )

    assert fake.submitted == ['sol.cpp', 'sol.cpp']


async def test_bumping_the_cache_version_invalidates_every_entry(
    testing_pkg, tmp_path, monkeypatch
):
    """The version is *in* the key, so an old entry is unreachable, not wrong.

    That is what a bump is for: a change in what an entry means costs one
    redundant submission per solution and needs no migration and no deletion
    pass.
    """
    minimal_package(testing_pkg)
    fake = FakeApi().install(monkeypatch)
    ctx = context(tmp_path)

    await time_run(ctx)
    monkeypatch.setattr(
        runner_module,
        'JUDGEMENT_CACHE_VERSION',
        runner_module.JUDGEMENT_CACHE_VERSION + 1,
    )
    await time_run(ctx)

    assert fake.submitted == ['sol.cpp', 'sol.cpp']


async def test_an_entry_that_parses_but_is_not_the_right_shape_reads_as_a_miss(
    testing_pkg, tmp_path, monkeypatch
):
    """Valid JSON is not a valid measurement.

    A file rbx wrote in some other version, or something that landed under this
    name by accident, must send the run back to the judge rather than resolve
    into whatever it happens to coerce to.
    """
    minimal_package(testing_pkg)
    fake = FakeApi().install(monkeypatch)
    ctx = context(tmp_path)

    await time_run(ctx)
    for entry in _entries(testing_pkg):
        entry.write_text(json.dumps({'submission': '1', 'runs': 'all of them'}))

    await time_run(ctx)

    assert fake.submitted == ['sol.cpp', 'sol.cpp']


async def test_an_unreadable_entry_reads_as_a_miss(testing_pkg, tmp_path, monkeypatch):
    """Half a file is not half a measurement.

    Anything that does not parse into the shape it was written in has to re-run,
    because the alternative is feeding a time limit off bytes nobody can vouch
    for.
    """
    minimal_package(testing_pkg)
    fake = FakeApi().install(monkeypatch)
    ctx = context(tmp_path)

    await time_run(ctx)
    for entry in _entries(testing_pkg):
        entry.write_text('{"submission": "1", "run')

    await time_run(ctx)

    assert fake.submitted == ['sol.cpp', 'sol.cpp']


# -- what may never be cached ----------------------------------------------------


async def test_a_compile_error_is_never_cached(testing_pkg, tmp_path, monkeypatch):
    """THE constraint. A remembered `CE` would be maddening.

    The setter reads "it did not build on the judge", fixes the code, runs again
    -- and a cache that remembered the failure would tell them the same thing
    forever, with no submission to show for it. DOMjudge reports a compile error
    as a judging with a `CE` verdict and no runs at all, which is why "no runs"
    is the rule rather than a special case for one verdict.
    """
    minimal_package(testing_pkg)
    fake = FakeApi().install(monkeypatch)
    fake.results['sol.cpp'] = []
    fake.verdicts['sol.cpp'] = 'CE'
    ctx = context(tmp_path)

    await time_run(ctx)
    assert _entries(testing_pkg) == []

    # The setter fixes it. (The source did not have to change for the judge to
    # answer differently -- a compile error can be the instance's own compile
    # script -- so this run has the same key as the failed one, deliberately.)
    fake.results.pop('sol.cpp')
    fake.verdicts.pop('sol.cpp')
    await time_run(ctx)

    assert fake.submitted == ['sol.cpp', 'sol.cpp']


async def test_a_verdict_rbx_could_not_read_is_never_cached(
    testing_pkg, tmp_path, monkeypatch
):
    """The same rule, for the other thing the runner refuses to interpret.

    An unrecognised verdict fails the solution by name so the fix is a one-line
    table entry. Caching the response would mean the fix appeared to do nothing
    until the cache was cleared.
    """
    minimal_package(testing_pkg)
    fake = FakeApi().install(monkeypatch)
    fake.results['sol.cpp'] = [run(1), run(2, 'AWOOGA')]
    ctx = context(tmp_path)

    with pytest.raises(DomjudgeRunnerError):
        await time_run(ctx)
    assert _entries(testing_pkg) == []

    fake.results.pop('sol.cpp')
    await time_run(ctx)

    assert fake.submitted == ['sol.cpp', 'sol.cpp']


async def test_a_judging_rbx_refused_to_pair_is_never_cached(
    testing_pkg, tmp_path, monkeypatch
):
    """More runs than the testset means nothing was attributed to anything.

    The remote problem holds testcases this run does not know about, so every
    ordinal is refused and every testcase comes back SKIPPED. There is no
    measurement in that to remember -- and remembering it would turn one
    confusing run into every run after it.
    """
    minimal_package(testing_pkg)
    fake = FakeApi().install(monkeypatch)
    fake.results['sol.cpp'] = [run(1), run(2), run(3)]
    ctx = context(tmp_path)

    await time_run(ctx)
    assert _entries(testing_pkg) == []

    fake.results.pop('sol.cpp')
    await time_run(ctx)

    assert fake.submitted == ['sol.cpp', 'sol.cpp']


async def test_a_solution_the_judge_rejected_is_still_cached(
    testing_pkg, tmp_path, monkeypatch
):
    """ "Do not cache a failure" means a judging rbx could not read, not a bad
    verdict.

    A WA, an RE or a TLE is a legitimate, reproducible measurement -- the
    validation phase exists to measure exactly the solutions that are supposed to
    fail, and their timings are as real as an accepted solution's. Refusing to
    cache them would re-submit, on every re-run, the slowest solutions in the
    package: the very ones that cost the judgehost the most.
    """
    minimal_package(testing_pkg)
    fake = FakeApi().install(monkeypatch)
    fake.results['sol.cpp'] = [run(1, 'TLE', 9.9), run(2, 'WA', 0.2)]
    ctx = context(tmp_path)

    await time_run(ctx)
    await time_run(ctx)

    assert fake.submitted == ['sol.cpp']


# -- how a hit is dispatched -----------------------------------------------------


async def test_a_hit_does_not_queue_behind_the_submission_in_flight(
    testing_pkg, tmp_path, monkeypatch
):
    """The cache is consulted before the concurrency slot, not inside it.

    A hit costs one file read and no judge time at all, so making it wait for the
    slot that bounds how much of the judgehost rbx occupies would serialize free
    work behind expensive work. That matters more, not less, with the cap at one:
    the hit would otherwise wait out every miss ahead of it.

    `sol.cpp` is deliberately last, so the slot is taken by a solution the judge
    is still chewing on by the time its turn comes.
    """
    solutions = [
        ('other.cpp', ExpectedOutcome.WRONG_ANSWER),
        ('third.cpp', ExpectedOutcome.WRONG_ANSWER),
        ('sol.cpp', ExpectedOutcome.ACCEPTED),
    ]
    # Declared with the model solution first, because the schema requires it, and
    # dispatched with it last, which is what this test is about.
    minimal_package(testing_pkg, solutions=list(reversed(solutions)))
    fake = FakeApi().install(monkeypatch)
    ctx = context(tmp_path, solutions=solutions)

    await time_run(ctx)

    # Only `sol.cpp` still hits.
    for path in ('other.cpp', 'third.cpp'):
        (testing_pkg.root / path).write_text('int main(){ return 1; }\n')

    runner = DomjudgeRunner()
    await runner.prepare(ctx)
    # The judge answers nobody until this is set, so the slot stays occupied.
    fake.hold = asyncio.Event()
    batches = [
        runner.run_solution(solution, ctx.skeleton.entries, ctx)
        for solution in ctx.skeleton.solutions
    ]

    # A bound, so a regression is a failing test rather than a hung suite.
    cached = [await asyncio.wait_for(deferred(), timeout=5) for deferred in batches[2]]

    assert len(cached) == 2
    # The hit resolved while a real submission was still in flight and unanswered
    # -- that is the whole claim -- and never went back to the judge itself.
    assert 'sol.cpp' not in fake.submitted[3:]

    fake.hold.set()
    await runner.close()


# -- the upload fast path --------------------------------------------------------
#
# `stage_problem` is four requests and a zip upload of the whole testset. A
# re-run whose package is byte-identical to what this machine last put there has
# nothing to say to the server, and the phases of `rbx time` alternate over and
# over as the picker narrows -- so this is the other half of what makes a re-run
# cheap.


async def test_a_second_run_does_not_re_upload_an_unchanged_package(
    testing_pkg, tmp_path, monkeypatch
):
    minimal_package(testing_pkg)
    fake = FakeApi().install(monkeypatch)
    ctx = context(tmp_path)

    await time_run(ctx)
    await time_run(ctx)

    assert len(fake.uploads) == 1


async def test_a_changed_package_is_uploaded_again_to_the_same_problem(
    testing_pkg, tmp_path, monkeypatch
):
    """The record says what was uploaded, not merely where.

    A new testcase is a different package under the *same* `rbxt-` id, because
    the id comes from the package's slug (`.rbx-id`) and nothing else. That is
    the second half of the claim here: before the slug, the id was a hash of the
    package name and its testcase count, so adding a testcase staged a brand new
    problem and left the previous one behind on the server for good.
    """
    minimal_package(testing_pkg)
    fake = FakeApi(entries=4).install(monkeypatch)

    await time_run(context(tmp_path))
    await time_run(
        context(tmp_path, entries=build_entries(tmp_path, ['samples', 'main']))
    )

    assert len(fake.uploads) == 2
    assert fake.uploads[0] == fake.uploads[1]


async def test_a_probe_problem_that_vanished_is_uploaded_again(
    testing_pkg, tmp_path, monkeypatch
):
    """The record is a claim about this machine; the problem list is the server's
    own answer, and it wins.

    Without the second check a probe problem deleted in the jury interface -- or
    a record carried onto an instance that was since wiped -- would leave every
    run submitting to a problem that is not there.
    """
    minimal_package(testing_pkg)
    fake = FakeApi().install(monkeypatch)
    ctx = context(tmp_path)

    await time_run(ctx)
    fake.forget_problems()
    await time_run(ctx)

    assert len(fake.uploads) == 2


async def test_the_record_does_not_carry_across_servers(
    testing_pkg, tmp_path, monkeypatch
):
    """Two instances holding the same package are two different measurements.

    `rbxt-` ids are derived from the package, so the same id on a staging server
    and on a production one collides by construction -- which is why the record
    and the cache key both name the server.
    """
    minimal_package(testing_pkg)
    ctx = context(tmp_path)

    first = FakeApi().install(monkeypatch)
    await time_run(ctx)

    second = FakeApi(server='http://elsewhere.test').install(monkeypatch)
    await time_run(ctx)

    assert len(first.uploads) == 1
    assert len(second.uploads) == 1
    assert second.submitted == ['sol.cpp']
