import os
import pathlib
from unittest.mock import patch

import pytest
import typer

from rbx.box import naming
from rbx.box.contest import contest_package as cp_module
from rbx.box.contest.contest_state import selected_variant_id_var
from rbx.box.schema import Package
from rbx.box.statements.schema import Statement


def _write_problem(folder: pathlib.Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'problem.rbx.yml').write_text(f'name: {name}\n')


def _write_single_contest(root: pathlib.Path, problems: list[tuple[str, str]]) -> None:
    body = '\n'.join(f'  - short_name: {sn}\n    path: {path}' for sn, path in problems)
    (root / 'contest.rbx.yml').write_text(f'name: ctt\nproblems:\n{body}\n')


def _write_dispatcher(
    root: pathlib.Path, variants: dict[str, list[tuple[str, str]]]
) -> None:
    (root / 'contest.rbx.yml').write_text('use_variants: true\n')
    for vid, problems in variants.items():
        body = '\n'.join(
            f'  - short_name: {sn}\n    path: {path}' for sn, path in problems
        )
        (root / f'contest.{vid}.rbx.yml').write_text(
            f'name: {vid}-c\nproblems:\n{body}\n'
        )


class TestGetProblemEntryInContest:
    @pytest.fixture(autouse=True)
    def _clear_state(self):
        cp_module.find_contest_yaml.cache_clear()
        cp_module.find_contest_package.cache_clear()
        token = selected_variant_id_var.set(None)
        try:
            yield
        finally:
            selected_variant_id_var.reset(token)
            cp_module.find_contest_yaml.cache_clear()
            cp_module.find_contest_package.cache_clear()

    def test_get_entry_in_single_contest_returns_entry(self, tmp_path: pathlib.Path):
        _write_single_contest(tmp_path, [('A', 'A'), ('B', 'B')])
        _write_problem(tmp_path / 'A', 'prob-a')
        _write_problem(tmp_path / 'B', 'prob-b')

        os.chdir(tmp_path / 'A')

        entry = naming.get_problem_entry_in_contest()
        assert entry is not None
        idx, problem = entry
        assert idx == 0
        assert problem.short_name == 'A'

    def test_get_entry_dispatcher_problem_in_one_variant_auto_picks(
        self, tmp_path: pathlib.Path
    ):
        _write_dispatcher(
            tmp_path,
            {
                'div1': [('A', 'A'), ('B', 'B')],
                'div2': [('B', 'B')],
            },
        )
        _write_problem(tmp_path / 'A', 'prob-a')
        _write_problem(tmp_path / 'B', 'prob-b')

        os.chdir(tmp_path / 'A')

        entry = naming.get_problem_entry_in_contest()
        assert entry is not None
        idx, problem = entry
        assert idx == 0
        assert problem.short_name == 'A'

    def test_get_entry_dispatcher_problem_in_two_variants_no_selection_returns_none(
        self, tmp_path: pathlib.Path
    ):
        _write_dispatcher(
            tmp_path,
            {
                'div1': [('A', 'A')],
                'div2': [('A', 'A')],
            },
        )
        _write_problem(tmp_path / 'A', 'prob-a')

        os.chdir(tmp_path / 'A')

        assert naming.get_problem_entry_in_contest() is None

    def test_get_entry_dispatcher_problem_in_two_variants_with_selection_returns_selected(
        self, tmp_path: pathlib.Path
    ):
        _write_dispatcher(
            tmp_path,
            {
                'div1': [('A', 'A')],
                'div2': [('A', 'A')],
            },
        )
        _write_problem(tmp_path / 'A', 'prob-a')

        os.chdir(tmp_path / 'A')

        # Autouse fixture handles the contextvar reset.
        selected_variant_id_var.set('div2')
        entry = naming.get_problem_entry_in_contest()
        assert entry is not None
        idx, problem = entry
        assert idx == 0
        assert problem.short_name == 'A'


class TestRequireProblemInContest:
    @pytest.fixture(autouse=True)
    def _clear_state(self):
        cp_module.find_contest_yaml.cache_clear()
        cp_module.find_contest_package.cache_clear()
        token = selected_variant_id_var.set(None)
        try:
            yield
        finally:
            selected_variant_id_var.reset(token)
            cp_module.find_contest_yaml.cache_clear()
            cp_module.find_contest_package.cache_clear()

    def test_require_problem_in_contest_errors_when_ambiguous(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
    ):
        _write_dispatcher(
            tmp_path,
            {
                'div1': [('A', 'A')],
                'div2': [('A', 'A')],
            },
        )
        _write_problem(tmp_path / 'A', 'prob-a')

        os.chdir(tmp_path / 'A')

        with pytest.raises(typer.Exit):
            naming.require_problem_in_contest()

        out = capsys.readouterr().out
        assert '-C' in out
        assert 'RBX_CONTEST' in out
        assert 'div1' in out
        assert 'div2' in out

    def test_require_problem_in_contest_returns_entry_when_unique(
        self, tmp_path: pathlib.Path
    ):
        _write_dispatcher(
            tmp_path,
            {
                'div1': [('A', 'A'), ('B', 'B')],
                'div2': [('B', 'B')],
            },
        )
        _write_problem(tmp_path / 'A', 'prob-a')
        _write_problem(tmp_path / 'B', 'prob-b')

        os.chdir(tmp_path / 'A')

        idx, problem = naming.require_problem_in_contest()
        assert idx == 0
        assert problem.short_name == 'A'

    def test_require_problem_in_contest_errors_when_selection_does_not_contain_problem(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
    ):
        _write_dispatcher(
            tmp_path,
            {
                'div1': [('B', 'B')],
                'div2': [('A', 'A')],
            },
        )
        _write_problem(tmp_path / 'A', 'prob-a')
        _write_problem(tmp_path / 'B', 'prob-b')

        os.chdir(tmp_path / 'A')

        # Autouse fixture handles the contextvar reset.
        selected_variant_id_var.set('div1')

        with pytest.raises(typer.Exit):
            naming.require_problem_in_contest()

        out = capsys.readouterr().out
        assert 'div1' in out
        assert 'div2' in out


