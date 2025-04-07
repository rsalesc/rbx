import atexit
import pathlib
import tempfile
from typing import Dict, List, Optional

import syncer
from rich.columns import Columns
from rich.panel import Panel
from rich.progress import MofNCompleteColumn, Progress, SpinnerColumn
from rich.text import Text

from rbx import annotations, config, grading_utils, metadata, testcase_rendering
from rbx.config import Language, get_config
from rbx.console import console, multiline_prompt
from rbx.grading import steps
from rbx.grading.judge.sandbox import SandboxBase
from rbx.grading.judge.sandboxes import stupid_sandbox
from rbx.schema import DumpedProblem, Problem


def get_testcase_index(path: pathlib.Path) -> int:
    return int(path.stem.split('.')[-1])


def get_testcases_io(
    problem: DumpedProblem, root: pathlib.Path = pathlib.Path()
) -> List[steps.TestcaseIO]:
    testcases_per_index: Dict[int, steps.TestcaseIO] = {}
    for input_file in root.glob(f'{problem.code}.*.in'):
        try:
            index = get_testcase_index(input_file)
        except ValueError:
            continue
        testcases_per_index[index] = steps.TestcaseIO(index=index, input=input_file)

    for output_file in root.glob(f'{problem.code}.*.out'):
        index = get_testcase_index(output_file)
        try:
            index = get_testcase_index(output_file)
        except ValueError:
            continue
        if index in testcases_per_index:
            testcases_per_index[index].output = output_file
            continue
        testcases_per_index[index] = steps.TestcaseIO(index=index, output=output_file)

    return sorted(testcases_per_index.values(), key=lambda x: x.index)


async def _run_testcases(
    problem: Problem,
    lang: Language,
    lang_name: Optional[str],
    sandbox: SandboxBase,
    testcases: List[steps.TestcaseIO],
    persist_root: pathlib.Path = pathlib.Path(),
) -> Dict[int, Optional[steps.TestcaseLog]]:
    logs: Dict[int, Optional[steps.TestcaseLog]] = {}

    # Ensure persist dir exists.
    persist_root.mkdir(parents=True, exist_ok=True)

    progress = Progress(
        SpinnerColumn(),
        *Progress.get_default_columns(),
        MofNCompleteColumn(),
        transient=True,
    )
    with progress:
        for testcase in progress.track(testcases, description='Running testcases...'):
            params = grading_utils.build_run_sandbox_params(
                problem, testcase.input is not None
            )
            artifacts = grading_utils.build_run_grading_artifacts(
                testcase, persist_root
            )
            run_log = await steps.run(
                lang.exec,
                params,
                sandbox,
                artifacts,
                metadata=steps.RunLogMetadata(language=lang_name),
            )
            if not run_log:
                logs[testcase.index] = None
                continue
            logs[testcase.index] = steps.TestcaseLog(
                **run_log.__dict__,
                stdout_absolute_path=persist_root / f'stdout-{testcase.index}.txt',
                stderr_absolute_path=persist_root / f'stderr-{testcase.index}.txt',
            )

    return logs


def _evaluate_testcases(
    problem: DumpedProblem,
    sandbox: SandboxBase,
    testcases: List[steps.TestcaseIO],
    testcase_logs: Dict[int, Optional[steps.TestcaseLog]],
    persist_root: pathlib.Path = pathlib.Path(),
) -> List[steps.Evaluation]:
    evaluations = []
    artifacts = grading_utils.build_checker_run_grading_artifacts(
        problem,
        persist_root,
    )
    for testcase in testcases:
        if testcase.index not in testcase_logs:
            continue

        log = testcase_logs[testcase.index]
        evaluations.append(
            steps.evaluate(
                sandbox,
                testcase,
                log,
                artifacts,
                should_use_python_checker=not problem.checker,
            )
        )

    return evaluations


def _pretty_print_output_on_panel(file: Optional[pathlib.Path], title: str) -> Panel:
    if not file:
        return Panel('[error]No file to read from.[/error]', title=title, expand=False)
    return Panel(
        testcase_rendering.render_from_file(file),
        title=title,
        expand=False,
    )


def _pretty_print_side_by_side(result: steps.Evaluation):
    if not result.testcase.output:
        return _pretty_print_output_on_panel(result.log.stdout_absolute_path, 'Output')
    return Columns(
        [
            _pretty_print_output_on_panel(result.testcase.output, 'Expected'),
            _pretty_print_output_on_panel(result.log.stdout_absolute_path, 'Actual'),
        ],
        equal=True,
        expand=False,
    )


def _get_outcome_style(outcome: steps.Outcome) -> str:
    if outcome == steps.Outcome.ACCEPTED:
        return 'success'
    if outcome == steps.Outcome.JUDGE_FAILED or outcome == steps.Outcome.INTERNAL_ERROR:
        return 'warning'
    return 'error'


def _pretty_print_outcome_panel(
    problem: DumpedProblem, eval: steps.Evaluation
) -> Panel:
    result: steps.CheckerResult = eval.result
    is_tle = result.outcome == steps.Outcome.TIME_LIMIT_EXCEEDED or (
        problem.timeLimit and eval.log.time * 1000 > problem.timeLimit
    )

    text = Text()
    text.append('Outcome: ')
    text.append(
        result.outcome.value,
        style=_get_outcome_style(result.outcome),
    )
    text.append(' ' * 4)
    text.append('Time: ')
    text.append(f'{eval.log.time:.2f}s', style='error' if is_tle else 'item')
    text.append('\n')
    if eval.testcase.input:
        text.append(f'Input path: {eval.testcase.input.absolute()}')
        text.append('\n')
    if eval.testcase.output:
        text.append(f'Expected path: {eval.testcase.output.absolute()}')
        text.append('\n')
    text.append(f'Answer path: {eval.log.stdout_absolute_path}')
    return Panel(
        text,
        title=f'[bold]Testcase [item]#{eval.testcase.index}[/item]',
        expand=False,
    )


