"""`MojRunner.prepare`: getting a calibrated probe problem onto the judge.

Nothing here touches the network or spawns a `moj`. The CLI wrapper is faked at
the module boundary -- `cli.whoami` / `upload` / `calibrate` / `check` -- which is
the same seam `test_cli.py` drives from the other side, so what these tests
exercise is the runner's own decisions: which problem it is willing to write to,
what cap it pins, when it may skip the work, and when it must give up.

The upload fake **snapshots the directory it was handed**, because half of what
`prepare` decides is only visible in the bytes it uploads: the pinned cap lives in
`conf` and the submission whitelist in `.moj-meta.json`.
"""

import json
import pathlib
import shutil
from typing import Dict, List, Optional, Tuple

import pytest

from rbx.box import environment
from rbx.box.environment import TimingConfig, VerificationLevel
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.runners.base import RunContext
from rbx.box.runners.moj import cli
from rbx.box.runners.moj import runner as runner_module
from rbx.box.runners.moj.cli import MojCheck
from rbx.box.runners.moj.problem_id import moj_id_path
from rbx.box.runners.moj.runner import MojRunner, MojRunnerError
from rbx.box.schema import ExpectedOutcome
from rbx.box.solutions import SolutionReportSkeleton, SolutionSkeleton
from tests.rbx.box.packaging.moj.conftest import build_entries, minimal_package

pytestmark = pytest.mark.shared_cache


