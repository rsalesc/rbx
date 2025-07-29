import pathlib
import tempfile
import typing
from typing import Annotated, Any, Dict, List, Optional, Tuple

import syncer
import typer

from rbx import annotations, console, utils
from rbx.box import environment, limits_info, naming, package
from rbx.box.formatting import href
from rbx.box.schema import Package, expand_any_vars
from rbx.box.statements.builders import (
    BUILDER_LIST,
    PROBLEM_BUILDER_LIST,
    StatementBuilder,
    StatementBuilderContext,
    StatementBuilderProblem,
    StatementCodeLanguage,
    StatementSample,
    prepare_assets,
)
from rbx.box.statements.schema import (
    ConversionStep,
    ConversionType,
    Statement,
    StatementType,
)
from rbx.box.testcase_utils import get_samples

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


def get_environment_languages_for_statement() -> List[StatementCodeLanguage]:
    env = environment.get_environment()

    res = []
    for language in env.languages:
        cmd = ''
        compilation_cfg = environment.get_compilation_config(language.name)
        cmd = ' && '.join(compilation_cfg.commands or [])
        if not cmd:
            execution_cfg = environment.get_execution_config(language.name)
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


def get_relative_assets(
    relative_to: pathlib.Path,
    assets: List[str],
) -> List[Tuple[pathlib.Path, pathlib.Path]]:
    relative_to = utils.abspath(relative_to)
    if not relative_to.is_dir():
        relative_to = relative_to.parent
    res = []
    for asset in assets:
        relative_path = pathlib.Path(asset)
        if not relative_path.is_file():
            globbed = list(
                path
                for path in pathlib.Path().glob(str(relative_path))
                if path.is_file()
            )
            if not globbed and '*' not in str(relative_path):
                console.console.print(
                    f'[error]Asset [item]{asset}[/item] does not exist.[/error]'
                )
                raise typer.Exit(1)
            res.extend(get_relative_assets(relative_to, list(map(str, globbed))))
            continue
        if not utils.abspath(relative_path).is_relative_to(relative_to):
            console.console.print(
                f'[error]Asset [item]{asset}[/item] is not relative to your statement.[/error]'
            )
            raise typer.Exit(1)

        res.append(
            (
                utils.abspath(relative_path),
                utils.abspath(relative_path).relative_to(relative_to),
            )
        )

    return res


def build_statement_bytes(
    statement: Statement,
    pkg: Package,
    output_type: Optional[StatementType] = None,
    short_name: Optional[str] = None,
    overridden_params_root: pathlib.Path = pathlib.Path(),
    overridden_params: Optional[Dict[ConversionType, ConversionStep]] = None,
    overridden_assets: Optional[List[Tuple[pathlib.Path, pathlib.Path]]] = None,
    use_samples: bool = True,
    custom_vars: Optional[Dict[str, Any]] = None,
) -> Tuple[bytes, StatementType]:
    overridden_params = overridden_params or {}
    overridden_assets = overridden_assets or []

    if not statement.path.is_file():
        console.console.print(
            f'[error]Statement file [item]{statement.path}[/item] does not exist.[/error]'
        )
        raise typer.Exit(1)
    builders = get_builders(
        str(statement.path),
        statement.steps,
        statement.configure,
        statement.type,
        output_type,
        builder_list=PROBLEM_BUILDER_LIST,
    )
    last_output = statement.type
    last_content = statement.path.read_bytes()
    for bdr, params in builders:
        with tempfile.TemporaryDirectory() as td:
            # Here, create a new temp context for each builder call.
            assets = get_relative_assets(statement.path, statement.assets)

            # Use either overridden assets (by contest) or usual assets.
            # Remember to modify the root to contest root if that's the case.
            if bdr.name() in overridden_params:
                assets.extend(
                    bdr.inject_assets(
                        overridden_params_root, overridden_params[bdr.name()]
                    )
                )
            else:
                assets.extend(bdr.inject_assets(pathlib.Path(), params))
            assets.extend(overridden_assets)

            prepare_assets(assets, pathlib.Path(td))
            output = bdr.build(
                input=last_content,
                context=StatementBuilderContext(
                    lang=statement.language,
                    languages=get_environment_languages_for_statement(),
                    params=params,
                    root=pathlib.Path(td),
                ),
                item=StatementBuilderProblem(
                    limits=limits_info.get_limits_profile(
                        profile=limits_info.get_active_profile()
                    ),
                    package=pkg,
                    statement=statement,
                    samples=StatementSample.from_testcases(
                        get_samples() if use_samples else []
                    ),
                    short_name=short_name,
                    vars={
                        **pkg.expanded_vars,
                        **statement.expanded_vars,
                        **(custom_vars or {}),
                    },
                ),
                verbose=False,
            )
        last_output = bdr.output_type()
        last_content = output

    return last_content, last_output


def build_statement(
    statement: Statement,
    pkg: Package,
    output_type: Optional[StatementType] = None,
    use_samples: bool = True,
    custom_vars: Optional[Dict[str, Any]] = None,
) -> pathlib.Path:
    last_content, last_output = build_statement_bytes(
        statement,
        pkg,
        output_type=output_type,
        use_samples=use_samples,
        custom_vars=custom_vars,
        short_name=naming.get_problem_shortname(),
    )
    statement_path = (package.get_build_path() / statement.name).with_suffix(
        last_output.get_file_suffix()
    )
    active_profile = limits_info.get_active_profile()
    if (
        active_profile is not None
        and limits_info.get_saved_limits_profile(active_profile) is not None
    ):
        statement_path = statement_path.with_stem(
            f'{statement_path.stem}-{active_profile}'
        )
    statement_path.parent.mkdir(parents=True, exist_ok=True)
    statement_path.write_bytes(last_content)
    console.console.print(
        f'Statement [item]{statement.name}[/item] built successfully for language '
        f'[item]{statement.language}[/item] at '
        f'{href(statement_path)}'
    )
    return statement_path


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
        Optional[StatementType],
        typer.Option(
            case_sensitive=False,
            help='Output type to be generated. If not specified, will infer from the conversion steps specified in the package.',
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
):
    # At most run the validators, only in samples.
    if samples:
        from rbx.box import builder

        if not await builder.build(
            verification=verification,
            groups=set(['samples']),
            output=None,
        ):
            console.console.print(
                '[error]Failed to build statements with samples, aborting.[/error]'
            )
            raise typer.Exit(1)

    pkg = package.find_problem_package_or_die()
    candidate_languages = set(languages or [])
    candidate_names = set(names or [])

    def should_process(st: Statement) -> bool:
        if candidate_languages and st.language not in candidate_languages:
            return False
        if candidate_names and st.name not in candidate_names:
            return False
        return True

    valid_statements = [st for st in pkg.expanded_statements if should_process(st)]

    if not valid_statements:
        console.console.print(
            '[error]No statement found according to the specified criteria.[/error]',
        )
        raise typer.Exit(1)

    for statement in valid_statements:
        build_statement(
            statement,
            pkg,
            output_type=output,
            use_samples=samples,
            custom_vars=expand_any_vars(annotations.parse_dictionary_items(vars)),
        )


@app.callback()
def callback():
    pass
