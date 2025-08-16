from unittest.mock import patch

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
