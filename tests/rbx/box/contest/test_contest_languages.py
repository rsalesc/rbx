"""A problem inside a contest inherits the contest's `languages:` list, which
the package loader injects (design 2026-09-20 §1)."""

import pathlib

import pytest

from rbx.box import package
from rbx.box.contest import contest_utils
from rbx.box.statements.wildcards import WildcardExpansionError

_WILDCARD_PROBLEM = """
name: "prob"
timeLimit: 1000
memoryLimit: 256
statements:
  - language: "*"
    file: "statement/statement-{lang}.rbx.tex"
"""


def _write_contest(root: pathlib.Path, languages: str) -> pathlib.Path:
    (root / 'contest.rbx.yml').write_text(
        f'name: "contest"\n{languages}problems:\n  - short_name: "A"\n    path: "A"\n'
    )
    problem = root / 'A'
    problem.mkdir()
    (problem / 'problem.rbx.yml').write_text(_WILDCARD_PROBLEM)
    contest_utils.clear_all_caches()
    return problem


def test_problem_inside_contest_inherits_languages(cleandir: pathlib.Path):
    problem = _write_contest(cleandir, 'languages: ["en", "pt"]\n')

    pkg = package.find_problem_package_or_die(problem)

    assert pkg.languages is None
    assert pkg.effective_languages == ['en', 'pt']
    assert [(s.language, str(s.file)) for s in pkg.expanded_statements] == [
        ('en', 'statement/statement-en.rbx.tex'),
        ('pt', 'statement/statement-pt.rbx.tex'),
    ]


def test_problem_own_list_wins_over_contest(cleandir: pathlib.Path):
    problem = _write_contest(cleandir, 'languages: ["en", "pt"]\n')
    (problem / 'problem.rbx.yml').write_text(_WILDCARD_PROBLEM + 'languages: ["pt"]\n')
    package.clear_package_cache()

    pkg = package.find_problem_package_or_die(problem)

    assert pkg.effective_languages == ['pt']


def test_problem_inside_contest_without_list_errors_on_expansion(
    cleandir: pathlib.Path,
):
    problem = _write_contest(cleandir, '')

    pkg = package.find_problem_package_or_die(problem)

    assert pkg.effective_languages == []
    with pytest.raises(WildcardExpansionError):
        _ = pkg.expanded_statements


def test_standalone_problem_is_unaffected(cleandir: pathlib.Path):
    (cleandir / 'problem.rbx.yml').write_text(_WILDCARD_PROBLEM + 'languages: ["es"]\n')
    contest_utils.clear_all_caches()

    pkg = package.find_problem_package_or_die(cleandir)

    assert [s.language for s in pkg.expanded_statements] == ['es']
