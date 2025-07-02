import dataclasses
import pathlib
import subprocess
import tempfile
import typing
from typing import Any, Dict, List, Optional, Tuple

import typer

from rbx import console, testing_utils, utils
from rbx.box import cd, package
from rbx.box.contest.contest_package import get_problems
from rbx.box.contest.schema import Contest, ContestProblem, ContestStatement
from rbx.box.formatting import href
from rbx.box.schema import Package, Testcase
from rbx.box.statements import build_statements
from rbx.box.statements.build_statements import (
    get_builders,
    get_environment_languages_for_statement,
    get_relative_assets,
)
from rbx.box.statements.builders import (
    CONTEST_BUILDER_LIST,
    StatementBuilderContest,
    StatementBuilderContext,
    StatementBuilderProblem,
    StatementSample,
    prepare_assets,
)
from rbx.box.statements.joiners import (
    JOINER_LIST,
    StatementJoiner,
    StatementJoinerContext,
)
from rbx.box.statements.schema import Statement, StatementType
from rbx.box.testcase_utils import get_samples


@dataclasses.dataclass
class ExtractedProblem:
    package: Package
    statement: Statement
    problem: ContestProblem
    samples: List[Testcase]
    built_statement: Optional[pathlib.Path] = None

    def get_statement_path(self) -> pathlib.Path:
        return self.problem.get_path() / self.statement.path

    def get_statement_assets(self) -> List[str]:
        return [str(self.problem.get_path() / asset) for asset in self.statement.assets]

    def get_statement_builder_problem(self) -> StatementBuilderProblem:
        return StatementBuilderProblem(
            package=self.package,
            statement=self.statement,
            samples=StatementSample.from_testcases(self.samples),
            io_path=self.built_statement,
            short_name=self.problem.short_name,
        )


def _get_samples(problem: ContestProblem) -> List[Testcase]:
    with cd.new_package_cd(problem.get_path()):
        package.clear_package_cache()
        return get_samples()


def get_statement_builder_problems(
    extracted_problems: List[ExtractedProblem],
) -> List[StatementBuilderProblem]:
    return [ex.get_statement_builder_problem() for ex in extracted_problems]


def get_statement_builder_contest(
    statement: ContestStatement,
    extracted_problems: List[ExtractedProblem],
) -> StatementBuilderContest:
    return StatementBuilderContest(
        title=statement.title,
        location=statement.location,
        date=statement.date,
        problems=get_statement_builder_problems(extracted_problems),
    )


def get_problems_for_statement(
    contest: Contest,
    contest_statement: ContestStatement,
    requires_matching_statement: bool = True,
) -> List[ExtractedProblem]:
    pkgs = get_problems(contest)
    if not pkgs and not requires_matching_statement:
        console.console.print(
            '[error]No problems found in the contest, cannot infer statement type.[/error]'
        )
        raise typer.Exit(1)

    def matches(statement: Statement) -> bool:
        if not requires_matching_statement:
            return True
        if contest_statement.match is None:
            return statement.language == contest_statement.language
        return statement.name == contest_statement.match

    res = []
    for pkg, problem in zip(pkgs, contest.problems):
        matching_statements = [
            statement for statement in pkg.expanded_statements if matches(statement)
        ]
        if not matching_statements:
            console.console.print(
                f'[error]No statement found for language {contest_statement.language} in problem {problem.short_name}[/error]'
            )
            raise typer.Exit(1)
        res.append(
            ExtractedProblem(
                package=pkg,
                statement=matching_statements[0],
                problem=problem,
                samples=_get_samples(problem),
            )
        )

    return res


def get_builder_problems(
    extracted_problems: List[ExtractedProblem],
) -> List[StatementBuilderProblem]:
    return [
        StatementBuilderProblem(
            package=ex.package,
            statement=ex.statement,
            samples=StatementSample.from_testcases(ex.samples),
        )
        for ex in extracted_problems
    ]


def get_joiner(name: str) -> StatementJoiner:
    for joiner in JOINER_LIST:
        if joiner.name() == name:
            return joiner
    console.console.print(f'[error]Joiner [item]{name}[/item] not found.[/error]')
    raise typer.Exit(1)


def _build_problem_statements(
    statement: ContestStatement,
    contest: Contest,
    root: pathlib.Path,
    output_type: StatementType,
    use_samples: bool = True,
    custom_vars: Optional[Dict[str, Any]] = None,
) -> List[ExtractedProblem]:
    console.console.print('Building problem-level statements...')
    extracted_problems = get_problems_for_statement(contest, statement)
    res = []
    contest_cwd_absolute = utils.abspath(pathlib.Path())
    contest_assets = get_relative_assets(statement.path, statement.assets)

    extra_vars = dict(statement.override.vars if statement.override is not None else {})
    extra_vars.update(custom_vars or {})

    for extracted_problem in extracted_problems:
        console.console.print(
            f'Building statement for problem {extracted_problem.problem.short_name}...'
        )
        with cd.new_package_cd(extracted_problem.problem.get_path()):
            package.clear_package_cache()
            # TODO: respect steps override
            content, _ = build_statements.build_statement_bytes(
                extracted_problem.statement,
                extracted_problem.package,
                output_type=output_type,
                short_name=extracted_problem.problem.short_name,
                overridden_params={
                    cfg.type: cfg for cfg in statement.override.configure
                }
                if statement.override is not None
                else {},  # overridden configure params
                overridden_assets=contest_assets,  # overridden assets
                overridden_params_root=contest_cwd_absolute,
                use_samples=use_samples,
                # Use custom var overriding and problem-level overriding.
                custom_vars=extra_vars,
            )
        dest_dir = root / '.problems' / extracted_problem.problem.short_name
        dest_path = dest_dir / f'statement{output_type.get_file_suffix()}'
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(content)

        problem_assets = (
            get_relative_assets(
                extracted_problem.get_statement_path(),
                extracted_problem.get_statement_assets(),
            )
            + contest_assets
        )
        prepare_assets(problem_assets, dest_dir)

        res.append(dataclasses.replace(extracted_problem, built_statement=dest_path))
    return res


