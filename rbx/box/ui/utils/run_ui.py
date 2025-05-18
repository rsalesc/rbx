import typing
from typing import List, Optional

from rbx import utils
from rbx.box import package, solutions
from rbx.box.solutions import SolutionReportSkeleton, SolutionSkeleton
from rbx.box.testcase_extractors import GenerationTestcaseEntry
from rbx.box.testcase_utils import TestcaseEntry
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
    return [get_solution_eval(solution, entry) for entry in skeleton.entries]


def get_solution_evals_or_null(
    skeleton: SolutionReportSkeleton, solution: SolutionSkeleton
) -> Optional[List[Evaluation]]:
    evals = get_solution_evals(skeleton, solution)
    if any(e is None for e in evals):
        return None
    return typing.cast(List[Evaluation], evals)


def get_solution_markup(
    skeleton: SolutionReportSkeleton, solution: SolutionSkeleton
) -> str:
    header = f'[b $accent]{solution.path}[/b $accent] ({solution.path})'

    evals = get_solution_evals_or_null(skeleton, solution)
    report = solutions.get_solution_outcome_report(
        solution, evals or [], skeleton.verification, subset=False
    )
    if evals is None:
        return header + '\n' + report.get_verdict_markup(incomplete=True)
    return header + '\n' + report.get_outcome_markup()


def get_run_testcase_markup(solution: SolutionSkeleton, entry: TestcaseEntry) -> str:
    eval = get_solution_eval(solution, entry)
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
    time_str = solutions.get_capped_evals_formatted_time(
        solution, [eval], skeleton.verification
    )
    memory_str = solutions.get_evals_formatted_memory([eval])

    checker_msg = _get_checker_msg_last_line(eval)

    lines = []
    lines.append(
        f'[b]{solutions.get_full_outcome_markup_verdict(eval.result.outcome)}[/b]'
    )
    lines.append(f'[b]Time:[/b] {time_str} / [b]Memory:[/b] {memory_str}')
    if checker_msg is not None:
        lines.append(f'[b]Checker:[/b] {checker_msg}')
    return '\n'.join(lines)


def get_metadata_markup(entry: GenerationTestcaseEntry) -> str:
    lines = []
    lines.append(f'[b]{entry.group_entry.group}[/b] / [b]{entry.group_entry.index}[/b]')
    if entry.metadata.copied_from is not None:
        lines.append(f'[b]Copied from:[/b] {entry.metadata.copied_from.inputPath}')
    if entry.metadata.generator_call is not None:
        lines.append(f'[b]Gen. call:[/b] {entry.metadata.generator_call}')
    if entry.metadata.generator_script is not None:
        lines.append(f'[b]Gen. script:[/b] {entry.metadata.generator_script}')
    return '\n'.join(lines)
