import asyncio
import pathlib
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Literal, Optional, Set

import rich
import rich.progress
import typer

from rbx import console, utils
from rbx.box import header, naming, package
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.packaging import flattening
from rbx.box.packaging.polygon import polygon_api as api
from rbx.box.packaging.polygon.statement_block_utils import (
    get_processed_statement_blocks,
    process_statements,
)
from rbx.box.packaging.polygon.utils import get_polygon_language_from_code_item
from rbx.box.schema import (
    CodeItem,
    ExpectedOutcome,
    Generator,
    GeneratorCall,
    Solution,
    TaskType,
    Testcase,
)
from rbx.box.solutions import get_best_interaction_file
from rbx.box.statements.build_statements import get_produced_tikz_pdfs
from rbx.box.statements.builders import (
    StatementSample,
)
from rbx.box.statements.schema import Statement
from rbx.box.statements.statement_utils import get_relative_assets
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
from rbx.box.testcase_sample_utils import get_statement_samples
from rbx.box.testcase_utils import (
    TestcaseInteractionParsingError,
    get_alternate_interaction_texts,
    parse_interaction,
)
from rbx.config import get_jngen, get_tgen

_API_URL = 'https://polygon.codeforces.com/api'

ParamChoices = Literal['statements', 'solutions', 'tests', 'files']

ALL_PARAMS_CHOICES = list(ParamChoices.__args__)
MAX_WORKERS = 4
_RAW_TEST_SIZE_LIMIT = 1024 * 1024


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


def _collect_generators() -> List[Generator]:
    """Generators referenced by the package's testcases, de-duplicated by path,
    in deterministic order.

    Mirrors the de-duplication used by ``_upload_testcases`` so the upload
    namespace and the actual generator uploads agree on the set of generators.
    """
    entries = asyncio.run(extract_generation_testcases_from_groups())
    generators: Dict[str, Generator] = {}
    for entry in entries:
        if not entry.metadata.generator_call:
            continue
        gen = package.get_generator_or_nil(entry.metadata.generator_call.name)
        if gen is None:
            continue
        generators[str(gen.path)] = gen
    return [generators[k] for k in sorted(generators)]


def _build_upload_namespace() -> flattening.FlatNamespace:
    """Build a single flat namespace spanning every uploaded source.

    The checker/interactor/validator keep their special Polygon names via
    ``reserved``; everything else (solutions, generators) is disambiguated so
    same-basename sources in different directories no longer collide (#527).
    ``enforce_stem_unique`` is required because Polygon compiles each source to a
    program named after its stem.
    """
    pkg = package.find_problem_package_or_die()
    sources: List[CodeItem] = []
    reserved: Dict[pathlib.Path, str] = {}

    checker = package.get_checker_or_builtin()
    sources.append(checker)
    reserved[package.get_relative_source_path(checker)] = _get_checker_name()

    interactor = package.get_interactor_or_nil()
    if interactor is not None:
        sources.append(interactor)
        reserved[package.get_relative_source_path(interactor)] = _get_interactor_name()

    if pkg.validator is not None:
        validator = package.get_validator()
        sources.append(validator)
        reserved[package.get_relative_source_path(validator)] = _get_validator_name()

    sources.extend(package.get_solutions())
    sources.extend(_collect_generators())

    return flattening.build_flat_namespace(
        sources, reserved=reserved, enforce_stem_unique=True
    )


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
    jngen = get_jngen()
    console.console.print('Uploading jngen.h...')
    problem.save_file(
        type=api.FileType.RESOURCE,
        name='jngen.h',
        file=jngen.read_bytes(),
        source_type=None,
    )


def _update_tgen(problem: api.Problem):
    tgen = get_tgen()
    console.console.print('Uploading tgen.h...')
    problem.save_file(
        type=api.FileType.RESOURCE,
        name='tgen.h',
        file=tgen.read_bytes(),
        source_type=None,
    )


