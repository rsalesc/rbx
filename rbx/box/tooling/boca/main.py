import pathlib

import typer

from rbx import annotations

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)

# Every import of the scraper below is deferred into the command that needs it.
# This module is reached from `rbx.box.cli` just to register the sub-app, and the
# scraper pulls in `bs4`, `lxml`, `mechanize` and `dateparser` -- a web-scraping
# stack no other command has any use for.


@app.command('scrape', help='Scrape runs from BOCA.')
def scrape() -> None:
    from rbx.box.tooling.boca.scrape import scrape_boca

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
    from rbx.box.tooling.boca.ui import run_app

    # Normalize empty input to None to let the UI apply default
    cid = (contest_id or '').strip() or None
    run_app(contest_id=cid)


@app.command('submit', help='Submit solutions to BOCA.')
def submit() -> None:
    from rbx.box.tooling.boca.scraper import get_boca_scraper
    from rbx.box.tooling.boca.submitter import judge_all, submit_all_solutions

    judged_solutions = list(submit_all_solutions(get_boca_scraper(is_judge=True)))
    judge_all(judged_solutions)
