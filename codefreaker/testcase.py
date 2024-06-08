from typing import Optional
from typing_extensions import Annotated
import typer
import pathlib

from . import annotations
from . import hydration
from . import metadata
from .console import console, multiline_prompt
from .schema import Testcase

app = typer.Typer()


@app.command()
def hydrate(problem: annotations.ProblemOption = None):
    """
    Populate all samples of a problem (or of all problems in the folder).
    """
    hydration.main(problem=problem)


@app.command("add, a")
def add(problem: annotations.Problem):
    """
    Add a testcase to a problem.
    """
    dumped_problem = metadata.find_problem_by_anything(problem)
    if dumped_problem is None:
        console.print(f"[error]Problem [item]{problem}[/item] not found.[/error]")
        return

    input = multiline_prompt("Testcase input")
    output = multiline_prompt("Testcase output")

    hydration.add_testcase(
        pathlib.Path(), dumped_problem, Testcase(input=input, output=output)
    )


@app.command("delete, d")
def delete(
    problem: annotations.Problem,
    i: annotations.TestcaseIndex,
):
    """
    Remove the i-th testcase from a problem.
    """
    dumped_problem = metadata.find_problem_by_anything(problem)
    if dumped_problem is None:
        console.print(f"[error]Problem [item]{problem}[/item] not found.[/error]")
        return

    hydration.remove_testcase(pathlib.Path(), dumped_problem, i)
