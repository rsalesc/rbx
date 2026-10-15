"""The statement build report (#909), written by a real `rbx st b` over the
`statements_v2` package, with pdflatex mocked."""

import pathlib
import subprocess

import pytest
import typer
import yaml

from rbx.box import cd, package_utils
from rbx.box.statements import build_report, build_statements
from rbx.box.statements.latex import Latex, LatexResult
from rbx.box.statements.schema import StatementType

STATEMENT = 'statement/statement.rbx.tex'


def _read(root: pathlib.Path) -> dict:
    return yaml.safe_load(build_report.report_path(root).read_text())


async def _build(output: StatementType = StatementType.PDF) -> None:
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        await build_statements.execute_build(
            verification=0,
            samples=False,
            validate=False,
            output=output,
        )


def _failing_pdflatex(needle: str, message: str):
    """A pdflatex that fails on the first line of the TeX it is handed holding
    `needle`, reporting it the way `-file-line-error` does."""

    def build_pdf(self: Latex, temp_dir: pathlib.Path) -> LatexResult:
        lines = self.latex.split('\n')
        line = next(i for i, text in enumerate(lines, start=1) if needle in text)
        log = f'(./statement.tex\n./statement.tex:{line}: {message}\nl.{line} x\n'
        return LatexResult(
            result=subprocess.CompletedProcess(
                args='', returncode=1, stdout=log.encode(), stderr=b''
            ),
            pdf=None,
        )

    return build_pdf


@pytest.mark.test_pkg('contests/statements_v2')
async def test_successful_build_publishes_the_output(cleandir_with_testdata):
    await _build()

    report = _read(cleandir_with_testdata / 'A')
    assert report['version'] == build_report.REPORT_VERSION
    [output] = report['outputs']
    assert output['kind'] == 'statement'
    assert output['language'] == 'en'
    assert output['format'] == 'pdf'
    assert output['path'] == 'build/statement-en.pdf'
    assert output['source'] == STATEMENT
    assert output['status'] == 'ok'
    assert 'findings' not in output or output['findings'] == []


@pytest.mark.test_pkg('contests/statements_v2')
async def test_tex_output_has_no_tags(cleandir_with_testdata):
    await _build(StatementType.TeX)
    text = (cleandir_with_testdata / 'A' / 'build' / 'statement-en.tex').read_text()
    assert '' not in text and 'authored by Alice' in text


@pytest.mark.test_pkg('contests/statements_v2')
async def test_latex_error_is_located_in_the_statement_source(
    cleandir_with_testdata, monkeypatch
):
    monkeypatch.setattr(
        Latex,
        'build_pdf',
        _failing_pdflatex('belongs to', 'Undefined control sequence.'),
    )
    with pytest.raises(typer.Exit):
        await _build()

    [output] = _read(cleandir_with_testdata / 'A')['outputs']
    assert output['status'] == 'failed'
    assert output['findings'] == [
        {
            'origin': 'latex',
            'severity': 'error',
            'message': 'Undefined control sequence.',
            'file': STATEMENT,
            'line': 3,
            'context': 'x',
        }
    ]


@pytest.mark.test_pkg('contests/statements_v2')
async def test_latex_error_in_the_template_points_at_the_template(
    cleandir_with_testdata, monkeypatch
):
    monkeypatch.setattr(
        Latex, 'build_pdf', _failing_pdflatex('\\section*', 'Missing $ inserted.')
    )
    with pytest.raises(typer.Exit):
        await _build()

    [finding] = _read(cleandir_with_testdata / 'A')['outputs'][0]['findings']
    # The chrome lives outside the problem, so its path is absolute.
    template = cleandir_with_testdata / 'statements' / 'problem-standalone.rbx.tex'
    assert pathlib.Path(finding['file']) == template.resolve()
    assert finding['line'] == 14


@pytest.mark.test_pkg('contests/statements_v2')
async def test_undefined_variable_is_a_template_finding(cleandir_with_testdata):
    source = cleandir_with_testdata / 'A' / STATEMENT
    source.write_text(source.read_text().replace('vars.author', 'vars.nobody'))

    with pytest.raises(typer.Abort):
        await _build()

    [finding] = _read(cleandir_with_testdata / 'A')['outputs'][0]['findings']
    assert finding['origin'] == 'template'
    assert finding['file'] == STATEMENT
    assert finding['line'] == 2
    assert 'nobody' in finding['message']


@pytest.mark.test_pkg('contests/statements_v2')
async def test_rebuild_replaces_the_entry(cleandir_with_testdata, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(Latex, 'build_pdf', _failing_pdflatex('belongs to', 'Boom.'))
        with pytest.raises(typer.Exit):
            await _build()
    await _build()

    [output] = _read(cleandir_with_testdata / 'A')['outputs']
    assert output['status'] == 'ok'


def test_unknown_version_is_ignored(tmp_path):
    path = build_report.report_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('version: 999\noutputs: [{weird: true}]\n')
    assert build_report.read_report(path).outputs == []


@pytest.mark.test_pkg('contests/statements_v2')
async def test_error_in_a_deferred_argument_lands_where_it_was_written(
    cleandir_with_testdata, monkeypatch
):
    """TeX reports an error inside a stored argument at the line that expands
    it (here the last one); the argument text it prints finds the real line."""

    def build_pdf(self: Latex, temp_dir: pathlib.Path) -> LatexResult:
        last = len(self.latex.rstrip('\n').split('\n'))
        log = (
            f'./statement.tex:{last}: Undefined control sequence.\n'
            '<argument> This problem belongs \n'
            '                   to Statements v2 Contest.\n'
            f'l.{last} \\end{{document}}\n'
        )
        return LatexResult(
            result=subprocess.CompletedProcess('', 1, log.encode(), b''), pdf=None
        )

    monkeypatch.setattr(Latex, 'build_pdf', build_pdf)
    with pytest.raises(typer.Exit):
        await _build()

    [finding] = _read(cleandir_with_testdata / 'A')['outputs'][0]['findings']
    assert (finding['file'], finding['line']) == (STATEMENT, 3)
