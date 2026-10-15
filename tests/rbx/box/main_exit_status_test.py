from unittest import mock

import pytest
import typer

from rbx.box import main


@pytest.mark.parametrize(
    'exc, status',
    [
        (SystemExit(0), 'ok'),
        (SystemExit(None), 'ok'),
        # What click turns a Ctrl-C inside a command into.
        (SystemExit(130), 'interrupted'),
        (SystemExit(1), 'error'),
        (KeyboardInterrupt(), 'interrupted'),
        (typer.Abort(), 'interrupted'),
        (typer.Exit(0), 'ok'),
        (typer.Exit(1), 'error'),
        (RuntimeError('boom'), 'error'),
    ],
)
def testexit_status_of(exc, status):
    assert main.exit_status_of(exc) == status


def test_finish_run_stamps_an_open_stress_session():
    from rbx.box import stress_manifest

    with mock.patch.object(stress_manifest, 'finish_open_session') as finish:
        main._finish_run('interrupted')  # noqa: SLF001

    finish.assert_called_once_with('interrupted')
