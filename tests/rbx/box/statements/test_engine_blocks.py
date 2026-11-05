import pathlib

import pytest

from rbx import utils
from rbx.box import cd, package, package_utils
from rbx.box.statements import build_statements
from rbx.box.statements.render import StatementBlocks
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


FIG = 'artifacts/tikz_figures/'


def _build_overlay_blocks(name: str) -> StatementBlocks:
    overlay = pathlib.Path('build') / 'statements' / 'st' / 'en-default'
    return utils.model_from_yaml(StatementBlocks, (overlay / name).read_text())


@pytest.mark.test_pkg('contests/statements_v2_picture_macros')
async def test_pictures_drawn_by_macros_are_labeled_at_each_use(
    cleandir_with_testdata,
):
    """#1006: a picture that only exists once a macro is expanded -- defined in
    the defs block or by the template, with or without arguments -- gets a
    label of its own at every use, and its substitution keeps its place."""
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        pkg = package.find_problem_package_or_die()
        await build_statements.build_statement(
            pkg.expanded_statements[0],
            pkg,
            output_type=StatementType.TeX,
            use_samples=False,
            extra_mergeable_params=_externalize_params(),
        )

        ext = _build_overlay_blocks('blocks.ext.yml')
        legend = ext.blocks['legend']
        assert legend.count(r'\tikzsetnextfilename{legend_') == 5
        assert r'\begin{tikzpicture}[baseline=(c.base)]\node[draw] (c) {Bye};' in (
            legend
        )
        for macro in (r'\button', r'\badge', r'\ratingstar'):
            assert macro not in legend
        # The definitions are templates, not figures.
        assert 'tikzsetnextfilename' not in ext.blocks['defs']

        sub = _build_overlay_blocks('blocks.sub.yml').blocks['legend']
        assert 'tikzpicture' not in sub
        # In running text: bare. A display: centered once. Already centered:
        # left alone.
        assert sub.startswith(
            rf'Press \includegraphics{{{FIG}legend_0}} to thank, or '
            rf'\includegraphics{{{FIG}legend_1}} to leave.'
        )
        assert sub.count(r'\begin{center}') == 2
        assert r'\begin{center}\begin{center}' not in sub
        assert sub.rstrip().endswith(rf'Rated \includegraphics{{{FIG}legend_3}}.')

        # The raw blocks, the setter's source of truth, are untouched.
        raw = _build_overlay_blocks('blocks.yml').blocks['legend']
        assert r'Press \button{Thanks!}' in raw


@pytest.mark.test_pkg('contests/statements_v2_picture_macros')
async def test_picture_macros_stay_unexpanded_outside_the_export_build(
    cleandir_with_testdata,
):
    with cd.new_package_cd(pathlib.Path('A')):
        package_utils.clear_package_cache()
        pkg = package.find_problem_package_or_die()
        await build_statements.build_statement(
            pkg.expanded_statements[0],
            pkg,
            output_type=StatementType.TeX,
            use_samples=False,
        )
        tex = (pathlib.Path('build') / 'statement-en.tex').read_text()
        assert r'Press \button{Thanks!}' in tex
        assert 'tikzsetnextfilename' not in tex


@pytest.mark.test_pkg('contests/statements_v2_picture_macros')
async def test_picture_macros_whose_static_read_is_unsafe_stay_unexpanded(
    cleandir_with_testdata, capsys
):
    """Review findings 3, 4 and 8: a macro redefined between uses, one picked
    from a table at run time, and one whose body names an `@` macro are not
    spliced into the blocks -- the build does what it did before #1006 and
    says so -- and nothing inside `\\verb` is expanded."""
    with cd.new_package_cd(pathlib.Path('B')):
        package_utils.clear_package_cache()
        pkg = package.find_problem_package_or_die()
        capsys.readouterr()
        await build_statements.build_statement(
            pkg.expanded_statements[0],
            pkg,
            output_type=StatementType.TeX,
            use_samples=False,
            extra_mergeable_params=_externalize_params(),
        )
        out = ' '.join(capsys.readouterr().out.split())

        legend = _build_overlay_blocks('blocks.ext.yml').blocks['legend']
        assert legend.count(r'\pdot') == 3  # the \renewcommand and both uses
        assert r'\pkgbutton{Go}' in legend
        assert r'\strButton' in legend
        assert 'Enviar' not in legend
        assert r'\verb|\ratingstar|' in legend
        # The one safe macro is still expanded and labeled.
        assert r'get \tikzsetnextfilename{legend_' in legend

        assert 'Not expanding these TikZ-drawing macros' in out
        for name in (r'\pdot', r'\pkgbutton', r'\strButton'):
            assert name in out
