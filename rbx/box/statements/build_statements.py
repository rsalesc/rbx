import pathlib
import shutil
import typing
from typing import Annotated, Any, Dict, Iterable, List, Optional, Tuple

import syncer
import typer

from rbx import annotations, console, utils
from rbx.box import environment, limits_info, naming, package
from rbx.box.contest import contest_package
from rbx.box.contest.schema import ContestStatement
from rbx.box.formatting import href
from rbx.box.schema import Package, expand_any_vars
from rbx.box.statements import engine, overlay, render, resolver
from rbx.box.statements.builders import (
    BUILDER_LIST,
    StatementBuilder,
    StatementCodeLanguage,
)
from rbx.box.statements.context import ContestRenderContext, ProblemRenderContext
from rbx.box.statements.schema import (
    DEFAULT_VARIANT,
    ConversionStep,
    ConversionType,
    Statement,
    StatementType,
)
from rbx.box.testcase_sample_utils import build_samples, get_statement_samples

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)

# statements v2: the Polygon export path (S12, #568) still consumes the v1
# per-builder build dirs / TikZ artifacts. Those entry points stay stubbed until
# the packager is reworked; the standalone build (this module) is rebuilt below.
_V2_POLYGON_PENDING = (
    'statements v2: the Polygon export build path is not wired yet; it lands in '
    '#568 (S12). See docs/plans/2026-06-09-statements-v2-design.md §7.'
)


def get_environment_languages_for_statement() -> List[StatementCodeLanguage]:
    """The configured environment languages exposed to templates as ``languages``
    (id, readable name, and the compile/run command shown in limit tables)."""
    env = environment.get_environment()

    res = []
    for language in env.languages:
        cmd = ''
        compilation_cfg = environment.get_compilation_config(
            language.name, solution=True
        )
        cmd = ' && '.join(compilation_cfg.commands or [])
        if not cmd:
            execution_cfg = environment.get_execution_config(
                language.name, solution=True
            )
            cmd = execution_cfg.command

        res.append(
            StatementCodeLanguage(
                id=language.name,
                name=language.readableName or language.name,
                command=cmd or '',
            )
        )

    return res


def get_builder(
    name: ConversionType, builder_list: List[StatementBuilder]
) -> StatementBuilder:
    """Look up the (legacy v1) builder for a conversion type, or exit. Kept for
    the deferred Polygon export path; the v2 build uses ``render.py`` directly."""
    candidates = [builder for builder in builder_list if builder.name() == name]
    if not candidates:
        console.console.print(
            f'[error]No statement builder found with name [name]{name}[/name][/error]'
        )
        raise typer.Exit(1)
    return candidates[0]


def get_implicit_builders(
    input_type: StatementType, output_type: StatementType
) -> Optional[List[StatementBuilder]]:
    """Shortest chain of (legacy v1) builders converting ``input_type`` to
    ``output_type``, or None if unreachable.

    A BFS over ``BUILDER_LIST`` treating each builder as an edge
    ``input_type -> output_type``; ``par`` maps a reached type to the builder
    that produced it, then the chain is walked back from ``output_type``. Legacy
    v1 machinery kept for the deferred Polygon path.
    """
    par: Dict[StatementType, Optional[StatementBuilder]] = {input_type: None}

    def _iterate() -> bool:
        nonlocal par
        for bdr in BUILDER_LIST:
            u = bdr.input_type()
            if u not in par:
                continue
            v = bdr.output_type()
            if v in par:
                continue
            par[v] = bdr
            return True
        return False

    while _iterate() and output_type not in par:
        pass

    if output_type not in par:
        return None

    res = []
    cur = output_type
    while par[cur] is not None:
        res.append(par[cur])
        cur = typing.cast(StatementBuilder, par[cur]).input_type()

    return list(reversed(res))


def _try_implicit_builders(
    statement_id: str, input_type: StatementType, output_type: StatementType
) -> List[StatementBuilder]:
    """Like :func:`get_implicit_builders` but exits with an error message when no
    conversion chain exists (legacy v1 path)."""
    implicit_builders = get_implicit_builders(input_type, output_type)
    if implicit_builders is None:
        console.console.print(
            f'[error]Cannot implicitly convert statement [item]{statement_id}[/item] '
            f'from [item]{input_type}[/item] '
            f'to specified output type [item]{output_type}[/item].[/error]'
        )
        raise typer.Exit(1)
    console.console.print(
        'Implicitly adding statement builders to convert statement '
        f'from [item]{input_type}[/item] to [item]{output_type}[/item]...'
    )
    return implicit_builders


