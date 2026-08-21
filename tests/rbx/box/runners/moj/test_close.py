"""`MojRunner.close`: dropping the testruns nobody is going to read.

Every solution is dispatched up front -- that is what the per-solution seam buys
-- while the report consumes them one at a time and stops at the first failure.
So a run that ends early (a failed solution, a report that raised, Ctrl-C) leaves
later solutions polling MOJ for results nothing will ever ask for, until the loop
is torn down and asyncio complains about rbx internals long after the error the
setter actually cares about.

The fake judge is the one `test_run_solution.py` drives; `hold` is what keeps a
testrun in flight so there is something to cancel.
"""

import asyncio
import re
from typing import List

import pytest

from rbx.box.schema import ExpectedOutcome
from tests.rbx.box.runners.moj.test_run_solution import (  # noqa: F401
    SAMPLE_NAMES,
    _instant_polls,
    _prepared,
    _test,
)

pytestmark = pytest.mark.shared_cache

_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def _flat(text: str) -> str:
    return ' '.join(_ANSI.sub('', text).split())


async def _dispatch_two_and_hold(testing_pkg, tmp_path, monkeypatch):
    """Two solutions queued on a judge that will not answer until told to."""
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

    batches = [
        runner.run_solution(solution, ctx.skeleton.entries, ctx)
        for solution in ctx.skeleton.solutions
    ]
    # Let both reach the judge and settle into their poll.
    for _ in range(20):
        await asyncio.sleep(0)
    return runner, fake, batches


async def test_closing_cancels_the_testruns_still_in_flight(
    testing_pkg, tmp_path, monkeypatch
):
    """The gap this closes: without it those tasks poll on, and asyncio reports
    them as `Task was destroyed but it is pending!` at interpreter exit."""
    runner, fake, _ = await _dispatch_two_and_hold(testing_pkg, tmp_path, monkeypatch)
    jobs: List[asyncio.Task] = list(runner._jobs)  # noqa: SLF001
    assert jobs and not any(job.done() for job in jobs)

    runner.close()
    # Cancellation lands on the next turn of the loop, not on the call.
    for _ in range(10):
        await asyncio.sleep(0)

    assert all(job.cancelled() for job in jobs)


async def test_closing_says_what_it_left_running_on_the_judge(
    testing_pkg, tmp_path, monkeypatch, capsys
):
    """An interrupted setter otherwise has no way to know whether they left
    something broken on a park they share with everyone else."""
    runner, _, _ = await _dispatch_two_and_hold(testing_pkg, tmp_path, monkeypatch)

    runner.close()

    printed = _flat(capsys.readouterr().out)
    assert 'Stopped waiting for 2 MOJ testrun(s)' in printed
    # The reassurance is the point: a testrun is outside history and placar, so
    # the ones left running need no cleaning up.
    assert 'nothing to clean up' in printed


async def test_closing_a_finished_run_says_nothing(
    testing_pkg, tmp_path, monkeypatch, capsys
):
    """The ordinary path: every consumer closes, so a run that completed normally
    must not end with a warning about work that is not outstanding."""
    runner, fake, batches = await _dispatch_two_and_hold(
        testing_pkg, tmp_path, monkeypatch
    )
    fake.hold.set()
    for batch in batches:
        for deferred in batch:
            await deferred()
    capsys.readouterr()

    runner.close()

    assert _flat(capsys.readouterr().out) == ''


async def test_closing_twice_cancels_and_complains_once(
    testing_pkg, tmp_path, monkeypatch, capsys
):
    """`close` is idempotent: a consumer may close in a `finally` that another
    `finally` runs after."""
    runner, _, _ = await _dispatch_two_and_hold(testing_pkg, tmp_path, monkeypatch)

    runner.close()
    capsys.readouterr()
    runner.close()

    assert _flat(capsys.readouterr().out) == ''


async def test_a_cancelled_testrun_is_not_resubmitted_or_undone(
    testing_pkg, tmp_path, monkeypatch
):
    """rbx cancels its own *wait*, and nothing else.

    MOJ already has the submission and finishes it on its own schedule; there is
    no un-submit, and none is needed -- a testrun runs outside history and placar.
    Anything here that tried to talk to the judge on the way out would be talking
    from a `finally`, while the setter is looking at an error.
    """
    runner, fake, _ = await _dispatch_two_and_hold(testing_pkg, tmp_path, monkeypatch)
    submitted = list(fake.submissions)
    polls = len(fake.status_calls)

    runner.close()
    for _ in range(20):
        await asyncio.sleep(0)

    assert fake.submissions == submitted
    assert len(fake.status_calls) == polls
