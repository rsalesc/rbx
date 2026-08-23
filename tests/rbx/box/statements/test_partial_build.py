import inspect
import pathlib

import pytest
import typer

from rbx.box import cd, package_utils
from rbx.box.statements import build_statements
from rbx.box.statements.schema import StatementType


def _break_statement(path: pathlib.Path) -> None:
    """Make a statement fail to render, via a var no namespace defines."""
    path.write_text(
        '%- block legend\nBroken: \\VAR{vars.this_var_does_not_exist}.\n%- endblock\n'
    )


@pytest.mark.test_pkg('contests/statements_v2_partial')
async def test_failing_statement_does_not_stop_later_ones(cleandir_with_testdata):
    # Problem A declares en first, then pt. Break en; pt must still build.
    _break_statement(cleandir_with_testdata / 'A' / 'statement' / 'statement.rbx.tex')

    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        with pytest.raises(typer.Exit) as exc_info:
            await build_statements.execute_build(
                verification=0,
                samples=False,
                validate=False,
                output=StatementType.TeX,
                keep_going=True,
            )

    assert exc_info.value.exit_code == 1
    build_dir = cleandir_with_testdata / 'A' / 'build'
    assert (build_dir / 'statement-pt.tex').exists()
    assert not (build_dir / 'statement-en.tex').exists()


@pytest.mark.test_pkg('contests/statements_v2_partial')
async def test_packager_default_still_fails_fast(cleandir_with_testdata):
    # execute_build_on_statements defaults to keep_going=False so a packager,
    # which cannot ship an incomplete set of statements, keeps aborting on the
    # first failure rather than silently emitting the rest.
    _break_statement(cleandir_with_testdata / 'A' / 'statement' / 'statement.rbx.tex')

    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        with pytest.raises(BaseException) as exc_info:
            await build_statements.execute_build(
                verification=0,
                samples=False,
                validate=False,
                output=StatementType.TeX,
            )

    # It aborted on the first statement, so the later one was never attempted.
    assert not isinstance(exc_info.value, typer.Exit) or exc_info.value.exit_code != 1
    assert not (cleandir_with_testdata / 'A' / 'build' / 'statement-pt.tex').exists()


def test_keep_going_defaults_to_false():
    sig = inspect.signature(build_statements.execute_build_on_statements)
    assert sig.parameters['keep_going'].default is False
