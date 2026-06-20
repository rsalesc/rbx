import pathlib

from rbx.box.statements import sample_staging
from rbx.box.statements.sample_staging import SampleSource


def _write(path: pathlib.Path, content: str = 'x') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestStageSamples:
    def test_mirrors_io_and_sets_root_relative_paths_standalone(self, tmp_path):
        src = tmp_path / 'src'
        _write(src / '000.in', 'INPUT')
        _write(src / '000.out', 'OUTPUT')
        source = SampleSource(
            input_path=src / '000.in',
            output_path=src / '000.out',
            has_output=True,
        )

        root = tmp_path / 'overlay'
        root.mkdir()
        handles = sample_staging.stage_samples(
            problem_root=root, root_prefix='', sources=[source]
        )

        assert (root / '.samples' / '000' / 'in').read_text() == 'INPUT'
        assert (root / '.samples' / '000' / 'out').read_text() == 'OUTPUT'
        # Root-relative for verbatim I/O.
        assert handles[0].input == '.samples/000/in'
        assert handles[0].output == '.samples/000/out'

    def test_root_prefix_anchors_io_for_join(self, tmp_path):
        src = tmp_path / 'src'
        _write(src / '000.in', 'INPUT')
        source = SampleSource(
            input_path=src / '000.in', output_path=None, has_output=False
        )

        root = tmp_path / 'overlay' / '.problems' / 'A'
        root.mkdir(parents=True)
        handles = sample_staging.stage_samples(
            problem_root=root, root_prefix='.problems/A/', sources=[source]
        )
        assert handles[0].input == '.problems/A/.samples/000/in'
        assert handles[0].output is None

    def test_no_explanation_leaves_handle_blank(self, tmp_path):
        src = tmp_path / 'src'
        _write(src / '000.in')
        source = SampleSource(input_path=src / '000.in')

        root = tmp_path / 'overlay'
        root.mkdir()
        handles = sample_staging.stage_samples(
            problem_root=root, root_prefix='', sources=[source]
        )
        assert handles[0].explanation_file is None
        assert handles[0].dir is None


