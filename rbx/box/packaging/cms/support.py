"""What CMS cannot judge, refused before anything is built."""

import typer

from rbx import console
from rbx.box import code, environment, package
from rbx.box.packaging.cms import communication
from rbx.box.schema import CodeItem, Package
from rbx.grading.language_kind import LanguageKind


def _is_cpp(item: CodeItem) -> bool:
    return LanguageKind.CPP in environment.language_kinds(code.find_language(item))


def _refuse(pkg: Package, reason: str):
    console.console.print(
        f'[error]Problem [item]{pkg.name}[/item] cannot be packaged for CMS: '
        f'{reason}[/error]'
    )
    raise typer.Exit(1)


def ensure_supported(pkg: Package):
    """Refuse a problem CMS could not judge the way rbx does.

    `cms_conf.py` compiles the checker with `g++`, so it must be C++ whenever it
    judges: on a batch problem, and behind a legacy interactor. An interactive
    problem runs through rbx's CMS manager, which compiles the interactor into
    itself, so that must be C++ too.
    """
    if communication.is_communication(pkg):
        if pkg.interactor is None or not _is_cpp(pkg.interactor):
            _refuse(pkg, 'its interactor must be written in C++.')
        if not communication.needs_checker(pkg):
            return
    if not _is_cpp(package.get_checker_or_builtin()):
        _refuse(pkg, 'its checker must be written in C++.')
