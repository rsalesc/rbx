import pathlib
import shutil

import pytest

from rbx import utils
from rbx.box.packaging.polygon.importer import PolygonImporter
from rbx.box.schema import Package
from rbx.box.statements.schema import Statement, StatementType


@pytest.mark.parametrize('main_language', ['pt', 'en'])
async def test_import_pdf_statements(tmp_path, testdata_path, main_language):
    source = tmp_path / 'source'
    destination = tmp_path / 'destination'
    source.mkdir()
    destination.mkdir()
    (source / 'problem.xml').write_text(
        """<problem short-name="pdf-statements">
  <names>
    <name language="english" value="PDF statements"/>
    <name language="portuguese" value="Enunciados PDF"/>
  </names>
  <statements>
    <statement language="english" type="application/pdf" path="english.pdf"/>
    <statement language="portuguese" type="application/pdf" path="portuguese.pdf"/>
  </statements>
  <judging>
    <testset name="tests">
      <test-count>1</test-count>
      <input-path-pattern>input%02d.txt</input-path-pattern>
      <answer-path-pattern>answer%02d.txt</answer-path-pattern>
      <tests><test method="manual" sample="true"/></tests>
    </testset>
  </judging>
</problem>"""
    )
    # Importing copies PDFs without rendering them; reuse the existing dummy.
    for language in ('english', 'portuguese'):
        shutil.copyfile(
            testdata_path / 'problems/box1/dummy.pdf', source / f'{language}.pdf'
        )
    (source / 'input01.txt').write_text('1\n')
    (source / 'answer01.txt').write_text('2\n')

    await PolygonImporter(main_language=main_language).import_package(
        source, destination
    )

    imported = utils.model_from_yaml(
        Package, (destination / 'problem.rbx.yml').read_text()
    )
    expected = [
        Statement(
            language=code,
            file=pathlib.Path(f'statements/{language}.pdf'),
            type=StatementType.PDF,
        )
        for code, language in [('en', 'english'), ('pt', 'portuguese')]
    ]
    expected.sort(key=lambda statement: statement.language != main_language)
    assert imported.statements == expected
    for statement in imported.statements:
        assert (destination / statement.file).read_bytes() == (
            source / statement.file.name
        ).read_bytes()
