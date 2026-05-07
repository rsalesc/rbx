"""Verify the BOCA scraper's upload() raises the picker error in dispatcher mode.

The scraper's upload() call site at scraper.py:~385 calls
`naming.require_problem_in_contest()` after fetching the upload form. We
exercise that path with the form-fetching layer mocked out so we don't
need a real BOCA server.
"""

import os
import pathlib
from unittest import mock

import pytest
import typer

from rbx.box.contest import contest_package as cp_module
from rbx.box.contest.contest_state import selected_variant_id_var
from rbx.box.tooling.boca.scraper import BocaScraper


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


def test_upload_errors_in_ambiguous_dispatcher(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
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

    # Bypass __init__ so we don't need real BOCA credentials or a network.
    scraper = BocaScraper.__new__(BocaScraper)
    scraper.base_url = 'http://example.invalid'

    # Stub out the form-fetching layer: upload() opens the admin page and
    # selects a form before reaching the require_problem_in_contest() call.
    fake_form = mock.MagicMock()
    fake_form.set_all_readonly = mock.MagicMock()
    fake_br = mock.MagicMock()
    fake_br.form = fake_form
    scraper.br = fake_br
    scraper.open = mock.MagicMock(return_value=(None, ''))

    file_arg = tmp_path / 'pkg.zip'
    file_arg.write_bytes(b'')

    with pytest.raises(typer.Exit):
        scraper.upload(file_arg)

    out = capsys.readouterr().out
    assert '-C' in out
    assert 'RBX_CONTEST' in out
    assert 'div1' in out and 'div2' in out
