import re
from typing import Any, Dict, List, Optional

import typer
import typer.core
from typing_extensions import Annotated


class _PackagePathMarker:
    """Marker for path parameters that should be resolved relative to the package root."""


PackagePath = _PackagePathMarker()


def _adapt(key: str):
    """Typer autocompletion callback that delegates to the registry completer `key`.

    Builds the same CompletionContext the fast engine builds, so real-Typer and
    fast-path completions agree. Returns plain string values (Typer wraps them).
    """

    def _cb(incomplete: str = ''):
        from rbx.box.completion import (
            completers,  # noqa: F401  (registers keys)
            context,
        )
        from rbx.box.completion.registry import CompletionContext, load_completer

        ctx = CompletionContext(
            args=[],
            command=(),
            option_values={},
            package_root=context.find_package_root(),
        )
        return [item.value for item in load_completer(key)(ctx, incomplete)]

    _cb._completer_key = key  # noqa: SLF001  read by the spec generator to recover the key
    return _cb


def _get_language_default():
    from rbx.config import get_config

    return get_config().defaultLanguage


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
        autocompletion=_adapt('language'),
    ),
]
LanguageWithDefault = Annotated[
    Optional[str],
    typer.Option(
        '--language',
        '--lang',
        '-l',
        help='Language to use.',
        autocompletion=_adapt('language'),
    ),
]
Problem = Annotated[str, typer.Argument(autocompletion=_adapt('problem'))]

ProblemOption = Annotated[
    Optional[str], typer.Option('--problem', '-p', autocompletion=_adapt('problem'))
]

TestcaseIndex = Annotated[Optional[int], typer.Option('--index', '--idx', '-i')]

Checker = Annotated[
    str,
    typer.Argument(
        autocompletion=_adapt('checker'), help='Path to a testlib checker file.'
    ),
]


def parse_dictionary(value: Optional[str]) -> Dict[str, Any]:
    if value is None:
        return {}
    res = {}
    for item in value.split(','):
        key, value = item.split('=', 1)
        res[key] = value
    return res


def parse_dictionary_items(items: Optional[List[str]]) -> Dict[str, Any]:
    if items is None:
        return {}
    res = {}
    for item in items:
        key, value = item.split('=', 1)
        res[key] = value
    return res


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
