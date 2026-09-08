"""A DOMjudge that answers, minus the DOMjudge.

The runner's other tests are unit-level -- they drive `_Judging`, `staging` and
the API wrapper directly. The cache is not testable that way: what it claims is
about *whole runs*, and specifically about what the second one does. So this
fixes the API at its own boundary (`DomjudgeApi`, faked wholesale) and drives
`prepare` / `run_solution` / `close` for real, package build included.

Nothing here touches the network.
"""

import asyncio
import pathlib
from typing import Any, Dict, List, Optional, Tuple, Union

import pytest

from rbx.box import header
from rbx.box.environment import VerificationLevel
from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.runners.base import RunContext, RunPurpose
from rbx.box.runners.domjudge import runner as runner_module
from rbx.box.runners.domjudge.api import Credentials
from rbx.box.runners.domjudge.runner import DomjudgeRunner
from rbx.box.schema import ExpectedOutcome, Testcase
from rbx.box.solutions import SolutionReportSkeleton, SolutionSkeleton
from rbx.box.testcase_schema import TestcaseEntry
from rbx.grading.limits import Limits

CHECKER = '#include "testlib.h"\nint main(){ quitf(_ok, "ok"); }\n'
ACCEPTED_SOL = 'int main(){ return 0; }\n'

SERVER = 'http://domjudge.test'


def run(ordinal: int, verdict: str = 'AC', run_time: float = 0.1) -> Dict[str, Any]:
    """One judging run, in the shape `/judgements/{id}/runs` returns."""
    return {
        'id': str(ordinal),
        'ordinal': ordinal,
        'judgement_type_id': verdict,
        'run_time': run_time,
    }


class FakeApi:
    """One DOMjudge instance that judges whatever it is told to judge.

    Every submission is answered from `results`, keyed by the *filename* rbx
    submits under -- which is the solution's own name, so a test says
    `fake.results['sol.cpp'] = [...]` and means it.

    The list of submissions is the assertion in almost every test here: the whole
    claim of the cache is which submissions a second run does *not* make.
    """

    def __init__(self, entries: int = 2, server: str = SERVER):
        # An instance attribute, not a constant: the upload record is keyed by
        # server, so a test has to be able to be a *different* instance.
        self.server = server
        self._entries = entries
        # filename -> the runs the judgehost reports for it. Absent means "all
        # accepted", which is what a test that does not care wants.
        self.results: Dict[str, List[Dict[str, Any]]] = {}
        # filename -> the run-level verdict, when it is not derived from the runs.
        # A compile error is the case that needs it: no runs, and a `CE`.
        self.verdicts: Dict[str, str] = {}
        # (submission id, filename), in submission order.
        self.submissions: List[Tuple[str, str]] = []
        self.uploads: List[str] = []
        self.staged: List[str] = []
        self._problems: List[Dict[str, Any]] = []
        self._contests: List[Dict[str, Any]] = []
        # Set to make every submission hang inside the concurrency slot, which is
        # how a test keeps one occupied while another solution is dispatched.
        self.hold: Optional[asyncio.Event] = None

    def install(self, monkeypatch: pytest.MonkeyPatch) -> 'FakeApi':
        monkeypatch.setattr(
            runner_module,
            'credentials_from_env',
            lambda: Credentials(server=self.server, username='jury', password='jury'),
        )
        monkeypatch.setattr(runner_module, 'DomjudgeApi', lambda credentials: self)
        return self

    # -- preflight and staging ------------------------------------------------

    async def version(self) -> Dict[str, Any]:
        return {'api_version': 4}

    async def config(self) -> Dict[str, Any]:
        return {}

    async def judgehosts(self) -> List[Dict[str, Any]]:
        return [{'id': '1', 'enabled': True, 'polltime': str(2**31)}]

    async def contests(self) -> List[Dict[str, Any]]:
        return list(self._contests)

    async def create_contest(self, contest: Dict[str, Any]) -> str:
        self._contests.append({'id': contest['id']})
        return contest['id']

    async def teams(self) -> List[Dict[str, Any]]:
        return [{'id': 'domjudge'}]

    async def languages(self, contest: str) -> List[Dict[str, Any]]:
        return [{'id': 'cpp', 'extensions': ['cpp', 'cc', 'cxx']}]

    async def problems(self, contest: str) -> List[Dict[str, Any]]:
        return list(self._problems)

    async def add_problem_data(self, contest, problem_id, label, name):
        self._problems.append({'id': problem_id})
        return [problem_id]

    async def upload_problem(self, contest, problem_id, zip_path):
        self.uploads.append(problem_id)
        return {'problem_id': problem_id}

    async def unlink_problem(self, contest, problem_id) -> None:
        return None

    async def link_problem(self, contest, problem_id, label, lazy_eval_results):
        self.staged.append(problem_id)
        return {'id': problem_id}

    # -- submitting and judging -----------------------------------------------

    async def submit(
        self, contest, problem_id, language_id, team_id, filename, source
    ) -> Dict[str, Any]:
        if self.hold is not None:
            await self.hold.wait()
        submission_id = str(len(self.submissions) + 1)
        self.submissions.append((submission_id, filename))
        return {'id': submission_id}

    async def judgements(self, contest, submission) -> List[Dict[str, Any]]:
        filename = dict(self.submissions)[submission]
        return [
            {
                'id': submission,
                'submission_id': submission,
                'judgement_type_id': self._verdict(filename),
                # Judged in one poll: what these tests are about is which
                # submissions happen, not how a judging is watched -- which
                # `test_pairing.py` covers on `_Judging` directly.
                'end_time': '2026-09-08T12:00:00+00:00',
                'max_run_time': 0.2,
            }
        ]

    async def runs(self, contest, judgement) -> List[Dict[str, Any]]:
        return list(self._runs_for(dict(self.submissions)[judgement]))

    def _runs_for(self, filename: str) -> List[Dict[str, Any]]:
        if filename in self.results:
            return self.results[filename]
        return [run(ordinal) for ordinal in range(1, self._entries + 1)]

    def _verdict(self, filename: str) -> str:
        if filename in self.verdicts:
            return self.verdicts[filename]
        verdicts = [
            str(item.get('judgement_type_id')) for item in self._runs_for(filename)
        ]
        return next((item for item in verdicts if item != 'AC'), 'AC')

    def forget_problems(self) -> None:
        """Drop every problem, as a wiped instance or a hand-deleted probe would.

        The contest is left alone: what this models is somebody removing the
        probe problem, not the whole server going away.
        """
        self._problems.clear()

    # -- what a test asserts on -----------------------------------------------

    @property
    def submitted(self) -> List[str]:
        """The filename of every submission made, in order."""
        return [filename for _, filename in self.submissions]


