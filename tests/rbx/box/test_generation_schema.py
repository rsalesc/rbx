import pathlib
from unittest import mock

import pytest
import typer

from rbx.box.generation_schema import (
    GeneratorScriptEntry,
    get_parsed_entry,
)
from rbx.box.testcase_utils import TestcaseEntry


class TestGeneratorScriptEntry:
    """Test GeneratorScriptEntry functionality."""

    def test_parse_valid_spec(self):
        """Test parsing valid generator script specification."""
        entry = GeneratorScriptEntry.parse('gen_script.txt:10')
        assert entry.path == pathlib.Path('gen_script.txt')
        assert entry.line == 10

    def test_parse_with_nested_path(self):
        """Test parsing spec with nested path."""
        entry = GeneratorScriptEntry.parse('path/to/script.txt:25')
        assert entry.path == pathlib.Path('path/to/script.txt')
        assert entry.line == 25

    def test_parse_with_absolute_path(self):
        """Test parsing spec with absolute path."""
        entry = GeneratorScriptEntry.parse('/absolute/path/script.txt:5')
        assert entry.path == pathlib.Path('/absolute/path/script.txt')
        assert entry.line == 5

    def test_parse_raises_on_no_colon(self):
        """Test that parsing raises ValueError when spec has no colon."""
        with pytest.raises(ValueError, match='Invalid generator script spec'):
            GeneratorScriptEntry.parse('script.txt')

    def test_parse_raises_on_multiple_colons(self):
        """Test that parsing raises ValueError when spec has multiple colons."""
        with pytest.raises(ValueError, match='Invalid generator script spec'):
            GeneratorScriptEntry.parse('script:txt:10')

    def test_parse_raises_on_invalid_line_number(self):
        """Test that parsing raises ValueError when line is not a number."""
        with pytest.raises(ValueError):
            GeneratorScriptEntry.parse('script.txt:invalid')

    def test_str_method(self):
        """Test string representation."""
        entry = GeneratorScriptEntry(path=pathlib.Path('script.txt'), line=42)
        assert str(entry) == 'script.txt:42'

    def test_hash_method(self, tmp_path):
        """Test that entries can be hashed."""
        script_path = tmp_path / 'script.txt'
        script_path.write_text('test')

        entry1 = GeneratorScriptEntry(path=script_path, line=10)
        entry2 = GeneratorScriptEntry(path=script_path, line=10)

        # Should be hashable and have same hash
        assert hash(entry1) == hash(entry2)

        # Should work in sets/dicts
        assert {entry1, entry2} == {entry1}

    def test_equality_same_path_and_line(self, tmp_path):
        """Test equality for entries with same path and line."""
        script_path = tmp_path / 'script.txt'
        script_path.write_text('test')

        entry1 = GeneratorScriptEntry(path=script_path, line=10)
        entry2 = GeneratorScriptEntry(path=script_path, line=10)

        assert entry1 == entry2

    def test_inequality_different_line(self, tmp_path):
        """Test inequality for entries with different line numbers."""
        script_path = tmp_path / 'script.txt'
        script_path.write_text('test')

        entry1 = GeneratorScriptEntry(path=script_path, line=10)
        entry2 = GeneratorScriptEntry(path=script_path, line=20)

        assert entry1 != entry2

    def test_inequality_different_type(self):
        """Test inequality with different types."""
        entry = GeneratorScriptEntry(path=pathlib.Path('script.txt'), line=10)

        assert entry != 'script.txt:10'
        assert entry != 42


