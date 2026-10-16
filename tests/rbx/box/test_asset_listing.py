"""`rbx assets` / `rbx contest assets`: what a problem or a contest is made of,
by category, with globs expanded -- the listing the VS Code Assets view draws."""

import json
import os
import pathlib

import pytest
from typer.testing import CliRunner

from rbx.box import asset_listing, package
from rbx.box.cli.commands import assets as assets_commands
from rbx.box.contest import contest_utils
from rbx.box.contest import main as contest_main

_PROBLEM = """
name: "cats"
titles:
  en: "Cats"
timeLimit: 1000
memoryLimit: 256
checker: {path: "judge/checker.cpp"}
validator: {path: "validators/main.cpp"}
extraValidators:
  - path: "validators/common-*.*"
generators:
  - name: "gen"
    path: "gens/gen.cpp"
testcases:
  - name: "samples"
    testcaseGlob: "documents/*.in"
  - name: "manual"
    testcases:
      - inputPath: "attic/hand.in"
  - name: "plan"
    generatorScript:
      path: "attic/testplan.txt"
solutions:
  - path: "solutions/good/*reference*.*"
    outcome: ACCEPTED
  - path: "solutions/good/*.*"
    outcome: ACCEPTED
  - path: "solutions/wrong/*.*"
    outcome: WRONG_ANSWER
  - path: "solutions/missing.cpp"
    outcome: ACCEPTED
statements:
  - language: "*"
    file: "documents/statement-{lang}.rbx.tex"
tutorials:
  - language: "*"
    file: "documents/editorial-{lang}.rbx.tex"
"""

_FILES = [
    'judge/checker.cpp',
    'validators/main.cpp',
    'validators/common-lines.py',
    'gens/gen.cpp',
    'documents/1.in',
    'documents/2.in',
    'attic/hand.in',
    'attic/testplan.txt',
    'solutions/good/reference.cpp',
    'solutions/good/alt.py',
    'solutions/wrong/greedy.cpp',
    'documents/statement-en.rbx.tex',
    'documents/statement-pt.rbx.tex',
    'documents/editorial-en.rbx.tex',
]

_CONTEST = """
name: "contest"
languages: ["en", "pt"]
titles:
  en: "The Finals"
problems:
  - short_name: "A"
    path: "cats"
  - short_name: "B"
    path: "broken"
statements:
  - name: "contest-{lang}"
    language: "*"
    file: "statement/contest.rbx.tex"
"""


def _write_problem(root: pathlib.Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'problem.rbx.yml').write_text(_PROBLEM)
    for name in _FILES:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text('')


@pytest.fixture
def contest(cleandir: pathlib.Path) -> pathlib.Path:
    """Problem A is complete; problem B's manifest does not load."""
    (cleandir / 'contest.rbx.yml').write_text(_CONTEST)
    (cleandir / 'statement').mkdir()
    (cleandir / 'statement/contest.rbx.tex').write_text('')
    _write_problem(cleandir / 'cats')
    (cleandir / 'broken').mkdir()
    (cleandir / 'broken/problem.rbx.yml').write_text('name: "broken"\nnope: 1\n')
    contest_utils.clear_all_caches()
    package.clear_package_cache()
    return cleandir


def _rows(problem: asset_listing.ListedProblem):
    root = pathlib.Path(problem.root)
    return [
        (asset.category, str(pathlib.Path(asset.path).relative_to(root)), asset.detail)
        for asset in problem.assets
    ]


