import pathlib

from rbx.box.statements import render
from rbx.box.statements.context import ContestRenderContext, ProblemRenderContext


def _write(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestExtractBlocks:
    def test_extracts_named_blocks_with_namespaced_vars(self, tmp_path):
        content = (
            '%- block legend\n'
            'Hello \\VAR{vars.author}, show=\\VAR{params.show}\n'
            '%- endblock\n'
            '%- block input\n'
            'the input\n'
            '%- endblock\n'
        ).encode()
        problem = ProblemRenderContext(
            title='P', vars={'author': 'alice'}, params={'show': 'YES'}
        )
        contest = ContestRenderContext(title='C')
        blocks = render.extract_blocks(
            tmp_path, content, lang='en', languages=[], problem=problem, contest=contest
        )
        assert 'alice' in blocks.blocks['legend']
        assert 'YES' in blocks.blocks['legend']
        assert 'the input' in blocks.blocks['input']

    def test_extracts_per_sample_explanation_blocks(self, tmp_path):
        content = ('%- block explanation_0\nwhy sample zero\n%- endblock\n').encode()
        problem = ProblemRenderContext(title='P')
        contest = ContestRenderContext(title='C')
        blocks = render.extract_blocks(
            tmp_path, content, lang='en', languages=[], problem=problem, contest=contest
        )
        assert 0 in blocks.explanations
        assert 'why sample zero' in blocks.explanations[0]


class TestRenderProblemDocument:
    def test_fills_template_with_blocks_and_namespaces(self, tmp_path):
        # Template lives in the overlay root (staged by the stager).
        _write(
            tmp_path / 'tpl.rbx.tex',
            '\\documentclass{article}\n'
            '\\begin{document}\n'
            'TITLE=\\VAR{problem.title}\n'
            'LEGEND=\\VAR{problem.blocks.legend}\n'
            'CONTEST=\\VAR{contest.title}\n'
            '\\end{document}\n',
        )
        problem = ProblemRenderContext(title='My Problem')
        problem.blocks = {'legend': 'LEG'}
        contest = ContestRenderContext(title='My Contest')
        out = render.render_problem_document(
            tmp_path,
            'tpl.rbx.tex',
            lang='en',
            languages=[],
            problem=problem,
            contest=contest,
        ).decode()
        assert 'TITLE=My Problem' in out
        assert 'LEGEND=LEG' in out
        assert 'CONTEST=My Contest' in out


class TestRenderContestDocument:
    def test_joins_problems_via_import_handles(self, tmp_path):
        _write(
            tmp_path / 'contest.rbx.tex',
            '\\documentclass{article}\n'
            '\\usepackage{import}\n'
            '\\begin{document}\n'
            '%- for problem in problems\n'
            '\\subimport{\\VAR{problem.import_dir}}{\\VAR{problem.import_file}}\n'
            '%- endfor\n'
            '\\end{document}\n',
        )
        contest = ContestRenderContext(title='C')
        problems = [
            ProblemRenderContext(
                title='A', import_dir='.problems/A/', import_file='statement'
            ),
            ProblemRenderContext(
                title='B', import_dir='.problems/B/', import_file='statement'
            ),
        ]
        out = render.render_contest_document(
            tmp_path,
            'contest.rbx.tex',
            lang='en',
            languages=[],
            contest=contest,
            problems=problems,
        ).decode()
        assert '\\subimport{.problems/A/}{statement}' in out
        assert '\\subimport{.problems/B/}{statement}' in out


class TestCompilePdf:
    def test_returns_pdf_bytes(self, tmp_path):
        # mock_pdflatex (autouse) makes build_pdf return an empty PDF.
        pdf = render.compile_pdf(
            tmp_path, b'\\documentclass{article}\\begin{document}x\\end{document}'
        )
        assert isinstance(pdf, bytes)
