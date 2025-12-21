import asyncio
import pathlib
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Literal, Optional, Set

import rich
import rich.progress
import typer

from rbx import console, utils
from rbx.box import download, header, limits_info, naming, package
from rbx.box.lang import code_to_langs, is_valid_lang_code
from rbx.box.packaging.polygon import polygon_api as api
from rbx.box.packaging.polygon.utils import get_polygon_language_from_code_item
from rbx.box.schema import (
    ExpectedOutcome,
    Generator,
    GeneratorCall,
    Solution,
    TaskType,
    Testcase,
)
from rbx.box.statements.build_statements import get_relative_assets
from rbx.box.statements.builders import (
    ExplainedStatementSample,
    StatementBlocks,
    StatementBuilderProblem,
    StatementSample,
    render_jinja_blocks,
)
from rbx.box.statements.schema import Statement, StatementType
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
from rbx.box.testcase_utils import (
    TestcaseInteractionParsingError,
    get_alternate_interaction_texts,
    get_samples,
    parse_interaction,
)

_API_URL = 'https://polygon.codeforces.com/api'

ParamChoices = Literal['statements', 'solutions', 'tests', 'files']

ALL_PARAMS_CHOICES = list(ParamChoices.__args__)
MAX_WORKERS = 4


def _get_polygon_api() -> api.Polygon:
    env = utils.environ()
    return api.Polygon(
        _API_URL,
        env.get('POLYGON_API_KEY', '').strip(),
        env.get('POLYGON_API_SECRET', '').strip(),
    )


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
    api = _get_polygon_api()
    results = api.problems_list(name=problem_name)
    for result in results:
        if result.name == problem_name:
            console.console.print(
                f'Found already existing problem [item]{problem_name}[/item].'
            )
            return result
    console.console.print(f'Creating new problem [item]{problem_name}[/item].')
    return api.problem_create(problem_name)


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


def _update_jngen(problem: api.Problem):
    jngen = download.get_jngen()
    console.console.print('Uploading jngen.h...')
    problem.save_file(
        type=api.FileType.RESOURCE,
        name='jngen.h',
        file=jngen.read_bytes(),
        source_type=None,
    )


def _update_checker(problem: api.Problem):
    checker = package.get_checker_or_builtin()
    source_type = get_polygon_language_from_code_item(checker)
    console.console.print(f'Uploading checker (lang: {source_type})...')
    problem.save_file(
        type=api.FileType.SOURCE,
        name=_get_checker_name(),
        file=checker.path.read_bytes(),
        source_type=source_type,
    )

    problem.set_checker(_get_checker_name())


def _update_interactor(problem: api.Problem):
    interactor = package.get_interactor()
    source_type = get_polygon_language_from_code_item(interactor)
    console.console.print(f'Uploading interactor (lang: {source_type})...')
    problem.save_file(
        type=api.FileType.SOURCE,
        name=_get_interactor_name(),
        file=interactor.path.read_bytes(),
        source_type=source_type,
    )

    problem.set_interactor(_get_interactor_name())


def _upload_validator(problem: api.Problem):
    validator = package.get_validator()
    if validator is None:
        return
    source_type = get_polygon_language_from_code_item(validator)
    console.console.print(f'Uploading validator (lang: {source_type})...')
    validator = package.get_validator()
    problem.save_file(
        type=api.FileType.SOURCE,
        name=_get_validator_name(),
        file=validator.path.read_bytes(),
        source_type=source_type,
    )

    problem.set_validator(_get_validator_name())


def _get_samples() -> List[StatementSample]:
    return StatementSample.from_testcases(get_samples(), explanation_suffix='.tex')


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
        try:
            interaction = parse_interaction(pio_path)
        except TestcaseInteractionParsingError:
            pass
        else:
            res['test_input_for_statements'], res['test_output_for_statements'] = (
                get_alternate_interaction_texts(interaction)
            )
            return res

    # .pio does not exist or is not parseable, fallback to .pin and .pout.
    pin_path = testcase.outputPath.with_suffix('.pin')
    if pin_path.is_file():
        res['test_input_for_statements'] = pin_path.read_text()
    pout_path = testcase.outputPath.with_suffix('.pout')
    if pout_path.is_file():
        res['test_output_for_statements'] = pout_path.read_text()
    return res


def _get_freemarker_for_calls(calls: List[GeneratorCall], next_index: int = 1) -> str:
    return (
        '\n'.join(
            [
                f'{call.name} {call.args} > {i + next_index}'
                for i, call in enumerate(calls)
            ]
        )
        + '\n'
    )


def _upload_generator(problem: api.Problem, generator: Generator):
    generator_source_type = get_polygon_language_from_code_item(generator)
    console.console.print(
        f'Uploading generator {generator.href()} (lang: {generator_source_type})...'
    )
    problem.save_file(
        type=api.FileType.SOURCE,
        name=generator.path.name,
        file=generator.path.read_bytes(),
        source_type=generator_source_type,
    )


