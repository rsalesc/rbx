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
from typing import Dict, List, Optional, Tuple, Union

import pytest

from rbx.box import environment
from rbx.box.environment import (
    EnvironmentLanguage,
    ExecutionConfig,
    TimingConfig,
    VerificationLevel,
)
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.runners.base import RunContext
from rbx.box.runners.moj import cli
from rbx.box.runners.moj import runner as runner_module
from rbx.box.runners.moj.cli import MojCheck, MojCliError
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
        # Set to make `moj calibrate` blow up, which is how a session dies
        # *between* a completed upload and a finished calibration.
        self.calibrate_fails = False
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
        if self.calibrate_fails:
            raise MojCliError(f'`moj calibrate {problem_id}` failed.')
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
    timelimit_override: Optional[Union[int, Dict[str, int]]] = -1,
    entries: Optional[List[GenerationTestcaseEntry]] = None,
) -> RunContext:
    """A `RunContext` carrying what `prepare` reads: the entries and the solutions.

    `timelimit_override` takes the two shapes `rbx time` really passes -- an
    `int` while estimating, a per-language mapping while validating -- and
    defaults to **-1**, rbx's "no override" sentinel, which is neither.
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


# -- what limits the probe pins ------------------------------------------------


async def test_the_estimation_phase_pins_one_cap_for_every_language(
    testing_pkg, tmp_path, monkeypatch
):
    """Phase 1 passes a single `inferenceTimeout` for the accepted solutions.

    Whatever the run is measuring under is what the judge has to enforce, or the
    timings feeding the estimate were taken under a different limit than rbx
    believes.
    """
    minimal_package(testing_pkg)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    await MojRunner().prepare(_context(tmp_path, timelimit_override=2500))

    conf = _conf(fake.uploaded)
    assert conf['TLOVERRIDE[default]'] == '2.500'
    # One cap means one cap: a per-language entry beside it would measure that
    # language under a tighter cap than rbx asked for.
    assert [key for key in conf if key.startswith('TLOVERRIDE[')] == [
        'TLOVERRIDE[default]'
    ]


async def test_the_validation_phase_pins_the_limit_each_language_must_clear(
    testing_pkg, tmp_path, monkeypatch
):
    """Phase 2 passes one limit per language group, so the probe pins one each.

    `ceil(TL_lang x timeLimitToTle)` is the bound the slow solutions of that
    language have to survive, and it differs by group. Pinning any one of them
    for everybody would check the other languages against a bound nobody asked
    for -- and phase 2 reads the judge's own verdict at that bound.
    """
    minimal_package(testing_pkg)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    await MojRunner().prepare(
        _context(tmp_path, timelimit_override={'cpp': 150, 'java': 900})
    )

    conf = _conf(fake.uploaded)
    assert conf['TLOVERRIDE[cpp]'] == '0.150'
    # The loosest of them is the default: only a language the run did NOT name
    # falls back to it, and being generous there cannot truncate a measurement.
    assert conf['TLOVERRIDE[default]'] == '0.900'


async def test_the_no_override_sentinel_falls_back_to_the_inference_timeout(
    testing_pkg, tmp_path, monkeypatch
):
    """-1 is rbx's "no override" sentinel, and it is not a cap.

    No `rbx time` phase passes it any more -- both pin something real -- but any
    other caller of `run_solutions` may, and reading it as a cap would pin
    `TLOVERRIDE[default]=-0.001` and TLE every single measurement.
    """
    minimal_package(testing_pkg)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    await MojRunner().prepare(_context(tmp_path, timelimit_override=-1))

    # The estimation cap the problem configures, 10s by default: the limit rbx
    # itself enforces on a solution while estimating.
    assert _conf(fake.uploaded)['TLOVERRIDE[default]'] == '10.000'


async def test_an_absent_override_also_falls_back_rather_than_crashing(
    testing_pkg, tmp_path, monkeypatch
):
    """`RunContext.timelimit_override` is `Optional[int]`, so `None` is reachable."""
    minimal_package(testing_pkg)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    await MojRunner().prepare(_context(tmp_path, timelimit_override=None))

    assert _conf(fake.uploaded)['TLOVERRIDE[default]'] == '10.000'


async def test_a_formula_problem_falls_back_like_any_other(
    testing_pkg, tmp_path, monkeypatch
):
    """A formula defines no multipliers, but it does have an estimation cap.

    `inferenceTimeout` is a property of the estimation rather than of the
    multipliers and is resolved in both modes, so there is nothing left for the
    runner to refuse here -- which is what this pins. MOJ always enforces a
    limit, so a mode with genuinely nothing to fall back on would have to be
    refused rather than guessed at.
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

    await MojRunner().prepare(_context(tmp_path, timelimit_override=-1))

    assert _conf(fake.uploaded)['TLOVERRIDE[default]'] == '10.000'


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