def test_problem_listing_expands_globs_and_marks_the_main_assets(
    contest: pathlib.Path,
):
    listing = asset_listing.problem_asset_listing(contest / 'cats')

    assert listing.scope == 'problem'
    assert listing.contest is None
    [problem] = listing.problems
    assert (problem.short_name, problem.name, problem.title, problem.error) == (
        None,
        'cats',
        'Cats',
        None,
    )
    assert _rows(problem) == [
        ('manifest', 'problem.rbx.yml', {}),
        (
            'statement',
            'documents/statement-en.rbx.tex',
            {
                'kind': 'statement',
                'language': 'en',
                'variant': 'default',
                'type': 'rbxTeX',
            },
        ),
        (
            'statement',
            'documents/statement-pt.rbx.tex',
            {
                'kind': 'statement',
                'language': 'pt',
                'variant': 'default',
                'type': 'rbxTeX',
            },
        ),
        # The pt editorial is declared but absent from disk, so it is not listed.
        (
            'statement',
            'documents/editorial-en.rbx.tex',
            {
                'kind': 'tutorial',
                'language': 'en',
                'variant': 'default',
                'type': 'rbxTeX',
            },
        ),
        # A file globbed by two entries belongs to the first; a declared file
        # missing from disk is not listed.
        (
            'solution',
            'solutions/good/reference.cpp',
            {'outcome': 'ACCEPTED', 'main': True},
        ),
        ('solution', 'solutions/good/alt.py', {'outcome': 'ACCEPTED'}),
        ('solution', 'solutions/wrong/greedy.cpp', {'outcome': 'WRONG_ANSWER'}),
        ('generator', 'gens/gen.cpp', {}),
        ('checker', 'judge/checker.cpp', {}),
        ('validator', 'validators/main.cpp', {'main': True}),
        ('validator', 'validators/common-lines.py', {}),
        (
            'manual_test',
            'documents/1.in',
            {'group': 'samples', 'glob': 'documents/*.in'},
        ),
        (
            'manual_test',
            'documents/2.in',
            {'group': 'samples', 'glob': 'documents/*.in'},
        ),
        ('manual_test', 'attic/hand.in', {'group': 'manual'}),
        ('testplan', 'attic/testplan.txt', {'group': 'plan', 'main': True}),
    ]


def test_problem_listing_sources_name_the_contest_files(contest: pathlib.Path):
    listing = asset_listing.problem_asset_listing(contest / 'cats')

    assert listing.sources == sorted(
        str(contest / name) for name in ('cats/problem.rbx.yml', 'contest.rbx.yml')
    )


def test_contest_listing_keeps_going_past_a_broken_problem(contest: pathlib.Path):
    listing = asset_listing.contest_asset_listing(contest)

    assert listing.scope == 'contest'
    assert listing.contest is not None
    assert (listing.contest.variant, listing.contest.title) == (None, 'The Finals')
    # One file serving both languages is one row.
    assert [(asset.category, asset.path) for asset in listing.contest.assets] == [
        ('manifest', str(contest / 'contest.rbx.yml')),
        ('statement', str(contest / 'statement/contest.rbx.tex')),
    ]
    a, b = listing.problems
    assert (a.short_name, a.name, a.error) == ('A', 'cats', None)
    assert len(a.assets) == 15
    assert (b.short_name, b.root, b.assets) == ('B', str(contest / 'broken'), [])
    assert b.error
    # The broken problem's manifest is still a source: fixing it must reload.
    assert str(contest / 'broken/problem.rbx.yml') in listing.sources


def test_contest_listing_of_a_dispatcher_without_a_selection_is_empty(
    cleandir: pathlib.Path,
):
    (cleandir / 'contest.rbx.yml').write_text('use_variants: true\n')
    (cleandir / 'contest.div1.rbx.yml').write_text(
        'name: "div1"\nproblems:\n  - short_name: "A"\n    path: "cats"\n'
    )
    _write_problem(cleandir / 'cats')
    contest_utils.clear_all_caches()

    listing = asset_listing.contest_asset_listing(cleandir)

    assert (listing.contest, listing.problems) == (None, [])


def test_assets_json(contest: pathlib.Path):
    os.chdir(contest / 'cats')

    result = CliRunner().invoke(assets_commands.app, ['assets', '--json'])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload['version'] == asset_listing.ASSET_LISTING_VERSION
    assert payload == asset_listing.problem_asset_listing(contest / 'cats').model_dump(
        mode='json'
    )


def test_contest_assets_json_honours_the_selected_variant(contest: pathlib.Path):
    (contest / 'contest.div1.rbx.yml').write_text(
        'name: "div1"\nproblems:\n  - short_name: "Z"\n    path: "cats"\n'
    )
    contest_utils.clear_all_caches()
    os.chdir(contest)

    result = CliRunner().invoke(contest_main.app, ['-C', 'div1', 'assets', '--json'])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload['contest']['variant'] == 'div1'
    assert [p['short_name'] for p in payload['problems']] == ['Z']


def test_contest_assets_json_keeps_stdout_clean(contest: pathlib.Path):
    """The broken problem is reported, but never onto stdout."""
    os.chdir(contest)

    result = CliRunner().invoke(contest_main.app, ['assets', '--json'])

    assert result.exit_code == 0, result.output
    json.loads(result.stdout)


def test_contest_assets_outside_a_contest_fails(cleandir: pathlib.Path):
    result = CliRunner().invoke(contest_main.app, ['assets'])

    assert result.exit_code == 1
