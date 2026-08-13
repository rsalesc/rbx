"""The MOJ statement, through the judge's own tooling.

Every other test in this directory asserts what rbx *writes*. This one runs
`mojtools`' real `validate-problem.sh` and `render-statement.sh` over the
emitted package -- the same renderer the student sees -- which is the only way
to prove that the reference remap and the notes' `--resource-path` base are
right rather than merely self-consistent.

Skipped unless `MOJTOOLS_DIR` points at a `cd-moj/mojtools` checkout.
"""

import json
import os
import pathlib
import shutil
import subprocess

import pytest

from tests.rbx.box.packaging.moj.conftest import (
    PT_BLOCKS,
    build_entries,
    minimal_package,
    run_packager,
    with_statements,
)

pytestmark = pytest.mark.slow

EXPLANATION = 'Veja o \\includegraphics{diagram} para entender o exemplo.'


def _mojtools() -> pathlib.Path:
    directory = os.environ.get('MOJTOOLS_DIR')
    if not directory:
        pytest.skip('MOJTOOLS_DIR is not set; set it to a cd-moj/mojtools checkout.')
    path = pathlib.Path(directory)
    if not (path / 'validate-problem.sh').is_file():
        pytest.skip(f'{path} does not look like a mojtools checkout.')
    for tool in ('bash', 'jq', 'pandoc'):
        if shutil.which(tool) is None:
            pytest.skip(f'{tool} is required to run mojtools.')
    return path


@pytest.fixture
def packaged(testing_pkg, tmp_path, monkeypatch) -> pathlib.Path:
    """A package carrying a statement figure and a sample explanation."""
    minimal_package(testing_pkg)
    with_statements(testing_pkg, monkeypatch, PT_BLOCKS, explanations={0: EXPLANATION})
    # mojtools derives the problem id from the package directory's name.
    return run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))


def _validate(mojtools: pathlib.Path, package: pathlib.Path, tmp_path: pathlib.Path):
    rundir = tmp_path / 'run'
    rundir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ['bash', str(mojtools / 'validate-problem.sh'), str(package), 'rbx-e2e'],
        capture_output=True,
        env={
            **os.environ,
            'RUNDIR': str(rundir),
            # No bwrap outside Linux; the solutions are verified at calibration
            # time on the real judge anyway, and this test is about the statement.
            'VALIDATE_RUN_SOLS': '0',
        },
    )
    report = rundir / 'validation' / 'rbx-e2e.json'
    assert report.is_file(), 'validate-problem.sh wrote no report'
    return json.loads(report.read_text())


def _check(report, name: str):
    for check in report['checks']:
        if check['name'] == name:
            return check
    raise AssertionError(f'validate-problem.sh reported no {name!r} check')


def test_validate_problem_passes_the_statement_gate(packaged, tmp_path):
    mojtools = _mojtools()
    report = _validate(mojtools, packaged, tmp_path)

    # The three hard statement checks. `secao_*` are grepped out of the RAW file,
    # which is why the headings are emitted whether or not the block exists.
    for name in ('has_statement', 'html_builds', 'secao_entrada', 'secao_saida'):
        check = _check(report, name)
        assert check['ok'], f'{name}: {check["detail"]}'

    # And nothing soft either: no leaked LaTeX, no examples section, no fence, and
    # no note left unpaired with a sample.
    assert report['render_warnings'] == ''


def test_render_statement_embeds_the_figure(packaged, tmp_path):
    """The end-to-end proof that the remap is right: pandoc resolved the rewritten
    reference against docs/ and base64-embedded the file."""
    mojtools = _mojtools()
    result = subprocess.run(
        [
            'bash',
            str(mojtools / 'render-statement.sh'),
            str(packaged / 'docs' / 'enunciado.md'),
            'md',
            '',
            'Soma',
        ],
        capture_output=True,
        text=True,
    )
    html = result.stdout
    # pandoc adds its own attributes, so match the src rather than the whole tag.
    assert 'src="data:image/png;base64,' in html
    # The title comes from the field, injected by the renderer -- never from the
    # document, which carries none.
    assert '<h1 class="moj-title">Soma</h1>' in html
    assert html.count('<h1') == 1


def test_render_statement_embeds_a_note_figure(packaged, tmp_path):
    """gen-problem-json.sh renders a note with --resource-path=<pkg>/docs, NOT the
    note's own directory. Running it exactly that way is the only check that the
    constant `docs` remap base is correct."""
    _mojtools()
    note = packaged / 'docs' / 'notes' / 'sample001.md'
    assert note.is_file()
    result = subprocess.run(
        [
            'pandoc',
            '-f',
            'markdown',
            '-t',
            'html',
            '--embed-resources',
            f'--resource-path={packaged / "docs"}',
        ],
        input=note.read_text(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert 'src="data:image/png;base64,' in result.stdout
