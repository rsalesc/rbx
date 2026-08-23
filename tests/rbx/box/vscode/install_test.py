import pathlib
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box.vscode import extension
from rbx.box.vscode import main as vscode_main

runner = CliRunner()


@pytest.fixture
def bundled(tmp_path: pathlib.Path, monkeypatch) -> pathlib.Path:
    directory = tmp_path / 'resources'
    directory.mkdir()
    vsix = directory / 'rbx-vscode-0.2.0.vsix'
    vsix.touch()
    monkeypatch.setattr(extension, 'vsix_dir', lambda: directory)
    return vsix


@pytest.fixture
def in_editor(monkeypatch):
    monkeypatch.setenv('TERM_PROGRAM', 'vscode')
    monkeypatch.delenv('VSCODE_GIT_ASKPASS_NODE', raising=False)
    monkeypatch.delenv('VSCODE_GIT_ASKPASS_MAIN', raising=False)


def _ran(returncode: int = 0, stdout: str = '', stderr: str = ''):
    patched = mock.patch('subprocess.run')
    started = patched.start()
    started.return_value = mock.Mock(
        returncode=returncode, stdout=stdout, stderr=stderr
    )
    return patched, started


def test_install_runs_the_editor_cli_with_the_bundled_vsix(bundled, in_editor):
    with mock.patch('shutil.which', return_value='/usr/bin/code'):
        patched, run = _ran()
        try:
            result = runner.invoke(vscode_main.app, ['install'])
        finally:
            patched.stop()

    assert result.exit_code == 0, result.output
    assert run.call_args.args[0] == [
        'code',
        '--install-extension',
        str(bundled),
        '--force',
    ]
    assert 'Reload the window' in result.output


def test_install_honors_an_explicit_editor(bundled, monkeypatch):
    # No TERM_PROGRAM at all: --editor is what makes this work from a plain
    # terminal.
    monkeypatch.delenv('TERM_PROGRAM', raising=False)

    with mock.patch('shutil.which', return_value='/usr/bin/cursor'):
        patched, run = _ran()
        try:
            result = runner.invoke(vscode_main.app, ['install', '--editor', 'cursor'])
        finally:
            patched.stop()

    assert result.exit_code == 0, result.output
    assert run.call_args.args[0][0] == 'cursor'


def test_install_rejects_an_unknown_editor(bundled, in_editor):
    result = runner.invoke(vscode_main.app, ['install', '--editor', 'notepad'])

    assert result.exit_code == 1
    assert 'notepad' in result.output


def test_install_fails_clearly_without_a_bundled_vsix(
    tmp_path: pathlib.Path, monkeypatch, in_editor
):
    monkeypatch.setattr(extension, 'vsix_dir', lambda: tmp_path / 'empty')

    result = runner.invoke(vscode_main.app, ['install'])

    assert result.exit_code == 1
    assert 'mise run vscode:vsix' in result.output


def test_install_fails_clearly_outside_an_editor(bundled, monkeypatch):
    monkeypatch.delenv('TERM_PROGRAM', raising=False)

    result = runner.invoke(vscode_main.app, ['install'])

    assert result.exit_code == 1
    assert '--editor' in result.output


def test_install_explains_a_missing_editor_command(bundled, in_editor):
    with mock.patch('shutil.which', return_value=None):
        result = runner.invoke(vscode_main.app, ['install'])

    assert result.exit_code == 1
    # The manual command has to be spelled out -- this is the one failure the
    # user can still work around by hand.
    assert '--install-extension' in result.output


def test_install_surfaces_the_editor_cli_failure(bundled, in_editor):
    with mock.patch('shutil.which', return_value='/usr/bin/code'):
        patched, _ = _ran(returncode=1, stderr='boom')
        try:
            result = runner.invoke(vscode_main.app, ['install'])
        finally:
            patched.stop()

    assert result.exit_code == 1
    assert 'boom' in result.output
