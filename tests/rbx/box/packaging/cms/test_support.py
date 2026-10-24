import pytest
import typer

from rbx.box.packaging.cms import support
from rbx.box.schema import Interactor, TaskType


def _interactive(testing_pkg, interactor: str, legacy: bool = False):
    testing_pkg.add_file(interactor).write_text('')
    testing_pkg.yml.type = TaskType.COMMUNICATION
    testing_pkg.yml.interactor = Interactor(path=interactor, legacy=legacy)
    testing_pkg.save()


def test_batch_problems_are_supported(testing_pkg):
    support.ensure_supported(testing_pkg.yml)


def test_cpp_interactors_are_supported(testing_pkg):
    _interactive(testing_pkg, 'interactor.cpp')

    support.ensure_supported(testing_pkg.yml)


def test_legacy_interactors_with_a_cpp_checker_are_supported(testing_pkg):
    testing_pkg.set_checker('checker.cpp')
    _interactive(testing_pkg, 'interactor.cpp', legacy=True)

    support.ensure_supported(testing_pkg.yml)


def test_non_cpp_interactors_are_refused(testing_pkg):
    # The manager compiles the interactor into itself.
    _interactive(testing_pkg, 'interactor.py')

    with pytest.raises(typer.Exit):
        support.ensure_supported(testing_pkg.yml)


def test_legacy_interactors_with_a_non_cpp_checker_are_refused(testing_pkg):
    testing_pkg.set_checker('checker.py')
    _interactive(testing_pkg, 'interactor.cpp', legacy=True)

    with pytest.raises(typer.Exit):
        support.ensure_supported(testing_pkg.yml)
