import pathlib

import typer

from rbx import annotations
from rbx.box.tooling.boca.scrape import scrape_boca

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


@app.command('scrape', help='Scrape runs from BOCA.')
def scrape() -> None:
    scrape_boca(pathlib.Path())