def _get_configured_params_for(
    configure: List[ConversionStep], conversion_type: ConversionType
) -> Optional[ConversionStep]:
    for step in configure:
        if step.type == conversion_type:
            return step
    return None


def merge_conversion_steps(lhs: ConversionStep, rhs: ConversionStep) -> ConversionStep:
    """Overlay the explicitly-set fields of ``rhs`` onto ``lhs`` (same type)."""
    assert lhs.type == rhs.type
    return lhs.model_copy(update=rhs.model_dump(exclude_unset=True), deep=True)


def merge_conversion_configurations(
    configure: Iterable[ConversionStep],
) -> List[ConversionStep]:
    """Collapse a list of conversion steps to one per type, later steps
    overlaying earlier ones via :func:`merge_conversion_steps`."""
    mapping = {}
    for step in configure:
        if step.type not in mapping:
            mapping[step.type] = step
            continue
        mapping[step.type] = merge_conversion_steps(mapping[step.type], step)
    return list(mapping.values())


def merge_conversion_configuration_maps(
    lhs: Dict[ConversionType, ConversionStep],
    rhs: Dict[ConversionType, ConversionStep],
) -> Dict[ConversionType, ConversionStep]:
    """Merge two type-keyed conversion-step maps, ``rhs`` overlaying ``lhs``."""
    consolidated = merge_conversion_configurations(
        list(lhs.values()) + list(rhs.values())
    )
    return {step.type: step for step in consolidated}


def _get_overridden_configuration_list(
    configure: List[ConversionStep],
    overridden_params: Dict[ConversionType, ConversionStep],
) -> List[ConversionStep]:
    return merge_conversion_configurations(configure + list(overridden_params.values()))


def get_builders(
    statement_id: str,
    steps: List[ConversionStep],
    configure: List[ConversionStep],
    input_type: StatementType,
    output_type: Optional[StatementType],
    builder_list: List[StatementBuilder] = BUILDER_LIST,
) -> List[Tuple[StatementBuilder, ConversionStep]]:
    """Resolve the ordered ``(builder, params)`` pipeline that turns
    ``input_type`` into ``output_type`` (legacy v1 path).

    Walks the explicit ``steps``, inserting implicit conversion builders
    (:func:`get_implicit_builders`) wherever consecutive types don't line up,
    then appends implicit builders to reach ``output_type``. Finally each step's
    params are overridden by any matching entry in ``configure``. ``statement_id``
    is only used for error messages. Kept for the deferred Polygon export path.
    """
    last_output = input_type
    builders: List[Tuple[StatementBuilder, ConversionStep]] = []

    for step in steps:
        builder = get_builder(step.type, builder_list=builder_list)
        if builder.input_type() != last_output:
            implicit_builders = _try_implicit_builders(
                statement_id, last_output, builder.input_type()
            )
            builders.extend(
                (builder, builder.default_params()) for builder in implicit_builders
            )
        builders.append((builder, step))
        last_output = builder.output_type()

    if output_type is not None and last_output != output_type:
        implicit_builders = _try_implicit_builders(
            statement_id, last_output, output_type
        )
        builders.extend(
            (builder, builder.default_params()) for builder in implicit_builders
        )

    def reconfigure(params: ConversionStep) -> ConversionStep:
        new_params = _get_configured_params_for(configure, params.type)
        return new_params or params

    reconfigured_builders = [
        (builder, reconfigure(params)) for builder, params in builders
    ]
    return reconfigured_builders


# --- Polygon export path (deferred to S12); kept importable. ---


def get_statement_dir(
    statement: Statement, builder_name: Optional[str] = None
) -> pathlib.Path:
    """[deferred S12] The per-builder Polygon scratch dir. Stubbed until #568."""
    raise NotImplementedError(_V2_POLYGON_PENDING)


def get_produced_tikz_pdfs(
    statement: Statement,
) -> Iterable[Tuple[pathlib.Path, pathlib.Path]]:
    """[deferred S12] Externalized TikZ PDFs for Polygon resource upload. Stubbed
    until #568."""
    raise NotImplementedError(_V2_POLYGON_PENDING)