def _pretty_print_evaluation_result(
    problem: DumpedProblem,
    eval: steps.Evaluation,
    interactive: bool = False,
):
    console.print(_pretty_print_outcome_panel(problem, eval))
    if eval.result.outcome != steps.Outcome.ACCEPTED:
        if interactive:
            console.print(
                _pretty_print_output_on_panel(eval.log.stdout_absolute_path, 'Output')
            )
        else:
            console.print(_pretty_print_side_by_side(eval))
        if eval.result.message:
            console.print(
                f'[error]Checker message:[/error] {eval.result.message.strip()}'
            )
    console.print()


def pretty_print_summary(
    problem: DumpedProblem,
    lang: Language,
    evals: List[steps.Evaluation],
    root: pathlib.Path = pathlib.Path(),
):
    submission_file = root / lang.get_submit_file(problem.code)
    passed = sum(1 for eval in evals if eval.result.outcome == steps.Outcome.ACCEPTED)
    total = len(evals)
    console.print(f'Summary for problem [item]{problem.pretty_name()}[/item]:')

    # Test summary.
    text = Text()
    text.append('Passed tests: ')
    text.append(f'{passed}/{total}', style='success' if passed == total else 'error')
    console.print(text)

    console.print(f'Submission file: {submission_file.absolute()}')


def pretty_print_evaluation_results(
    problem: DumpedProblem,
    evals: List[steps.Evaluation],
    interactive: bool = False,
):
    for eval in evals:
        _pretty_print_evaluation_result(problem, eval, interactive=interactive)


@syncer.sync
async def main(
    problem: annotations.Problem,
    language: annotations.LanguageWithDefault = None,
    keep_sandbox: bool = False,
    interactive: bool = False,
    index: Optional[annotations.TestcaseIndex] = None,
):
    dumped_problem = metadata.find_problem_by_anything(problem)
    if not dumped_problem:
        console.print(
            f'[error]Problem with identifier [item]{problem}[/item] not found.[/error]'
        )
        return

    lang = get_config().get_language(language)
    if not lang:
        console.print(
            f'[error]Language {language or get_config().defaultLanguage} not found in config. Please check your configuration.[/error]'
        )
        return

    if interactive:
        testcases = []
        while True:
            console.print(
                f'Providing IO for testcase [item]#{len(testcases)}[/item]...'
            )
            input = multiline_prompt('Testcase input')
            if not input.strip():
                break
            output = multiline_prompt('Testcase output')
            input_path = pathlib.Path(tempfile.mktemp())
            output_path = pathlib.Path(tempfile.mktemp())
            input_path.write_text(input)
            output_path.write_text(output)
            testcases.append(
                steps.TestcaseIO(
                    index=len(testcases), input=input_path, output=output_path
                )
            )
    else:
        testcases = get_testcases_io(dumped_problem)

    if index is not None:
        testcases = [tc for tc in testcases if tc.index == index]

    if not testcases:
        console.print(
            f'[error]No testcases found for the problem [item]{dumped_problem.pretty_name()}[/item].[/error]'
        )
        return

    box = stupid_sandbox.StupidSandbox()
    atexit.register(lambda: box.cleanup(delete=not keep_sandbox))
    persist_root = config.get_empty_app_persist_path()

    with console.status(
        f'Preprocessing code for problem [item]{dumped_problem.pretty_name()}[/item] in language [item]{language or get_config().defaultLanguage}[/item]...'
    ):
        if lang.preprocess:
            preprocess_cmds = grading_utils.build_preprocess_commands(
                dumped_problem, lang
            )
            sandbox_params = grading_utils.build_preprocess_sandbox_params()
            artifacts = grading_utils.build_compile_grading_artifacts(
                dumped_problem, lang
            )
            if not steps.compile(preprocess_cmds, sandbox_params, box, artifacts):
                console.print(
                    f'[error]Failed to preprocess problem [item]{dumped_problem.pretty_name()}[/item].[/error]'
                )
                return

    with console.status(
        f'Compiling checker for problem [item]{dumped_problem.pretty_name()}[/item]...'
    ):
        command = '/usr/bin/g++ -std=c++17 -o checker checker.cpp'
        artifacts = grading_utils.build_checker_compile_grading_artifacts(
            dumped_problem, persist_root
        )
        if dumped_problem.checker and not steps.compile(
            [command], grading_utils.build_preprocess_sandbox_params(), box, artifacts
        ):
            console.print(
                f'[error]Failed to compile checker for problem [item]{dumped_problem.pretty_name()}[/item].[/error]'
            )
            return

    testcase_logs = await _run_testcases(
        dumped_problem, lang, language, box, testcases, persist_root
    )

    if not testcase_logs:
        console.print(
            f'[error]Failed to run testcases for problem [item]{dumped_problem.pretty_name()}[/item]. Sandbox probably crashed.[/error]'
        )
        return

    with console.status(
        f'Evaluating testcases for problem [item]{dumped_problem.pretty_name()}[/item]...'
    ):
        evals = _evaluate_testcases(
            dumped_problem, box, testcases, testcase_logs, persist_root
        )
    if not evals:
        console.print(
            f'[error]Failed to evaluate testcases for problem [item]{dumped_problem.pretty_name()}[/item].[/error]'
        )
        return
    pretty_print_evaluation_results(dumped_problem, evals, interactive=interactive)
    pretty_print_summary(dumped_problem, lang, evals)
