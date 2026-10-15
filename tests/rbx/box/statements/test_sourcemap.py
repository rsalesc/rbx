import pathlib

import pytest
import typer

from rbx.box.statements import render, sourcemap
from rbx.box.statements.context import ContestRenderContext, ProblemRenderContext
from rbx.box.statements.sourcemap import Origins, SourcePos


def _write(path: pathlib.Path, content: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _real(path: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(path).resolve()


STATEMENT = (
    '%- block legend\n'  # 1
    'Given $A$ and $B$.\n'  # 2
    '\n'  # 3
    'Print \\VAR{vars.what} of them.\n'  # 4
    '%- endblock\n'  # 5
    '%- block input\n'  # 6
    '%- for i in range(2)\n'  # 7
    'Line \\VAR{i}.\n'  # 8
    '%- endfor\n'  # 9
    '%- endblock\n'  # 10
    '%- block notes\n'  # 11
    '   \n'  # 12
    '%- endblock\n'  # 13
)

TEMPLATE = (
    '\\documentclass{article}\n'  # 1
    '\\begin{document}\n'  # 2
    '\\VAR{problem.blocks.legend}\n'  # 3
    '\\section{Input}\n'  # 4
    '\\VAR{problem.blocks.input}\n'  # 5
    '%- if problem.blocks.notes | trim\n'  # 6
    'NOTES\n'  # 7
    '%- endif\n'  # 8
    '\\end{document}\n'  # 9
)


@pytest.fixture
def staged(tmp_path):
    """A source tree (problem dir + chrome dir) and the overlay staged from it,
    the way `rbx st b` stages a standalone build."""
    problem_dir = tmp_path / 'problem'
    chrome_dir = tmp_path / 'chrome'
    overlay = tmp_path / 'build' / 'overlay'
    statement = _write(problem_dir / 'statement.rbx.tex', STATEMENT)
    template = _write(chrome_dir / 'template.rbx.tex', TEMPLATE)
    _write(overlay / 'statement.rbx.tex', STATEMENT)
    _write(overlay / 'template.rbx.tex', TEMPLATE)

    origins = Origins()
    origins.mount(overlay, problem_dir)
    origins.mount(overlay, chrome_dir)
    origins.source(statement)
    return overlay, origins, _real(statement), _real(template)


def _render(overlay: pathlib.Path) -> str:
    problem = ProblemRenderContext(title='P', vars={'what': 'the sum'})
    contest = ContestRenderContext(title='C')
    blocks = render.extract_blocks(
        overlay,
        STATEMENT.encode(),
        lang='en',
        languages=[],
        problem=problem,
        contest=contest,
    )
    problem.blocks = blocks.blocks
    return render.render_problem_document(
        overlay,
        'template.rbx.tex',
        lang='en',
        languages=[],
        problem=problem,
        contest=contest,
    ).decode()


def _line_of(text: str, needle: str) -> int:
    for number, line in enumerate(text.split('\n'), start=1):
        if needle in line:
            return number
    raise AssertionError(f'{needle!r} not in output')


class TestTracking:
    def test_output_is_identical_once_stripped(self, staged):
        overlay, origins, _, _ = staged
        plain = _render(overlay)
        with sourcemap.tracking(origins) as tracker:
            tagged = _render(overlay)
            assert sourcemap.TAG_OPEN in tagged
            emitted = tracker.emit(overlay / 'statement.tex', tagged)
        assert emitted == plain
        assert sourcemap.strip(tagged) == plain

    def test_maps_spliced_block_lines_back_to_the_statement(self, staged):
        overlay, origins, statement, template = staged
        with sourcemap.tracking(origins) as tracker:
            tex = tracker.emit(overlay / 'statement.tex', _render(overlay))

        def at(needle: str):
            return tracker.locate(overlay / 'statement.tex', _line_of(tex, needle))

        assert at('Given $A$') == SourcePos(statement, 2)
        assert at('Print the sum') == SourcePos(statement, 4)
        # Both iterations of the loop come from the one source line.
        assert at('Line 0.') == SourcePos(statement, 8)
        assert at('Line 1.') == SourcePos(statement, 8)
        assert at('\\section{Input}') == SourcePos(template, 4)
        assert at('\\end{document}') == SourcePos(template, 9)

    def test_blank_block_stays_falsy(self, staged):
        overlay, origins, _, _ = staged
        with sourcemap.tracking(origins):
            tex = sourcemap.strip(_render(overlay))
        assert 'NOTES' not in tex

    def test_relative_paths_name_the_same_file(self, staged, monkeypatch):
        overlay, origins, _, template = staged
        with sourcemap.tracking(origins) as tracker:
            tex = tracker.emit(overlay / 'statement.tex', _render(overlay))
        monkeypatch.chdir(overlay)
        line = _line_of(tex, '\\section{Input}')
        assert tracker.locate('./statement.tex', line) == SourcePos(template, 4)

    def test_tags_survive_filters(self, tmp_path):
        source = _write(
            tmp_path / 'src' / 'doc.tex', 'a\n%- filter upper\nb\n%- endfilter\n'
        )
        overlay = tmp_path / 'overlay'
        _write(overlay / 'doc.tex', source.read_text())
        origins = Origins()
        origins.mount(overlay, source.parent)
        with sourcemap.tracking(origins) as tracker:
            out = render.render_jinja(overlay, b'%- extends "doc.tex"').decode()
            tex = tracker.emit(overlay / 'statement.tex', out)
        assert tex == 'a\nB\n'
        assert tracker.locate(overlay / 'statement.tex', 2) == SourcePos(
            _real(source), 3
        )

    def test_nothing_is_tagged_outside_tracking(self, staged):
        overlay, _, _, _ = staged
        assert sourcemap.TAG_OPEN not in _render(overlay)

    def test_emit_without_tracking_only_strips(self, tmp_path):
        tagged = f'{sourcemap.TAG_OPEN}0:1{sourcemap.TAG_CLOSE}x'
        assert sourcemap.emit(tmp_path / 'f.tex', tagged) == 'x'


class TestLocate:
    def test_copied_file_maps_line_for_line(self, staged):
        overlay, origins, _, template = staged
        tracker = sourcemap.SourceTracker(origins)
        assert tracker.locate(overlay / 'template.rbx.tex', 7) == SourcePos(template, 7)

    def test_unknown_file_is_unlocated(self, staged, tmp_path):
        _, origins, _, _ = staged
        tracker = sourcemap.SourceTracker(origins)
        assert tracker.locate(tmp_path / 'texmf' / 'article.cls', 3) is None

    def test_line_past_the_end_clamps_to_the_last(self, tmp_path):
        tracker = sourcemap.SourceTracker()
        tracker.intern(_real(tmp_path))  # id 0
        tracker.emit(
            tmp_path / 'out.tex', f'{sourcemap.TAG_OPEN}0:5{sourcemap.TAG_CLOSE}x'
        )
        assert tracker.locate(tmp_path / 'out.tex', 40) == SourcePos(_real(tmp_path), 5)


class TestOrigins:
    def test_deeper_mount_wins(self, tmp_path):
        chrome = _write(tmp_path / 'chrome' / 'x.tex', 'chrome')
        problem = _write(tmp_path / 'a' / 'x.tex', 'problem')
        overlay = tmp_path / 'overlay'
        origins = Origins()
        origins.mount(overlay, chrome.parent)
        origins.mount(overlay / '.problems' / 'A', problem.parent)
        assert origins.resolve(overlay / '.problems' / 'A' / 'x.tex') == _real(problem)
        assert origins.resolve(overlay / 'x.tex') == _real(chrome)

    def test_alias(self, tmp_path):
        source = _write(tmp_path / 'elsewhere' / 't.tex', 't')
        origins = Origins()
        origins.alias(tmp_path / 'overlay' / 't.tex', source)
        assert origins.resolve(tmp_path / 'overlay' / 't.tex') == _real(source)

    def test_scratch_file_matches_by_content(self, tmp_path):
        source = _write(tmp_path / 'src' / 'statement.rbx.tex', 'hello')
        scratch = _write(tmp_path / 'overlay' / '__input__.tex', 'hello')
        origins = Origins()
        origins.source(source)
        origins.mount(tmp_path / 'overlay', tmp_path / 'src')
        assert origins.resolve(scratch) == _real(source)
        scratch.write_text('%- extends "x"')
        assert origins.resolve(scratch) is None


class TestTemplateErrors:
    def test_undefined_variable(self, staged):
        overlay, origins, statement, _ = staged
        broken = STATEMENT.replace('vars.what', 'vars.missing')
        _write(overlay / 'statement.rbx.tex', broken)
        statement.write_text(broken)
        origins = Origins()
        origins.source(statement)
        with sourcemap.tracking(origins) as tracker:
            with pytest.raises(typer.Abort) as info:
                render.extract_blocks(
                    overlay,
                    broken.encode(),
                    lang='en',
                    languages=[],
                    problem=ProblemRenderContext(title='P'),
                    contest=ContestRenderContext(title='C'),
                )
        assert tracker.locate_template_error(info.value) == SourcePos(statement, 4)

    def test_undefined_variable_in_template(self, staged):
        overlay, origins, _, template = staged
        _write(overlay / 'template.rbx.tex', TEMPLATE.replace('Input', '\\VAR{nope.x}'))
        with sourcemap.tracking(origins) as tracker:
            with pytest.raises(typer.Abort) as info:
                _render(overlay)
        assert tracker.locate_template_error(info.value) == SourcePos(template, 4)

    def test_syntax_error(self, staged):
        overlay, origins, statement, _ = staged
        broken = STATEMENT.replace('%- endfor\n', '')
        statement.write_text(broken)
        origins = Origins()
        origins.source(statement)
        with sourcemap.tracking(origins) as tracker:
            with pytest.raises(Exception) as info:
                render.extract_blocks(
                    overlay,
                    broken.encode(),
                    lang='en',
                    languages=[],
                    problem=ProblemRenderContext(title='P'),
                    contest=ContestRenderContext(title='C'),
                )
        pos = tracker.locate_template_error(info.value)
        assert pos is not None and pos.path == statement


class TestFindExcerpt:
    TEX = (
        '\\begin{document}\n'  # 1
        '\\inputdesc{\\badcmd{} The input is two integers.\n'  # 2
        'More input.}\n'  # 3
        '\\inputdesc{\\badcmd{} Another use.}\n'  # 4
        '\\end{document}\n'  # 5
    )

    def _tracker(self, tmp_path):
        tracker = sourcemap.SourceTracker()
        tracker.emit(tmp_path / 'statement.tex', self.TEX)
        return tracker

    def test_finds_the_line_holding_the_argument(self, tmp_path):
        tracker = self._tracker(tmp_path)
        found = tracker.find_excerpt(
            tmp_path / 'statement.tex', 5, '\\badcmd ', '{} The input is two integers.'
        )
        assert found == 2

    def test_nearest_above_the_reported_line_wins(self, tmp_path):
        tracker = self._tracker(tmp_path)
        assert tracker.find_excerpt(tmp_path / 'statement.tex', 5, '\\badcmd ', '') == 4
        assert tracker.find_excerpt(tmp_path / 'statement.tex', 3, '\\badcmd ', '') == 2

    def test_falls_back_to_the_text_before_the_stop(self, tmp_path):
        # What follows ran onto the next source line, so only the head matches.
        tracker = self._tracker(tmp_path)
        found = tracker.find_excerpt(
            tmp_path / 'statement.tex', 5, 'two integers. ', 'More input.'
        )
        assert found == 2

    def test_nothing_found(self, tmp_path):
        tracker = self._tracker(tmp_path)
        assert tracker.find_excerpt(tmp_path / 'statement.tex', 5, '\\nope', '') is None
        assert tracker.find_excerpt(tmp_path / 'other.tex', 5, '\\badcmd', '') is None


class TestNeverChangesWhatIsWritten:
    def test_blocks_yaml_round_trips_under_tracking(self, tmp_path):
        """The scalar style must be chosen for the tag-free text: `- x` and
        `123` stay strings and indentation survives."""
        import yaml

        from rbx.box.statements import engine

        source = (
            '\\BLOCK{block a}- dash inline\\BLOCK{endblock}\n'
            '\\BLOCK{block b}123\\BLOCK{endblock}\n'
            '\\BLOCK{block c}{\\bf x} y\\BLOCK{endblock}\n'
            '%- block d\n'
            '  \\begin{itemize}\n'
            '    \\item a\n'
            '  \\end{itemize}\n'
            '%- endblock\n'
        )
        expected = render.render_jinja_blocks(tmp_path, source.encode())
        with sourcemap.tracking():
            tagged = render.render_jinja_blocks(tmp_path, source.encode())
            assert sourcemap.TAG_OPEN in tagged.blocks['d']
            engine.write_blocks(tmp_path, 'blocks.yml', tagged)

        loaded = yaml.safe_load((tmp_path / 'blocks.yml').read_text())
        assert loaded['blocks'] == expected.blocks
        assert loaded['blocks']['b'] == '123'

    def test_markdown_is_never_tagged(self, tmp_path):
        source = _write(tmp_path / 'src' / 'explanation.md', '# Why\n\n- item\n')
        overlay = tmp_path / 'overlay'
        overlay.mkdir()
        origins = Origins()
        origins.source(source)
        with sourcemap.tracking(origins):
            out = render.render_jinja(overlay, source.read_bytes()).decode()
            _write(overlay / 'doc.md', '# Title\n')
            origins.mount(overlay, tmp_path / 'nothing')
            doc = render.render_jinja(overlay, b'%- extends "doc.md"').decode()
        # Jinja drops the final newline either way; nothing else may change.
        assert out == '# Why\n\n- item'
        assert doc == '# Title'


def test_find_excerpt_long_truncated_argument_spanning_lines(tmp_path):
    """The shape TeX prints for an error at the end of the default preset's
    notes: a truncated argument running over several lines of the emitted
    file, followed by a `\\par` TeX inserted itself (#909 manual test)."""
    tex = (
        '\\begin{problem}{Sum}\n'  # 1
        '\\vspace{0.1cm}\n'  # 2
        '\\subsection*{\\strExamples}\n'  # 3
        '\\example{.samples/000/in}{.samples/000/out}\n'  # 4
        '\\explanation{\\subimport{.samples/000/}{explanation}}\n'  # 5
        '\\example{.samples/001/in}{.samples/001/out}\n'  # 6
        '\\subsection*{\\strNotes}\n'  # 7
        '\t\tHahaha \\badcmd\n'  # 8
        '\n'  # 9
        '}\\end{document}\n'  # 10
    )
    tracker = sourcemap.SourceTracker()
    tracker.emit(tmp_path / 'statement.tex', tex)
    before = (
        '...0.1cm} \\subsection *{\\strExamples } \\example {.samples/000/in} '
        '{.samples/000/out} \\explanation {\\subimport {.samples/000/}{explanation}} '
        '\\example {.samples/001/in} {.samples/001/out} \\subsection *{\\strNotes } '
        'Hahaha \\badcmd '
    )
    assert tracker.find_excerpt(tmp_path / 'statement.tex', 10, before, '\\par ') == 8
