"""Verify the BOCA submitter raises the picker error in dispatcher mode."""

import os
import pathlib
from unittest import mock

import pytest
import typer

from rbx.box.contest import contest_package as cp_module
from rbx.box.contest.contest_state import selected_variant_id_var
from rbx.box.tooling.boca import submitter


def _write_problem(folder: pathlib.Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'problem.rbx.yml').write_text(f'name: {name}\n')


def _write_dispatcher(
    root: pathlib.Path, variants: dict[str, list[tuple[str, str]]]
) -> None:
    (root / 'contest.rbx.yml').write_text('use_variants: true\n')
    for vid, problems in variants.items():
        body = '\n'.join(
            f'  - short_name: {sn}\n    path: {path}' for sn, path in problems
        )
        (root / f'contest.{vid}.rbx.yml').write_text(
            f'name: {vid}-c\nproblems:\n{body}\n'
        )


@pytest.fixture(autouse=True)
def _clear_state():
    cp_module.find_contest_yaml.cache_clear()
    cp_module.find_contest_package.cache_clear()
    token = selected_variant_id_var.set(None)
    try:
        yield
    finally:
        selected_variant_id_var.reset(token)
        cp_module.find_contest_yaml.cache_clear()
        cp_module.find_contest_package.cache_clear()


def test_submit_all_solutions_errors_in_ambiguous_dispatcher(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
):
    _write_dispatcher(
        tmp_path,
        {
            'div1': [('A', 'A')],
            'div2': [('A', 'A')],
        },
    )
    _write_problem(tmp_path / 'A', 'prob-a')
    os.chdir(tmp_path / 'A')

    # The submitter logs into BOCA and reads env vars — we only care that the
    # picker error triggers before any of that matters when ambiguous.
    monkeypatch.setenv('BOCA_BASE_URL', 'http://example.invalid')
    monkeypatch.setenv('BOCA_JUDGE_USERNAME', 'judge')

    fake_scraper = mock.MagicMock()
    fake_scraper.loggedIn = True
    fake_scraper.list_problems_as_judge.return_value = {'A': 1}

    with pytest.raises(typer.Exit):
        # submit_all_solutions is a generator — must consume it to trigger the
        # body to execute.
        list(submitter.submit_all_solutions(fake_scraper))

    out = capsys.readouterr().out
    assert '-C' in out
    assert 'div1' in out and 'div2' in out
