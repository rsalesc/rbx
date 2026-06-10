import pathlib

import pytest

from rbx.box import cd, package, package_utils
from rbx.box.statements import build_statements
from rbx.box.statements.texsoup_utils import EXTERNALIZATION_DIR


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
