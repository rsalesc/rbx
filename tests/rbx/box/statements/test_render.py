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


def test_explanation_blocks_are_removed_from_named_blocks(tmp_path):
    # An `explanation_<i>` block is split into `.explanations` and must NOT
    # remain in `.blocks` under its string key (it would otherwise be labeled
    # `explanation_0_0` on externalize -> a PDF never produced or uploaded).
    content = (
        b'%- block legend\nhi\n%- endblock\n'
        b'%- block explanation_0\nwhy sample zero\n%- endblock\n'
    )
    blocks = render.render_jinja_blocks(tmp_path, content, mode='latex')
    assert 0 in blocks.explanations
    assert 'why sample zero' in blocks.explanations[0]
    assert 'explanation_0' not in blocks.blocks
    assert 'legend' in blocks.blocks


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

    def test_var_shorthand_renders_through_a_real_template(self, tmp_path):
        # The shorthand (#630) has to survive the actual Jinja env, not just the
        # context dict: \VAR{N.max} == \VAR{vars.N.max}, and a group renders its
        # own resolved value through \VAR{g.N.max}.
        from rbx.box.schema import Package
        from rbx.box.statements.context import GroupView

        _write(
            tmp_path / 'tpl.rbx.tex',
            '\\documentclass{article}\n'
            '\\begin{document}\n'
            'SHORT=\\VAR{AB.max}\n'
            'LONG=\\VAR{vars.AB.max}\n'
            'NESTED=\\VAR{problem.AB.min}\n'
            'CONTEST=\\VAR{contest.date}\n'
            '%- for g in problem.groups\n'
            'GROUP=\\VAR{g.name}:\\VAR{g.AB.max}\n'
            '%- endfor\n'
            '\\end{document}\n',
        )
        pkg = Package.model_validate(
            {
                'name': 'test',
                'timeLimit': 1000,
                'memoryLimit': 256,
                'scoring': 'points',
                'vars': {'AB': {'min': 1, 'max': 200}},
                'testcases': [
                    {'name': 'sub1', 'score': 50, 'vars': {'AB': {'max': 10}}},
                    {'name': 'sub2', 'score': 50},
                ],
            }
        )
        problem = ProblemRenderContext(
            title='My Problem',
            vars=pkg.expanded_vars,
            groups={
                g.name: GroupView(g, pkg.expanded_vars_for_group(g.name))
                for g in pkg.testcases
            },
        )
        contest = ContestRenderContext(title='My Contest', vars={'date': '2026-06-21'})

        out = render.render_problem_document(
            tmp_path,
            'tpl.rbx.tex',
            lang='en',
            languages=[],
            problem=problem,
            contest=contest,
        ).decode()

        assert 'SHORT=200' in out
        assert 'LONG=200' in out
        assert 'NESTED=1' in out
        # A contest date is an ordinary contest var now, spelled like a field.
        assert 'CONTEST=2026-06-21' in out
        # The overriding group renders its own value; the other inherits.
        assert 'GROUP=sub1:10' in out
        assert 'GROUP=sub2:200' in out


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
