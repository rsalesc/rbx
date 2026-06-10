import pathlib

import pytest

from rbx import utils
from rbx.box import cd, package, package_utils
from rbx.box.statements import build_statements
from rbx.box.statements.builders import StatementBlocks
from rbx.box.statements.schema import (
    ConversionType,
    StatementType,
    TexToPDF,
    rbxToTeX,
)


def _externalize_params():
    return [
        rbxToTeX(type=ConversionType.rbxToTex, externalize=True),
        TexToPDF(type=ConversionType.TexToPDF, externalize=True, demacro=True),
    ]


@pytest.mark.test_pkg('contests/statements_v2_polygon')
async def test_render_persists_block_yamls_with_externalization(
    cleandir_with_testdata,
):
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        pkg = package.find_problem_package_or_die()
        statement = pkg.expanded_statements[0]
        await build_statements.build_statement(
            statement,
            pkg,
            output_type=StatementType.TeX,
            use_samples=False,
            extra_mergeable_params=_externalize_params(),
        )
        overlay = pathlib.Path('build') / 'statements' / 'st' / 'en-default'
        # All three block YAMLs persisted (source of truth, v1 parity).
        assert (overlay / 'blocks.yml').is_file()
        assert (overlay / 'blocks.ext.yml').is_file()
        assert (overlay / 'blocks.sub.yml').is_file()

        # Raw blocks keep the TikZ picture verbatim.
        raw = utils.model_from_yaml(
            StatementBlocks, (overlay / 'blocks.yml').read_text()
        )
        assert 'tikzpicture' in raw.blocks['legend']

        # Substituted blocks replaced the TikZ with an \includegraphics handle.
        sub = utils.model_from_yaml(
            StatementBlocks, (overlay / 'blocks.sub.yml').read_text()
        )
        assert '\\includegraphics' in sub.blocks['legend']
        assert 'tikzpicture' not in sub.blocks['legend']
        # Non-figure blocks survive untouched.
        assert 'integer' in sub.blocks['input']


@pytest.mark.test_pkg('contests/statements_v2_polygon')
async def test_render_without_externalize_writes_only_blocks_yml(
    cleandir_with_testdata,
):
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        pkg = package.find_problem_package_or_die()
        statement = pkg.expanded_statements[0]
        await build_statements.build_statement(
            statement,
            pkg,
            output_type=StatementType.TeX,
            use_samples=False,
        )
        overlay = pathlib.Path('build') / 'statements' / 'st' / 'en-default'
        # blocks.yml is the always-on source of truth ...
        assert (overlay / 'blocks.yml').is_file()
        # ... but the externalized variants are only produced on demand.
        assert not (overlay / 'blocks.ext.yml').exists()
        assert not (overlay / 'blocks.sub.yml').exists()
