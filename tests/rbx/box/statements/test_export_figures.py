"""What the export does with the figures the externalize build produced
(#1006): inline ones get their natural height, and pictures it cannot place
are reported instead of silently dropped."""

import pathlib

import pytest

from rbx import utils
from rbx.box import cd, package, package_utils
from rbx.box.statements import build_statements, export
from rbx.box.statements.demacro_utils import MacroDefinitions
from rbx.box.statements.render import StatementBlocks
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


def _figure(height_bp: float) -> bytes:
    return (
        b'%PDF-1.4\n1 0 obj\n<< /Type /Page /MediaBox [0 0 40 '
        + str(height_bp).encode()
        + b'] >>\nendobj\n%%EOF\n'
    )


async def _build(st, pkg) -> pathlib.Path:
    await build_statements.build_statement(
        st,
        pkg,
        output_type=StatementType.TeX,
        use_samples=False,
        extra_mergeable_params=_externalize_params(),
    )
    overlay = build_statements.get_statement_dir(st)
    MacroDefinitions().to_json_file(overlay / 'macros.json')
    return overlay


def _out(capsys) -> str:
    return ' '.join(capsys.readouterr().out.split())


@pytest.mark.test_pkg('contests/statements_v2_picture_macros')
async def test_inline_figures_get_their_natural_height(cleandir_with_testdata, capsys):
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        pkg = package.find_problem_package_or_die()
        st = pkg.expanded_statements[0]
        overlay = await _build(st, pkg)
        figures = overlay / EXTERNALIZATION_DIR
        figures.mkdir(parents=True, exist_ok=True)
        for index in range(5):
            (figures / f'legend_{index}.pdf').write_bytes(_figure(13.95))
        capsys.readouterr()

        legend = export.get_processed_statement_blocks(st).blocks['legend']

        fig = EXTERNALIZATION_DIR
        assert legend.startswith(
            rf'Press \includegraphics[height=14pt]{{{fig}legend_0}} to thank, or '
            rf'\includegraphics[height=14pt]{{{fig}legend_1}} to leave.'
        )
        assert rf'Rated \includegraphics[height=14pt]{{{fig}legend_3}}.' in legend
        # Displays keep their natural size.
        assert rf'\begin{{center}}\includegraphics{{{fig}legend_2}}' in legend
        assert rf'\includegraphics{{{fig}legend_4}}' in legend
        assert _out(capsys) == ''


@pytest.mark.test_pkg('contests/statements_v2_picture_macros')
async def test_a_picture_left_in_a_block_is_reported(cleandir_with_testdata, capsys):
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        pkg = package.find_problem_package_or_die()
        st = pkg.expanded_statements[0]
        overlay = await _build(st, pkg)
        # What the export used to receive for a picture drawn by a macro it
        # could not see: raw TikZ, which no target can show.
        sub_path = overlay / 'blocks.sub.yml'
        sub = utils.model_from_yaml(StatementBlocks, sub_path.read_text())
        sub.blocks['input'] = r'Read \tikz{\draw (0,0) -- (1,0);} carefully.'
        sub_path.write_text(utils.model_to_yaml(sub))
        capsys.readouterr()

        export.get_processed_statement_blocks(st)

        out = _out(capsys)
        assert 'The input block of statement en still has a TikZ picture' in out
        # The defs block holds the macros' own pictures, which are no figures.
        assert out.count('still has a TikZ picture') == 1


@pytest.mark.test_pkg('contests/statements_v2_picture_macros')
async def test_figures_externalized_without_a_label_are_reported(
    cleandir_with_testdata, capsys
):
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        pkg = package.find_problem_package_or_die()
        st = pkg.expanded_statements[0]
        overlay = await _build(st, pkg)
        figures = overlay / EXTERNALIZATION_DIR
        figures.mkdir(parents=True, exist_ok=True)
        (figures / 'legend_0.pdf').write_bytes(_figure(10))
        (figures / 'statement-figure0.pdf').write_bytes(_figure(10))
        capsys.readouterr()

        export.get_processed_statement_blocks(st)

        out = _out(capsys)
        assert 'TikZ externalized 1 picture(s) rbx did not label' in out
        assert 'statement-figure0.pdf' in out
        assert 'legend_0' not in out
