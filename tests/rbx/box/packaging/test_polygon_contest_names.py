"""The Polygon contest descriptor takes its title from the contest's `titles`.

Statements v2 dropped the per-statement `title`, so reading it off the contest
statement yields `None` and crashes `rbx contest package polygon` while it
builds `contest.xml`.
"""

import os
import pathlib
from unittest import mock

import pytest
import syncer
import typer

from rbx.box import package_utils
from rbx.box.contest import contest_package as cp_module
from rbx.box.packaging import contest_main
from rbx.box.packaging.polygon.packager import (
    PolygonContestPackager,
    PolygonPackager,
)
from rbx.box.packaging.polygon.xml_schema import Name


def _clear_caches():
    cp_module.find_contest_yaml.cache_clear()
    cp_module.find_contest_package.cache_clear()
    package_utils.clear_package_cache()


@pytest.fixture
def v2_contest(tmp_path: pathlib.Path):
    (tmp_path / 'contest.rbx.tex').write_text('')
    (tmp_path / 'contest.rbx.yml').write_text(
        'name: my-contest\n'
        'titles:\n'
        '  en: My Contest\n'
        'problems: []\n'
        'statements:\n'
        '  - name: main-en\n'
        '    language: en\n'
        '    file: contest.rbx.tex\n'
        '    type: rbx-tex\n'
    )
    cwd = os.getcwd()
    os.chdir(tmp_path)
    _clear_caches()
    try:
        yield tmp_path
    finally:
        os.chdir(cwd)
        _clear_caches()


def test_contest_names_come_from_contest_titles(v2_contest):
    packager = PolygonContestPackager()

    assert packager._get_names() == [  # noqa: SLF001
        Name(language='english', value='My Contest', main=True)
    ]
    assert '@contest "My Contest"' in packager._get_dat([])  # noqa: SLF001


@pytest.fixture
def contest_without_statements(tmp_path: pathlib.Path):
    (tmp_path / 'A').mkdir()
    (tmp_path / 'A' / 'problem.rbx.yml').write_text(
        'name: problem-a\ntimeLimit: 1000\nmemoryLimit: 256\n'
    )
    (tmp_path / 'contest.rbx.yml').write_text(
        'name: no-statements\n'
        'titles:\n'
        '  en: No Statements\n'
        'problems:\n'
        '  - short_name: A\n'
    )
    cwd = os.getcwd()
    os.chdir(tmp_path)
    _clear_caches()
    try:
        yield tmp_path
    finally:
        os.chdir(cwd)
        _clear_caches()


def test_a_contest_without_statements_is_refused_with_a_reason(
    contest_without_statements, capsys
):
    with pytest.raises(typer.Exit):
        PolygonContestPackager().check_contest()

    out = ' '.join(capsys.readouterr().out.split())
    assert 'declares no statements' in out
    assert 'contest.rbx.yml' in out


def test_the_refusal_comes_before_any_problem_is_built(contest_without_statements):
    with mock.patch.object(contest_main, 'run_packager') as run_packager:
        with pytest.raises(typer.Exit):
            syncer.sync(
                contest_main.run_contest_packager(
                    PolygonContestPackager,
                    PolygonPackager,
                    verification=0,
                )
            )

    run_packager.assert_not_called()


def test_languages_keep_the_declaration_order(tmp_path: pathlib.Path):
    (tmp_path / 'contest.rbx.tex').write_text('')
    (tmp_path / 'contest.rbx.yml').write_text(
        'name: my-contest\n'
        'problems: []\n'
        'statements:\n'
        + ''.join(
            f'  - name: main-{lang}\n'
            f'    language: {lang}\n'
            '    file: contest.rbx.tex\n'
            '    type: rbx-tex\n'
            for lang in ['pt', 'en', 'es']
        )
    )
    cwd = os.getcwd()
    os.chdir(tmp_path)
    _clear_caches()
    try:
        assert PolygonContestPackager().languages() == ['pt', 'en', 'es']
    finally:
        os.chdir(cwd)
        _clear_caches()