def _upload_testcases(problem: api.Problem):
    entries = asyncio.run(extract_generation_testcases_from_groups())
    generators: Dict[str, Generator] = {}
    for entry in entries:
        if not entry.metadata.generator_call:
            continue
        generator = package.get_generator_or_nil(entry.metadata.generator_call.name)
        if generator is None:
            continue
        generators[str(generator.path)] = generator

    if generators:
        _update_jngen(problem)  # TODO: only upload if necessary
        console.console.print('Clearing existing script...')
        problem.save_script(testset='tests', source='<#-- empty placeholder script -->')

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for generator in generators.values():
            futures.append(executor.submit(_upload_generator, problem, generator))
        for future in futures:
            future.result()

    with rich.progress.Progress(speed_estimate_period=5) as progress:
        next_index = 1
        task_id = progress.add_task('Uploading testcases...', total=len(entries))
        calls = []
        for entry in entries:
            if entry.metadata.generator_call is not None:
                # Generated testcases are handled later.
                generator = package.get_generator_or_nil(
                    entry.metadata.generator_call.name
                )
                if generator is None:
                    continue
                calls.append(
                    GeneratorCall(
                        name=generator.path.stem,
                        args=entry.metadata.generator_call.args,
                    )
                )
                continue

            if (
                entry.metadata.copied_from is None
                or not entry.metadata.copied_from.inputPath.is_file()
            ):
                continue
            saved = _save_skip_coinciding_testcases(
                problem,
                testset='tests',
                test_index=next_index,
                test_input=entry.metadata.copied_from.inputPath.read_text(),
                **_get_test_params_for_statement(
                    entry.metadata.copied_from,
                    is_sample=entry.is_sample(),
                ),
            )
            progress.update(task_id, advance=1)
            if saved:
                next_index += 1

        if calls:
            try:
                problem.save_script(
                    testset='tests', source=_get_freemarker_for_calls(calls, next_index)
                )
            except api.PolygonRequestFailedException as e:
                if 'already used in non-script' in e.comment.lower():
                    console.console.print(f'[error]{e.comment}[/error]')
                    console.console.print(
                        '[error]Please remove the conflicting manual tests on the Polygon UI and try again.[/error]'
                    )
                    raise typer.Exit(1) from None
                raise
        progress.update(task_id, completed=len(entries))


def _upload_solutions(problem: api.Problem):
    saved_solutions = set()

    def process_solution(solution: Solution, i: int):
        source_type = get_polygon_language_from_code_item(solution)
        console.console.print(
            f'Uploading solution {solution.href()} (lang: {source_type}, tag: [item]{_get_solution_tag(solution, is_first=i == 0)}[/item])...'
        )
        problem.save_solution(
            solution.path.name,
            solution.path.read_bytes(),
            source_type=source_type,
            tag=_get_solution_tag(solution, is_first=i == 0),
        )
        saved_solutions.add(solution.path.name)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for i, solution in enumerate(package.get_solutions()):
            futures.append(executor.submit(process_solution, solution, i))
        for future in futures:
            future.result()

    def delete_solution(solution: api.Solution):
        console.console.print(f'Deleting solution [item]{solution.name}[/item]...')
        problem.save_solution(
            solution.name,
            '# This solution is no longer used in the problem but was kept by rbx.cp.',
            source_type='python.3',
            tag=api.SolutionTag.NR,
        )

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for solution in problem.solutions():
            if solution.name not in saved_solutions:
                futures.append(executor.submit(delete_solution, solution))
        for future in futures:
            future.result()


def _get_statement_for_language(language: str) -> Optional[Statement]:
    pkg = package.find_problem_package_or_die()
    for statement in pkg.expanded_statements:
        if statement.language == language:
            return statement
    return None


