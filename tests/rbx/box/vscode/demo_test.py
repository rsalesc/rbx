"""The demo contest under vscode/demo/ is a manual fixture: nothing builds or
judges it in CI. This only checks that its manifests still parse, so a schema
change that breaks the demo fails here instead of in an editor later.
"""

import pathlib

from rbx.box import package
from rbx.box.contest import contest_package

DEMO_DIR = pathlib.Path(__file__).parents[4] / 'vscode' / 'demo'


def test_demo_contest_parses():
    contest = contest_package.find_contest_package(DEMO_DIR)

    assert contest is not None
    assert [p.short_name for p in contest.problems] == ['A', 'B']


def test_demo_problems_parse():
    contest = contest_package.find_contest_package(DEMO_DIR)
    assert contest is not None

    for problem in contest.problems:
        pkg = package.find_problem_package(DEMO_DIR / problem.path)
        assert pkg is not None, problem.path
        assert pkg.name == str(problem.path)
