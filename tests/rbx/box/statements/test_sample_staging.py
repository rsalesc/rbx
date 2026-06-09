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
