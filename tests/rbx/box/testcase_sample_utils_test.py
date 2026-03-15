from unittest import mock

from rbx.box.testcase_sample_utils import (
    SampleInteractionChunk,
    SampleTestcaseInteraction,
    _build_sample_interaction,
)
from rbx.box.testcase_schema import TestcaseEntry
from rbx.box.testcase_utils import (
    TestcaseInteraction,
    TestcaseInteractionEntry,
)


def _make_entry(group_entry_str='samples/0'):
    """Create a minimal GenerationTestcaseEntry mock with a group_entry."""
    entry = mock.Mock()
    entry.group_entry = TestcaseEntry.parse(group_entry_str)
    return entry


class TestBuildSampleInteraction:
    """Test _build_sample_interaction function."""

    def test_basic_interaction(self, tmp_path):
        """Test building sample interaction with alternating entries."""
        entry = _make_entry('samples/0')
        entries = [
            TestcaseInteractionEntry(data='Hello', pipe=0),
            TestcaseInteractionEntry(data='Hi', pipe=1),
        ]
        interaction = TestcaseInteraction(
            entries=entries, prefixes=('INTERACTOR:', 'SOLUTION:')
        )

        with mock.patch(
            'rbx.box.testcase_sample_utils.package.get_statement_chunks_folder'
        ) as mock_chunks:
            mock_chunks.return_value = tmp_path
            result = _build_sample_interaction(entry, interaction)

        assert isinstance(result, SampleTestcaseInteraction)
        assert result.entries == entries
        assert len(result.chunks) == 2

        # Verify chunks have correct data and pipes
        assert result.chunks[0].data == 'Hello'
        assert result.chunks[0].pipe == 0
        assert result.chunks[1].data == 'Hi'
        assert result.chunks[1].pipe == 1

        # Verify chunk files were written
        for chunk in result.chunks:
            assert isinstance(chunk, SampleInteractionChunk)
            assert chunk.path.is_file()
            assert chunk.path.read_text() == chunk.data

    def test_consecutive_entries_are_merged(self, tmp_path):
        """Test that consecutive entries with same pipe are merged into one chunk."""
        entry = _make_entry('samples/1')
        entries = [
            TestcaseInteractionEntry(data='line1', pipe=0),
            TestcaseInteractionEntry(data='line2', pipe=0),
            TestcaseInteractionEntry(data='response', pipe=1),
        ]
        interaction = TestcaseInteraction(
            entries=entries, prefixes=('INTERACTOR:', 'SOLUTION:')
        )

        with mock.patch(
            'rbx.box.testcase_sample_utils.package.get_statement_chunks_folder'
        ) as mock_chunks:
            mock_chunks.return_value = tmp_path
            result = _build_sample_interaction(entry, interaction)

        # Two merged chunks: pipe=0 merged, pipe=1 separate
        assert len(result.chunks) == 2
        assert result.chunks[0].data == 'line1\nline2'
        assert result.chunks[0].pipe == 0
        assert result.chunks[1].data == 'response'
        assert result.chunks[1].pipe == 1

        # Original entries are preserved unmerged
        assert len(result.entries) == 3

    def test_empty_entries(self, tmp_path):
        """Test building interaction with no entries."""
        entry = _make_entry('samples/0')
        interaction = TestcaseInteraction(
            entries=[], prefixes=('INTERACTOR:', 'SOLUTION:')
        )

        with mock.patch(
            'rbx.box.testcase_sample_utils.package.get_statement_chunks_folder'
        ) as mock_chunks:
            mock_chunks.return_value = tmp_path
            result = _build_sample_interaction(entry, interaction)

        assert result.entries == []
        assert result.chunks == []

    def test_chunk_file_paths(self, tmp_path):
        """Test that chunk files are placed in the correct directory structure."""
        entry = _make_entry('samples/2')
        entries = [
            TestcaseInteractionEntry(data='a', pipe=0),
            TestcaseInteractionEntry(data='b', pipe=1),
            TestcaseInteractionEntry(data='c', pipe=0),
        ]
        interaction = TestcaseInteraction(entries=entries, prefixes=('I:', 'S:'))

        with mock.patch(
            'rbx.box.testcase_sample_utils.package.get_statement_chunks_folder'
        ) as mock_chunks:
            mock_chunks.return_value = tmp_path
            result = _build_sample_interaction(entry, interaction)

        # Chunks should be in tmp_path / 'samples/2' / '000.txt', '001.txt', '002.txt'
        expected_dir = tmp_path / 'samples/2'
        assert expected_dir.is_dir()
        assert (expected_dir / '000.txt').read_text() == 'a'
        assert (expected_dir / '001.txt').read_text() == 'b'
        assert (expected_dir / '002.txt').read_text() == 'c'

        # Paths in chunks should be resolved (absolute)
        for chunk in result.chunks:
            assert chunk.path.is_absolute()

    def test_chunk_paths_are_resolved(self, tmp_path):
        """Test that chunk paths are absolute resolved paths."""
        entry = _make_entry('samples/0')
        entries = [TestcaseInteractionEntry(data='data', pipe=0)]
        interaction = TestcaseInteraction(entries=entries, prefixes=('I:', 'S:'))

        with mock.patch(
            'rbx.box.testcase_sample_utils.package.get_statement_chunks_folder'
        ) as mock_chunks:
            mock_chunks.return_value = tmp_path
            result = _build_sample_interaction(entry, interaction)

        assert result.chunks[0].path == (tmp_path / 'samples/0' / '000.txt').resolve()
