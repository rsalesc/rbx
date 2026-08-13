from typer.testing import CliRunner

from rbx.box.packaging.main import app


def test_moj_command_is_registered():
    result = CliRunner().invoke(app, ['--help'])
    assert result.exit_code == 0
    assert 'moj' in result.output


def test_moj_next_command_is_gone():
    # `moj-next` replaced the legacy packager outright rather than living beside it.
    result = CliRunner().invoke(app, ['--help'])
    assert 'moj-next' not in result.output


def test_moj_command_has_no_legacy_boca_flag():
    # `--for-boca` belonged to the legacy BocaPackager subclass, which is gone.
    result = CliRunner().invoke(app, ['moj', '--help'])
    assert result.exit_code == 0
    assert '--for-boca' not in result.output