def entry(
    tmp_path: pathlib.Path, group: str, index: int, content: str
) -> GenerationTestcaseEntry:
    """A built testcase entry backed by real files.

    The packager only requires that `copied_to.inputPath` exists, so it can be
    exercised without a full sandboxed build.
    """
    group_dir = tmp_path / 'built' / group
    group_dir.mkdir(parents=True, exist_ok=True)
    input_path = group_dir / f'{index:03d}.in'
    output_path = group_dir / f'{index:03d}.out'
    input_path.write_text(content)
    output_path.write_text('42\n')
    testcase_entry = TestcaseEntry(group=group, index=index)
    return GenerationTestcaseEntry(
        group_entry=testcase_entry,
        subgroup_entry=testcase_entry,
        metadata=GenerationMetadata(
            copied_to=Testcase(inputPath=input_path, outputPath=output_path)
        ),
    )


def build_entries(
    tmp_path: pathlib.Path, groups: Optional[List[str]] = None
) -> List[GenerationTestcaseEntry]:
    return [
        entry(tmp_path, group, index, f'{group} {index}\n')
        for group in (groups or ['samples'])
        for index in range(2)
    ]


def minimal_package(
    testing_pkg, solutions: Optional[List[Tuple[str, ExpectedOutcome]]] = None
) -> None:
    """The smallest package the DOMjudge packager will build: a checker and a
    solution per declared entry."""
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    for path, outcome in solutions or [('sol.cpp', ExpectedOutcome.ACCEPTED)]:
        testing_pkg.add_solution(path, outcome=outcome.value).write_text(ACCEPTED_SOL)
    testing_pkg.save()
    header.generate_header()


def limits_for(
    timelimit_override: Optional[Union[int, Dict[str, int]]],
) -> Dict[str, Limits]:
    """The per-language limits `_get_report_skeleton` would have resolved.

    The runner pins the probe package's limit from these, so a context built by
    hand has to carry what a real run does -- an empty table would make packages
    that should differ compare equal, which is precisely what the cache keys on.
    """
    if isinstance(timelimit_override, dict):
        return {
            language: Limits(time=limit_ms)
            for language, limit_ms in timelimit_override.items()
        }
    if isinstance(timelimit_override, int) and timelimit_override > 0:
        return {'cpp': Limits(time=timelimit_override)}
    return {'cpp': Limits(time=1000)}


def purpose_for(
    timelimit_override: Optional[Union[int, Dict[str, int]]],
) -> RunPurpose:
    """The purpose the caller that passes this override would have declared."""
    if isinstance(timelimit_override, dict):
        return RunPurpose.VALIDATION
    if isinstance(timelimit_override, int) and timelimit_override > 0:
        return RunPurpose.ESTIMATION
    return RunPurpose.RUN


def context(
    tmp_path: pathlib.Path,
    solutions: Optional[List[Tuple[str, ExpectedOutcome]]] = None,
    entries: Optional[List[GenerationTestcaseEntry]] = None,
    timelimit_override: Optional[Union[int, Dict[str, int]]] = -1,
    purpose: Optional[RunPurpose] = None,
) -> RunContext:
    """A `RunContext` carrying what `prepare` and `run_solution` read.

    `timelimit_override` defaults to **-1**, rbx's "no override" sentinel, and
    the limits and the purpose are derived from it exactly as the caller that
    passes that shape would have set them.
    """
    if solutions is None:
        solutions = [('sol.cpp', ExpectedOutcome.ACCEPTED)]
    if entries is None:
        entries = build_entries(tmp_path)
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
        limits=limits_for(timelimit_override),
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
        purpose=purpose_for(timelimit_override) if purpose is None else purpose,
    )


async def time_run(ctx: RunContext) -> Dict[str, List]:
    """One whole `rbx time` run: prepare, then every solution to completion."""
    runner = DomjudgeRunner()
    await runner.prepare(ctx)
    try:
        evaluations = {}
        for solution in ctx.skeleton.solutions:
            deferreds = runner.run_solution(solution, ctx.skeleton.entries, ctx)
            evaluations[str(solution.path)] = [
                await asyncio.wait_for(deferred(), timeout=10) for deferred in deferreds
            ]
        return evaluations
    finally:
        await runner.close()
