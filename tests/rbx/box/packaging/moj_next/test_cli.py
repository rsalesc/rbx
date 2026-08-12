from typer.testing import CliRunner

from rbx.box.packaging.main import app


def test_moj_next_command_is_registered():
    result = CliRunner().invoke(app, ['--help'])
    assert result.exit_code == 0
    assert 'moj-next' in result.output


def test_legacy_moj_command_is_untouched():
    # The new packager is additive: interactive problems still go through `moj`.
    result = CliRunner().invoke(app, ['--help'])
    assert 'moj' in result.output
