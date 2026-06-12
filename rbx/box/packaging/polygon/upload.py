import asyncio
import dataclasses
import pathlib
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

import rich
import rich.markup
import rich.progress
import typer
from TexSoup.data import BraceGroup, BracketGroup

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
from rbx.box.statements import sample_staging
from rbx.box.statements.build_statements import (
    get_produced_tikz_pdfs,
    get_statement_dir,
)
from rbx.box.statements.schema import Statement
from rbx.box.statements.texsoup_utils import parse_latex
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
from rbx.box.testcase_sample_utils import StatementSample, get_statement_samples
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


def _format_request_failed_comment(comment: str) -> str:
    """Prepare a Polygon FAILED ``comment`` for safe Rich rendering.

    Compiler output routinely contains ``[...]`` (e.g. ``[with _Tp = int]``), so it
    must be escaped or Rich would interpret it as markup and silently drop those
    segments. When the comment reaches Polygon's server-side length cap it was
    almost certainly truncated, so we append a hint pointing at the Polygon UI,
    which holds the full compilation log (#389).
    """
    rendered = rich.markup.escape(comment)
    if len(comment) >= api.COMMENT_LENGTH_LIMIT:
        rendered += (
            f'\n[warning]Note: Polygon truncates error messages to '
            f'{api.COMMENT_LENGTH_LIMIT} characters, so this one is likely cut off. '
            f'Open the problem in the Polygon UI to see the full compilation log.'
            f'[/warning]'
        )
    return rendered


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


def _extracted_entries(
    entries: Optional[List['GenerationTestcaseEntry']],
) -> List['GenerationTestcaseEntry']:
    """Return ``entries`` if already extracted, else extract them synchronously.

    The synchronous ``asyncio.run`` fallback only works OUTSIDE a running event
    loop -- it exists for sync callers such as the namespace-builder unit tests.
    The async ``upload_problem`` path runs inside the event loop driven by
    ``syncer``, so it MUST extract once via ``await`` and thread the result down,
    never reaching this fallback (#591).
    """
    if entries is not None:
        return entries
    return asyncio.run(extract_generation_testcases_from_groups())


def _collect_generators(
    entries: Optional[List['GenerationTestcaseEntry']] = None,
) -> List[Generator]:
    """Generators referenced by the package's testcases, de-duplicated by path,
    in deterministic order.

    Shared by ``_build_upload_namespace`` and ``_upload_testcases`` so the upload
    namespace and the actual generator uploads agree on the set of generators.
    Pass already-extracted ``entries`` to avoid re-walking the testcase groups.
    """
    entries = _extracted_entries(entries)
    generators: Dict[str, Generator] = {}
    for entry in entries:
        if not entry.metadata.generator_call:
            continue
        gen = package.get_generator_or_nil(entry.metadata.generator_call.name)
        if gen is None:
            continue
        generators[str(gen.path)] = gen
    return [generators[k] for k in sorted(generators)]


