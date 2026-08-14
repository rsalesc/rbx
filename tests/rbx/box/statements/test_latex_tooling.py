"""The statement pipeline's external binaries go through the tool registry, so a
missing one names itself and says how to install it."""

from unittest import mock

import pytest
import typer

from rbx.box.statements import latex

# `tests/rbx/box/conftest.py` installs a session-scoped autouse `mock_pdflatex`
# that replaces `Latex.build_pdf` wholesale, so the real method is unreachable
# from a test body. Test modules are imported during collection, before any
# fixture runs, so this binds the genuine implementation.
_REAL_BUILD_PDF = latex.Latex.build_pdf


def test_build_pdf_reports_missing_pdflatex_via_the_registry(tmp_path, capsys):
    with (
        mock.patch.object(latex.Latex, 'build_pdf', _REAL_BUILD_PDF),
        mock.patch('rbx.tooling.command_exists', return_value=False),
        pytest.raises(typer.Exit),
    ):
        latex.Latex(
            '\\documentclass{article}\\begin{document}x\\end{document}'
        ).build_pdf(tmp_path)
    assert 'pdflatex' in capsys.readouterr().out


def test_install_tex_packages_stays_silent_without_texliveonfly(tmp_path, capsys):
    """texliveonfly is genuinely optional -- a best-effort package install -- so
    its absence must remain a silent no-op rather than an error."""
    with mock.patch('rbx.tooling.command_exists', return_value=False):
        latex.install_tex_packages(tmp_path / 'statement.tex', tmp_path)
    assert capsys.readouterr().out == ''
