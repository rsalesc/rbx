# MOJ Remote Solution Runner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let `rbx time -p moj --runner moj` measure solution timings on the MOJ judge park
instead of on the setter's machine, by swapping the backend that produces evaluations.

**Architecture:** A `SolutionRunner` protocol at *per-solution* grain (one call gets a
solution's whole testcase list and returns one `Deferred[Evaluation]` per testcase).
`LocalRunner` is today's `_run_solution` moved verbatim; `MojRunner` uploads one
calibration-only MOJ package and then issues one `moj testrun` per solution, fanning the
single job's per-test results out into the deferreds. The deferreds and their consumption
order never change, so the report streams exactly as it does today.

**Tech Stack:** Python 3, Pydantic v2, `asyncio`, Typer, pytest (`pytest-asyncio`), the
`moj` CLI (bash, `--json` on every relevant subcommand).

**Design doc:** [`2026-08-20-moj-remote-runner-design.md`](2026-08-20-moj-remote-runner-design.md).
Read it first -- it records *why* the seam is per-solution and what the MOJ CLI actually
provides.

**Scope of this plan:** Tasks 0-4. Tasks 5-8 (the runner itself and the timing wiring)
depend on answers only Task 0 can give -- most importantly MOJ's verdict-code vocabulary --
and get their own plan once the probe lands. See [After this plan](#after-this-plan).

---

## Background you need before starting

**`Deferred`** ([`rbx/box/deferred.py`](../../rbx/box/deferred.py)) is a lazily-evaluated,
memoizing async thunk. `run_solutions` returns one per (solution, testcase); the *caller*
decides when to await them, which is what makes the run report stream. Nothing in this plan
may change that contract.

**`Evaluation`** ([`rbx/grading/steps.py:321`](../../rbx/grading/steps.py)) is a plain
Pydantic model: `CheckerResult` + `TestcaseIO` + `TestcaseLog`. `TestcaseLog.time`,
`.wall_time` and `.memory` are already `Optional` and default to `None`, precisely so an
evaluation that measured nothing does not read back as an instantaneous run. Read
`_record_skipped_evaluation` ([`solutions.py:485`](../../rbx/box/solutions.py)) -- it is the
existing precedent for "this testcase produced no measurements and no artifacts", and the
MOJ runner follows the same rules.

**Run this before you start**, to know what already passes:

```bash
uv run pytest tests/rbx/box/solutions_test.py -x -q
```

Some C++/sandbox tests fail on macOS for unrelated reasons. Note the baseline; you are
responsible only for not making it worse.

**Every commit** must follow Conventional Commits -- the `commitizen check` pre-commit hook
rejects anything else. Use the `/commit` skill. Types you will need here: `refactor`,
`feat`, `test`.

---

## Task 0: Probe the live MOJ (manual, gates Tasks 5-8)

This is not a coding task and produces no production code. It answers questions the rest of
the design rests on. **Do not skip it and guess.**

**Files:**
- Create: `tests/rbx/box/runners/moj/testdata/*.json` (recorded responses)
- Create: `docs/plans/2026-08-20-moj-probe-notes.md`

**Prerequisites:** `moj login` must already have been run by a human, and the local CLI
must be current (`moj version` warns when it is not; `moj update` refreshes it). rbx never
handles credentials -- it reuses the CLI's session.

**Step 1: Confirm the CLI is current and you are logged in**

```bash
moj version
moj whoami
```

Expected: a build no older than the server's, and a `login: <you>` line. If `moj version`
says `DESATUALIZADO`, run `moj update` first -- `testrun` did not exist in older builds.

**Step 2: Create a throwaway problem from an existing test package**

Use any small package with an accepted solution. Package it, upload it under an `rbxt-`
name, and record what comes back:

```bash
uv run rbx package moj --calibrate
moj --json upload "<you>#rbxt-probe" build/moj > /tmp/probe-upload.json
```

**Step 3: Answer each question and write down the answer**

Record the raw JSON for each into `tests/rbx/box/runners/moj/testdata/`, and the
conclusions into the notes file.

| Question | How to find out | Why it matters |
|---|---|---|
| Does `testrun` need a prior calibration? | `moj --json testrun "<you>#rbxt-probe" sol.cpp` **before** any `moj calibrate`. | If it does not, `prepare()` loses the calibration wait entirely -- the single biggest latency in the flow. |
| Does it need a prior `moj validate`? | Same, checking `moj --json check` shows `unvalidated`. | `moj validate` *re-queues calibration* every call, so it must never be used as a status check. |
| What is the `code` vocabulary? | Submit an accepted, a wrong-answer and a deliberately slow solution; collect every distinct `tests[].code`. | Task 6 maps these onto rbx `Outcome`s. A missed code silently becomes the wrong verdict. |
| Does the response name the judge host? | `moj --json testrun-status <run>` -- look for a host/machine field. | The design records that testrun cannot *select* a judge. If it at least *reports* one, cross-run timing comparisons become checkable. |
| Is a submission outside `languages` really refused? | Set `.moj-meta.json` `languages` to `["cpp"]`, upload, then testrun a `.py` file. | This is the whole justification for widening the whitelist in Task 4. |
| Does a `TLOVERRIDE`-only `conf` change force recalibration? | Upload with a different `TLOVERRIDE[default]`, then `moj --json check` and read `.tl.needs_recalibration`. | Decides whether phase 2 of the timing flow costs a calibration wait or is nearly free. |

**Step 4: Commit the notes and fixtures**

```bash
git add docs/plans/2026-08-20-moj-probe-notes.md tests/rbx/box/runners/moj/testdata
git commit -m "docs(runners): record what the live MOJ answers about testrun"
```

**Step 5: Clean up the throwaway problem**

```bash
moj rm "<you>#rbxt-probe"
```

---

## Task 1: Extract the `SolutionRunner` seam

A **pure refactor**. When it is done, `uv run pytest tests/rbx/box/solutions_test.py` must
pass exactly as it did before, with no test changed. If a test needs changing, the refactor
is wrong.

**Files:**
- Create: `rbx/box/runners/__init__.py`
- Create: `rbx/box/runners/base.py`
- Create: `rbx/box/runners/local.py`
- Modify: `rbx/box/solutions.py` (`_run_solution` at 521, `_produce_solution_items` at 727, `run_solutions` at 803)
- Test: `tests/rbx/box/runners/test_local_runner.py`

**Step 1: Write the failing test**

This test pins the *contract*, which is the thing the refactor must preserve: one deferred
per entry, in entry order, each memoized.

```python
# tests/rbx/box/runners/test_local_runner.py
import pathlib

import pytest

from rbx.box.environment import VerificationLevel
from rbx.box.generators import (
    generate_outputs_for_testcases,
    generate_testcases,
)
from rbx.box.runners.local import LocalRunner
from rbx.box.solutions import run_solutions


@pytest.mark.test_pkg('problems/box1')
async def test_local_runner_yields_one_deferred_per_testcase(
    pkg_from_testdata: pathlib.Path,
):
    await generate_testcases()
    await generate_outputs_for_testcases(None)

    result = await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp'],
        runner=LocalRunner(),
    )

    # One item per (solution, testcase), and every one of them still lazy: nothing
    # may have run just because the items were produced.
    assert result.items
    assert all(item.eval.peek() is None for item in result.items)

    # Awaiting is what runs them, and the result is memoized.
    first = result.items[0]
    evaluation = await first.eval()
    assert first.eval.peek() is evaluation
    assert await first.eval() is evaluation


@pytest.mark.test_pkg('problems/box1')
async def test_run_solutions_defaults_to_the_local_runner(
    pkg_from_testdata: pathlib.Path,
):
    await generate_testcases()
    await generate_outputs_for_testcases(None)

    explicit = await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp'],
        runner=LocalRunner(),
    )
    implicit = await run_solutions(
        verification=VerificationLevel.FULL,
        tracked_solutions=['sol.cpp'],
    )

    assert len(implicit.items) == len(explicit.items)
```

**Step 2: Run it to verify it fails**

```bash
uv run pytest tests/rbx/box/runners/test_local_runner.py -x -q
```

Expected: `ModuleNotFoundError: No module named 'rbx.box.runners'`.

**Step 3: Write `rbx/box/runners/base.py`**

```python
"""The backend that actually runs a solution's testcases.

`run_solutions` decides *what* to run -- which solutions, which testcases, under
which limits -- and a `SolutionRunner` decides *where*. The local sandbox is one;
a judge reached over its own CLI is another.

The seam is per **solution**, not per testcase, because that is the grain a remote
judge works at: one submission is judged against every test at once. A per-testcase
seam would force every batch backend to secretly coalesce calls back into a batch.
"""

import dataclasses
from typing import TYPE_CHECKING, List, Optional, Protocol

from rbx.box.deferred import Deferred
from rbx.box.environment import VerificationLevel
from rbx.grading.steps import Evaluation
from rbx.utils import StatusProgress

if TYPE_CHECKING:
    from rbx.box.generation_schema import GenerationTestcaseEntry
    from rbx.box.schema import Solution
    from rbx.box.solutions import (
        GroupSkeleton,
        SolutionReportSkeleton,
        _AbortGate,
        AbortPredicate,
    )


@dataclasses.dataclass(frozen=True)
class RunnerCapabilities:
    """What a backend can and cannot report.

    Declared rather than discovered: a consumer that silently reads a `None` as
    zero would report an instantaneous run for something that was never measured.
    """

    # Fills TestcaseLog.memory.
    measures_memory: bool = True
    # Writes .out / .err / .log beside the .eval.
    captures_artifacts: bool = True
    # Fills CheckerResult.message with the checker's own words.
    checker_messages: bool = True
    # Can run a testcase several times and keep the best measurement.
    supports_nruns: bool = True
    # Can stop a solution part-way through, so `abort_on` means something.
    supports_abort: bool = True
    supports_interactive: bool = True
    supports_sanitizers: bool = True


@dataclasses.dataclass
class RunContext:
    """Everything a runner needs that is fixed for a whole `run_solutions` call."""

    skeleton: 'SolutionReportSkeleton'
    checker_digest: Optional[str]
    interactor_digest: Optional[str]
    verification: VerificationLevel
    timelimit_override: Optional[int]
    nruns: int
    capture_pipes: bool
    progress: Optional[StatusProgress]
    abort_on: Optional['AbortPredicate']


class SolutionRunner(Protocol):
    name: str
    caps: RunnerCapabilities

    async def prepare(self, ctx: RunContext) -> None:
        """Do the once-per-run setup, before any solution is run."""
        ...

    def run_solution(
        self,
        solution: 'Solution',
        entries: List['GenerationTestcaseEntry'],
        groups: List['GroupSkeleton'],
        ctx: RunContext,
        gate: Optional['_AbortGate'],
    ) -> List[Deferred[Evaluation]]:
        """One deferred per entry, in entry order. Must not block."""
        ...

    async def finalize(self) -> None:
        """Release whatever `prepare` acquired. Always called."""
        ...
```

**Step 4: Write `rbx/box/runners/local.py`**

Move the body of `_run_solution` (`solutions.py:521-592`) here **verbatim** -- do not
"improve" it while moving. It reads `ctx.skeleton.get_solution_compiled_digest(solution)`
and `solution.runs_dir` where the old code took them as parameters.

```python
"""The sandbox on this machine. What rbx has always done."""

from typing import List, Optional

from rbx.box.deferred import Deferred
from rbx.box.runners.base import RunContext, RunnerCapabilities
from rbx.grading.steps import Evaluation


class LocalRunner:
    name = 'local'
    caps = RunnerCapabilities()

    async def prepare(self, ctx: RunContext) -> None:
        return None

    def run_solution(self, solution, entries, groups, ctx, gate) -> List[Deferred[Evaluation]]:
        # <-- the verbatim body of the old solutions._run_solution goes here,
        #     reading ctx.checker_digest / ctx.interactor_digest / ctx.verification /
        #     ctx.timelimit_override / ctx.nruns / ctx.capture_pipes / ctx.progress /
        #     ctx.abort_on, and pulling the compiled digest off ctx.skeleton.
        ...

    async def finalize(self) -> None:
        return None
```

**Step 5: Rewire `solutions.py`**

`_produce_solution_items` keeps the group iteration, the `_AbortGate` construction and the
`EvaluationItem` assembly -- only the call changes:

```python
res.extend(
    EvaluationItem(solution=solution, testcase_entry=entry.group_entry, eval=eval)
    for entry, eval in zip(
        entries,
        runner.run_solution(solution, entries, skeleton.groups, ctx, gate),
    )
)
```

`run_solutions` gains `runner: Optional[SolutionRunner] = None`, defaults it to
`LocalRunner()`, builds the `RunContext`, and wraps the loop:

```python
await runner.prepare(ctx)
try:
    items = await _produce_solution_items(runner=runner, ctx=ctx, ...)
finally:
    await runner.finalize()
```

`finally`, so a failure part-way through still releases whatever `prepare` acquired.

Delete the old `_run_solution`. Keep `AbortContext`, `AbortPredicate`, `_AbortGate` and
`_record_skipped_evaluation` in `solutions.py` -- they are shared, not local-only.

**Step 6: Run the full solution suite**

```bash
uv run pytest tests/rbx/box/runners/test_local_runner.py tests/rbx/box/solutions_test.py -x -q
uv run pytest tests/rbx/box/test_timing_inference_run.py tests/rbx/box/run_report_test.py -x -q
```

Expected: PASS, with no test file other than the new one modified. The three production
callers (`builder.py:145`, `timing.py:1065`, `cli.py:465`) pass no `runner=`, so they take
the default and must be untouched.

**Step 7: Lint and commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/runners tests/rbx/box/runners rbx/box/solutions.py
git commit -m "refactor(solutions): extract a SolutionRunner seam behind run_solutions"
```

---

## Task 2: Make the missing-information path explicit

`RunnerCapabilities` exists after Task 1 but nothing consults it. This task proves that an
evaluation carrying no memory, no artifacts and no checker message renders correctly, and
makes `run_solutions` refuse the combinations a limited backend cannot honor.

**Good news, verified before writing this plan:** the formatting layer is already
`None`-safe. `solutions.py` defines `_UNMEASURED = '-'`, and both `get_evals_formatted_time`
and `get_evals_formatted_memory` return it when nothing was measured. So this task is about
*pinning* that behavior and adding the guards -- not about rewriting the report.

**Files:**
- Modify: `rbx/box/solutions.py` (`run_solutions`)
- Modify: `rbx/box/runners/base.py`
- Test: `tests/rbx/box/runners/test_capabilities.py`

**Step 1: Write the failing tests**

```python
# tests/rbx/box/runners/test_capabilities.py
import pathlib

import pytest

from rbx.box.runners.base import RunnerCapabilities
from rbx.box.solutions import (
    get_evals_formatted_memory,
    get_evals_formatted_time,
)
from rbx.grading.steps import (
    CheckerResult,
    Evaluation,
    Outcome,
    TestcaseIO,
    TestcaseLog,
)


def _unmeasured_evaluation() -> Evaluation:
    """What a backend that reports a verdict but no resource usage produces."""
    return Evaluation(
        result=CheckerResult(outcome=Outcome.ACCEPTED, message=''),
        testcase=TestcaseIO(index=0),
        log=TestcaseLog(exitcode=0, exitstatus='ok', time=None, wall_time=None, memory=None),
    )


def test_unmeasured_memory_reads_as_unmeasured_not_zero():
    assert get_evals_formatted_memory([_unmeasured_evaluation()]) == '-'


def test_unmeasured_time_reads_as_unmeasured_not_zero():
    assert get_evals_formatted_time([_unmeasured_evaluation()]) == '-'


def test_a_memoryless_backend_still_reports_a_time():
    eval = _unmeasured_evaluation()
    eval.log.time = 250.0
    assert get_evals_formatted_time([eval]) == get_evals_formatted_time([eval])
    assert get_evals_formatted_memory([eval]) == '-'


async def test_run_solutions_refuses_nruns_a_backend_cannot_honor(pkg_from_testdata):
    from rbx.box.environment import VerificationLevel
    from rbx.box.exception import RbxException
    from rbx.box.solutions import run_solutions

    class OneShotRunner:
        name = 'one-shot'
        caps = RunnerCapabilities(supports_nruns=False)

        async def prepare(self, ctx): ...
        def run_solution(self, solution, entries, groups, ctx, gate): return []
        async def finalize(self): ...

    with pytest.raises(RbxException, match='one-shot'):
        await run_solutions(
            verification=VerificationLevel.FULL,
            nruns=3,
            runner=OneShotRunner(),
        )
```

Mark the last one `@pytest.mark.test_pkg('problems/box1')`.

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/rbx/box/runners/test_capabilities.py -x -q
```

Expected: the three formatting tests PASS already (that is the point -- they are
regression pins), and `test_run_solutions_refuses_nruns_a_backend_cannot_honor` FAILS
because nothing raises.

**Step 3: Add the guard to `run_solutions`**

Right after the runner is resolved, before `prepare`:

```python
def _check_capabilities(runner: SolutionRunner, *, nruns: int, sanitized: bool) -> None:
    """Refuse up front what the backend cannot do, naming it.

    Refusing beats silently downgrading: a caller who asked for three runs and
    got one would read a single noisy measurement as a stable one.
    """
    caps = runner.caps
    if nruns > 1 and not caps.supports_nruns:
        raise RbxException(
            f'The {runner.name} runner runs each testcase exactly once, so '
            f'--runs {nruns} cannot be honored.'
        )
    if sanitized and not caps.supports_sanitizers:
        raise RbxException(
            f'The {runner.name} runner cannot run sanitized builds.'
        )
    pkg = package.find_problem_package_or_die()
    if pkg.type == TaskType.COMMUNICATION and not caps.supports_interactive:
        raise RbxException(
            f'The {runner.name} runner cannot run interactive problems.'
        )
```

`abort_on` is deliberately **not** refused: a backend that cannot abort simply runs
everything, which is correct, only slower. Note that in the docstring.

**Step 4: Run the tests**

```bash
uv run pytest tests/rbx/box/runners/test_capabilities.py -x -q
```

Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/runners tests/rbx/box/runners rbx/box/solutions.py
git commit -m "feat(runners): declare and enforce what a backend can report"
```

---

## Task 3: The `moj` CLI wrapper and `.moj-id`

A thin, fully-tested layer over the CLI. **No network in the tests** -- every test drives
recorded JSON from Task 0 through a faked subprocess.

**Files:**
- Create: `rbx/box/runners/moj/__init__.py`
- Create: `rbx/box/runners/moj/cli.py`
- Create: `rbx/box/runners/moj/problem_id.py`
- Test: `tests/rbx/box/runners/moj/test_cli.py`
- Test: `tests/rbx/box/runners/moj/test_problem_id.py`

**Step 1: Write the failing `.moj-id` tests**

```python
# tests/rbx/box/runners/moj/test_problem_id.py
import json

from rbx.box.runners.moj.problem_id import ensure_moj_id, moj_id_path


def test_creates_a_stable_id_scoped_to_the_login(cleandir):
    first = ensure_moj_id(login='alice')
    second = ensure_moj_id(login='alice')

    assert first == second == 'alice#rbxt-' + first.split('rbxt-')[1]
    assert json.loads(moj_id_path().read_text())['id'] == first


def test_reuses_the_committed_id_rather_than_generating_a_new_one(cleandir):
    moj_id_path().write_text(json.dumps({'id': 'bob#rbxt-deadbeef'}))

    assert ensure_moj_id(login='bob') == 'bob#rbxt-deadbeef'


def test_a_different_login_reclaims_the_problem_under_its_own_org(cleandir):
    """The slug is the identity; the org is whoever is logged in.

    A co-setter must reach *their* copy, not fail on someone else's org.
    """
    moj_id_path().write_text(json.dumps({'id': 'alice#rbxt-deadbeef'}))

    assert ensure_moj_id(login='bob') == 'bob#rbxt-deadbeef'
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/rbx/box/runners/moj/test_problem_id.py -x -q
```

Expected: `ModuleNotFoundError`.

**Step 3: Implement `problem_id.py`**

```python
"""Binding an rbx package to its throwaway problem on MOJ.

The id lives in `.moj-id` at the package root and is **committed**: two setters on
the same problem must reach the same remote problem instead of each orphaning one
on the server. `.moj-id` is also the MOJ CLI's own binding file -- `moj testrun`
accepts a directory containing one in place of an id -- so this is its convention,
not an invention.

The slug is the stable half and the org is not: the org is whoever is logged in, so
a co-setter reaches their own copy of the same problem rather than failing on an org
they cannot write to.
"""

import json
import pathlib
import secrets
from typing import Optional

MOJ_ID_FILENAME = '.moj-id'
SLUG_PREFIX = 'rbxt-'


def moj_id_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    return root / MOJ_ID_FILENAME


def _read_slug(path: pathlib.Path) -> Optional[str]:
    if not path.is_file():
        return None
    try:
        stored = json.loads(path.read_text()).get('id', '')
    except json.JSONDecodeError:
        return None
    _, _, slug = stored.partition('#')
    return slug or None


def ensure_moj_id(login: str, root: pathlib.Path = pathlib.Path()) -> str:
    path = moj_id_path(root)
    slug = _read_slug(path) or f'{SLUG_PREFIX}{secrets.token_hex(4)}'
    problem_id = f'{login}#{slug}'
    path.write_text(json.dumps({'id': problem_id}, indent=2) + '\n')
    return problem_id
```

**Step 4: Run the tests**

```bash
uv run pytest tests/rbx/box/runners/moj/test_problem_id.py -x -q
```

Expected: PASS.

**Step 5: Write the failing CLI-wrapper tests**

Every subcommand rbx needs, driven from recorded JSON. `moj whoami` is the awkward one:
it does **not** honor the global `--json` flag, so its human-readable
`login: <x>  nome: <y>` line has to be parsed. Pin that, so a future CLI change that adds
`--json` support is caught by a failing test rather than by a wrong login.

```python
# tests/rbx/box/runners/moj/test_cli.py
import json

import pytest

from rbx.box.exception import RbxException
from rbx.box.runners.moj import cli as moj_cli


@pytest.fixture
def fake_moj(monkeypatch):
    """Drive the wrapper from canned CLI output; nothing touches the network."""
    calls = []
    responses = {}

    async def _run(args, **kwargs):
        calls.append(args)
        key = tuple(a for a in args if not a.startswith('-'))
        return responses[key]

    monkeypatch.setattr(moj_cli, '_run_moj', _run)
    return calls, responses


async def test_whoami_parses_the_unstructured_line(fake_moj):
    calls, responses = fake_moj
    responses[('whoami',)] = 'login: alice  nome: Alice A\npode criar problemas: sim\n'

    assert await moj_cli.whoami() == 'alice'


async def test_whoami_says_how_to_log_in_when_there_is_no_session(fake_moj):
    calls, responses = fake_moj
    responses[('whoami',)] = ''

    with pytest.raises(RbxException, match='moj login'):
        await moj_cli.whoami()


async def test_testrun_returns_the_queued_run_id(fake_moj):
    calls, responses = fake_moj
    responses[('testrun', 'alice#rbxt-x', 'sol.cpp')] = json.dumps({'run': 'r-42'})

    assert await moj_cli.testrun('alice#rbxt-x', 'sol.cpp') == 'r-42'
    assert '--no-wait' in calls[0], 'rbx polls itself; the CLI must not block'


async def test_testrun_status_reports_pending_without_tests(fake_moj):
    calls, responses = fake_moj
    responses[('testrun-status', 'r-42')] = json.dumps({'status': 'running'})

    status = await moj_cli.testrun_status('r-42')
    assert not status.done
    assert status.tests == []


async def test_testrun_status_exposes_every_test_by_name(fake_moj):
    calls, responses = fake_moj
    responses[('testrun-status', 'r-42')] = json.dumps(
        {
            'status': 'done',
            'verdict': 'AC',
            'tl_used': 2.0,
            'tests': [
                {'name': 'sample001', 'code': 'AC', 'time': 0.11, 'tl': 2.0},
                {'name': 't01_main_001', 'code': 'AC', 'time': 0.94, 'tl': 2.0},
            ],
        }
    )

    status = await moj_cli.testrun_status('r-42')
    assert status.done
    assert {t.name for t in status.tests} == {'sample001', 't01_main_001'}
    assert status.by_name['t01_main_001'].time == 0.94


async def test_check_reports_a_calibration_still_in_flight(fake_moj):
    calls, responses = fake_moj
    responses[('check', 'alice#rbxt-x')] = json.dumps(
        {'tl': {'calibrated': False, 'being_calibrated': True, 'needs_recalibration': False}}
    )

    check = await moj_cli.check('alice#rbxt-x')
    assert check.being_calibrated
    assert not check.is_ready


async def test_check_is_ready_only_when_calibrated_and_not_stale(fake_moj):
    calls, responses = fake_moj
    responses[('check', 'alice#rbxt-x')] = json.dumps(
        {'tl': {'calibrated': True, 'being_calibrated': False, 'needs_recalibration': True}}
    )

    assert not (await moj_cli.check('alice#rbxt-x')).is_ready
```

**Step 6: Run to verify they fail**

```bash
uv run pytest tests/rbx/box/runners/moj/test_cli.py -x -q
```

Expected: `ModuleNotFoundError: No module named 'rbx.box.runners.moj'`.

**Step 7: Implement `cli.py`**

Shape it around one private `_run_moj(args) -> str` that shells out (`asyncio.create_subprocess_exec`),
raises `RbxException` naming the failing command on a non-zero exit, and puts `--json`
*before* the subcommand -- the CLI's global flag position. Then one small typed wrapper per
subcommand: `whoami`, `upload`, `calibrate`, `check`, `testrun`, `testrun_status`, each
returning a Pydantic model rather than a raw dict.

`TestrunStatus` needs `done`, `verdict`, `tl_used`, `tests: List[TestrunTest]` and a
`by_name` mapping. `MojCheck` needs `calibrated`, `being_calibrated`,
`needs_recalibration` and an `is_ready` property that is
`calibrated and not being_calibrated and not needs_recalibration`.

**Step 8: Run the tests**

```bash
uv run pytest tests/rbx/box/runners/moj -x -q
```

Expected: PASS.

**Step 9: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/runners/moj tests/rbx/box/runners/moj
git commit -m "feat(runners): wrap the moj CLI and bind a package to its remote problem"
```

---

## Task 4: The package the runner uploads

Three changes to `MojPackager`, all narrow. Read
[`rbx/box/packaging/moj/CLAUDE.md`](../../rbx/box/packaging/moj/CLAUDE.md) first --
especially *Time limits* and *`.moj-meta.json`*.

**Files:**
- Modify: `rbx/box/packaging/moj/packager.py` (`__init__` at 185, `_time_limit_lines` at 442, `_fixed_time_limits` at 457, `_report_time_limits` at 480, `_submission_languages` at 273)
- Modify: `rbx/box/packaging/moj/timing.py`
- Test: `tests/rbx/box/packaging/moj/test_runner_package.py`

### 4a: A `UniformPinned` timing mode

`_time_limit_lines` refuses to guess between two modes today: the `moj` limits profile pins
the limits, or `--calibrate` hands them to the judge. The runner needs a third -- *pin every
language to one explicit number*.

**Why uniform, and not just "a different profile":** `ctx.timelimit_override` is a single
cap (the inference timeout, or `timeLimitToTle x TL`). Emitting the profile's per-language
`TLOVERRIDE` entries alongside it would measure some languages under a **tighter** cap than
rbx asked for, quietly truncating the very timings the estimate rests on.

**Step 1: Write the failing test**

```python
# tests/rbx/box/packaging/moj/test_runner_package.py
from rbx.box.packaging.moj import timing as moj_timing


def test_a_uniform_limit_pins_every_language_to_one_number():
    limits = moj_timing.build_uniform_limits(3000)

    assert limits.base_ms == 3000
    assert limits.per_language_ms == {}

    lines = moj_timing.fixed_limit_lines(limits)
    assert 'TLOVERRIDE[default]=3.000' in lines
    assert not [line for line in lines if line.startswith('TLOVERRIDE[') and 'default' not in line]


def test_a_uniform_limit_raises_calibrationtl_to_match():
    """calibreitor.sh's 5s dummy would TLE a solution rbx is willing to wait 8s for."""
    lines = moj_timing.fixed_limit_lines(moj_timing.build_uniform_limits(8000))

    assert 'CALIBRATIONTL=8' in lines
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/rbx/box/packaging/moj/test_runner_package.py -x -q
```

Expected: `AttributeError: module ... has no attribute 'build_uniform_limits'`.

**Step 3: Implement**

In `timing.py`, one small function -- `fixed_limit_lines` and `calibration_tl_seconds` are
reused unchanged:

```python
def build_uniform_limits(limit_ms: int) -> FixedTimeLimits:
    """One limit for every language, with no per-language entries.

    What a *timing probe* needs, as opposed to a real package: rbx is enforcing a
    single cap and must be able to read back how long each solution actually took
    under it. A per-language entry tighter than that cap would truncate exactly the
    measurement being taken.
    """
    return FixedTimeLimits(base_ms=limit_ms, per_language_ms={})
```

In `packager.py`, replace the `calibrate: bool` constructor argument with a mode object:

```python
@dataclasses.dataclass(frozen=True)
class ProfilePinned:
    """Pin the limits to the `moj` limits profile. The default."""


@dataclasses.dataclass(frozen=True)
class JudgeCalibrated:
    """Let MOJ measure them. `rbx package moj --calibrate`."""


@dataclasses.dataclass(frozen=True)
class UniformPinned:
    """Pin every language to one number. What a remote timing run uploads."""

    limit_ms: int


TimingMode = Union[ProfilePinned, JudgeCalibrated, UniformPinned]
```

`_time_limit_lines` dispatches on it; `_report_time_limits` gets a `UniformPinned` branch
that says plainly that this is a probe limit, not the problem's. Keep `--calibrate`
constructing `JudgeCalibrated` so the CLI surface does not change.

### 4b: A calibration-only solution set

**Step 4: Write the failing test**

```python
def test_a_calibration_only_package_ships_just_the_model_solution(...):
    """Calibration needs one sols/good solution; testrun carries the rest itself.

    `moj testrun` sends the source in the request body, so the solutions being
    *timed* never have to be in the package. Shipping only the model solution keeps
    the one calibration the session pays for as short as possible.
    """
```

Assert `sols/good/` has exactly one file and `sols/wrong`, `sols/slow`, `sols/pass` are
absent.

### 4c: The widened language whitelist

**This is the bug that makes 4b safe.** `.moj-meta.json`'s `languages` is the whitelist of
submission languages and **the API rejects a submission outside it** -- a testrun included.
`_submission_languages` derives it from the languages with an **ACCEPTED** solution, which
is right for a real problem and wrong here: a calibration-only package ships one accepted
solution, so the whitelist collapses to that language and every testrun in another one is
refused -- including, in phase 2, the slow and wrong solutions, which are never accepted by
construction.

**Step 5: Write the failing test**

```python
def test_a_runner_package_whitelists_every_language_it_may_testrun(...):
    """The narrowing that protects a real problem buys nothing on a private probe.

    A package shipping only a C++ model solution must still accept a Python
    testrun, or phase 2 cannot measure a Python slow solution at all.
    """
    # package with only a C++ accepted solution, but a Python wrong solution present
    # in problem.rbx.yml
    meta = json.loads((pkg_dir / '.moj-meta.json').read_text())
    assert set(meta['languages']) >= {'cpp', 'py'}
```

**Step 6: Implement**

Give `_submission_languages` a runner branch that takes the union over **every solution rbx
may testrun**, not the accepted ones, and skips `_report_submission_languages` (there is no
student submission surface to warn about on a probe problem).

**Step 7: Run the whole MOJ packaging suite**

```bash
uv run pytest tests/rbx/box/packaging/moj -x -q
```

Expected: PASS, including the existing tests -- `--calibrate` and profile pinning must be
byte-identical to before. If a golden-file test moves, you changed a mode you should not
have.

**Step 8: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/packaging/moj tests/rbx/box/packaging/moj
git commit -m "feat(packaging): let a caller pin MOJ limits to one uniform number"
```

---

## After this plan

Tasks 5-8 need Task 0's answers before they can be specified honestly:

- **Task 5 -- `MojRunner.prepare`.** Upload, calibrate, poll, and the already-calibrated
  fast path. Shape depends on whether `testrun` needs a prior calibration at all, and
  whether it needs a prior `moj validate`.
- **Task 6 -- `MojRunner.run_solution`.** The testrun fan-out and the background task. The
  verdict mapping *cannot* be written until the `code` vocabulary is recorded. Tests pair
  by MOJ test name through
  [`packaging/moj/naming.py`](../../rbx/box/packaging/moj/naming.py), never by position.
- **Task 7 -- the timing wiring.** `--runner` on `rbx time`, the inference cap becoming
  `TLOVERRIDE`, and the phase-2 upload at `timeLimitToTle x decided TL`. Whether phase 2
  costs a second calibration wait is exactly the last probe question.
- **Task 8 -- caching.** Key testrun results by (package checksum, solution digest,
  `TLOVERRIDE`) so a re-run costs no judge time.

Tasks 1 and 2 are worth landing on their own merits regardless: they are pure rbx-side and
touch nothing MOJ-specific.
