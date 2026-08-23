import inspect

import pytest

from rbx.box.contest import statements as contest_statements_cli
from rbx.box.statements.resolver import StatementResolverError
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
async def test_fixture_currently_aborts_every_statement(cleandir_with_testdata):
    # Characterization of the bug: main-pt fails (B has no pt statement) and
    # takes main-en down with it. Deleted in Task 3.
    with pytest.raises(StatementResolverError):
        await _run()
    assert not (cleandir_with_testdata / 'build' / 'main-en.tex').exists()
