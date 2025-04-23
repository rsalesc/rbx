import os
import pathlib
import tempfile
from typing import Any, Dict, Optional

import rich
import rich.progress
import typer

from rbx import console
from rbx.box import header, package
from rbx.box.generators import get_all_built_testcases
from rbx.box.packaging.polygon import polygon_api as api
from rbx.box.packaging.polygon.packager import code_to_langs, is_valid_lang_code
from rbx.box.schema import CodeItem, ExpectedOutcome, Solution, TaskType, Testcase
from rbx.box.statements.build_statements import get_relative_assets
from rbx.box.statements.builders import (
    StatementBlocks,
    StatementBuilderProblem,
    render_jinja_blocks,
)
from rbx.box.statements.schema import Statement, StatementType
from rbx.box.testcase_utils import get_alternate_interaction_texts, parse_interaction

_API_URL = 'https://polygon.codeforces.com/api'

POLY = api.Polygon(
    _API_URL,
    os.environ.get('POLYGON_API_KEY', '').strip(),
    os.environ.get('POLYGON_API_SECRET', '').strip(),
)


def _get_source_type(code: CodeItem):
    return None


def _get_solution_tag(solution: Solution, is_first: bool = False) -> api.SolutionTag:
    if solution.outcome == ExpectedOutcome.ACCEPTED:
        return api.SolutionTag.OK if not is_first else api.SolutionTag.MA
    if solution.outcome == ExpectedOutcome.ACCEPTED_OR_TLE:
        return api.SolutionTag.TO
    if solution.outcome == ExpectedOutcome.WRONG_ANSWER:
        return api.SolutionTag.WA
    if solution.outcome == ExpectedOutcome.TIME_LIMIT_EXCEEDED:
        return api.SolutionTag.TL
    if solution.outcome == ExpectedOutcome.MEMORY_LIMIT_EXCEEDED:
        return api.SolutionTag.ML
    if solution.outcome == ExpectedOutcome.RUNTIME_ERROR:
        return api.SolutionTag.RE
    return api.SolutionTag.RJ


def _find_or_create_problem(problem_name: str) -> api.Problem:
    results = POLY.problems_list(name=problem_name)
    for result in results:
        if result.name == problem_name:
            console.console.print(
                f'Found already existing problem [item]{problem_name}[/item].'
            )
            return result
    console.console.print(f'Creating new problem [item]{problem_name}[/item].')
    return POLY.problem_create(problem_name)


def _update_problem_info(problem: api.Problem):
    pkg = package.find_problem_package_or_die()

    problem.update_info(
        api.ProblemInfo(
            interactive=pkg.type == TaskType.COMMUNICATION,
            time_limit=pkg.timeLimit,
            memory_limit=pkg.memoryLimit,
        )
    )


def _get_checker_name() -> str:
    checker = package.get_checker()
    return checker.path.with_stem('checker').name


def _get_interactor_name() -> str:
    interactor = package.get_interactor()
    return interactor.path.with_stem('interactor').name


def _get_validator_name() -> str:
    validator = package.get_validator()
    return validator.path.with_stem('validator').name


def _update_rbx_header(problem: api.Problem):
    console.console.print('Uploading rbx.h...')
    rbx_header = header.get_header()
    problem.save_file(
        type=api.FileType.RESOURCE,
        name='rbx.h',
        file=rbx_header.read_bytes(),
        source_type=None,
    )


def _update_checker(problem: api.Problem):
    console.console.print('Uploading checker...')
    checker = package.get_checker()
    problem.save_file(
        type=api.FileType.SOURCE,
        name=_get_checker_name(),
        file=checker.path.read_bytes(),
        source_type=_get_source_type(checker),
    )

    problem.set_checker(_get_checker_name())


def _update_interactor(problem: api.Problem):
    console.console.print('Uploading interactor...')
    interactor = package.get_interactor()
    problem.save_file(
        type=api.FileType.SOURCE,
        name=_get_interactor_name(),
        file=interactor.path.read_bytes(),
        source_type=_get_source_type(interactor),
    )

    problem.set_interactor(_get_interactor_name())


def _upload_validator(problem: api.Problem):
    console.console.print('Uploading validator...')
    validator = package.get_validator()
    problem.save_file(
        type=api.FileType.SOURCE,
        name=_get_validator_name(),
        file=validator.path.read_bytes(),
        source_type=_get_source_type(validator),
    )

    problem.set_validator(_get_validator_name())


def _save_skip_coinciding_testcases(problem: api.Problem, *args, **kwargs) -> bool:
    try:
        problem.save_test(*args, **kwargs)
    except api.PolygonRequestFailedException as e:
        if 'test coincides with' in e.comment.lower():
            return False
        raise
    return True


def _get_test_params_for_statement(
    testcase: Testcase, is_sample: bool
) -> Dict[str, Any]:
    if not is_sample:
        return {}
    res: Dict[str, Any] = {'test_use_in_statements': True}
    if testcase.outputPath is not None:
        res['test_output_for_statements'] = testcase.outputPath.read_text()
    else:
        return res

    pio_path = testcase.outputPath.with_suffix('.pio')
    if pio_path.is_file():
        interaction = parse_interaction(pio_path)
        res['test_input_for_statements'], res['test_output_for_statements'] = (
            get_alternate_interaction_texts(interaction)
        )
    else:
        pin_path = testcase.outputPath.with_suffix('.pin')
        if pin_path.is_file():
            res['test_input_for_statements'] = pin_path.read_text()
        pout_path = testcase.outputPath.with_suffix('.pout')
        if pout_path.is_file():
            res['test_output_for_statements'] = pout_path.read_text()
    return res


