import pathlib

import pytest
import typer

from rbx.box import limits_info
from rbx.box.contest import statements as contest_statements_cli
from rbx.box.statements.schema import StatementType


def _async_build():
    # `build` is decorated with @within_contest (sync wrapper) and @syncer.sync.
    # Peel both layers to reach the underlying async coroutine function.
    return contest_statements_cli.build.__wrapped__.__wrapped__


@pytest.mark.test_pkg('contests/two_problems')
async def test_contest_build_skips_problems_missing_profile(
    cleandir_with_testdata, monkeypatch
):
    pathlib.Path('A/.limits').mkdir(parents=True, exist_ok=True)
    pathlib.Path('A/.limits/icpc.yml').write_text('timeLimit: 5000\n')

    built_for = []
    seen_profiles = []

    async def fake_build_statement(
        statement, contest, *, problems_of_interest=None, **kwargs
    ):
        seen_profiles.append(limits_info.get_active_profile())
        built_for.append([p.short_name for p in (problems_of_interest or [])])
        return pathlib.Path('fake.pdf')

    monkeypatch.setattr(
        'rbx.box.contest.statements.build_statement',
        fake_build_statement,
    )

    await _async_build()(
        verification=0,
        names=None,
        languages=None,
        validate=False,
        output=StatementType.PDF,
        samples=False,
        vars=None,
        install_tex=False,
        profile='icpc',
    )

    assert built_for, 'expected at least one statement build call'
    for problems in built_for:
        assert 'A' in problems
        assert 'B' not in problems
    assert seen_profiles == ['icpc']


@pytest.mark.test_pkg('contests/two_problems')
async def test_contest_build_all_missing_profile_exits(cleandir_with_testdata):
    with pytest.raises(typer.Exit) as exc_info:
        await _async_build()(
            verification=0,
            names=None,
            languages=None,
            validate=False,
            output=StatementType.PDF,
            samples=False,
            vars=None,
            install_tex=False,
            profile='nonexistent',
        )
    assert exc_info.value.exit_code == 1
