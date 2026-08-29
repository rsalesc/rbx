import inspect

import pytest
import typer

from rbx.box.contest import statements as contest_statements_cli
from rbx.box.statements.schema import StatementType

_build_async = inspect.unwrap(contest_statements_cli.build)
_build_tut_async = inspect.unwrap(contest_statements_cli.build_tutorials)


async def _run(output=StatementType.TeX, names=None):
    await _build_async(
        verification=0,
        names=names,
        languages=None,
        validate=False,
        output=output,
        samples=False,
        vars=None,
        install_tex=False,
        profile=None,
    )


async def _run_tutorials(output=StatementType.TeX):
    await _build_tut_async(
        verification=0,
        names=None,
        languages=None,
        validate=False,
        output=output,
        samples=False,
        vars=None,
        install_tex=False,
        profile=None,
    )


@pytest.mark.test_pkg('contests/statements_v2')
async def test_contest_join_subimports_each_problem(cleandir_with_testdata):
    await _run(output=StatementType.TeX)

    contest_tex = (cleandir_with_testdata / 'build' / 'main-en.tex').read_text()
    assert 'Statements v2 Contest' in contest_tex
    assert '\\subimport{.problems/A/}{statement}' in contest_tex
    assert '\\subimport{.problems/B/}{statement}' in contest_tex


@pytest.mark.test_pkg('contests/statements_v2')
async def test_contest_fragments_are_isolated_per_problem(cleandir_with_testdata):
    await _run(output=StatementType.TeX)

    overlay = cleandir_with_testdata / 'build' / 'statements' / 'main-en'
    frag_a = (overlay / '.problems' / 'A' / 'statement.tex').read_text()
    frag_b = (overlay / '.problems' / 'B' / 'statement.tex').read_text()

    # Fragment uses the contestProblemTemplate (a fragment, no \documentclass).
    assert '\\documentclass' not in frag_a
    assert 'Problem A. Problem A' in frag_a
    assert 'authored by Alice' in frag_a
    assert 'Problem B. Problem B' in frag_b
    assert 'authored by Bob' in frag_b


@pytest.mark.test_pkg('contests/statements_v2')
async def test_documents_emitted_without_joining(cleandir_with_testdata):
    await _run(output=StatementType.TeX)

    info = (cleandir_with_testdata / 'build' / 'info-en.tex').read_text()
    assert 'info sheet' in info
    assert 'Statements v2 Contest' in info
    assert '\\subimport' not in info


@pytest.mark.test_pkg('contests/statements_v2')
async def test_document_can_be_selected_by_name(cleandir_with_testdata):
    # Naming only a document must build it, even though it matches no statement.
    await _run(output=StatementType.TeX, names=['info-en'])

    assert (cleandir_with_testdata / 'build' / 'info-en.tex').is_file()
    assert not (cleandir_with_testdata / 'build' / 'main-en.tex').exists()


@pytest.mark.test_pkg('contests/statements_v2')
async def test_statement_selected_by_name_skips_documents(cleandir_with_testdata):
    await _run(output=StatementType.TeX, names=['main-en'])

    assert (cleandir_with_testdata / 'build' / 'main-en.tex').is_file()
    assert not (cleandir_with_testdata / 'build' / 'info-en.tex').exists()


@pytest.mark.test_pkg('contests/statements_v2')
async def test_unknown_name_still_fails(cleandir_with_testdata):
    with pytest.raises(typer.Exit):
        await _run(output=StatementType.TeX, names=['nonexistent'])


@pytest.mark.test_pkg('contests/statements_v2')
async def test_contest_tutorials_join_each_problem(cleandir_with_testdata):
    # `rbx contest tut b` joins the problems' tutorials (editorials), pulling
    # from each problem's `tutorials` section, into the contest tutorial doc.
    await _run_tutorials(output=StatementType.TeX)

    sheet = (cleandir_with_testdata / 'build' / 'editorial-en.tex').read_text()
    assert '\\subimport{.problems/A/}{statement}' in sheet
    assert '\\subimport{.problems/B/}{statement}' in sheet

    overlay = cleandir_with_testdata / 'build' / 'statements' / 'editorial-en'
    frag_a = (overlay / '.problems' / 'A' / 'statement.tex').read_text()
    # Fragment rendered the problem's TUTORIAL file (editorial), not its statement.
    assert 'Editorial A. Problem A' in frag_a
    assert 'Editorial for A, authored by Alice' in frag_a

    # The statements channel is untouched by the tutorials build.
    assert not (cleandir_with_testdata / 'build' / 'main-en.tex').is_file()


@pytest.mark.test_pkg('contests/statements_v2')
async def test_documents_can_read_problem_metadata(cleandir_with_testdata):
    await _run(output=StatementType.TeX)

    info = (cleandir_with_testdata / 'build' / 'info-en.tex').read_text()
    # A document never imports problem statements or samples, but it CAN read
    # per-problem metadata (here, limits) via the `problems` namespace.
    assert 'Limits for A: 1000 ms.' in info
    assert 'Limits for B: 2000 ms.' in info
    assert '\\subimport' not in info


@pytest.mark.test_pkg('contests/statements_v2')
async def test_contest_build_pdf_with_mocked_pdflatex(cleandir_with_testdata):
    await _run(output=StatementType.PDF)
    assert (cleandir_with_testdata / 'build' / 'main-en.pdf').is_file()
    assert (cleandir_with_testdata / 'build' / 'info-en.pdf').is_file()


@pytest.mark.test_pkg('contests/statements_v2_group_vars')
async def test_join_fragment_renders_group_resolved_vars(cleandir_with_testdata):
    # The contest JOIN site: each problem fragment is rendered from the
    # contestProblemTemplate, which loops over `problem.groups`.
    await _run(output=StatementType.TeX)

    overlay = cleandir_with_testdata / 'build' / 'statements' / 'main-en'
    frag = (overlay / '.problems' / 'A' / 'statement.tex').read_text()
    assert '\\subtask{sub1}{1}{10}' in frag
    assert '\\subtask{sub2}{100}{200}' in frag
    # sub3 overrides nothing and still renders both inherited bounds.
    assert '\\subtask{sub3}{1}{200}' in frag


@pytest.mark.test_pkg('contests/statements_v2_group_vars')
async def test_document_metadata_exposes_group_resolved_vars(cleandir_with_testdata):
    # The document-metadata site (`_collect_problem_metadata`), which builds its
    # own ProblemRenderContext without rendering any statement.
    await _run(output=StatementType.TeX)

    info = (cleandir_with_testdata / 'build' / 'info-en.tex').read_text()
    assert '\\info{A}{sub1}{1}{10}' in info
    assert '\\info{A}{sub2}{100}{200}' in info
    assert '\\info{A}{sub3}{1}{200}' in info
    assert '\\subimport' not in info