def build_contest_only(
    statement: ContestStatement,
    contest: Contest,
    extracted_problems: List[ExtractedProblem],
    input: bytes,
    input_type: StatementType,
    output_type: Optional[StatementType] = None,
    custom_vars: Optional[Dict[str, Any]] = None,
    install_tex: bool = False,
) -> Tuple[bytes, StatementType]:
    console.console.print('Building contest-level statement.')
    if install_tex:
        output_type = StatementType.TeX

    bdrs = get_builders(
        contest.name,
        statement.steps,
        statement.configure,
        input_type,
        output_type=output_type,
        builder_list=CONTEST_BUILDER_LIST,
    )

    last_content = input
    last_output = input_type
    for bdr, params in bdrs:
        with tempfile.TemporaryDirectory() as td:
            assets = get_relative_assets(
                statement.path, statement.assets
            ) + bdr.inject_assets(pathlib.Path(), params)
            prepare_assets(assets, pathlib.Path(td))
            output = bdr.build(
                input=last_content,
                context=StatementBuilderContext(
                    lang=statement.language,
                    languages=get_environment_languages_for_statement(),
                    params=params,
                    root=pathlib.Path(td),
                    custom_vars=custom_vars,
                    vars={**contest.expanded_vars, **statement.expanded_vars},
                ),
                item=get_statement_builder_contest(statement, extracted_problems),
                verbose=False,
            )

            if install_tex and bdr.output_type() == StatementType.TeX:
                console.console.log(
                    f'Installing LaTeX packages for [item]{statement.name} {statement.language}[/item]...'
                )
                subprocess.run(
                    ['texliveonfly', output],
                    cwd=td,
                )
        last_content = output
        last_output = bdr.output_type()

    return last_content, last_output


def build_statement_rooted(
    statement: ContestStatement,
    contest: Contest,
    root: pathlib.Path,
    output_type: Optional[StatementType] = None,
    use_samples: bool = True,
    custom_vars: Optional[Dict[str, Any]] = None,
    install_tex: bool = False,
) -> Tuple[bytes, StatementType]:
    # Validate.
    if not statement.path.is_file():
        console.console.print(
            f'[error]Statement file [item]{statement.path}[/item] does not exist for contest.[/error]'
        )
        raise typer.Exit(1)

    if statement.joiner is None:
        joiner = None
        extracted_problems = get_problems_for_statement(
            contest, statement, requires_matching_statement=False
        )
    else:
        # Build problem-level statements.
        joiner = get_joiner(statement.joiner.type)
        extracted_problems = _build_problem_statements(
            statement,
            contest,
            root,
            output_type=joiner.joined_type(),
            use_samples=use_samples,
            custom_vars=custom_vars,
        )

    # Build contest-level statement into joiner input type.
    last_content, last_output = build_contest_only(
        statement,
        contest,
        extracted_problems,
        statement.path.read_bytes(),
        statement.type,
        output_type=joiner.joined_type() if joiner is not None else output_type,
        custom_vars=custom_vars,
        install_tex=install_tex,
    )

    if joiner is None or install_tex:
        return last_content, last_output
    assert statement.joiner is not None

    # Join statements.
    console.console.print('Joining statements...')
    joiner_assets = get_relative_assets(statement.path, statement.assets)
    prepare_assets(joiner_assets, root)

    testing_utils.print_directory_tree(root, show_hidden=True)

    joiner_context = StatementJoinerContext(
        languages=get_environment_languages_for_statement(),
        params=statement.joiner,
        root=root,
    )
    last_content = joiner.build(
        last_content,
        context=joiner_context,
        contest=get_statement_builder_contest(statement, extracted_problems),
    )
    last_output = joiner.output_type()

    # Finish statement.
    last_content, last_output = build_contest_only(
        statement,
        contest,
        extracted_problems,
        last_content,
        last_output,
        output_type=output_type,
        custom_vars=custom_vars,
    )

    return last_content, last_output


def build_statement(
    statement: ContestStatement,
    contest: Contest,
    output_type: Optional[StatementType] = None,
    use_samples: bool = True,
    custom_vars: Optional[Dict[str, Any]] = None,
    install_tex: bool = False,
) -> pathlib.Path:
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        last_content, last_output = build_statement_rooted(
            statement,
            contest,
            root,
            output_type=output_type,
            use_samples=use_samples,
            custom_vars=custom_vars,
            install_tex=install_tex,
        )

    statement_path = (pathlib.Path('build') / statement.name).with_suffix(
        last_output.get_file_suffix()
    )
    statement_path.parent.mkdir(parents=True, exist_ok=True)
    statement_path.write_bytes(typing.cast(bytes, last_content))
    console.console.print(
        f'[success]Statement [item]{statement.name}[/item] built successfully for language '
        f'[item]{statement.language}[/item] at '
        f'{href(statement_path)}[/success]'
    )
    return statement_path