class TestGetParsedEntry:
    """Test get_parsed_entry function."""

    def test_parses_generator_script_entry_with_colon(self):
        """Test that specs with one colon are parsed as GeneratorScriptEntry."""
        entry = get_parsed_entry('gen_script.txt:15')

        assert isinstance(entry, GeneratorScriptEntry)
        assert entry.path == pathlib.Path('gen_script.txt')
        assert entry.line == 15

    def test_parses_testcase_entry_with_slash(self):
        """Test that specs with one slash are parsed as TestcaseEntry."""
        entry = get_parsed_entry('main/5')

        assert isinstance(entry, TestcaseEntry)
        assert entry.group == 'main'
        assert entry.index == 5

    def test_parses_generator_script_with_nested_path(self):
        """Test parsing generator script spec with nested path."""
        entry = get_parsed_entry('path/to/gen.txt:42')

        assert isinstance(entry, GeneratorScriptEntry)
        assert entry.path == pathlib.Path('path/to/gen.txt')
        assert entry.line == 42

    def test_prefers_colon_over_slash_when_both_present(self):
        """Test that colon takes precedence when both colon and slash are present."""
        # This has both, but colon should take precedence
        entry = get_parsed_entry('path/gen.txt:10')

        assert isinstance(entry, GeneratorScriptEntry)
        assert entry.path == pathlib.Path('path/gen.txt')
        assert entry.line == 10

    def test_exits_on_invalid_spec_no_colon_or_slash(self):
        """Test that invalid spec without colon or slash exits."""
        with mock.patch('rbx.box.generation_schema.console.console.print'):
            with pytest.raises(typer.Exit) as exc_info:
                get_parsed_entry('invalid_spec')

            assert exc_info.value.exit_code == 1

    def test_exits_on_spec_with_multiple_colons(self):
        """Test that spec with multiple colons exits."""
        with mock.patch('rbx.box.generation_schema.console.console.print'):
            with pytest.raises(typer.Exit) as exc_info:
                get_parsed_entry('path:to:gen.txt:10')

            assert exc_info.value.exit_code == 1

    def test_exits_on_spec_with_multiple_slashes_no_colon(self):
        """Test that spec with multiple slashes and no colon exits."""
        with mock.patch('rbx.box.generation_schema.console.console.print'):
            with pytest.raises(typer.Exit) as exc_info:
                get_parsed_entry('path/to/gen/5')

            assert exc_info.value.exit_code == 1

    def test_exits_on_invalid_line_number(self):
        """Test that spec with invalid line number exits."""
        with mock.patch('rbx.box.generation_schema.console.console.print'):
            with pytest.raises(typer.Exit) as exc_info:
                get_parsed_entry('gen.txt:not_a_number')

            assert exc_info.value.exit_code == 1

    def test_exits_on_invalid_testcase_index(self):
        """Test that spec with invalid testcase index exits."""
        with mock.patch('rbx.box.generation_schema.console.console.print'):
            with pytest.raises(typer.Exit) as exc_info:
                get_parsed_entry('main/not_a_number')

            assert exc_info.value.exit_code == 1

    def test_prints_error_message_on_invalid_spec(self):
        """Test that error message is printed for invalid spec."""
        with mock.patch(
            'rbx.box.generation_schema.console.console.print'
        ) as mock_print:
            with pytest.raises(typer.Exit):
                get_parsed_entry('invalid_spec')

            # Check that an error was printed
            mock_print.assert_called_once()
            call_args = mock_print.call_args[0][0]
            assert 'Invalid testcase spec' in call_args
            assert 'invalid_spec' in call_args

    def test_parses_edge_case_line_zero(self):
        """Test parsing generator script with line 0."""
        entry = get_parsed_entry('gen.txt:0')

        assert isinstance(entry, GeneratorScriptEntry)
        assert entry.line == 0

    def test_parses_edge_case_index_zero(self):
        """Test parsing testcase entry with index 0."""
        entry = get_parsed_entry('samples/0')

        assert isinstance(entry, TestcaseEntry)
        assert entry.group == 'samples'
        assert entry.index == 0

    def test_parses_large_line_numbers(self):
        """Test parsing generator script with large line number."""
        entry = get_parsed_entry('gen.txt:999999')

        assert isinstance(entry, GeneratorScriptEntry)
        assert entry.line == 999999

    def test_parses_large_testcase_indices(self):
        """Test parsing testcase entry with large index."""
        entry = get_parsed_entry('main/999999')

        assert isinstance(entry, TestcaseEntry)
        assert entry.index == 999999

    def test_parses_testcase_with_hyphenated_group(self):
        """Test parsing testcase entry with hyphenated group name."""
        entry = get_parsed_entry('large-cases/10')

        assert isinstance(entry, TestcaseEntry)
        assert entry.group == 'large-cases'
        assert entry.index == 10

    def test_parses_testcase_with_underscored_group(self):
        """Test parsing testcase entry with underscored group name."""
        entry = get_parsed_entry('edge_cases/5')

        assert isinstance(entry, TestcaseEntry)
        assert entry.group == 'edge_cases'
        assert entry.index == 5
