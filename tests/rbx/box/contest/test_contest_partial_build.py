import inspect

import pytest
import typer

from rbx.box.contest import statements as contest_statements_cli
from rbx.box.statements.schema import StatementType

_build_async = inspect.unwrap(contest_statements_cli.build)


async def _run(**kwargs):
    defaults = dict(
        verification=0,
        names=None,
        languages=None,
        validate=False,
        output=StatementType.TeX,
        samples=False,
        vars=None,
        install_tex=False,
        profile=None,
    )
    defaults.update(kwargs)
    await _build_async(**defaults)


@pytest.mark.test_pkg('contests/statements_v2_partial')
async def test_failing_statement_does_not_stop_later_ones(cleandir_with_testdata):
    # main-pt is listed first and fails (problem B has no pt statement).
    # main-en must still build.
    with pytest.raises(typer.Exit) as exc_info:
        await _run()

    assert exc_info.value.exit_code == 1
    assert (cleandir_with_testdata / 'build' / 'main-en.tex').exists()
    assert not (cleandir_with_testdata / 'build' / 'main-pt.tex').exists()


@pytest.mark.test_pkg('contests/statements_v2_partial')
async def test_successful_statement_joins_all_problems(cleandir_with_testdata):
    with pytest.raises(typer.Exit):
        await _run()

    contest_tex = (cleandir_with_testdata / 'build' / 'main-en.tex').read_text()
    assert '\\subimport{.problems/A/}{statement}' in contest_tex
    assert '\\subimport{.problems/B/}{statement}' in contest_tex
