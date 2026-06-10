import inspect

import pytest

from rbx.box.contest import statements as contest_statements_cli
from rbx.box.statements.schema import StatementType

_build_async = inspect.unwrap(contest_statements_cli.build)


async def _run(output=StatementType.TeX):
    await _build_async(
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
