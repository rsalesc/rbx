"""`rbx statements ls` / `rbx contest statements ls`: the resolved statement
entries of a package, and every YAML file they were read from."""

import json
import os
import pathlib

import pytest
from typer.testing import CliRunner

from rbx.box import package
from rbx.box.contest import contest_utils
from rbx.box.contest import statements as contest_statements
from rbx.box.statements import build_statements, listing

_PROBLEM = """
name: "prob"
timeLimit: 1000
memoryLimit: 256
statements:
  - language: "*"
    file: "documents/statement-{lang}.rbx.tex"
  - language: "pt"
    file: "documents/especial.rbx.tex"
tutorials:
  - language: "*"
    file: "documents/editorial-{lang}.rbx.tex"
"""

_CONTEST = """
<<: !include_deep shared.rbx.yml
name: "contest"
problems:
  - short_name: "A"
    path: "A"
statements:
  - name: "contest-{lang}"
    language: "*"
    file: "statement/contest-{lang}.rbx.tex"
"""


@pytest.fixture
def contest(cleandir: pathlib.Path) -> pathlib.Path:
    """A contest whose `languages:` lives in an included fragment, holding one
    problem that inherits it."""
    (cleandir / 'shared.rbx.yml').write_text('languages: ["en", "pt"]\n')
    (cleandir / 'contest.rbx.yml').write_text(_CONTEST)
    problem = cleandir / 'A'
    problem.mkdir()
    (problem / 'problem.rbx.yml').write_text(_PROBLEM)
    contest_utils.clear_all_caches()
    package.clear_package_cache()
    return cleandir


def _entries(resolved: listing.StatementListing, root: pathlib.Path):
    return [
        (
            st.kind,
            st.language,
            str(pathlib.Path(st.file).relative_to(root)) if st.file else None,
        )
        for st in resolved.statements
    ]


def test_problem_listing_expands_wildcards_with_the_inherited_languages(
    contest: pathlib.Path,
):
    resolved = listing.problem_listing(contest / 'A')

    assert resolved.scope == 'problem'
    assert resolved.root == str(contest / 'A')
    # The concrete `pt` entry beats the wildcard's `pt` expansion.
    assert sorted(_entries(resolved, contest / 'A')) == [
        ('statement', 'en', 'documents/statement-en.rbx.tex'),
        ('statement', 'pt', 'documents/especial.rbx.tex'),
        ('tutorial', 'en', 'documents/editorial-en.rbx.tex'),
        ('tutorial', 'pt', 'documents/editorial-pt.rbx.tex'),
    ]


def test_problem_listing_sources_name_the_contest_and_its_fragments(
    contest: pathlib.Path,
):
    (contest / 'contest.div1.rbx.yml').write_text(
        'name: "div1"\nproblems:\n  - short_name: "A"\n    path: "A"\n'
    )

    resolved = listing.problem_listing(contest / 'A')

    assert resolved.sources == sorted(
        str(contest / name)
        for name in (
            'A/problem.rbx.yml',
            'contest.rbx.yml',
            'contest.div1.rbx.yml',
            'shared.rbx.yml',
        )
    )


def test_standalone_problem_listing_sources_are_its_own_manifest(
    cleandir: pathlib.Path,
):
    (cleandir / 'problem.rbx.yml').write_text(_PROBLEM + 'languages: ["es"]\n')
    package.clear_package_cache()

    resolved = listing.problem_listing(cleandir)

    assert resolved.sources == [str(cleandir / 'problem.rbx.yml')]
    assert sorted(st.language for st in resolved.statements) == ['es', 'es', 'pt']


def test_contest_listing_covers_every_variant(contest: pathlib.Path):
    (contest / 'contest.div1.rbx.yml').write_text(
        'name: "div1"\nlanguages: ["es"]\n'
        'problems:\n  - short_name: "A"\n    path: "A"\n'
        'documents:\n  - name: "info"\n    type: "jinja-tex"\n'
        '    file: "statement/info.rbx.tex"\n'
    )

    resolved = listing.contest_listing(contest)

    assert resolved.scope == 'contest'
    assert [(st.kind, st.name, st.contest, st.file) for st in resolved.statements] == [
        (
            'statement',
            'contest-en',
            None,
            str(contest / 'statement/contest-en.rbx.tex'),
        ),
        (
            'statement',
            'contest-pt',
            None,
            str(contest / 'statement/contest-pt.rbx.tex'),
        ),
        ('document', 'info', 'div1', str(contest / 'statement/info.rbx.tex')),
    ]
    assert resolved.sources == sorted(
        str(contest / name)
        for name in ('contest.rbx.yml', 'contest.div1.rbx.yml', 'shared.rbx.yml')
    )


def test_contest_listing_of_a_dispatcher_names_the_dispatcher_too(
    cleandir: pathlib.Path,
):
    (cleandir / 'contest.rbx.yml').write_text('use_variants: true\n')
    (cleandir / 'contest.div1.rbx.yml').write_text(
        'name: "div1"\nstatements:\n  - name: "main"\n'
        '    file: "statement/contest.rbx.tex"\n'
    )
    contest_utils.clear_all_caches()

    resolved = listing.contest_listing(cleandir)

    assert [(st.name, st.contest) for st in resolved.statements] == [('main', 'div1')]
    assert resolved.sources == sorted(
        str(cleandir / name) for name in ('contest.rbx.yml', 'contest.div1.rbx.yml')
    )


def test_statements_ls_json(contest: pathlib.Path):
    os.chdir(contest / 'A')

    result = CliRunner().invoke(build_statements.app, ['ls', '--json'])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload['version'] == listing.LISTING_VERSION
    assert payload == listing.problem_listing(contest / 'A').model_dump(mode='json')


def test_contest_statements_ls_json(contest: pathlib.Path):
    os.chdir(contest / 'A')

    result = CliRunner().invoke(contest_statements.app, ['ls', '--json'])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == listing.contest_listing(contest).model_dump(
        mode='json'
    )


def test_contest_statements_ls_outside_a_contest_fails(cleandir: pathlib.Path):
    result = CliRunner().invoke(contest_statements.app, ['ls'])

    assert result.exit_code == 1
