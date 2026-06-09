import pathlib
import typing
from typing import Annotated, Any, Dict, Iterable, List, Optional, Tuple

import syncer
import typer

from rbx import annotations, console
from rbx.box import environment, package
from rbx.box.contest.schema import ContestStatement
from rbx.box.schema import Package
from rbx.box.statements.builders import (
    BUILDER_LIST,
    StatementBuilder,
    StatementCodeLanguage,
)
from rbx.box.statements.schema import (
    ConversionStep,
    ConversionType,
    Statement,
    StatementType,
)

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)

# statements v2: the standalone build pipeline (resolver -> overlay stager ->
# builders) is rebuilt in #560-#566 (S4-S9). Until then these orchestration
# entry points are intentionally stubbed; the pure conversion-step helpers below
# are kept because the v2 builders reuse them. See
# docs/plans/2026-06-09-statements-v2-design.md §7.
_V2_PENDING = (
    'statements v2: the standalone build pipeline is not wired yet; it lands in '
    '#565 (S9). See docs/plans/2026-06-09-statements-v2-design.md.'
)


def get_environment_languages_for_statement() -> List[StatementCodeLanguage]:
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
    assert lhs.type == rhs.type
    return lhs.model_copy(update=rhs.model_dump(exclude_unset=True), deep=True)


def merge_conversion_configurations(
    configure: Iterable[ConversionStep],
) -> List[ConversionStep]:
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
    consolidated = merge_conversion_configurations(
        list(lhs.values()) + list(rhs.values())
    )
    return {step.type: step for step in consolidated}


def _get_overridden_configuration_list(
    configure: List[ConversionStep],
    overridden_params: Dict[ConversionType, ConversionStep],
) -> List[ConversionStep]:
    return merge_conversion_configurations(configure + list(overridden_params.values()))


def get_statement_dir(
    statement: Statement, builder_name: Optional[str] = None
) -> pathlib.Path:
    raise NotImplementedError(_V2_PENDING)


def get_produced_tikz_pdfs(
    statement: Statement,
) -> Iterable[Tuple[pathlib.Path, pathlib.Path]]:
    raise NotImplementedError(_V2_PENDING)


def get_builders(
    statement_id: str,
    steps: List[ConversionStep],
    configure: List[ConversionStep],
    input_type: StatementType,
    output_type: Optional[StatementType],
    builder_list: List[StatementBuilder] = BUILDER_LIST,
) -> List[Tuple[StatementBuilder, ConversionStep]]:
    last_output = input_type
    builders: List[Tuple[StatementBuilder, ConversionStep]] = []

    # Conversion steps to force during build.
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

    # Override statement configs.
    def reconfigure(params: ConversionStep) -> ConversionStep:
        new_params = _get_configured_params_for(configure, params.type)
        return new_params or params

    reconfigured_builders = [
        (builder, reconfigure(params)) for builder, params in builders
    ]
    return reconfigured_builders


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
    raise NotImplementedError(_V2_PENDING)


def get_statement_build_path(
    statement: Statement, output_type: StatementType, profile: Optional[str] = None
) -> pathlib.Path:
    raise NotImplementedError(_V2_PENDING)


def needs_samples(statement: Statement) -> bool:
    raise NotImplementedError(_V2_PENDING)


async def build_statement(
    statement: Statement,
    pkg: Package,
    output_type: StatementType,
    use_samples: bool = True,
    custom_vars: Optional[Dict[str, Any]] = None,
    extra_mergeable_params: Optional[List[ConversionStep]] = None,
) -> pathlib.Path:
    raise NotImplementedError(_V2_PENDING)


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
    raise NotImplementedError(_V2_PENDING)


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
    raise NotImplementedError(_V2_PENDING)


@app.command('build, b', help='Build statements.')
@package.within_problem
@syncer.sync
async def build(
    verification: environment.VerificationParam,
    names: Annotated[
        Optional[List[str]],
        typer.Argument(
            help='Names of statements to build.',
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
        ),
    ] = None,
):
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