def _get_statement_blocks(statement: Statement) -> StatementBlocks:
    # TODO: actually try to convert to rbxTeX
    assert statement.type == StatementType.rbxTeX
    pkg = package.find_problem_package_or_die()
    # TODO: pull this from a library, too hacky at the moment
    builder_problem = StatementBuilderProblem(
        limits=limits_info.get_limits_profile(profile='polygon'),
        package=pkg,
        statement=statement,
        vars={
            **pkg.expanded_vars,
            **statement.expanded_vars,
        },
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


def _get_notes_with_explanations(
    blocks: StatementBlocks, samples: List[StatementSample]
) -> Optional[str]:
    notes = blocks.blocks.get('notes')
    explanations = ExplainedStatementSample.samples_to_explanations(
        samples, blocks.explanations
    )
    if notes is None and not explanations:
        return None
    if notes is None:
        return _get_explanations(explanations)
    return notes + '\n\n' + _get_explanations(explanations)


def _upload_statement_resources(
    problem: api.Problem, statement: Statement
) -> Dict[str, str]:
    res: Dict[str, str] = {}
    assets = get_relative_assets(statement.path, statement.assets)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
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
            no_suffix_relative_asset = relative_asset.with_suffix('')
            key_asset = (
                None
                if len(no_suffix_relative_asset.parents) <= 1
                else str(no_suffix_relative_asset).replace('/', '__')
                + relative_asset.suffix
            )
            if key_asset is not None:
                res[str(relative_asset.with_suffix(''))] = key_asset
            if key_asset is None:
                key_asset = str(no_suffix_relative_asset) + relative_asset.suffix
            console.console.print(
                f'Uploading statement resource [item]{relative_asset}[/item] (normalized name: [item]{key_asset}[/item])...'
            )
            futures.append(
                executor.submit(
                    problem.save_statement_resource,
                    name=key_asset,
                    file=resource_bytes,
                )
            )
    for future in futures:
        future.result()
    return res


def _upload_statement(
    problem: api.Problem, main_language: Optional[str], upload_as_english: bool = False
):
    pkg = package.find_problem_package_or_die()

    lang_list = []
    languages = set()
    for statement in pkg.expanded_statements:
        if not is_valid_lang_code(statement.language):
            continue
        languages.add(statement.language)
        lang_list.append(statement.language)
    uploaded_languages = set()

    if main_language is None:
        main_language = lang_list[0]

    # Put the main language first.
    lang_list = list(languages)
    for i in range(len(lang_list)):
        if lang_list[i] == main_language:
            lang_list[i], lang_list[0] = lang_list[0], lang_list[i]
            break

    # Prioritize English statements.
    for language in lang_list:
        statement = _get_statement_for_language(language)
        if statement is None:
            continue
        if statement.type != StatementType.rbxTeX:
            continue
        statement_lang = code_to_langs([language])[0]
        console.console.print(
            f'Uploading statement for language [item]{language}[/item] (polygon language: [item]{statement_lang}[/item])...'
        )
        uploaded_language = statement_lang
        if main_language == language:
            if not upload_as_english:
                console.console.print(
                    '[warning]By default, Polygon statements are uploaded respecting their original language.\n'
                    'Codeforces does not work well with statements in other languages. If you want a better experience, '
                    'use the [item]--upload-as-english[/item] option to force the main statement to be uploaded in English.[/warning]'
                )
            else:
                uploaded_language = 'english'
        if uploaded_language in uploaded_languages:
            continue
        uploaded_languages.add(uploaded_language)
        blocks = _get_statement_blocks(statement)
        resources = _upload_statement_resources(problem, statement)

        def _replace_resources(block: str, resources=resources) -> str:
            for key, value in resources.items():
                block = block.replace(key, value)
            return block

        def _get_block(block_name: str, blocks=blocks, resources=resources) -> str:
            block = blocks.blocks.get(block_name) or ''
            return _replace_resources(block, resources)

        polygon_statement = api.Statement(
            encoding='utf-8',
            name=naming.get_problem_title(statement.language, statement, pkg),
            legend=_get_block('legend'),
            input=_get_block('input'),
            output=_get_block('output'),
            interaction=_get_block('interaction')
            if pkg.type == TaskType.COMMUNICATION
            else None,
            notes=_replace_resources(
                _get_notes_with_explanations(blocks, _get_samples()) or ''
            ),
        )
        problem.save_statement(
            lang=uploaded_language,
            problem_statement=polygon_statement,
        )


def _normalize_problem_name(name: str) -> str:
    return name.replace(' ', '-').replace('_', '-').lower()


async def upload_problem(
    name: str,
    main_language: Optional[str],
    upload_as_english: bool = False,
    upload_only: Optional[Set[str]] = None,
    dont_upload: Optional[Set[str]] = None,
):
    if upload_only is None:
        upload_only = set()
    if dont_upload is None:
        dont_upload = set()

    if not upload_only:
        upload_only = set(ALL_PARAMS_CHOICES)

    which_upload = upload_only - dont_upload
    pkg = package.find_problem_package_or_die()
    name = _normalize_problem_name(name)
    problem = _find_or_create_problem(name)
    _update_problem_info(problem)

    if 'files' in which_upload:
        _update_rbx_header(problem)
        _update_checker(problem)

    if (
        pkg.type == TaskType.COMMUNICATION
        and package.get_interactor_or_nil() is not None
    ):
        if 'files' in which_upload:
            _update_interactor(problem)

    if pkg.validator is not None:
        if 'files' in which_upload:
            _upload_validator(problem)

    if 'solutions' in which_upload:
        _upload_solutions(problem)
    if 'tests' in which_upload:
        _upload_testcases(problem)
    if 'statements' in which_upload:
        _upload_statement(
            problem, main_language=main_language, upload_as_english=upload_as_english
        )

    # Commit.
    console.console.print('Committing changes...')
    problem.commit_changes()

    console.console.print(
        f'[success]Problem [item]{name}[/item] uploaded successfully![/success]'
    )
