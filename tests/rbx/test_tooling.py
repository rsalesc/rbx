import subprocess
from unittest import mock

import pytest
import typer

from rbx import tooling


def _tool(**kwargs) -> tooling.ExternalTool:
    defaults = dict(
        name='poppler',
        executable='pdftoppm',
        probe_flags=['-v'],
        purpose='rasterizing PDF figures',
        install_hints={
            'darwin': 'brew install poppler',
            'linux': 'apt install poppler-utils',
        },
    )
    defaults.update(kwargs)
    return tooling.ExternalTool(**defaults)


def test_is_available_true_when_command_exists():
    with mock.patch('rbx.tooling.command_exists', return_value=True):
        assert _tool().is_available()


def test_is_available_false_when_command_missing():
    with mock.patch('rbx.tooling.command_exists', return_value=False):
        assert not _tool().is_available()


def test_ensure_is_a_noop_when_available():
    with mock.patch('rbx.tooling.command_exists', return_value=True):
        _tool().ensure()


def test_ensure_reports_purpose_and_platform_hint(capsys):
    with (
        mock.patch('rbx.tooling.command_exists', return_value=False),
        mock.patch('rbx.tooling.sys.platform', 'darwin'),
        pytest.raises(typer.Exit),
    ):
        _tool().ensure()
    out = capsys.readouterr().out
    assert 'pdftoppm' in out
    assert 'rasterizing PDF figures' in out
    assert 'brew install poppler' in out


def test_ensure_still_names_the_tool_without_a_hint_for_the_platform(capsys):
    with (
        mock.patch('rbx.tooling.command_exists', return_value=False),
        mock.patch('rbx.tooling.sys.platform', 'sunos'),
        pytest.raises(typer.Exit),
    ):
        _tool().ensure()
    out = capsys.readouterr().out
    assert 'pdftoppm' in out


def test_run_ensures_before_invoking():
    """A missing tool must fail with the actionable error, never a raw
    FileNotFoundError from subprocess."""
    with (
        mock.patch('rbx.tooling.command_exists', return_value=False),
        pytest.raises(typer.Exit),
    ):
        _tool().run(['-png', 'a.pdf'])


def test_run_passes_args_after_the_executable():
    with (
        mock.patch('rbx.tooling.command_exists', return_value=True),
        mock.patch('rbx.tooling.subprocess.run') as run,
    ):
        run.return_value = subprocess.CompletedProcess([], 0)
        _tool().run(['-png', 'a.pdf'])
    assert run.call_args.args[0] == ['pdftoppm', '-png', 'a.pdf']


def test_registry_entries_exist():
    for tool in (
        tooling.PDFLATEX,
        tooling.TEXLIVEONFLY,
        tooling.PANDOC,
        tooling.PDFTOPPM,
    ):
        assert tool.executable
        assert tool.purpose
        assert tool.install_hints
