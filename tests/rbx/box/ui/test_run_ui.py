"""Tests for path resolution in `rbx.box.ui.utils.run_ui`.

Regression coverage for the bug where ``get_solution_eval`` recomputed the
on-disk filename from the zero-padded testcase index, missing ``.eval`` files
written under the actual stem (e.g. ``1-gen-000.eval``) for tests generated
through subgroups.
"""

import pathlib
from unittest import mock

from rbx import utils
from rbx.box.environment import VerificationLevel
from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.schema import ExpectedOutcome, ScoreType, Solution, Testcase
from rbx.box.solutions import (
    SolutionReportSkeleton,
    SolutionSkeleton,
)
from rbx.box.testcase_schema import TestcaseEntry
from rbx.box.ui.utils.run_ui import (
    get_entries_options,
    get_main_badge,
    get_skeleton,
    get_solution_eval,
    get_solution_evals,
    get_solution_markup,
    has_run,
    is_main_solution,
)
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


def _entry(group: str, index: int) -> GenerationTestcaseEntry:
    te = TestcaseEntry(group=group, index=index)
    return GenerationTestcaseEntry(
        group_entry=te,
        subgroup_entry=te,
        metadata=GenerationMetadata(
            copied_to=Testcase(inputPath=pathlib.Path(f'{group}-{index}.in'))
        ),
    )


def test_entries_options_align_with_optionlist_indices():
    """Regression for #464.

    ``OptionList.highlighted`` indexes into the *options-only* list that
    Textual builds: a ``None`` separator does not occupy an index, it just
    turns the preceding option into a divider. The parallel ``expanded_entries``
    list returned by ``get_entries_options`` must therefore align 1:1 with the
    real ``OptionList._options`` so highlighting maps to the right testcase.
    """
    from textual.widgets import OptionList

    entries = [
        _entry('group-a', 0),
        _entry('group-a', 1),
        _entry('group-b', 0),
        _entry('group-b', 1),
    ]

    options, expanded_entries = get_entries_options(entries)

    option_list = OptionList(*options)

    # One expanded-entry slot per real option Textual tracks.
    assert len(expanded_entries) == option_list.option_count

    # Every selectable (non-disabled) option must map to a real entry, and
    # those entries must appear in the original order.
    selectable_entries = [
        expanded_entries[i]
        for i in range(option_list.option_count)
        if not option_list.get_option_at_index(i).disabled
    ]
    assert selectable_entries == entries


def test_predicate_filters_entries_and_keeps_alignment_across_groups():
    """#464: expanded_entries stays aligned with OptionList indices after filtering."""
    from textual.widgets import OptionList

    entries = [
        _entry('group-a', 0),
        _entry('group-a', 1),
        _entry('group-b', 0),
        _entry('group-b', 1),
    ]
    # Keep only index 1 of every group.
    keep = {
        (e.group_entry.group, e.group_entry.index) for e in (entries[1], entries[3])
    }
    options, expanded_entries = get_entries_options(
        entries,
        predicate=lambda e: (e.group_entry.group, e.group_entry.index) in keep,
    )

    option_list = OptionList(*options)
    assert len(expanded_entries) == option_list.option_count

    selectable = [
        expanded_entries[i]
        for i in range(option_list.option_count)
        if not option_list.get_option_at_index(i).disabled
    ]
    assert selectable == [entries[1], entries[3]]


def test_predicate_emptying_a_group_drops_its_header_and_divider():
    from textual.widgets import OptionList

    entries = [_entry('group-a', 0), _entry('group-b', 0)]
    # Drop group-b entirely.
    options, expanded_entries = get_entries_options(
        entries, predicate=lambda e: e.group_entry.group == 'group-a'
    )
    option_list = OptionList(*options)
    header_texts = [
        option_list.get_option_at_index(i).prompt
        for i in range(option_list.option_count)
        if option_list.get_option_at_index(i).disabled
    ]
    rendered = ' '.join(str(t) for t in header_texts)
    assert 'group-a' in rendered
    assert 'group-b' not in rendered
    # No divider/entry slot leaked for the dropped group.
    assert all(e is None or e.group_entry.group == 'group-a' for e in expanded_entries)


def test_predicate_recomputes_points_total_over_visible_groups(tmp_path):
    from rbx.box.solutions import GroupSkeleton

    entries = [_entry('g1', 0), _entry('g2', 0)]
    skeleton = _make_skeleton(tmp_path / 'runs', tmp_path / 'tests', stems=['g1-0'])
    skeleton.groups = [
        GroupSkeleton(name='g1', score=50, deps=[], testcases=[]),
        GroupSkeleton(name='g2', score=50, deps=[], testcases=[]),
    ]
    sol = skeleton.solutions[0]

    fake_report = mock.Mock()
    fake_report.gotScorePerGroup = {'g1': 50, 'g2': 50}
    with mock.patch(
        'rbx.box.ui.utils.run_ui.get_solution_outcome_report', return_value=fake_report
    ):
        options, _ = get_entries_options(
            entries,
            skeleton=skeleton,
            solution=sol,
            predicate=lambda e: e.group_entry.group == 'g1',
        )

    texts = ' '.join(str(o.prompt) for o in options if hasattr(o, 'prompt'))
    # TOTAL reflects only the visible group's score (50/50), not 100.
    assert 'TOTAL' in texts
    assert '100' not in texts


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


