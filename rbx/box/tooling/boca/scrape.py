import pathlib
from concurrent.futures import ThreadPoolExecutor

from rich.progress import MofNCompleteColumn, Progress, SpinnerColumn

from rbx.box.tooling.boca.scraper import BocaRun, BocaScraper


def scrape_boca(into_path: pathlib.Path):
    scraper = BocaScraper()
    scraper.login()
    runs = scraper.list_runs()

    progress = Progress(
        SpinnerColumn(),
        *Progress.get_default_columns(),
        MofNCompleteColumn(),
        transient=True,
    )
    scrape_task = progress.add_task('Scraping runs...', total=len(runs))
    with progress:

        def work(run: BocaRun):
            scraper.download_run(
                run,
                pathlib.Path(into_path),
                name=f'{run.run_number}-{run.site_number}-{run.outcome.short_name().lower()}',
            )

            progress.update(scrape_task, advance=1)

        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(work, runs)
