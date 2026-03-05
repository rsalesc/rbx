import os
from typing import Dict, Iterable, List

import typer
from pydantic import BaseModel

from rbx import console
from rbx.box import code, naming, package
from rbx.box.packaging.boca.boca_language_utils import (
    get_boca_language_from_rbx_language,
)
from rbx.box.packaging.boca.boca_outcome_utils import simplify_rbx_expected_outcome
from rbx.box.schema import ExpectedOutcome, Solution
from rbx.box.tooling.boca.scraper import BocaDetailedRun, BocaScraper, ContestSnapshot


def _get_all_eligible_solutions() -> List[Solution]:
    return package.get_solutions()


def _get_env_languages() -> Dict[str, int]:
    # BOCA_LANGUAGES=1:c,2:cpp,3:java,4:py3,5:kt
    languages = os.environ['BOCA_LANGUAGES']
    return {
        language.split(':')[1]: int(language.split(':')[0])
        for language in languages.split(',')
    }


class JudgedSolution(BaseModel):
    solution: Solution
    run: BocaDetailedRun
    expected_outcome: ExpectedOutcome


def submit_all_solutions(scraper: BocaScraper) -> Iterable[JudgedSolution]:
    print(f'BOCA_BASE_URL: {os.environ["BOCA_BASE_URL"]}')
    print(f'BOCA_JUDGE_USERNAME: {os.environ["BOCA_JUDGE_USERNAME"]}')
    scraper.login()
    if not scraper.loggedIn:
        console.console.print('[error]Failed to login to BOCA.[/error]')
        raise typer.Exit(1)

    problem_indices = scraper.list_problems_as_judge()
    problem_index = problem_indices.get(naming.get_problem_shortname() or '')
    if problem_index is None:
        console.console.print(
            f'[error]Problem [item]{naming.get_problem_shortname()}[/item] not found in BOCA.[/error]'
        )
        raise typer.Exit(1)

    solutions = _get_all_eligible_solutions()
    env_languages = _get_env_languages()
    for solution in solutions:
        boca_language = get_boca_language_from_rbx_language(
            code.find_language_name(solution)
        )
        language_index = env_languages.get(boca_language)
        if language_index is None:
            console.console.print(
                f'[error]Solution {solution.href()} has language [item]{boca_language}[/item] not found in BOCA.[/error]'
            )
            continue
        scraper.submit_as_judge(problem_index, language_index, solution.path)

    scraper.wait_for_all_judged()
    runs = scraper.retrieve_runs(only_judged=True)
    runs_snapshot = ContestSnapshot(detailed_runs=runs)
    for solution in solutions:
        try:
            run = runs_snapshot.get_detailed_run_by_path(solution.path)
        except ValueError:
            console.console.print(
                f'[error]Solution {solution.href()} not found in BOCA snapshot, skipping it.[/error]'
            )
            continue
        expected_outcome = simplify_rbx_expected_outcome(solution.outcome)
        judged_solution = JudgedSolution(
            solution=solution,
            run=run,
            expected_outcome=expected_outcome,
        )
        yield judged_solution


def judge_all(judged_solutions: Iterable[JudgedSolution]) -> None:
    for judged_solution in judged_solutions:
        if judged_solution.run.outcome is None:
            console.console.print(
                f'[error]Solution {judged_solution.solution.href()} has no outcome, skipping it.[/error]'
            )
            continue
        if not judged_solution.expected_outcome.match(judged_solution.run.outcome):
            console.console.print(
                f'[error]Solution {judged_solution.solution.href()} expected outcome [item]{judged_solution.expected_outcome}[/item] but got [item]{judged_solution.run.outcome}[/item].[/error]'
            )
        else:
            console.console.print(
                f'[success]Solution {judged_solution.solution.href()} got [item]{judged_solution.run.outcome}[/item].[/success]'
            )