def _solution(path: str, outcome=ExpectedOutcome.ACCEPTED) -> Solution:
    return Solution(path=pathlib.Path(path), outcome=outcome)


def test_is_main_solution_true_for_the_main_solution():
    sol = _solution('sol.cpp')
    with mock.patch('rbx.box.package.get_main_solution', return_value=sol):
        assert is_main_solution(sol) is True


def test_is_main_solution_false_for_a_different_solution():
    main = _solution('main.cpp')
    other = _solution('other.cpp')
    with mock.patch('rbx.box.package.get_main_solution', return_value=main):
        assert is_main_solution(other) is False


def test_is_main_solution_false_when_there_is_no_main():
    sol = _solution('sol.cpp')
    with mock.patch('rbx.box.package.get_main_solution', return_value=None):
        assert is_main_solution(sol) is False


def test_get_main_badge_marks_only_the_main_solution():
    main = _solution('main.cpp')
    other = _solution('other.cpp')
    with mock.patch('rbx.box.package.get_main_solution', return_value=main):
        assert 'MAIN' in get_main_badge(main)
        assert get_main_badge(other) == ''


def test_get_solution_markup_marks_the_main_solution(tmp_path):
    skeleton = _make_skeleton(
        tmp_path / 'runs', tmp_path / 'tests', stems=['1-gen-000']
    )
    sol = skeleton.solutions[0]
    with (
        mock.patch('rbx.box.package.get_main_solution', return_value=sol),
        mock.patch('rbx.box.package.get_scoring', return_value=ScoreType.BINARY),
    ):
        markup = get_solution_markup(skeleton, sol)
    assert 'MAIN' in markup


def test_get_solution_markup_omits_badge_for_non_main_solution(tmp_path):
    skeleton = _make_skeleton(
        tmp_path / 'runs', tmp_path / 'tests', stems=['1-gen-000']
    )
    sol = skeleton.solutions[0]
    with (
        mock.patch(
            'rbx.box.package.get_main_solution', return_value=_solution('other.cpp')
        ),
        mock.patch('rbx.box.package.get_scoring', return_value=ScoreType.BINARY),
    ):
        markup = get_solution_markup(skeleton, sol)
    assert 'MAIN' not in markup


def test_solution_selection_label_marks_main_with_badge_not_outcome():
    from rbx.box.ui.screens.run import _build_solution_selection_label

    main = _solution('main.cpp')
    with mock.patch('rbx.box.package.get_main_solution', return_value=main):
        label = _build_solution_selection_label(main).plain
    assert 'MAIN' in label
    # The main solution shows the badge in place of its raw outcome name.
    assert 'ACCEPTED' not in label


def test_solution_selection_label_shows_outcome_for_non_main():
    from rbx.box.ui.screens.run import _build_solution_selection_label

    other = _solution('other.cpp', outcome=ExpectedOutcome.WRONG_ANSWER)
    with mock.patch(
        'rbx.box.package.get_main_solution', return_value=_solution('main.cpp')
    ):
        label = _build_solution_selection_label(other).plain
    assert 'MAIN' not in label
    assert 'WRONG_ANSWER' in label


def test_get_skeleton_returns_none_when_no_run(tmp_path):
    """Regression for #554: a missing skeleton.yml must not raise.

    Without a past ``rbx run`` there is no ``skeleton.yml`` on disk.
    ``get_skeleton`` used to call ``read_text`` unconditionally and raise
    ``FileNotFoundError``, crashing the run explorer. It now returns ``None``.
    """
    runs_dir = tmp_path / 'runs'
    runs_dir.mkdir()
    with mock.patch('rbx.box.package.get_problem_runs_dir', return_value=runs_dir):
        assert has_run() is False
        assert get_skeleton() is None


def test_get_skeleton_loads_skeleton_when_present(tmp_path):
    runs_dir = tmp_path / 'runs'
    runs_dir.mkdir()
    skeleton = _make_skeleton(runs_dir, tmp_path / 'tests', stems=['1-gen-000'])
    (runs_dir / 'skeleton.yml').write_text(utils.model_to_yaml(skeleton))
    with mock.patch('rbx.box.package.get_problem_runs_dir', return_value=runs_dir):
        assert has_run() is True
        assert get_skeleton() == skeleton
