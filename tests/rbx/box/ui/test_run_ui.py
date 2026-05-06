"""Tests for path resolution in `rbx.box.ui.utils.run_ui`.

Regression coverage for the bug where ``get_solution_eval`` recomputed the
on-disk filename from the zero-padded testcase index, missing ``.eval`` files
written under the actual stem (e.g. ``1-gen-000.eval``) for tests generated
through subgroups.
"""

import pathlib

from rbx import utils
from rbx.box.environment import VerificationLevel
from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.schema import ExpectedOutcome, Solution, Testcase
from rbx.box.solutions import (
    SolutionReportSkeleton,
    SolutionSkeleton,
)
from rbx.box.testcase_schema import TestcaseEntry
from rbx.box.ui.utils.run_ui import get_solution_eval, get_solution_evals
from rbx.grading.limits import Limits
from rbx.grading.steps import (
    CheckerResult,
    Evaluation,
    Outcome,
    TestcaseIO,
    TestcaseLog,
)


def _make_skeleton(
    runs_dir: pathlib.Path,
    inputs_dir: pathlib.Path,
    stems: list[str],
    group: str = 'main',
) -> SolutionReportSkeleton:
    inputs_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for idx, stem in enumerate(stems):
        input_path = inputs_dir / f'{stem}.in'
        input_path.write_text('')
        entry = TestcaseEntry(group=group, index=idx)
        entries.append(
            GenerationTestcaseEntry(
                group_entry=entry,
                subgroup_entry=entry,
                metadata=GenerationMetadata(copied_to=Testcase(inputPath=input_path)),
            )
        )
    solution = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    return SolutionReportSkeleton(
        solutions=[SolutionSkeleton(**solution.model_dump(), runs_dir=runs_dir)],
        entries=entries,
        groups=[],
        limits={'cpp': Limits(time=1000, memory=256, profile=None, isDoubleTL=False)},
        compiled_solutions={'sol.cpp': 'digest'},
        verification=VerificationLevel.FULL,
    )


def _write_eval(prefix: pathlib.Path, outcome: Outcome) -> None:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    eval = Evaluation(
        result=CheckerResult(outcome=outcome),
        log=TestcaseLog(),
        testcase=TestcaseIO(index=0),
    )
    prefix.with_suffix('.eval').write_text(utils.model_to_yaml(eval))


def test_get_entry_stem_uses_actual_input_stem(tmp_path):
    skeleton = _make_skeleton(
        tmp_path / 'runs',
        tmp_path / 'tests',
        stems=['1-gen-000', '1-gen-001'],
    )
    entry = TestcaseEntry(group='main', index=0)
    assert skeleton.get_entry_stem(entry) == '1-gen-000'


def test_get_entry_stem_falls_back_to_zero_padded_index(tmp_path):
    skeleton = _make_skeleton(
        tmp_path / 'runs',
        tmp_path / 'tests',
        stems=['1-gen-000'],
    )
    # Entry not present in skeleton.entries -> legacy fallback.
    missing = TestcaseEntry(group='other', index=7)
    assert skeleton.get_entry_stem(missing) == '007'


def test_get_solution_eval_reads_subgroup_stem(tmp_path):
    skeleton = _make_skeleton(
        tmp_path / 'runs',
        tmp_path / 'tests',
        stems=['1-gen-000'],
    )
    sol = skeleton.solutions[0]
    _write_eval(sol.runs_dir / 'main' / '1-gen-000', Outcome.WRONG_ANSWER)

    eval = get_solution_eval(skeleton, sol, TestcaseEntry(group='main', index=0))
    assert eval is not None
    assert eval.result.outcome == Outcome.WRONG_ANSWER


def test_get_solution_eval_reads_legacy_numeric_stem(tmp_path):
    skeleton = _make_skeleton(
        tmp_path / 'runs',
        tmp_path / 'tests',
        stems=['000', '001'],
    )
    sol = skeleton.solutions[0]
    _write_eval(sol.runs_dir / 'main' / '001', Outcome.ACCEPTED)

    eval = get_solution_eval(skeleton, sol, TestcaseEntry(group='main', index=1))
    assert eval is not None
    assert eval.result.outcome == Outcome.ACCEPTED


def test_get_solution_evals_finds_all_for_subgroup_stems(tmp_path):
    skeleton = _make_skeleton(
        tmp_path / 'runs',
        tmp_path / 'tests',
        stems=['1-gen-000', '1-gen-001'],
    )
    sol = skeleton.solutions[0]
    _write_eval(sol.runs_dir / 'main' / '1-gen-000', Outcome.ACCEPTED)
    _write_eval(sol.runs_dir / 'main' / '1-gen-001', Outcome.WRONG_ANSWER)

    evals = get_solution_evals(skeleton, sol)
    assert [e.result.outcome for e in evals if e is not None] == [
        Outcome.ACCEPTED,
        Outcome.WRONG_ANSWER,
    ]
    assert all(e is not None for e in evals)