class FakeMoj:
    """The `moj` CLI, minus the judge.

    `ready_from_check` is the 1-based index of the first `moj check` that reports
    a ready problem; `None` means it never does -- the judge that died silently,
    which is the case the poll's bound exists for.
    """

    def __init__(
        self,
        snapshots: pathlib.Path,
        login: str = 'alice',
        ready_from_check: Optional[int] = 1,
    ):
        self.snapshots = snapshots
        self.login = login
        self.ready_from_check = ready_from_check
        self.uploads: List[Tuple[str, pathlib.Path]] = []
        self.calibrations: List[str] = []
        self.checks: List[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> 'FakeMoj':
        monkeypatch.setattr(cli, 'whoami', self.whoami)
        monkeypatch.setattr(cli, 'upload', self.upload)
        monkeypatch.setattr(cli, 'calibrate', self.calibrate)
        monkeypatch.setattr(cli, 'check', self.check)
        return self

    async def whoami(self) -> str:
        return self.login

    async def upload(self, problem_id: str, directory: pathlib.Path) -> None:
        # Copied out, because `prepare` builds into a temporary directory that is
        # already gone by the time the assertions run.
        dest = self.snapshots / f'upload-{len(self.uploads)}'
        shutil.copytree(directory, dest)
        self.uploads.append((problem_id, dest))

    async def calibrate(self, problem_id: str) -> None:
        self.calibrations.append(problem_id)

    async def check(self, problem_id: str) -> MojCheck:
        self.checks.append(problem_id)
        ready = (
            self.ready_from_check is not None
            and len(self.checks) >= self.ready_from_check
        )
        return MojCheck(calibrated=ready, being_calibrated=not ready)

    @property
    def uploaded(self) -> pathlib.Path:
        """The package uploaded last."""
        assert self.uploads, 'nothing was uploaded'
        return self.uploads[-1][1]


@pytest.fixture(autouse=True)
def _instant_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never really wait three seconds between polls."""
    monkeypatch.setattr(runner_module, 'CALIBRATION_POLL_INTERVAL_SECONDS', 0)


def _context(
    tmp_path: pathlib.Path,
    solutions: Optional[List[Tuple[str, ExpectedOutcome]]] = None,
    timelimit_override: Optional[int] = -1,
    entries: Optional[List[GenerationTestcaseEntry]] = None,
) -> RunContext:
    """A `RunContext` carrying what `prepare` reads: the entries and the solutions.

    `timelimit_override` defaults to **-1**, not to `None`: that is the "no
    override" sentinel `timing.py` really passes whenever the run has no cap.
    """
    if solutions is None:
        solutions = [('sol.cpp', ExpectedOutcome.ACCEPTED)]
    if entries is None:
        entries = build_entries(tmp_path, ['samples'])
    skeleton = SolutionReportSkeleton(
        solutions=[
            SolutionSkeleton(
                path=pathlib.Path(path),
                outcome=outcome,
                runs_dir=tmp_path / 'runs' / path,
            )
            for path, outcome in solutions
        ],
        entries=entries,
        groups=[],
        limits={},
        compiled_solutions={},
        verification=VerificationLevel.ALL_SOLUTIONS,
    )
    return RunContext(
        skeleton=skeleton,
        checker_digest=None,
        interactor_digest=None,
        verification=VerificationLevel.ALL_SOLUTIONS,
        timelimit_override=timelimit_override,
        nruns=1,
        progress=None,
        abort_on=None,
    )


def _conf(package_path: pathlib.Path) -> Dict[str, str]:
    conf = (package_path / 'conf').read_text()
    return dict(line.split('=', 1) for line in conf.splitlines() if '=' in line)


# -- the data-loss guard -------------------------------------------------------


async def test_a_foreign_moj_binding_is_never_uploaded_over(
    testing_pkg, tmp_path, monkeypatch
):
    """THE guard. `.moj-id` is written by `moj upload` too.

    A package may legitimately be bound to a real, published problem, and
    `ensure_moj_id` hands that binding back verbatim rather than hijacking it.
    `moj upload` overwrites whatever id it is given, so uploading the probe here
    would replace a setter's published problem with a throwaway timing package --
    its tests, its statement and its solutions -- with no undo and no `rbxt-`
    marker left behind to explain what happened.
    """
    minimal_package(testing_pkg)
    moj_id_path(testing_pkg.root).write_text('{"id": "alice#soma-simples"}\n')
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    with pytest.raises(MojRunnerError) as exc:
        await MojRunner().prepare(_context(tmp_path))

    assert 'alice#soma-simples' in str(exc.value)
    # Nothing reached the server: not the upload, and not a calibration of
    # someone else's problem either.
    assert fake.uploads == []
    assert fake.calibrations == []


async def test_a_refusal_reaches_the_setter_as_plain_text(
    testing_pkg, tmp_path, monkeypatch
):
    """`main.py` bare-prints `str(e)`, so markup would arrive literally."""
    minimal_package(testing_pkg)
    moj_id_path(testing_pkg.root).write_text('{"id": "alice#soma-simples"}\n')
    FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    with pytest.raises(MojRunnerError) as exc:
        await MojRunner().prepare(_context(tmp_path))

    assert '[item]' not in str(exc.value)
    assert '[error]' not in str(exc.value)


async def test_a_binding_rbx_created_is_uploaded_to(testing_pkg, tmp_path, monkeypatch):
    """The guard refuses *foreign* ids, not every id.

    Without this, a guard that refused unconditionally would satisfy every
    assertion above while never uploading anything at all.
    """
    minimal_package(testing_pkg)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    await MojRunner().prepare(_context(tmp_path))

    assert [problem_id for problem_id, _ in fake.uploads] == fake.calibrations
    assert fake.calibrations and fake.calibrations[0].startswith('alice#rbxt-')


# -- what cap the probe pins ---------------------------------------------------


async def test_the_cap_comes_from_the_runs_time_limit_override(
    testing_pkg, tmp_path, monkeypatch
):
    """Phase 1 passes `_InferenceCap.timeout`; phase 2 `timeLimitToTle x TL`.

    Whatever the run is measuring under is what the judge has to enforce, or the
    timings feeding the estimate were taken under a different limit than rbx
    believes.
    """
    minimal_package(testing_pkg)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    await MojRunner().prepare(_context(tmp_path, timelimit_override=2500))

    conf = _conf(fake.uploaded)
    assert conf['TLOVERRIDE[default]'] == '2.500'
    # Uniform means uniform: a per-language entry beside it would measure that
    # language under a tighter cap than rbx asked for.
    assert [key for key in conf if key.startswith('TLOVERRIDE[')] == [
        'TLOVERRIDE[default]'
    ]


async def test_the_no_override_sentinel_falls_back_to_the_inference_timeout(
    testing_pkg, tmp_path, monkeypatch
):
    """`timing.py` passes **-1**, not `None`, when the run has no cap.

    That is not an edge case -- it is every problem with no `timeLimitToTle` and
    every problem with no upper-bound solution. Reading -1 as a cap would pin
    `TLOVERRIDE[default]=-0.001` and TLE every single measurement.
    """
    minimal_package(testing_pkg)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    await MojRunner().prepare(_context(tmp_path, timelimit_override=-1))

    # The environment's `timing.multipliers.inferenceTimeout`, 10s by default:
    # the limit rbx itself enforces on a solution while estimating.
    assert _conf(fake.uploaded)['TLOVERRIDE[default]'] == '10.000'


async def test_an_absent_override_also_falls_back_rather_than_crashing(
    testing_pkg, tmp_path, monkeypatch
):
    """`RunContext.timelimit_override` is `Optional[int]`, so `None` is reachable."""
    minimal_package(testing_pkg)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    await MojRunner().prepare(_context(tmp_path, timelimit_override=None))

    assert _conf(fake.uploaded)['TLOVERRIDE[default]'] == '10.000'


async def test_a_formula_problem_is_refused_by_name(testing_pkg, tmp_path, monkeypatch):
    """No cap and no multipliers: refuse rather than invent a number.

    MOJ always enforces a limit, so there is no "unlimited" to fall back on, and
    a guessed cap would silently truncate the very timings the estimate rests on.
    The same call `rbx package moj --calibrate` makes when a formula defines no
    `acToTimeLimit`.
    """
    minimal_package(testing_pkg)
    env = environment.get_environment()
    monkeypatch.setattr(
        environment,
        'get_environment',
        lambda *args, **kwargs: env.model_copy(
            update={'timing': TimingConfig(formula='slowest * 2')}
        ),
    )
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    with pytest.raises(MojRunnerError) as exc:
        await MojRunner().prepare(_context(tmp_path, timelimit_override=-1))

    # Names the setting to add and the file to add it to; nothing was uploaded.
    assert 'timing.multipliers.inferenceTimeout' in str(exc.value)
    assert 'env.rbx.yml' in str(exc.value)
    assert fake.uploads == []


# -- the submission whitelist --------------------------------------------------


async def test_the_whitelist_covers_a_language_with_no_accepted_solution(
    testing_pkg, tmp_path, monkeypatch
):
    """The bug the probe whitelist exists to prevent.

    `.moj-meta.json`'s `languages` is enforced by the API on every submission, a
    testrun included. A whitelist derived from the *accepted* solutions -- right
    for a real problem -- would refuse every testrun of a slow or wrong solution,
    which are never accepted by construction. So it comes from every solution
    this run may testrun.
    """
    minimal_package(testing_pkg)
    testing_pkg.add_solution('slow.py', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    await MojRunner().prepare(
        _context(
            tmp_path,
            solutions=[
                ('sol.cpp', ExpectedOutcome.ACCEPTED),
                ('slow.py', ExpectedOutcome.TIME_LIMIT_EXCEEDED),
            ],
        )
    )

    meta = json.loads((fake.uploaded / '.moj-meta.json').read_text())
    assert meta['languages'] == ['cpp', 'py']
    # And the package really ships only the C++ model solution, so an
    # accepted-solutions derivation could not have produced that list.
    assert [path.name for path in (fake.uploaded / 'sols' / 'good').iterdir()] == [
        'sol.cpp'
    ]


# -- the bounded wait ----------------------------------------------------------


async def test_calibration_that_never_finishes_stops_instead_of_hanging(
    testing_pkg, tmp_path, monkeypatch
):
    """`moj check` reports no terminal failure state, so "not ready" is forever.

    The CLI's own loop bounds itself (200 polls at 3s) and handles no failure
    status. Without a bound of its own, a judge that died mid-calibration leaves
    `rbx time` waiting with no output -- which reads as slowness, not as failure.
    """
    minimal_package(testing_pkg)
    monkeypatch.setattr(runner_module, 'CALIBRATION_POLL_ATTEMPTS', 4)
    fake = FakeMoj(tmp_path / 'snapshots', ready_from_check=None).install(monkeypatch)

    with pytest.raises(MojRunnerError) as exc:
        await MojRunner().prepare(_context(tmp_path))

    assert len(fake.checks) == 4
    # Says what to do next, and that nothing was lost.
    assert 'moj calibrate' in str(exc.value)


async def test_a_calibration_that_finishes_late_is_still_waited_for(
    testing_pkg, tmp_path, monkeypatch
):
    """The bound must not degenerate into "poll once and give up"."""
    minimal_package(testing_pkg)
    monkeypatch.setattr(runner_module, 'CALIBRATION_POLL_ATTEMPTS', 4)
    fake = FakeMoj(tmp_path / 'snapshots', ready_from_check=3).install(monkeypatch)

    await MojRunner().prepare(_context(tmp_path))

    assert len(fake.checks) == 3


# -- the already-calibrated fast path ------------------------------------------


async def test_an_already_calibrated_problem_is_not_uploaded_again(
    testing_pkg, tmp_path, monkeypatch
):
    """A second run over an unchanged package costs no judge time.

    Both halves have to hold: the judge says ready, *and* the package rbx just
    built is the one this machine last uploaded and saw calibrated.
    """
    minimal_package(testing_pkg)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    await MojRunner().prepare(_context(tmp_path))
    assert len(fake.uploads) == 1

    await MojRunner().prepare(_context(tmp_path))

    assert len(fake.uploads) == 1
    assert len(fake.calibrations) == 1


async def test_a_changed_package_is_uploaded_again_even_though_the_problem_is_ready(
    testing_pkg, tmp_path, monkeypatch
):
    """Ready is about the *previous* package. Skipping on it alone measures a lie.

    The judge reports its limits as calibrated for whatever it holds; it cannot
    know rbx now wants a different cap. Without the fingerprint half of the fast
    path, this run would measure every solution under the old 2.5s cap while
    believing it had asked for 4s.
    """
    minimal_package(testing_pkg)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    await MojRunner().prepare(_context(tmp_path, timelimit_override=2500))
    await MojRunner().prepare(_context(tmp_path, timelimit_override=4000))

    assert len(fake.uploads) == 2
    assert _conf(fake.uploads[0][1])['TLOVERRIDE[default]'] == '2.500'
    assert _conf(fake.uploads[1][1])['TLOVERRIDE[default]'] == '4.000'


async def test_a_run_that_never_finished_calibrating_is_not_skipped_next_time(
    testing_pkg, tmp_path, monkeypatch
):
    """The fingerprint records a *calibrated* upload, never a merely attempted one.

    Recording it before the wait would let the next run skip straight past a
    package the judge never finished calibrating, and then measure against limits
    that describe something else.
    """
    minimal_package(testing_pkg)
    monkeypatch.setattr(runner_module, 'CALIBRATION_POLL_ATTEMPTS', 2)
    fake = FakeMoj(tmp_path / 'snapshots', ready_from_check=None).install(monkeypatch)

    with pytest.raises(MojRunnerError):
        await MojRunner().prepare(_context(tmp_path))

    fake.ready_from_check = 1
    await MojRunner().prepare(_context(tmp_path))

    assert len(fake.uploads) == 2


# -- what task 6 still owes ----------------------------------------------------


async def test_running_a_solution_is_not_implemented_yet(testing_pkg, tmp_path):
    """No guessed verdict mapping: MOJ's `code` vocabulary is unobserved.

    A plausible-looking table would turn an unknown code into a confident wrong
    verdict, which is worse than not running at all.
    """
    ctx = _context(tmp_path)

    with pytest.raises(NotImplementedError) as exc:
        MojRunner().run_solution(ctx.skeleton.solutions[0], ctx.skeleton.entries, ctx)

    assert 'task 6' in str(exc.value)
