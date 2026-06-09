import enum

import pytest
import typer
import typer.main
from typing_extensions import Annotated

from rbx.box.completion import registry
from rbx.box.completion.generate import (
    UnregisteredCompleterError,
    build_spec,
)


# Registered at module load so key_for_function resolves it when the generator
# walks the autocompletion callable.
@registry.register_completer('gen_lang')
def _gen_lang(ctx, incomplete):
    return []


def _cli(app: typer.Typer):
    return typer.main.get_command(app)


def _child(node, name):
    return next(c for c in node['children'] if c['name'] == name)


def test_synthetic_command_with_registered_completer():
    app = typer.Typer()

    @app.command()
    def hello(
        name: str,
        lang: Annotated[str, typer.Option('--lang', autocompletion=_gen_lang)] = '',
    ):
        pass

    spec = build_spec(_cli(app), name='hello')

    # A single-command Typer app collapses to a single command (not a group).
    assert spec['is_group'] is False

    by_kind = {(p['kind'], tuple(p['names'])): p for p in spec['params']}
    # Positional argument: no option names.
    arg = by_kind[('argument', ())]
    assert arg['value'] == {'kind': 'none'}

    opt = by_kind[('option', ('--lang',))]
    assert opt['takes_value'] is True
    assert opt['value'] == {'kind': 'completer', 'completer': 'gen_lang'}


def test_unregistered_completer_raises():
    def _orphan(ctx, incomplete):
        return []

    app = typer.Typer()

    @app.command()
    def hello(
        lang: Annotated[str, typer.Option('--lang', autocompletion=_orphan)] = '',
    ):
        pass

    with pytest.raises(UnregisteredCompleterError):
        build_spec(_cli(app), name='hello')


def test_choice_option_emits_choices():
    class Color(str, enum.Enum):
        red = 'red'
        green = 'green'

    app = typer.Typer()

    @app.command()
    def paint(
        color: Annotated[Color, typer.Option('--color')] = Color.red,
    ):
        pass

    spec = build_spec(_cli(app), name='paint')
    opt = next(p for p in spec['params'] if p['names'] == ['--color'])
    assert opt['value']['kind'] == 'choice'
    assert set(opt['value']['choices']) == {'red', 'green'}


def test_real_app_captures_raw_alias_names_and_recurses():
    from rbx.box.cli import app

    spec = build_spec(typer.main.get_command(app), name='rbx')

    assert spec['is_group'] is True
    # Raw comma-joined registered name is captured verbatim.
    pkg = _child(spec, 'package, pkg')
    assert pkg['is_group'] is True
    # Recursion descends into the group's children.
    assert any(c['name'] == 'polygon' for c in pkg['children'])