def _upload_testcases(problem: api.Problem):
    pkg = package.find_problem_package_or_die()
    testcases = get_all_built_testcases()
    i = 0

    with rich.progress.Progress(speed_estimate_period=5) as progress:
        total_len = 0
        for group in pkg.testcases:
            total_len += len(testcases[group.name])
        task_id = progress.add_task('Uploading testcases...', total=total_len)
        for group in pkg.testcases:
            for testcase in testcases[group.name]:
                is_sample = group.name == 'samples'
                saved = _save_skip_coinciding_testcases(
                    problem,
                    testset='tests',
                    test_index=i + 1,
                    test_input=testcase.inputPath.read_text(),
                    **_get_test_params_for_statement(testcase, is_sample),
                )
                progress.update(task_id, advance=1)
                if saved:
                    i += 1


def _upload_solutions(problem: api.Problem):
    console.console.print('Uploading main solution...')
    pkg = package.find_problem_package_or_die()
    main_solution = pkg.solutions[0]
    if main_solution is None or main_solution.outcome != ExpectedOutcome.ACCEPTED:
        return
    problem.save_solution(
        main_solution.path.name,
        main_solution.path.read_bytes(),
        source_type=_get_source_type(main_solution),
        tag=api.SolutionTag.MA,
    )

    for i, solution in enumerate(pkg.solutions):
        console.console.print(
            f'Uploading solution [item]{solution.path.name}[/item] (tag: [item]{_get_solution_tag(solution, is_first=i == 0)}[/item])...'
        )
        problem.save_solution(
            solution.path.name,
            solution.path.read_bytes(),
            source_type=_get_source_type(solution),
            tag=_get_solution_tag(solution, is_first=i == 0),
        )


def _get_statement_for_language(language: str) -> Optional[Statement]:
    pkg = package.find_problem_package_or_die()
    for statement in pkg.statements:
        if statement.language == language:
            return statement
    return None


def _get_statement_blocks(statement: Statement) -> StatementBlocks:
    # TODO: actually try to convert to rbxTeX
    assert statement.type == StatementType.rbxTeX
    builder_problem = StatementBuilderProblem(
        package=package.find_problem_package_or_die(),
        statement=statement,
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        return render_jinja_blocks(
            pathlib.Path(temp_dir),
            statement.path.read_bytes(),
            **builder_problem.build_inner_jinja_kwargs(),
        )


def _get_explanations(explanations: Dict[int, str]) -> str:
    entries = []
    for i in sorted(explanations):
        explanation = explanations[i]
        entries.append(f'\\textbf{{Explanation for example {i + 1}}}\n\n{explanation}')
    return '\n\n'.join(entries)


def _get_notes_with_explanations(blocks: StatementBlocks) -> Optional[str]:
    notes = blocks.blocks.get('notes')
    explanations = blocks.explanations
    if notes is None and not explanations:
        return None
    if notes is None:
        return _get_explanations(blocks.explanations)
    return notes + '\n\n' + _get_explanations(blocks.explanations)


def _upload_statement_resources(problem: api.Problem, statement: Statement):
    assets = get_relative_assets(statement.path, statement.assets)
    for asset, relative_asset in assets:
        console.console.print(
            f'Uploading statement resource [item]{relative_asset}[/item]...'
        )
        resource_bytes = asset.read_bytes()
        if len(resource_bytes) >= 1024 * 1024:  # >= 1mb
            console.console.print(
                f'[error]Statement resource [item]{relative_asset}[/item] is too large to upload (more than 1MB).[/error]'
            )
            raise typer.Exit(1)
        problem.save_statement_resource(
            name=str(relative_asset),
            file=resource_bytes,
        )


def _upload_statement(problem: api.Problem):
    pkg = package.find_problem_package_or_die()

    languages = set()
    for statement in pkg.statements:
        if not is_valid_lang_code(statement.language):
            continue
        languages.add(statement.language)
    for language in languages:
        statement = _get_statement_for_language(language)
        if statement is None:
            continue
        if statement.type != StatementType.rbxTeX:
            continue
        console.console.print(
            f'Uploading statement for language [item]{language}[/item] (polygon language: [item]{code_to_langs([language])[0]}[/item])...'
        )
        blocks = _get_statement_blocks(statement)
        polygon_statement = api.Statement(
            encoding='utf-8',
            name=statement.title,
            legend=blocks.blocks.get('legend'),
            input=blocks.blocks.get('input'),
            output=blocks.blocks.get('output'),
            interaction=blocks.blocks.get('interaction'),
            notes=_get_notes_with_explanations(blocks),
        )
        problem.save_statement(
            lang=code_to_langs([language])[0], problem_statement=polygon_statement
        )

        _upload_statement_resources(problem, statement)


def _normalize_problem_name(name: str) -> str:
    return name.replace(' ', '-').replace('_', '-').lower()


async def upload_problem(name: str):
    pkg = package.find_problem_package_or_die()
    name = _normalize_problem_name(name)
    problem = _find_or_create_problem(name)
    _update_problem_info(problem)
    _update_rbx_header(problem)
    _update_checker(problem)

    if (
        pkg.type == TaskType.COMMUNICATION
        and package.get_interactor_or_nil() is not None
    ):
        _update_interactor(problem)

    # if pkg.validator is not None:
    #     _upload_validator(problem)

    _upload_solutions(problem)
    _upload_testcases(problem)
    _upload_statement(problem)

    # Commit.
    console.console.print('Committing changes...')
    problem.commit_changes()

    console.console.print(
        f'[success]Problem [item]{name}[/item] uploaded successfully![/success]'
    )