def _upload_dep_files(problem: api.Problem, ns: flattening.FlatNamespace):
    for dep in ns.dep_files():
        console.console.print(f'Uploading dependency {dep.flat_name}...')
        problem.save_file(
            type=api.FileType.RESOURCE,
            name=dep.flat_name,
            file=dep.content,
            source_type=None,
        )


def _update_checker(problem: api.Problem, ns: flattening.FlatNamespace):
    checker = package.get_checker_or_builtin()
    source_type = get_polygon_language_from_code_item(checker)
    console.console.print(f'Uploading checker (lang: {source_type})...')
    problem.save_file(
        type=api.FileType.SOURCE,
        name=_get_checker_name(),
        file=ns.content_for(checker),
        source_type=source_type,
    )

    problem.set_checker(_get_checker_name())


def _update_interactor(problem: api.Problem, ns: flattening.FlatNamespace):
    interactor = package.get_interactor()
    source_type = get_polygon_language_from_code_item(interactor)
    console.console.print(f'Uploading interactor (lang: {source_type})...')
    problem.save_file(
        type=api.FileType.SOURCE,
        name=_get_interactor_name(),
        file=ns.content_for(interactor),
        source_type=source_type,
    )

    problem.set_interactor(_get_interactor_name())


def _upload_validator(problem: api.Problem, ns: flattening.FlatNamespace):
    validator = package.get_validator()
    if validator is None:
        return
    source_type = get_polygon_language_from_code_item(validator)
    console.console.print(f'Uploading validator (lang: {source_type})...')
    problem.save_file(
        type=api.FileType.SOURCE,
        name=_get_validator_name(),
        file=ns.content_for(validator),
        source_type=source_type,
    )

    problem.set_validator(_get_validator_name())


async def _get_samples() -> List[StatementSample]:
    return await get_statement_samples(explanation_suffix='.tex')


def _save_skip_coinciding_testcases(problem: api.Problem, *args, **kwargs) -> bool:
    try:
        problem.save_test(*args, **kwargs)
    except api.PolygonRequestFailedException as e:
        if 'test coincides with' in e.comment.lower():
            return False
        raise
    return True


def _get_test_params_for_statement(
    testcase: Optional[Testcase], is_sample: bool
) -> Dict[str, Any]:
    if not is_sample or testcase is None:
        return {}
    res: Dict[str, Any] = {'test_use_in_statements': True}
    if testcase.outputPath is not None:
        res['test_output_for_statements'] = testcase.outputPath.read_text()
    else:
        return res

    interaction_path = get_best_interaction_file(testcase.outputPath)
    if interaction_path is not None:
        try:
            interaction = parse_interaction(interaction_path)
        except TestcaseInteractionParsingError:
            pass
        else:
            res['test_input_for_statements'], res['test_output_for_statements'] = (
                get_alternate_interaction_texts(interaction)
            )
            return res

    # interaction file does not exist or is not parseable, fallback to .pin and .pout.
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


def _resolve_raw_test_input_path(
    entry: 'GenerationTestcaseEntry',
) -> Optional[pathlib.Path]:
    if entry.metadata.copied_to.inputPath.is_file():
        return entry.metadata.copied_to.inputPath
    if (
        entry.metadata.copied_from is not None
        and entry.metadata.copied_from.inputPath.is_file()
    ):
        return entry.metadata.copied_from.inputPath
    return None


def _validate_raw_tests(
    entries: List['GenerationTestcaseEntry'],
) -> List[str]:
    errors: List[str] = []
    for entry in entries:
        label = entry.short_repr()
        path = _resolve_raw_test_input_path(entry)
        if path is None:
            errors.append(f'"{label}" was not built (input file missing)')
            continue
        size = path.stat().st_size
        if size >= _RAW_TEST_SIZE_LIMIT:
            errors.append(
                f'"{label}" is {utils.format_size(size)}, '
                f'exceeds the 1 MiB Polygon limit'
            )
    return errors