async def build_statement_bytes(
    statement: Statement,
    pkg: Package,
    output_type: Optional[StatementType] = None,
    short_name: Optional[str] = None,
    overridden_params_root: pathlib.Path = pathlib.Path(),
    overridden_params: Optional[Dict[ConversionType, ConversionStep]] = None,
    overridden_assets: Optional[List[Tuple[pathlib.Path, pathlib.Path]]] = None,
    use_samples: bool = True,
    custom_vars: Optional[Dict[str, Any]] = None,
    inherited_from: Optional['ContestStatement'] = None,
) -> Tuple[bytes, StatementType]:
    """[deferred S12] The v1 byte-level build the Polygon block extractor relied
    on. Stubbed until #568; the v2 standalone build is :func:`build_statement`."""
    raise NotImplementedError(_V2_POLYGON_PENDING)


# --- v2 standalone build (S9). ---


def _variant_suffix(statement: Statement) -> str:
    """The ``-<variant>`` filename suffix, empty for the default variant."""
    return '' if statement.variant == DEFAULT_VARIANT else f'-{statement.variant}'


def get_statement_build_path(
    statement: Statement, output_type: StatementType, profile: Optional[str] = None
) -> pathlib.Path:
    """The *final* output path for a built standalone statement, e.g.
    ``build/statement-en[-<variant>][-<profile>].pdf`` (design §7.2).

    This sits at the package build root (``get_build_path()``), NOT under the
    statements scratch dir — it is the artifact a user opens.
    """
    name = f'statement-{statement.language}{_variant_suffix(statement)}'
    path = (package.get_build_path() / name).with_suffix(output_type.get_file_suffix())
    if (
        profile is not None
        and limits_info.get_saved_limits_profile(profile) is not None
    ):
        path = path.with_stem(f'{path.stem}-{profile}')
    return path


def needs_samples(statement: Statement) -> bool:
    """Whether this statement should be built with sample I/O."""
    return statement.samples


def _standalone_overlay_root(statement: Statement) -> pathlib.Path:
    """The isolated *scratch* overlay root for this statement's standalone build.

    ``package.get_statements_build_path()`` is the shared ``build/statements``
    directory (it also holds e.g. interactive-sample chunk folders), so each
    standalone build gets its own subtree under it, keyed by
    ``(language, variant)``, to avoid clobbering other statements' overlays. The
    merged contest-chrome + problem-dir overlay is staged here and ``pdflatex``
    runs from it; it is wiped and recreated on every build. The final PDF is
    copied out to :func:`get_statement_build_path`.
    """
    root = (
        package.get_statements_build_path()
        / 'st'
        / f'{statement.language}-{statement.variant}'
    )
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _explanation_suffix(statement: Statement) -> str:
    """The on-disk suffix of a sample's explanation file for this statement type."""
    return '.md' if statement.type == StatementType.rbxMarkdown else '.tex'


def _externalize_demacro(
    extra_mergeable_params: Optional[List[ConversionStep]],
) -> Tuple[bool, bool]:
    """Resolve TikZ-externalize / demacro from packager-supplied steps (design
    §6 decision 6: these are export-time toggles, not user schema)."""
    externalize = False
    demacro = False
    for step in extra_mergeable_params or []:
        externalize = externalize or bool(getattr(step, 'externalize', False))
        demacro = demacro or bool(getattr(step, 'demacro', False))
    return externalize, demacro


def _emit_output(
    root: pathlib.Path,
    tex: bytes,
    statement: Statement,
    output_type: StatementType,
    *,
    externalize: bool = False,
    demacro: bool = False,
) -> bytes:
    """Take rendered TeX (or Markdown) and produce the requested output bytes."""
    if output_type == StatementType.PDF:
        if statement.type == StatementType.Markdown:
            return render.md_to_pdf(root, tex)
        return render.compile_pdf(root, tex, externalize=externalize, demacro=demacro)
    if output_type in (StatementType.TeX, StatementType.Markdown):
        return tex
    console.console.print(
        f'[error]statements v2 cannot yet emit output type [item]{output_type}[/item] '
        '(only pdf/tex/md). See #569 (S13).[/error]'
    )
    raise typer.Exit(1)


def _require_file(statement: Statement) -> None:
    """Exit with an error if the statement's source ``file`` is missing."""
    if statement.file is None or not statement.file.is_file():
        console.console.print(
            f'[error]Statement file [item]{statement.file}[/item] does not exist.[/error]'
        )
        raise typer.Exit(1)


