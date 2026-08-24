import re

from typer.testing import CliRunner

from rbx.box.packaging.main import app

_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def _plain(output: str) -> str:
    """Rich styles an option name in pieces (`-` then `-language`), so the flag
    is only a literal substring once the escape codes are gone."""
    return _ANSI.sub('', output)


def test_moj_command_is_registered():
    result = CliRunner().invoke(app, ['--help'])
    assert result.exit_code == 0
    assert 'moj' in result.output


def test_moj_next_command_is_gone():
    # `moj-next` replaced the legacy packager outright rather than living beside it.
    result = CliRunner().invoke(app, ['--help'])
    assert 'moj-next' not in result.output


def test_moj_command_takes_a_language():
    # The body and the <h1> must never come from different languages, so the
    # statement is selected once, by this flag, exactly as `package polygon` does.
    result = CliRunner().invoke(app, ['moj', '--help'])
    assert result.exit_code == 0
    assert '--language' in _plain(result.output)


def test_moj_command_takes_an_upload_flag():
    # Same spelling as `package boca` and `package polygon`, so `-u` means the
    # same thing on every backend.
    result = CliRunner().invoke(app, ['moj', '--help'])
    assert result.exit_code == 0
    assert '--upload' in _plain(result.output)


def test_moj_command_has_no_legacy_boca_flag():
    # `--for-boca` belonged to the legacy BocaPackager subclass, which is gone.
    result = CliRunner().invoke(app, ['moj', '--help'])
    assert result.exit_code == 0
    assert '--for-boca' not in result.output


def test_moj_command_takes_a_main_solution_only_flag():
    # Calibration runs every solution the package ships, so dropping all but the
    # model one is the knob that makes an upload cheap to iterate on.
    result = CliRunner().invoke(app, ['moj', '--help'])
    assert result.exit_code == 0
    assert '--main-solution-only' in _plain(result.output)
