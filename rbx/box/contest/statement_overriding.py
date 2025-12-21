import pathlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from rbx import utils
from rbx.box import naming
from rbx.box.contest import contest_package
from rbx.box.contest.schema import ContestStatement
from rbx.box.exception import RbxException
from rbx.box.fields import Primitive
from rbx.box.statements import statement_utils
from rbx.box.statements.builders import StatementBuilderContest
from rbx.box.statements.schema import ConversionStep, ConversionType, Statement


class StatementInheritanceError(RbxException):
    pass


@dataclass
class StatementOverrideData:
    root: pathlib.Path
    assets: List[Tuple[pathlib.Path, pathlib.Path]]
    params: Dict[ConversionType, ConversionStep]
    vars: Dict[str, Any]
    inheritedFrom: Optional[ContestStatement] = None

    def to_kwargs(self, custom_vars: Dict[str, Any]) -> Dict[str, Any]:
        extra_vars = dict(self.vars)
        extra_vars.update(custom_vars or {})
        return {
            'overridden_params_root': self.root,
            'overridden_assets': self.assets,
            'overridden_params': self.params,
            'custom_vars': extra_vars,
            'inherited_from': self.inheritedFrom,
        }


def get_overrides(
    statement: ContestStatement, inherit: bool = False
) -> StatementOverrideData:
    override = statement.inheritOverride if inherit else statement.override
    contest_cwd_absolute = utils.abspath(contest_package.find_contest())
    contest_assets = statement_utils.get_relative_assets(
        contest_cwd_absolute / statement.path,
        statement.assets,
        root=contest_cwd_absolute,
    )
    overridden_params = {}
    if override is not None:
        overridden_params.update({cfg.type: cfg for cfg in override.configure})
    return StatementOverrideData(
        root=contest_cwd_absolute,
        assets=contest_assets,
        params=overridden_params,
        vars=override.vars if override is not None else {},
        inheritedFrom=statement if inherit else None,
    )


def get_inheritance_overrides(statement: Statement) -> StatementOverrideData:
    contest = contest_package.find_contest_package()
    if contest is None:
        with StatementInheritanceError() as e:
            e.print(
                f'[error][item]{statement.name}[/item] inherits its configuration from the contest, but no contest was found.[/error]'
            )
        raise e

    def matches(contest_statement: ContestStatement) -> bool:
        if contest_statement.joiner is None:
            return False
        if contest_statement.match is None:
            return statement.language == contest_statement.language
        return statement.name == contest_statement.match

    for contest_statement in contest.statements:
        if matches(contest_statement):
            return get_overrides(contest_statement, inherit=True)

    with StatementInheritanceError() as e:
        e.print(
            f'[error][item]{statement.name}[/item] inherits its configuration from the contest, but no matching statement was found in the contest.[/error]'
        )
    raise e


def get_statement_builder_contest_for_problem(
    language: Optional[str] = None,
    inherited_from: Optional[ContestStatement] = None,
    custom_vars: Optional[Dict[str, Primitive]] = None,
) -> Optional[StatementBuilderContest]:
    contest = contest_package.find_contest_package()
    if contest is None:
        return None
    return StatementBuilderContest(
        title=naming.get_contest_title(
            lang=inherited_from.language if inherited_from is not None else language,
            statement=inherited_from,
            contest=contest,
        ),
        problems=[],
        vars={
            **contest.expanded_vars,
            **(inherited_from.expanded_vars if inherited_from is not None else {}),
            **(custom_vars or {}),
        },
    )