def _build_upload_namespace(
    entries: Optional[List['GenerationTestcaseEntry']] = None,
) -> flattening.FlatNamespace:
    """Build a single flat namespace spanning every uploaded source.

    The checker/interactor/validator keep their special Polygon names via
    ``reserved``; everything else (solutions, generators) is disambiguated so
    same-basename sources in different directories no longer collide (#527).
    ``enforce_stem_unique`` is required because Polygon compiles each source to a
    program named after its stem.

    Pass already-extracted ``entries`` to thread them into ``_collect_generators``
    (the async ``upload_problem`` caller must, to avoid ``asyncio.run`` inside the
    running loop -- #591).
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
    sources.extend(_collect_generators(entries))

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
            f'[error]Failed to upload generator {generator.href()}:[/error]\n{_format_request_failed_comment(e.comment)}'
        )
        raise typer.Exit(1) from None


def _upload_testcases(
    problem: api.Problem,
    ns: flattening.FlatNamespace,
    entries: Optional[List['GenerationTestcaseEntry']] = None,
):
    entries = _extracted_entries(entries)
    generators = _collect_generators(entries)

    if generators:
        _update_jngen(problem)  # TODO: only upload if necessary
        _update_tgen(problem)  # TODO: only upload if necessary
        console.console.print('Clearing existing script...')
        problem.save_script(testset='tests', source='<#-- empty placeholder script -->')

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for generator in generators:
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
                    console.console.print(
                        f'[error]{_format_request_failed_comment(e.comment)}[/error]'
                    )
                    console.console.print(
                        '[error]Please remove the conflicting manual tests on the Polygon UI and try again.[/error]'
                    )
                    raise typer.Exit(1) from None
                raise
        progress.update(task_id, completed=len(entries))


def _upload_testcases_raw(
    problem: api.Problem,
    entries: Optional[List['GenerationTestcaseEntry']] = None,
):
    entries = _extracted_entries(entries)

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
                    f'[error]Failed to upload solution {solution.href()}:[/error]\n{_format_request_failed_comment(e.comment)}'
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
                    f'[error]Failed to delete solution [item]{solution.name}[/item]:[/error]\n{_format_request_failed_comment(e.comment)}'  # pyright: ignore[reportAttributeAccessIssue]
                )


def _get_explanations(explanations: Dict[int, str]) -> str:
    entries = []
    for i in sorted(explanations):
        explanation = explanations[i]
        entries.append(f'\\textbf{{Explanation for example {i + 1}}}\n\n{explanation}')
    return '\n\n'.join(entries)


# Statement-resource scoping (#595). Replaces the old "ship everything under the
# statement dir" rule with explicit `assets` globs plus image/PDF runtime
# defaults over the statement subtree and each staged sample subtree.
_ASSET_EXTS = ('.png', '.jpg', '.jpeg', '.pdf')


def _flat_name(rel: pathlib.Path) -> str:
    """The uploaded (flat) resource name for a relative asset path: subdir
    separators become ``__`` and the extension is kept (``img/diagram.png`` ->
    ``img__diagram.png``)."""
    return str(rel).replace('/', '__')


def _remap_key(rel: pathlib.Path) -> str:
    """The reference key a block uses for an asset: its relative path WITHOUT the
    extension (``\\includegraphics`` is conventionally extensionless)."""
    return str(rel.with_suffix(''))


def _resolve_asset_globs(root: pathlib.Path, globs: List[str]) -> List[pathlib.Path]:
    """Absolute paths of files matching ``globs`` under ``root`` (``Path.glob``,
    so ``**`` recurses). Files only; deduped; deterministically sorted."""
    seen: Set[pathlib.Path] = set()
    for glob in globs:
        for path in root.glob(glob):
            if path.is_file():
                seen.add(utils.abspath(path))
    return sorted(seen)


def _image_files_under(base: pathlib.Path) -> List[pathlib.Path]:
    """Image/PDF files anywhere under ``base`` (recursive), deterministically
    sorted. Empty when ``base`` is not a directory."""
    if not base.is_dir():
        return []
    return sorted(
        path
        for path in base.rglob('*')
        if path.is_file() and path.suffix.lower() in _ASSET_EXTS
    )


def _strip_asset_ext(ref: str) -> str:
    """Drop a trailing image/PDF extension from an ``\\includegraphics`` argument
    so it lines up with a :func:`_remap_key` (which is extensionless)."""
    path = pathlib.Path(ref)
    return str(path.with_suffix('')) if path.suffix.lower() in _ASSET_EXTS else ref


def _rewrite_includegraphics(block: str, remap: Dict[str, str]) -> str:
    """Rewrite every ``\\includegraphics[opts]{ref}`` whose ``ref`` (with any
    image/PDF extension stripped) is a key in ``remap`` to the mapped flat name,
    preserving optional arguments and all surrounding text.

    Parser-based (TexSoup) rather than a naive ``str.replace`` (audit finding
    #6): order-independent, free of substring collisions, and — by stripping the
    extension before lookup — it never produces a double extension
    (``imgs__fig.png.png``)."""
    if not remap:
        return block
    soup = parse_latex(block)
    for node in list(soup.find_all('includegraphics')):
        brace = next((arg for arg in node.args if isinstance(arg, BraceGroup)), None)
        if brace is None:
            continue
        target = remap.get(_strip_asset_ext(str(brace.string)))
        if target is None:
            continue
        opts = ''.join(
            f'[{arg.string}]' for arg in node.args if isinstance(arg, BracketGroup)
        )
        node.replace_with(*parse_latex(f'\\includegraphics{opts}{{{target}}}').contents)
    return str(soup)


@dataclasses.dataclass
class _AssetRemaps:
    """Per-channel reference remaps (asset-reference-without-extension -> uploaded
    flat name). ``statement`` rewrites legend/input/output/the notes block;
    ``samples`` holds a per-explanation-index remap for the sample explanations
    (whose images are referenced sample-dir-relative)."""

    statement: Dict[str, str]
    samples: Dict[int, Dict[str, str]]


def _collect_assets(
    statement: Statement, explanation_indices: Set[int]
) -> Tuple[Dict[str, pathlib.Path], _AssetRemaps]:
    """Resolve the statement's resource set into three scopes (#595).

    Returns ``(uploads, remaps)`` where ``uploads`` maps each uploaded flat name
    to its absolute source path (deduped) and ``remaps`` carries the per-channel
    reference rewrites. Scopes:

    - **statement** — image/PDF under the statement dir, plus explicit ``assets``
      globs that fall under it (any extension), plus the externalized TikZ figure
      PDFs; referenced statement-dir-relative.
    - **sample** — image/PDF under each staged ``.samples/<idx>/`` overlay folder;
      referenced sample-dir-relative, uploaded under a ``sample_<idx>__`` prefix.
    - **out-of-tree** — explicit ``assets`` globs outside the statement dir;
      uploaded by flat name only (no auto-rewrite — referenced by that flat name).
    """
    pkg_root = utils.abspath(pathlib.Path())
    statement_dir = (
        utils.abspath(statement.file).parent if statement.file is not None else pkg_root
    )
    overlay = get_statement_dir(statement)

    uploads: Dict[str, pathlib.Path] = {}
    statement_remap: Dict[str, str] = {}

    def _add_statement_scope(abs_path: pathlib.Path) -> None:
        rel = abs_path.relative_to(statement_dir)
        flat = _flat_name(rel)
        uploads[flat] = abs_path
        statement_remap[_remap_key(rel)] = flat

    # 1. Statement-scope image/PDF defaults.
    for abs_path in _image_files_under(statement_dir):
        _add_statement_scope(abs_path)

    # 1b/3. Explicit assets: under the statement dir -> statement-scope (any
    #       extension); elsewhere -> out-of-tree (uploaded by flat name).
    for abs_path in _resolve_asset_globs(pkg_root, statement.assets):
        if abs_path.is_relative_to(statement_dir):
            _add_statement_scope(abs_path)
            continue
        try:
            rel = abs_path.relative_to(pkg_root)
        except ValueError:
            rel = pathlib.Path(abs_path.name)
        uploads[_flat_name(rel)] = abs_path

    # 2. Externalized TikZ figure PDFs (overlay-relative reference).
    for abs_path, overlay_rel in get_produced_tikz_pdfs(statement):
        flat = _flat_name(overlay_rel)
        uploads[flat] = abs_path
        statement_remap[_remap_key(overlay_rel)] = flat

    # 4. Per-sample scope: image/PDF under each staged .samples/<idx>/.
    sample_remaps: Dict[int, Dict[str, str]] = {}
    for idx in sorted(explanation_indices):
        base = overlay / sample_staging.SAMPLES_DIRNAME / f'{idx:03d}'
        sample_remap: Dict[str, str] = {}
        for abs_path in _image_files_under(base):
            rel = abs_path.relative_to(base)
            flat = f'sample_{idx}__{_flat_name(rel)}'
            uploads[flat] = abs_path
            sample_remap[_remap_key(rel)] = flat
        if sample_remap:
            sample_remaps[idx] = sample_remap

    return uploads, _AssetRemaps(statement=statement_remap, samples=sample_remaps)


def _upload_statement_resources(
    problem: api.Problem, statement: Statement, explanation_indices: Set[int]
) -> _AssetRemaps:
    uploads, remaps = _collect_assets(statement, explanation_indices)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for flat_name, asset in sorted(uploads.items()):
            console.console.print(
                f'Uploading statement resource [item]{flat_name}[/item]...'
            )
            resource_bytes = asset.read_bytes()
            if len(resource_bytes) >= 1024 * 1024:  # >= 1mb
                console.console.print(
                    f'[error]Statement resource [item]{flat_name}[/item] is too large to upload (more than 1MB).[/error]'
                )
                raise typer.Exit(1)
            futures.append(
                executor.submit(
                    problem.save_statement_resource,
                    name=flat_name,
                    file=resource_bytes,
                )
            )
        for future in futures:
            future.result()
    return remaps


async def _upload_statement(
    problem: api.Problem, main_language: Optional[str], upload_as_english: bool = False
):
    pkg = package.find_problem_package_or_die()

    def process_statement(statement: Statement, language: str, uploaded_language: str):
        console.console.print(
            f'Uploading statement for language [item]{language}[/item] (uploaded language: [item]{uploaded_language}[/item])...'
        )
        blocks = get_processed_statement_blocks(statement)
        remaps = _upload_statement_resources(
            problem, statement, set(blocks.explanations)
        )

        def _get_block(block_name: str, blocks=blocks, remaps=remaps) -> str:
            block = blocks.blocks.get(block_name) or ''
            return _rewrite_includegraphics(block, remaps.statement)

        def _rewritten_explanations(blocks=blocks, remaps=remaps) -> Dict[int, str]:
            # An explanation may reference a statement-scope asset (an inline
            # block citing a statement-dir image) or its own sample-scope image;
            # merge both remaps, the sample's winning on a key collision.
            out: Dict[int, str] = {}
            for idx, text in blocks.explanations.items():
                merged = {**remaps.statement, **remaps.samples.get(idx, {})}
                out[idx] = _rewrite_includegraphics(text, merged)
            return out

        def _get_notes_with_explanations(blocks=blocks) -> Optional[str]:
            notes = _get_block('notes')
            explanations = _rewritten_explanations()
            if not notes and not explanations:
                return None
            res = _get_explanations(explanations)
            if notes:
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

    # Build the shared flat namespace only when a source category is actually
    # uploaded -- statements-only uploads need no source naming and must not be
    # aborted by the flattening guardrail. Dependency headers are shared
    # resources, so ship them whenever any source that may ``#include`` them
    # (generators, solutions, checker/validator/interactor) is uploaded.
    uploads_sources = bool(which_upload & {'files', 'solutions', 'tests'})

    # Walk the testcase groups once here, on the async path, and thread the
    # result into the sync upload helpers. Those helpers must not call
    # asyncio.run() themselves -- this function already runs inside the event
    # loop driven by ``syncer`` (#591). The namespace builder needs the entries
    # for ``_collect_generators``, so they are required whenever sources upload.
    entries: Optional[List[GenerationTestcaseEntry]] = (
        await extract_generation_testcases_from_groups() if uploads_sources else None
    )

    ns: Optional[flattening.FlatNamespace] = (
        _build_upload_namespace(entries) if uploads_sources else None
    )
    if ns is not None:
        _upload_dep_files(problem, ns)

        if 'files' in which_upload:
            _update_rbx_header(problem)
            _update_checker(problem, ns)

        if (
            pkg.type == TaskType.COMMUNICATION
            and package.get_interactor_or_nil() is not None
            and 'files' in which_upload
        ):
            _update_interactor(problem, ns)

        if pkg.validator is not None and 'files' in which_upload:
            _upload_validator(problem, ns)

        if 'solutions' in which_upload:
            _upload_solutions(problem, ns)

        if 'tests' in which_upload:
            if raw_tests:
                _upload_testcases_raw(problem, entries)
            else:
                _upload_testcases(problem, ns, entries)

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
