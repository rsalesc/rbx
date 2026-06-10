import pathlib

import pytest

from rbx.box import cd, package, package_utils
from rbx.box.statements import build_statements
from rbx.box.statements.schema import (
    ConversionType,
    StatementType,
    TexToPDF,
    rbxToTeX,
)
from rbx.box.statements.texsoup_utils import EXTERNALIZATION_DIR


def _externalize_params():
    return [
        rbxToTeX(type=ConversionType.rbxToTex, externalize=True),
        TexToPDF(type=ConversionType.TexToPDF, externalize=True, demacro=True),
    ]


@pytest.mark.test_pkg('contests/statements_v2_polygon')
async def test_get_statement_dir_is_overlay_root(cleandir_with_testdata):
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        st = package.find_problem_package_or_die().expanded_statements[0]
        d = build_statements.get_statement_dir(st)
        # Keyed by (language, variant) under the shared statements build dir.
        assert d.parts[-3:] == ('statements', 'st', 'en-default')
        assert d.is_dir()


@pytest.mark.test_pkg('contests/statements_v2_polygon')
async def test_get_produced_tikz_pdfs_globs_externalization_dir(
    cleandir_with_testdata,
):
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        st = package.find_problem_package_or_die().expanded_statements[0]
        d = build_statements.get_statement_dir(st)
        (d / EXTERNALIZATION_DIR).mkdir(parents=True, exist_ok=True)
        (d / EXTERNALIZATION_DIR / 'legend_0.pdf').write_bytes(b'%PDF-1.5')

        produced = list(build_statements.get_produced_tikz_pdfs(st))
        assert len(produced) == 1
        abspath, rel = produced[0]
        assert rel == pathlib.Path(EXTERNALIZATION_DIR) / 'legend_0.pdf'
        assert abspath.is_file()


@pytest.mark.test_pkg('contests/statements_v2_polygon')
async def test_get_processed_statement_blocks_reads_overlay(cleandir_with_testdata):
    from rbx.box.packaging.polygon import statement_block_utils as sbu

    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        pkg = package.find_problem_package_or_die()
        st = pkg.expanded_statements[0]
        await build_statements.build_statement(
            st,
            pkg,
            output_type=StatementType.TeX,
            use_samples=False,
            extra_mergeable_params=_externalize_params(),
        )

        blocks = sbu.get_processed_statement_blocks(st)
        # The Polygon-bound blocks come straight from the overlay's blocks.sub.yml.
        assert 'legend' in blocks.blocks
        assert 'input' in blocks.blocks
        assert 'output' in blocks.blocks
        # The legend's TikZ was substituted for an \includegraphics handle.
        assert '\\includegraphics' in blocks.blocks['legend']
        assert 'tikzpicture' not in blocks.blocks['legend']


@pytest.mark.test_pkg('contests/statements_v2_polygon')
async def test_processed_blocks_expand_macros_when_present(cleandir_with_testdata):
    from rbx.box.packaging.polygon import statement_block_utils as sbu
    from rbx.box.statements.demacro_utils import MacroDefinitions

    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        pkg = package.find_problem_package_or_die()
        st = pkg.expanded_statements[0]
        await build_statements.build_statement(
            st,
            pkg,
            output_type=StatementType.TeX,
            use_samples=False,
            extra_mergeable_params=_externalize_params(),
        )
        # Simulate what the demacro compile pass drops in the overlay; the defs
        # block (\NN) is collected and expanded out of the Polygon blocks since
        # \NN is not a Polygon-allowed command.
        MacroDefinitions().to_json_file(
            build_statements.get_statement_dir(st) / 'macros.json'
        )

        blocks = sbu.get_processed_statement_blocks(st)
        assert '\\NN' not in blocks.blocks['notes']
        assert 'mathbb' in blocks.blocks['notes']
