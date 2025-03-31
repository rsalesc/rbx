import importlib.resources
import pathlib
import re
from typing import List, Optional

import typer
import typer.core
from typing_extensions import Annotated

from rbx import config, metadata
from rbx.config import get_config


def _get_language_options():
    return sorted(get_config().languages.keys())


def _get_language_default():
    return get_config().defaultLanguage


def _get_problem_options():
    options = set()
    all_problems = metadata.find_problems()
    for problem in all_problems:
        options.add(problem.code)
        options.update(problem.aliases)
    return sorted(options)


def _list_files(path: pathlib.Path) -> List[str]:
    if not path.is_dir():
        return []
    return [file.name for file in path.iterdir() if file.is_file()]


def _get_checker_options():
    options = set()
    with importlib.resources.as_file(
        importlib.resources.files('rbx') / 'resources' / 'checkers'
    ) as file:
        options.update(_list_files(file))

    options.update(_list_files(config.get_app_path() / 'checkers'))
    options.remove('boilerplate.cpp')
    return sorted(options)


Timelimit = Annotated[
    int,
    typer.Option(
        '--timelimit',
        '-t',
        help='Time limit in milliseconds.',
        prompt='Time limit (ms)',
    ),
]
Memorylimit = Annotated[
    int,
    typer.Option(
        '--memorylimit',
        '-m',
        help='Memory limit in megabytes.',
        prompt='Memory limit (MB)',
    ),
]
Multitest = Annotated[
    Optional[bool],
    typer.Option(
        '--multitest',
        '-m',
        is_flag=True,
        help='Whether this problem have multiple tests per file.',
        prompt='Multitest?',
    ),
]
Language = Annotated[
    str,
    typer.Option(
        '--language',
        '--lang',
        '-l',
        help='Language to use.',
        prompt='Language',
        default_factory=_get_language_default,
        autocompletion=_get_language_options,
    ),
]
LanguageWithDefault = Annotated[
    Optional[str],
    typer.Option(
        '--language',
        '--lang',
        '-l',
        help='Language to use.',
        autocompletion=_get_language_options,
    ),
]
Problem = Annotated[str, typer.Argument(autocompletion=_get_problem_options)]

ProblemOption = Annotated[
    Optional[str], typer.Option('--problem', '-p', autocompletion=_get_problem_options)
]

TestcaseIndex = Annotated[Optional[int], typer.Option('--index', '--idx', '-i')]

Checker = Annotated[
    str,
    typer.Argument(
        autocompletion=_get_checker_options, help='Path to a testlib checker file.'
    ),
]


class AliasGroup(typer.core.TyperGroup):
    _CMD_SPLIT_P = re.compile(r', ?')

    def get_command(self, ctx, cmd_name):
        cmd_name = self._group_cmd_name(cmd_name)
        return super().get_command(ctx, cmd_name)

    def _group_cmd_name(self, default_name):
        for cmd in self.commands.values():
            if cmd.name and default_name in self._CMD_SPLIT_P.split(cmd.name):
                return cmd.name
        return default_name