class TestExplanations:
    def test_inline_block_explanation_written_to_sample_folder(self, tmp_path):
        src = tmp_path / 'src'
        _write(src / '000.in')
        source = SampleSource(input_path=src / '000.in')

        root = tmp_path / 'overlay'
        root.mkdir()
        handles = sample_staging.stage_samples(
            problem_root=root,
            root_prefix='',
            sources=[source],
            explanation_blocks={0: 'WHY ZERO'},
        )
        explanation = root / '.samples' / '000' / 'explanation.tex'
        assert explanation.read_text() == 'WHY ZERO'
        # Base-relative \subimport handles.
        assert handles[0].dir == '.samples/000/'
        assert handles[0].explanation_file == 'explanation'

    def test_file_explanation_overlays_its_directory_for_figures(self, tmp_path):
        src = tmp_path / 'src'
        _write(src / '000.in')
        _write(src / '000.tex', 'see \\includegraphics{diagram}')
        _write(src / 'diagram.png', 'PNG')
        source = SampleSource(
            input_path=src / '000.in',
            explanation_path=src / '000.tex',
        )

        root = tmp_path / 'overlay'
        root.mkdir()
        handles = sample_staging.stage_samples(
            problem_root=root,
            root_prefix='',
            sources=[source],
            render_explanation_text=lambda content, mode: content,
        )
        folder = root / '.samples' / '000'
        # Explanation rendered into the hermetic sample folder.
        assert (
            folder / 'explanation.tex'
        ).read_text() == 'see \\includegraphics{diagram}'
        # The explanation's figure is overlaid alongside it so \includegraphics resolves.
        assert (folder / 'diagram.png').read_text() == 'PNG'
        assert handles[0].explanation_file == 'explanation'

    def test_staged_io_wins_over_explanation_dir_mirror(self, tmp_path):
        # The explanation's source dir happens to contain files named in/out;
        # the generated sample I/O must remain authoritative (regression).
        src = tmp_path / 'src'
        _write(src / '000.in', 'REAL_INPUT')
        _write(src / '000.out', 'REAL_OUTPUT')
        _write(src / '000.tex', 'explanation body')
        _write(src / 'in', 'BOGUS')
        _write(src / 'out', 'BOGUS')
        source = SampleSource(
            input_path=src / '000.in',
            output_path=src / '000.out',
            has_output=True,
            explanation_path=src / '000.tex',
        )

        root = tmp_path / 'overlay'
        root.mkdir()
        sample_staging.stage_samples(
            problem_root=root,
            root_prefix='',
            sources=[source],
            render_explanation_text=lambda content, mode: content,
        )
        folder = root / '.samples' / '000'
        assert (folder / 'in').read_text() == 'REAL_INPUT'
        assert (folder / 'out').read_text() == 'REAL_OUTPUT'

    def test_explanation_written_as_tex_even_in_markdown_mode(self, tmp_path):
        # Explanations are \subimport-ed by a LaTeX template regardless of the
        # statement format, so the staged file is always explanation.tex.
        src = tmp_path / 'src'
        _write(src / '000.in')
        source = SampleSource(input_path=src / '000.in')

        root = tmp_path / 'overlay'
        root.mkdir()
        handles = sample_staging.stage_samples(
            problem_root=root,
            root_prefix='',
            sources=[source],
            explanation_blocks={0: 'already latex'},
            mode='markdown',
        )
        assert (root / '.samples' / '000' / 'explanation.tex').is_file()
        assert handles[0].explanation_file == 'explanation'

    def test_extra_explanation_overrides_file_text_and_still_mirrors_dir(
        self, tmp_path
    ):
        # A separate-file explanation: the staged text comes from
        # `extra_explanations` (the engine's externalized copy), but the source
        # directory is STILL mirrored so the explanation's own figures resolve.
        src = tmp_path / 'src'
        _write(src / '000.in')
        _write(src / '000.tex', 'raw \\includegraphics{diagram}')
        _write(src / 'diagram.png', 'PNG')
        source = SampleSource(
            input_path=src / '000.in',
            explanation_path=src / '000.tex',
        )

        root = tmp_path / 'overlay'
        root.mkdir()
        handles = sample_staging.stage_samples(
            problem_root=root,
            root_prefix='',
            sources=[source],
            extra_explanations={0: 'labeled \\tikzsetnextfilename{0_0} text'},
        )

        explanation = root / '.samples' / '000' / 'explanation.tex'
        assert explanation.read_text() == 'labeled \\tikzsetnextfilename{0_0} text'
        # The source dir was still mirrored for the explanation's figures.
        assert (root / '.samples' / '000' / 'diagram.png').read_text() == 'PNG'
        assert handles[0].explanation_file == 'explanation'

    def test_inline_block_still_wins_over_extra_explanation(self, tmp_path):
        # An inline explanation_<i> block takes precedence over extra_explanations.
        src = tmp_path / 'src'
        _write(src / '000.in')
        source = SampleSource(input_path=src / '000.in')

        root = tmp_path / 'overlay'
        root.mkdir()
        sample_staging.stage_samples(
            problem_root=root,
            root_prefix='',
            sources=[source],
            explanation_blocks={0: 'INLINE'},
            extra_explanations={0: 'EXTRA'},
        )
        assert (root / '.samples' / '000' / 'explanation.tex').read_text() == 'INLINE'

    def test_inline_block_takes_precedence_over_file(self, tmp_path):
        src = tmp_path / 'src'
        _write(src / '000.in')
        _write(src / '000.tex', 'FROM FILE')
        source = SampleSource(
            input_path=src / '000.in', explanation_path=src / '000.tex'
        )

        root = tmp_path / 'overlay'
        root.mkdir()
        handles = sample_staging.stage_samples(
            problem_root=root,
            root_prefix='',
            sources=[source],
            explanation_blocks={0: 'FROM BLOCK'},
            render_explanation_text=lambda content, mode: content,
        )
        assert (
            root / '.samples' / '000' / 'explanation.tex'
        ).read_text() == 'FROM BLOCK'
        assert handles[0].explanation_file == 'explanation'


class TestInteractiveChunks:
    def test_chunks_staged_with_root_relative_paths(self, tmp_path):
        src = tmp_path / 'src'
        _write(src / '000.in')
        _write(src / 'chunk0.txt', 'reads')
        _write(src / 'chunk1.txt', 'writes')
        source = SampleSource(
            input_path=src / '000.in',
            interaction_chunks=[(src / 'chunk0.txt', 0), (src / 'chunk1.txt', 1)],
        )

        root = tmp_path / 'overlay'
        root.mkdir()
        handles = sample_staging.stage_samples(
            problem_root=root, root_prefix='', sources=[source]
        )
        chunks = handles[0].interaction.chunks
        assert chunks[0].path == '.samples/000/chunk_000.txt'
        assert chunks[0].pipe == 0
        assert chunks[1].path == '.samples/000/chunk_001.txt'
        assert chunks[1].pipe == 1
        assert (root / '.samples' / '000' / 'chunk_000.txt').read_text() == 'reads'