def _upload_generator(
    problem: api.Problem, generator: Generator, ns: flattening.FlatNamespace
):
    generator_source_type = get_polygon_language_from_code_item(generator)
    console.console.print(
        f'Uploading generator {generator.href()} (lang: {generator_source_type})...'
    )
    try:
        problem.save_file(
            type=api.FileType.SOURCE,
            name=ns.flat_name_for(generator),
            file=ns.content_for(generator),
            source_type=generator_source_type,
        )
    except api.PolygonRequestFailedException as e:
        console.console.print(
            f'[error]Failed to upload generator {generator.href()}:[/error]\n{e.comment}'
        )
        raise typer.Exit(1) from None


def _upload_testcases(problem: api.Problem, ns: flattening.FlatNamespace):
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
        _update_tgen(problem)  # TODO: only upload if necessary
        console.console.print('Clearing existing script...')
        problem.save_script(testset='tests', source='<#-- empty placeholder script -->')

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for generator in generators.values():
            futures.append(executor.submit(_upload_generator, problem, generator, ns))
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
                        name=pathlib.Path(ns.flat_name_for(generator)).stem,
                        args=entry.metadata.generator_call.args,
                    )
                )
                continue

            content = entry.metadata.content
            if (
                entry.metadata.copied_from is not None
                and entry.metadata.copied_from.inputPath.is_file()
            ):
                content = entry.metadata.copied_from.inputPath.read_text()
            if content is None:
                continue
            saved = _save_skip_coinciding_testcases(
                problem,
                testset='tests',
                test_index=next_index,
                test_input=content,
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


def _upload_testcases_raw(problem: api.Problem):
    entries = asyncio.run(extract_generation_testcases_from_groups())

    errors = _validate_raw_tests(entries)
    if errors:
        console.console.print('[error]Cannot upload raw tests:[/error]')
        for error in errors:
            console.console.print(f'[error]  - {error}[/error]')
        raise typer.Exit(1)

    console.console.print('Clearing existing script...')
    problem.save_script(testset='tests', source='<#-- empty placeholder script -->')

    with rich.progress.Progress(speed_estimate_period=5) as progress:
        next_index = 1
        task_id = progress.add_task('Uploading raw testcases...', total=len(entries))
        for entry in entries:
            path = _resolve_raw_test_input_path(entry)
            assert path is not None  # validated above
            content = path.read_text()
            saved = _save_skip_coinciding_testcases(
                problem,
                testset='tests',
                test_index=next_index,
                test_input=content,
                **_get_test_params_for_statement(
                    entry.metadata.copied_from,
                    is_sample=entry.is_sample(),
                ),
            )
            progress.update(task_id, advance=1)
            if saved:
                next_index += 1
        progress.update(task_id, completed=len(entries))


def _upload_solutions(problem: api.Problem, ns: flattening.FlatNamespace):
    saved_solutions = set()

    def process_solution(solution: Solution, i: int):
        source_type = get_polygon_language_from_code_item(solution)
        name = ns.flat_name_for(solution)
        console.console.print(
            f'Uploading solution {solution.href()} (lang: {source_type}, tag: [item]{_get_solution_tag(solution, is_first=i == 0)}[/item])...'
        )
        problem.save_solution(
            name,
            ns.content_for(solution),
            source_type=source_type,
            tag=_get_solution_tag(solution, is_first=i == 0),
        )
        saved_solutions.add(name)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for i, solution in enumerate(package.get_solutions()):
            futures.append(executor.submit(process_solution, solution, i))
        for solution, future in zip(package.get_solutions(), futures):
            try:
                future.result()
            except api.PolygonRequestFailedException as e:
                console.console.print(
                    f'[error]Failed to upload solution {solution.href()}:[/error]\n{e.comment}'
                )

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
        solutions = [
            solution
            for solution in problem.solutions()
            if solution.name not in saved_solutions
        ]
        for solution in solutions:
            futures.append(executor.submit(delete_solution, solution))
        for solution, future in zip(solutions, futures):
            try:
                future.result()
            except api.PolygonRequestFailedException as e:
                console.console.print(
                    f'[error]Failed to delete solution [item]{solution.name}[/item]:[/error]\n{e.comment}'  # pyright: ignore[reportAttributeAccessIssue]
                )


def _get_explanations(explanations: Dict[int, str]) -> str:
    entries = []
    for i in sorted(explanations):
        explanation = explanations[i]
        entries.append(f'\\textbf{{Explanation for example {i + 1}}}\n\n{explanation}')
    return '\n\n'.join(entries)


def _upload_statement_resources(
    problem: api.Problem, statement: Statement
) -> Dict[str, str]:
    res: Dict[str, str] = {}
    assets = get_relative_assets(statement.path, statement.assets)
    assets.extend(get_produced_tikz_pdfs(statement))
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


async def _upload_statement(
    problem: api.Problem, main_language: Optional[str], upload_as_english: bool = False
):
    pkg = package.find_problem_package_or_die()

    def process_statement(statement: Statement, language: str, uploaded_language: str):
        console.console.print(
            f'Uploading statement for language [item]{language}[/item] (uploaded language: [item]{uploaded_language}[/item])...'
        )
        blocks = get_processed_statement_blocks(statement)
        resources = _upload_statement_resources(problem, statement)

        def _replace_resources(block: str, resources=resources) -> str:
            for key, value in resources.items():
                block = block.replace(key, value)
            return block

        def _get_block(block_name: str, blocks=blocks, resources=resources) -> str:
            block = blocks.blocks.get(block_name) or ''
            return _replace_resources(block, resources)

        def _get_notes_with_explanations(
            blocks=blocks,
        ) -> Optional[str]:
            notes = _get_block('notes')
            if notes is None and not blocks.explanations:
                return None
            res = _replace_resources(_get_explanations(blocks.explanations))
            if notes is not None:
                res = notes + '\n\n' + res
            return res

        polygon_statement = api.Statement(
            encoding='utf-8',
            name=naming.get_problem_title(statement.language, statement, pkg),
            legend=_get_block('legend'),
            input=_get_block('input'),
            output=_get_block('output'),
            interaction=_get_block('interaction')
            if pkg.type == TaskType.COMMUNICATION
            else None,
            notes=_get_notes_with_explanations() or '',
        )
        problem.save_statement(
            lang=uploaded_language,
            problem_statement=polygon_statement,
        )

    process_statements(main_language, upload_as_english, process_statement)


def _normalize_problem_name(name: str) -> str:
    return name.replace(' ', '-').replace('_', '-').lower()


async def upload_problem(
    name: str,
    main_language: Optional[str],
    upload_as_english: bool = False,
    upload_only: Optional[Set[str]] = None,
    dont_upload: Optional[Set[str]] = None,
    raw_tests: bool = False,
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

    # Build the flat namespace once, unconditionally, so that flat names stay
    # globally consistent regardless of which subset is being uploaded. Only the
    # upload calls below are gated.
    ns = _build_upload_namespace()

    if 'files' in which_upload:
        _update_rbx_header(problem)
        _upload_dep_files(problem, ns)
        _update_checker(problem, ns)

    if (
        pkg.type == TaskType.COMMUNICATION
        and package.get_interactor_or_nil() is not None
    ):
        if 'files' in which_upload:
            _update_interactor(problem, ns)

    if pkg.validator is not None:
        if 'files' in which_upload:
            _upload_validator(problem, ns)

    if 'solutions' in which_upload:
        _upload_solutions(problem, ns)
    if 'tests' in which_upload:
        if raw_tests:
            _upload_testcases_raw(problem)
        else:
            _upload_testcases(problem, ns)
    if 'statements' in which_upload:
        await _upload_statement(
            problem, main_language=main_language, upload_as_english=upload_as_english
        )

    # Commit.
    console.console.print('Committing changes...')
    problem.commit_changes()

    console.console.print(
        f'[success]Problem [item]{name}[/item] uploaded successfully![/success]'
    )
