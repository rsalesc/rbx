import pathlib

import typer

from rbx import annotations
from rbx.box.tooling.boca.scrape import scrape_boca
from rbx.box.tooling.boca.ui import run_app

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


@app.command('scrape', help='Scrape runs from BOCA.')
def scrape() -> None:
    scrape_boca(pathlib.Path())


@app.command('view', help='Open Textual UI to visualize BOCA submissions.')
def view(
    contest_id: str = typer.Option(
        None,
        '--contest-id',
        '-c',
        prompt='Contest ID',
        help='Contest identifier to load (stored under app data).',
    ),
) -> None:
    # Normalize empty input to None to let the UI apply default
    cid = (contest_id or '').strip() or None
    run_app(contest_id=cid)
