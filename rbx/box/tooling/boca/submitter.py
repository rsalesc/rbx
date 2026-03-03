# from typing import Iterable, List

# import typer
# from pydantic import BaseModel

# from rbx import console
# from rbx.box import code, package
# from rbx.box.packaging.boca.boca_language_utils import (
#     get_boca_language_from_rbx_language,
# )
# from rbx.box.packaging.boca.boca_outcome_utils import simplify_rbx_expected_outcome
# from rbx.box.schema import ExpectedOutcome, Solution
# from rbx.box.tooling.boca.scraper import BocaDetailedRun, BocaScraper, ContestSnapshot


# def _get_all_eligible_solutions() -> List[Solution]:
#     return package.get_solutions()


# class JudgedSolution(BaseModel):
#     solution: Solution
#     run: BocaDetailedRun
#     expected_outcome: ExpectedOutcome


# def submit_all_solutions(scraper: BocaScraper) -> Iterable[JudgedSolution]:
#     scraper.login()
#     if not scraper.loggedIn:
#         console.console.print('[error]Failed to login to BOCA.[/error]')
#         raise typer.Exit(1)

#     solutions = _get_all_eligible_solutions()
#     for solution in solutions:
#         boca_language = get_boca_language_from_rbx_language(
#             code.find_language_name(solution)
#         )
#         scraper.submit_as_judge(problem_index, language_index, solution.path)

#     scraper.wait_for_all_judged()
#     runs = scraper.retrieve_runs(only_judged=True)
#     runs_snapshot = ContestSnapshot(detailed_runs=runs)
#     for solution in solutions:
#         run = runs_snapshot.get_detailed_run_by_path(solution.path)
#         expected_outcome = simplify_rbx_expected_outcome(solution.outcome)
#         judged_solution = JudgedSolution(
#             solution=solution,
#             run=run,
#             expected_outcome=expected_outcome,
#         )
#         yield judged_solution