async def build_statement(
    statement: Statement,
    pkg: Package,
    output_type: StatementType,
    use_samples: bool = True,
    custom_vars: Optional[Dict[str, Any]] = None,
    extra_mergeable_params: Optional[List[ConversionStep]] = None,
) -> pathlib.Path:
    """Build one problem statement standalone and return its output path.

    For an *rbx* statement: resolve the owning contest and its
    ``standaloneProblemTemplate`` (a contest is required), stage the merged
    overlay (contest chrome + the problem statement-dir), render the template as
    a full document, compile, and write ``build/statement-<lang>[-<variant>].pdf``.
    Static ``pdf`` is copied as-is; static ``tex``/``md`` are staged and emitted
    without a contest.

    Args:
        statement: the (expanded) problem statement to build.
        pkg: the loaded problem package (source of ``vars``, limits, groups).
        output_type: the desired output (``PDF``/``TeX``/``Markdown``).
        use_samples: stage sample I/O (assumes samples were already built).
        custom_vars: ``--vars`` overrides merged on top of the package vars.
        extra_mergeable_params: packager-supplied export toggles
            (TikZ-externalize / demacro); empty for non-Polygon builds.
    """
    languages = get_environment_languages_for_statement()
    custom_vars = custom_vars or {}

    # Static PDF: nothing to render, just publish the file.
    if statement.type == StatementType.PDF:
        _require_file(statement)
        assert statement.file is not None
        out_path = get_statement_build_path(
            statement, StatementType.PDF, limits_info.get_active_profile()
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(statement.file, out_path)
        _report_built(statement, out_path)
        return out_path

    _require_file(statement)
    assert statement.file is not None

    overlay_root = _standalone_overlay_root(statement)
    problem_dir = utils.abspath(statement.file).parent

    if statement.type.is_rbx():
        contest = resolver.require_contest_for_problem()
        contest_statement = resolver.select_standalone_contest_statement(
            statement, contest.expanded_statements
        )
        contest_root = contest_package.find_contest()
        assert contest_statement.file is not None
        chrome_dir = utils.abspath(contest_root / contest_statement.file).parent

        overlay.stage_standalone_overlay(
            overlay_root, chrome_dir=chrome_dir, problem_dir=problem_dir
        )
        assert contest_statement.standaloneProblemTemplate is not None
        template_rel = engine.relativize_template(
            contest_root,
            chrome_dir,
            contest_statement.standaloneProblemTemplate,
            overlay_root,
        )

        problem_ctx = ProblemRenderContext(
            title=naming.get_problem_title(statement.language, statement, pkg),
            vars={**pkg.expanded_vars, **custom_vars},
            params=statement.expanded_params,
            short_name=naming.get_problem_shortname(),
            limits=limits_info.get_limits_profile(
                profile=limits_info.get_active_profile()
            ),
            profiles=limits_info.get_available_limits_profiles(),
            groups={g.name: g for g in pkg.testcases},
        )
        contest_ctx = ContestRenderContext(
            title=naming.get_contest_title(
                lang=statement.language, statement=contest_statement, contest=contest
            ),
            vars=contest.expanded_vars,
            params=contest_statement.expanded_vars,
            location=contest_statement.location,
            date=contest_statement.date,
        )

        samples = (
            await get_statement_samples(
                explanation_suffix=_explanation_suffix(statement)
            )
            if use_samples
            else []
        )
        tex = engine.render_problem_tex(
            render_root=overlay_root,
            problem_root=overlay_root,
            root_prefix='',
            template_rel=template_rel,
            content=statement.file.read_bytes(),
            lang=statement.language,
            languages=languages,
            problem=problem_ctx,
            contest=contest_ctx,
            samples=samples,
            use_samples=use_samples,
            statement_type=statement.type,
        )
    else:
        # Static tex / md: mirror the statement-dir subtree so assets resolve,
        # then publish the (raw) content. No contest/template needed.
        overlay.mirror_tree(problem_dir, overlay_root)
        tex = statement.file.read_bytes()

    externalize, demacro = _externalize_demacro(extra_mergeable_params)
    output_bytes = _emit_output(
        overlay_root,
        tex,
        statement,
        output_type,
        externalize=externalize,
        demacro=demacro,
    )
    out_path = get_statement_build_path(
        statement, output_type, limits_info.get_active_profile()
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(output_bytes)
    _report_built(statement, out_path)
    return out_path


def _report_built(statement: Statement, path: pathlib.Path) -> None:
    """Print the success line with a clickable link to the built statement."""
    console.console.print(
        f'Statement for language [item]{statement.language}[/item]'
        f'{_variant_suffix(statement)} built successfully at {href(path)}'
    )


async def execute_build_on_statements(
    statements: List[Statement],
    verification: environment.VerificationParam,
    output: StatementType = StatementType.PDF,
    samples: bool = True,
    vars: Optional[List[str]] = None,
    validate: bool = True,
    extra_mergeable_params: Optional[List[ConversionStep]] = None,
    skip_building: bool = False,
) -> List[pathlib.Path]:
    """Build samples once (if any statement needs them) then build each statement.

    The shared entry point for both ``rbx st b`` and the packagers. ``vars`` are
    raw ``key=value`` ``--vars`` strings. ``skip_building`` only checks/validates
    pre-built samples instead of regenerating them (the packager builds them
    first). ``extra_mergeable_params`` carries packager export toggles. Returns
    the built output paths, one per statement.
    """
    pkg = package.find_problem_package_or_die()
    samples = samples and any(needs_samples(st) for st in statements)

    if samples:
        if not await build_samples(
            verification, validate, check_outputs_only=skip_building
        ):
            console.console.print(
                '[error]Failed to build statements with samples, aborting.[/error]'
            )
            raise typer.Exit(1)

    res = []
    for statement in statements:
        res.append(
            await build_statement(
                statement,
                pkg,
                output_type=output,
                use_samples=samples,
                custom_vars=expand_any_vars(annotations.parse_dictionary_items(vars)),
                extra_mergeable_params=extra_mergeable_params,
            )
        )
    return res


async def execute_build(
    verification: environment.VerificationParam,
    names: Optional[List[str]] = None,
    languages: Optional[List[str]] = None,
    output: StatementType = StatementType.PDF,
    samples: bool = True,
    vars: Optional[List[str]] = None,
    validate: bool = True,
    profile: Optional[str] = None,
) -> None:
    """Select and build this problem's statements (the ``rbx st b`` body).

    Filters ``pkg.expanded_statements`` by ``languages`` and ``names`` (which, in
    v2, match the statement *variant* since problem statements have no name),
    optionally under a timing ``profile``, and delegates to
    :func:`execute_build_on_statements`. Errors if nothing matches.
    """
    if profile is not None:
        limits_info.get_limits_profile(profile, fallback_to_package_profile=False)

    with limits_info.use_profile(profile, when=lambda: profile is not None):
        pkg = package.find_problem_package_or_die()
        candidate_languages = set(languages or [])
        candidate_variants = set(names or [])

        def should_process(st: Statement) -> bool:
            if candidate_languages and st.language not in candidate_languages:
                return False
            if candidate_variants and st.variant not in candidate_variants:
                return False
            return True

        valid_statements = [st for st in pkg.expanded_statements if should_process(st)]

        if not valid_statements:
            console.console.print(
                '[error]No statement found according to the specified criteria.[/error]',
            )
            raise typer.Exit(1)

        await execute_build_on_statements(
            valid_statements,
            verification,
            output=output,
            samples=samples,
            vars=vars,
            validate=validate,
        )


@app.command('build, b', help='Build statements.')
@package.within_problem
@syncer.sync
async def build(
    verification: environment.VerificationParam,
    names: Annotated[
        Optional[List[str]],
        typer.Argument(
            help='Variants of statements to build.',
        ),
    ] = None,
    languages: Annotated[
        Optional[List[str]],
        typer.Option(
            help='Languages to build statements for. If not specified, build statements for all available languages.',
        ),
    ] = None,
    output: Annotated[
        StatementType,
        typer.Option(
            case_sensitive=False,
            help='Output type to be generated.',
        ),
    ] = StatementType.PDF,
    samples: Annotated[
        bool,
        typer.Option(help='Whether to build the statement with samples or not.'),
    ] = True,
    vars: Annotated[
        Optional[List[str]],
        typer.Option(
            '--vars',
            help='Variables to be used in the statements.',
        ),
    ] = None,
    validate: Annotated[
        bool,
        typer.Option(help='Whether to validate outputs for testcases or not.'),
    ] = True,
    profile: Annotated[
        Optional[str],
        typer.Option(
            '-p',
            '--profile',
            help='Timing profile to render the statement against. Must exist in this problem.',
            autocompletion=annotations._adapt('profile'),  # noqa: SLF001
        ),
    ] = None,
):
    """``rbx st b`` — build this problem's statements (standalone).

    Thin Typer wrapper over :func:`execute_build`; see the option help above for
    each argument.
    """
    await execute_build(
        verification,
        names,
        languages,
        output,
        samples,
        vars,
        validate,
        profile=profile,
    )


@app.callback()
def callback():
    pass
