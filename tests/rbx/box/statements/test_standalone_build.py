import pathlib

import pytest

from rbx.box import cd, package_utils
from rbx.box.statements import build_statements
from rbx.box.statements.resolver import StatementResolverError
from rbx.box.statements.schema import StatementType


@pytest.mark.test_pkg('contests/statements_v2')
async def test_standalone_renders_full_document_with_namespaces(
    cleandir_with_testdata,
):
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        await build_statements.execute_build(
            verification=0,
            samples=False,
            validate=False,
            output=StatementType.TeX,
        )

    out = cleandir_with_testdata / 'A' / 'build' / 'statement-en.tex'
    text = out.read_text()
    # The standalone template (a FULL document) was applied.
    assert '\\documentclass' in text
    assert '\\begin{document}' in text
    # Problem namespace + the extracted legend block.
    assert 'Problem A' in text
    # vars (problem) and params (statement) are distinct namespaces.
    assert 'authored by Alice' in text
    assert 'Limits shown: True' in text
    # contest namespace available in the block.
    assert 'Statements v2 Contest' in text


@pytest.mark.test_pkg('contests/statements_v2')
async def test_standalone_builds_pdf_with_mocked_pdflatex(cleandir_with_testdata):
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        await build_statements.execute_build(
            verification=0,
            samples=False,
            validate=False,
            output=StatementType.PDF,
        )
    assert (cleandir_with_testdata / 'A' / 'build' / 'statement-en.pdf').is_file()


@pytest.mark.test_pkg('contests/statements_v2')
async def test_standalone_overlay_merges_contest_chrome(cleandir_with_testdata):
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        await build_statements.execute_build(
            verification=0,
            samples=False,
            validate=False,
            output=StatementType.TeX,
        )
        overlay_root = pathlib.Path('build') / 'statements' / 'st' / 'en-default'
        # Contest chrome (the templates) was merged into the problem overlay root.
        assert (overlay_root / 'problem-standalone.rbx.tex').is_file()


@pytest.mark.test_pkg('problems/rooted-tree-detective')
async def test_standalone_outside_contest_is_hard_error(pkg_from_testdata):
    with pytest.raises(StatementResolverError):
        await build_statements.execute_build(
            verification=0,
            samples=False,
            validate=False,
            output=StatementType.TeX,
        )
