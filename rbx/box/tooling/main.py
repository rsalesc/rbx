import typer

from rbx import annotations
from rbx.box.tooling.boca import main as boca_main

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)

app.add_typer(boca_main.app, name='boca')