class TestGetTitle:
    def test_returns_pkg_title_for_lang_when_present(self):
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title', 'pt': 'Título'},
        )

        assert naming.get_problem_title('en', pkg=pkg) == 'English Title'

    def test_falls_back_to_pkg_name_when_title_missing_lang(self):
        pkg = Package(name='base-name', timeLimit=1000, memoryLimit=256)

        assert naming.get_problem_title('en', pkg=pkg) == 'base-name'

    def test_statement_title_overrides_pkg_title(self):
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title'},
        )
        statement = Statement(name='statement', language='en', title='Custom Title')

        assert (
            naming.get_problem_title('en', statement=statement, pkg=pkg)
            == 'Custom Title'
        )

    def test_statement_without_title_uses_pkg_title(self):
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title'},
        )
        statement = Statement(name='statement', language='en')

        assert (
            naming.get_problem_title('en', statement=statement, pkg=pkg)
            == 'English Title'
        )

    def test_uses_problem_package_when_pkg_none(self):
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'pt': 'Título'},
        )

        with patch(
            'rbx.box.naming.package.find_problem_package_or_die', return_value=pkg
        ):
            assert naming.get_problem_title('pt') == 'Título'

    # New tests for updated functionality

    def test_lang_none_falls_back_to_pkg_name_by_default(self):
        """When lang=None and fallback_to_title=False, should return pkg.name"""
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title', 'pt': 'Título'},
        )

        assert naming.get_problem_title(lang=None, pkg=pkg) == 'base-name'

    def test_lang_none_with_statement_title_uses_statement_title(self):
        """When lang=None but statement has title, should use statement title"""
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title'},
        )
        statement = Statement(name='statement', language='en', title='Custom Title')

        assert (
            naming.get_problem_title(lang=None, statement=statement, pkg=pkg)
            == 'Custom Title'
        )

    def test_lang_none_with_statement_no_title_falls_back_to_pkg_name(self):
        """When lang=None and statement has no title, should fall back to pkg.name"""
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title'},
        )
        statement = Statement(name='statement', language='en')

        assert (
            naming.get_problem_title(lang=None, statement=statement, pkg=pkg)
            == 'base-name'
        )

    def test_fallback_to_title_true_with_single_title_succeeds(self):
        """When fallback_to_title=True and pkg has exactly one title, should use that title"""
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title'},
        )

        assert (
            naming.get_problem_title(lang=None, pkg=pkg, fallback_to_title=True)
            == 'English Title'
        )

    def test_fallback_to_title_true_with_multiple_titles_raises_error(self):
        """When fallback_to_title=True and pkg has multiple titles, should raise typer.Exit"""
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title', 'pt': 'Título'},
        )

        with pytest.raises(typer.Exit):
            naming.get_problem_title(lang=None, pkg=pkg, fallback_to_title=True)

    def test_fallback_to_title_true_with_no_titles_fallback_to_name(self):
        """When fallback_to_title=True but pkg has no titles, should raise error since len(titles) != 1"""
        pkg = Package(name='base-name', timeLimit=1000, memoryLimit=256)

        assert (
            naming.get_problem_title(lang=None, pkg=pkg, fallback_to_title=True)
            == 'base-name'
        )

    def test_fallback_to_title_true_with_statement_title_uses_statement_title(self):
        """When fallback_to_title=True but statement has title, should prioritize statement title"""
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title', 'pt': 'Título'},
        )
        statement = Statement(name='statement', language='en', title='Custom Title')

        assert (
            naming.get_problem_title(
                lang=None, statement=statement, pkg=pkg, fallback_to_title=True
            )
            == 'Custom Title'
        )

    def test_fallback_to_title_false_with_multiple_titles_falls_back_to_pkg_name(self):
        """When fallback_to_title=False and no specific title found, should use pkg.name regardless of available titles"""
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title', 'pt': 'Título'},
        )

        assert (
            naming.get_problem_title(lang=None, pkg=pkg, fallback_to_title=False)
            == 'base-name'
        )

    def test_lang_specified_but_missing_falls_back_correctly(self):
        """When lang is specified but not in titles, fallback behavior should work correctly"""
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title'},
        )

        # With fallback_to_title=False (default)
        assert (
            naming.get_problem_title(lang='fr', pkg=pkg, fallback_to_title=False)
            == 'base-name'
        )

        # With fallback_to_title=True and single title
        assert (
            naming.get_problem_title(lang='fr', pkg=pkg, fallback_to_title=True)
            == 'English Title'
        )

    def test_lang_specified_but_missing_with_multiple_titles_raises_error(self):
        """When lang is specified but not in titles, and fallback_to_title=True with multiple titles, should raise error"""
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title', 'pt': 'Título'},
        )

        with pytest.raises(typer.Exit):
            naming.get_problem_title(lang='fr', pkg=pkg, fallback_to_title=True)
