from unittest.mock import patch

import pytest
import typer

from rbx.box import naming
from rbx.box.schema import Package
from rbx.box.statements.schema import Statement


class TestGetTitle:
    def test_returns_pkg_title_for_lang_when_present(self):
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title', 'pt': 'Título'},
        )

        assert naming.get_title('en', pkg=pkg) == 'English Title'

    def test_falls_back_to_pkg_name_when_title_missing_lang(self):
        pkg = Package(name='base-name', timeLimit=1000, memoryLimit=256)

        assert naming.get_title('en', pkg=pkg) == 'base-name'

    def test_statement_title_overrides_pkg_title(self):
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title'},
        )
        statement = Statement(name='statement', language='en', title='Custom Title')

        assert naming.get_title('en', statement=statement, pkg=pkg) == 'Custom Title'

    def test_statement_without_title_uses_pkg_title(self):
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title'},
        )
        statement = Statement(name='statement', language='en')

        assert naming.get_title('en', statement=statement, pkg=pkg) == 'English Title'

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
            assert naming.get_title('pt') == 'Título'

    # New tests for updated functionality

    def test_lang_none_falls_back_to_pkg_name_by_default(self):
        """When lang=None and fallback_to_title=False, should return pkg.name"""
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title', 'pt': 'Título'},
        )

        assert naming.get_title(lang=None, pkg=pkg) == 'base-name'

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
            naming.get_title(lang=None, statement=statement, pkg=pkg) == 'Custom Title'
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

        assert naming.get_title(lang=None, statement=statement, pkg=pkg) == 'base-name'

    def test_fallback_to_title_true_with_single_title_succeeds(self):
        """When fallback_to_title=True and pkg has exactly one title, should use that title"""
        pkg = Package(
            name='base-name',
            timeLimit=1000,
            memoryLimit=256,
            titles={'en': 'English Title'},
        )

        assert (
            naming.get_title(lang=None, pkg=pkg, fallback_to_title=True)
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
            naming.get_title(lang=None, pkg=pkg, fallback_to_title=True)

    def test_fallback_to_title_true_with_no_titles_fallback_to_name(self):
        """When fallback_to_title=True but pkg has no titles, should raise error since len(titles) != 1"""
        pkg = Package(name='base-name', timeLimit=1000, memoryLimit=256)

        assert (
            naming.get_title(lang=None, pkg=pkg, fallback_to_title=True) == 'base-name'
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
            naming.get_title(
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
            naming.get_title(lang=None, pkg=pkg, fallback_to_title=False) == 'base-name'
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
            naming.get_title(lang='fr', pkg=pkg, fallback_to_title=False) == 'base-name'
        )

        # With fallback_to_title=True and single title
        assert (
            naming.get_title(lang='fr', pkg=pkg, fallback_to_title=True)
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
            naming.get_title(lang='fr', pkg=pkg, fallback_to_title=True)
