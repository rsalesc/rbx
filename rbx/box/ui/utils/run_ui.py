import collections
import typing
from typing import Dict, List, Optional, Tuple, Union

from textual.visual import VisualType
from textual.widgets.option_list import Option

from rbx import console, utils
from rbx.box import package, solutions
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.solutions import SolutionReportSkeleton, SolutionSkeleton
from rbx.box.testcase_schema import TestcaseEntry
from rbx.grading.steps import Evaluation


def has_run() -> bool:
    return (package.get_problem_runs_dir() / 'skeleton.yml').is_file()


def get_skeleton() -> SolutionReportSkeleton:
    skeleton_path = package.get_problem_runs_dir() / 'skeleton.yml'
    return utils.model_from_yaml(
        SolutionReportSkeleton,
        skeleton_path.read_text(),
    )


def get_solution_eval(
    solution: SolutionSkeleton, entry: TestcaseEntry
) -> Optional[Evaluation]:
    path = solution.get_entry_prefix(entry).with_suffix('.eval')
    if not path.is_file():
        return None
    return utils.model_from_yaml(Evaluation, path.read_text())


def get_solution_evals(
    skeleton: SolutionReportSkeleton, solution: SolutionSkeleton
) -> List[Optional[Evaluation]]:
    return [
        get_solution_eval(solution, entry.group_entry) for entry in skeleton.entries
    ]


def get_solution_evals_or_null(
    skeleton: SolutionReportSkeleton, solution: SolutionSkeleton
) -> Optional[List[Evaluation]]:
    evals = get_solution_evals(skeleton, solution)
    if any(e is None for e in evals):
        return None
    return typing.cast(List[Evaluation], evals)


def get_entries_per_group(
    entries: List[GenerationTestcaseEntry],
) -> Dict[str, List[GenerationTestcaseEntry]]:
    res = collections.OrderedDict()
    for entry in entries:
        if entry.group_entry.group not in res:
            res[entry.group_entry.group] = []
        res[entry.group_entry.group].append(entry)
    return res


def get_entries_options(
    entries: List[GenerationTestcaseEntry],
    solution: Optional[SolutionSkeleton] = None,
) -> Tuple[
    List[Union[VisualType, Option, None]], List[Optional[GenerationTestcaseEntry]]
]:
    entries_per_group = get_entries_per_group(entries)
    options = []
    expanded_entries = []

    def _add(
        renderable: Union[VisualType, Option, None],
        entry: Optional[GenerationTestcaseEntry] = None,
    ):
        expanded_entries.append(entry)
        options.append(renderable)

    for group, entries in entries_per_group.items():
        _add(Option(console.expand_markup(f'[b]{group}[/b]'), disabled=True))
        for entry in entries:
            if solution is not None:
                _add(
                    console.expand_markup(get_run_testcase_markup(solution, entry)),
                    entry,
                )
            else:
                _add(console.expand_markup(f'{entry}'), entry)
        _add(None)
    return options, expanded_entries


def get_solution_markup(
    skeleton: SolutionReportSkeleton, solution: SolutionSkeleton
) -> str:
    header = solution.display()

    evals = get_solution_evals_or_null(skeleton, solution)
    report = solutions.get_solution_outcome_report(
        solution, skeleton, evals or [], skeleton.verification, subset=False
    )
    if evals is None:
        return header + '\n' + report.get_verdict_markup(incomplete=True)
    return (
        header + '\n' + report.get_outcome_markup(skeleton=skeleton, print_scoring=True)
    )


def get_run_testcase_markup(
    solution: SolutionSkeleton, entry: GenerationTestcaseEntry
) -> str:
    eval = get_solution_eval(solution, entry.group_entry)
    if eval is None:
        return f'{entry}'
    testcase_markup = solutions.get_testcase_markup_verdict(eval)
    return f'{testcase_markup} {entry}'


def _get_checker_msg_last_line(eval: Evaluation) -> Optional[str]:
    if eval.result.message is None:
        return None
    return eval.result.message.rstrip().split('\n')[-1]


def get_run_testcase_metadata_markup(
    skeleton: SolutionReportSkeleton, solution: SolutionSkeleton, entry: TestcaseEntry
) -> Optional[str]:
    eval = get_solution_eval(solution, entry)
    if eval is None:
        return None
    limits = skeleton.get_solution_limits(solution)
    time_str = solutions.get_capped_evals_formatted_time(
        limits, [eval], skeleton.verification
    )
    memory_str = solutions.get_evals_formatted_memory([eval])

    checker_msg = _get_checker_msg_last_line(eval)

    lines = []
    lines.append(
        f'[b]{solutions.get_full_outcome_markup_verdict(eval.result.outcome)}[/b]'
    )
    lines.append(f'[b]Time:[/b] {time_str} / [b]Memory:[/b] {memory_str}')
    if checker_msg is not None:
        lines.append(f'[b]Checker:[/b] {utils.escape_markup(checker_msg)}')
    return '\n'.join(lines)