async def test_a_solution_moj_cannot_run_is_refused_rather_than_left_out(
    testing_pkg, tmp_path, monkeypatch
):
    """A language with no MOJ counterpart stops the run, loudly and here.

    Leaving it out of the whitelist does not leave it out of the *run*: rbx would
    still testrun it and the API would reject the submission, so the failure
    would surface in task 6 as a server-side message about a language. And a
    solution that goes unmeasured is not a mere downgrade -- if it is a
    lower-bound solution, the time limit gets estimated from incomplete data with
    nothing saying so.
    """
    minimal_package(testing_pkg)
    env = environment.get_environment()
    # A language rbx knows and MOJ does not. Added to the environment rather than
    # faked at the mapping, so what the test exercises is the real
    # rbx-language -> MOJ-id lookup.
    nim = EnvironmentLanguage(
        name='nim',
        extension='nim',
        execution=ExecutionConfig(command='{executable}'),
    )
    monkeypatch.setattr(
        environment,
        'get_environment',
        lambda *args, **kwargs: env.model_copy(
            update={'languages': [*env.languages, nim]}
        ),
    )
    testing_pkg.add_solution('sol.nim', outcome=ExpectedOutcome.WRONG_ANSWER)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    with pytest.raises(MojRunnerError) as exc:
        await MojRunner().prepare(
            _context(
                tmp_path,
                solutions=[
                    ('sol.cpp', ExpectedOutcome.ACCEPTED),
                    ('sol.nim', ExpectedOutcome.WRONG_ANSWER),
                ],
            )
        )

    # Names the solution and its language: the two things the setter needs to
    # either exclude it or map the language.
    assert 'sol.nim' in str(exc.value)
    assert 'nim' in str(exc.value)
    assert fake.uploads == []


async def test_the_whitelist_covers_the_package_not_just_this_batch(
    testing_pkg, tmp_path, monkeypatch
):
    """The two `rbx time` phases track disjoint solution sets.

    Estimation tracks only the accepted solutions; validation only the ones
    expected to be too slow. A whitelist built from the *batch* would therefore
    be a different -- and, in the validation phase, a disjoint -- list each time.
    Two costs, both real: the package would fingerprint differently in each phase
    even when the limits did not move, spending an upload and a calibration on
    nothing; and a package that fingerprinted equal would leave the validation
    phase submitting slow solutions against the estimation phase's
    accepted-only whitelist, which the API refuses.
    """
    minimal_package(testing_pkg)
    testing_pkg.add_solution('slow.py', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    # The estimation phase: only the accepted solution is tracked.
    await MojRunner().prepare(
        _context(tmp_path, solutions=[('sol.cpp', ExpectedOutcome.ACCEPTED)])
    )

    meta = json.loads((fake.uploaded / '.moj-meta.json').read_text())
    # `slow.py` is not in this batch, and is whitelisted anyway.
    assert meta['languages'] == ['cpp', 'py']


async def test_a_language_only_an_untracked_solution_uses_is_skipped(
    testing_pkg, tmp_path, monkeypatch
):
    """Refusing is for a solution this batch actually runs.

    The rest of the package is a superset offered for free -- widening the
    whitelist costs nothing on a private `rbxt-` problem -- so failing the run
    over a solution it never touches would be refusing work nobody asked for.
    """
    minimal_package(testing_pkg)
    env = environment.get_environment()
    nim = EnvironmentLanguage(
        name='nim',
        extension='nim',
        execution=ExecutionConfig(command='{executable}'),
    )
    monkeypatch.setattr(
        environment,
        'get_environment',
        lambda *args, **kwargs: env.model_copy(
            update={'languages': [*env.languages, nim]}
        ),
    )
    testing_pkg.add_solution('sol.nim', outcome=ExpectedOutcome.WRONG_ANSWER)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    await MojRunner().prepare(
        _context(tmp_path, solutions=[('sol.cpp', ExpectedOutcome.ACCEPTED)])
    )

    meta = json.loads((fake.uploaded / '.moj-meta.json').read_text())
    assert meta['languages'] == ['cpp']


# -- what a probe path can still raise -----------------------------------------


async def test_a_package_the_setter_broke_is_not_a_cli_exit(
    testing_pkg, tmp_path, monkeypatch
):
    """`MojPackager` reports setter mistakes with `typer.Exit`.

    That is a CLI control-flow exception, and `prepare` is a library call reached
    from inside `run_solutions`: letting it through would unwind the run as if a
    command had ended, with an exit code nothing here chose and no error anyone
    can catch by type. A non-C++ checker is one of the sites a probe still
    reaches (`packaging/moj/CLAUDE.md`, "What a probe path can still raise") --
    the statement build, which is most of the others, is suppressed for a probe.
    """
    minimal_package(testing_pkg)
    testing_pkg.set_checker('check.py')
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    with pytest.raises(MojRunnerError) as exc:
        await MojRunner().prepare(_context(tmp_path))

    assert 'probe package' in str(exc.value)
    assert fake.uploads == []


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


async def test_an_upload_that_never_reached_calibration_is_not_trusted_later(
    testing_pkg, tmp_path, monkeypatch
):
    """The record is cleared *before* an upload, not merely written after one.

    A session that dies between the upload landing and the calibration finishing
    leaves the server holding a package rbx has no record of. If the run before
    it had left a record, and the setter then goes back to the earlier cap, the
    fingerprint matches that stale record -- and `moj check` may well still say
    ready, since it describes whatever the judge last calibrated. The fast path
    would then skip an upload and measure every solution against a package that
    is not the one it built.
    """
    minimal_package(testing_pkg)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    await MojRunner().prepare(_context(tmp_path, timelimit_override=2500))

    # A different cap, so the fast path does not fire: this one really uploads,
    # and then dies before the calibration is queued.
    fake.calibrate_fails = True
    with pytest.raises(MojCliError):
        await MojRunner().prepare(_context(tmp_path, timelimit_override=4000))

    # Back to the first cap, whose package the first run did upload and calibrate.
    fake.calibrate_fails = False
    await MojRunner().prepare(_context(tmp_path, timelimit_override=2500))

    assert len(fake.uploads) == 3
    assert _conf(fake.uploaded)['TLOVERRIDE[default]'] == '2.500'


# `run_solution` -- the testrun fan-out that used to raise here -- now exists, and
# is exercised in `test_run_solution.py` against the same `FakeMoj`.
