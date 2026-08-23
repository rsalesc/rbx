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


@pytest.mark.test_pkg('contests/statements_v2_partial')
async def test_partial_builds_the_statement_without_the_problem(
    cleandir_with_testdata,
):
    await _run(partial=True)

    pt_tex = (cleandir_with_testdata / 'build' / 'main-pt.tex').read_text()
    assert '\\subimport{.problems/A/}{statement}' in pt_tex
    assert '\\subimport{.problems/B/}{statement}' not in pt_tex


@pytest.mark.test_pkg('contests/statements_v2_partial')
async def test_partial_exits_zero(cleandir_with_testdata):
    # --partial is an explicit request for best-effort output, so a dropped
    # problem is not a command failure. The issue report still lists it.
    await _run(partial=True)

    assert (cleandir_with_testdata / 'build' / 'main-en.tex').exists()
    assert (cleandir_with_testdata / 'build' / 'main-pt.tex').exists()


@pytest.mark.test_pkg('contests/statements_v2_partial')
async def test_missing_contest_problem_template_reports_clearly(
    cleandir_with_testdata, capsys
):
    config = cleandir_with_testdata / 'contest.rbx.yml'
    config.write_text(
        config.read_text().replace(
            "    contestProblemTemplate: 'statements/problem-in-contest.rbx.tex'\n",
            '',
        )
    )

    with pytest.raises(typer.Exit):
        await _run()

    out = capsys.readouterr().out
    assert 'contestProblemTemplate' in out
    assert 'AssertionError' not in out
