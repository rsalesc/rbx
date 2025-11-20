import pathlib
from unittest import mock

import pytest
import typer

from rbx.box.generation_schema import GenerationInput, GeneratorScriptEntry
from rbx.box.generator_script_handlers import (
    BoxGeneratorScriptHandler,
    GeneratorScriptHandlerParams,
    RbxGeneratorScriptHandler,
    get_generator_script_handler,
)
from rbx.box.schema import GeneratorCall, GeneratorScript, Testcase
from rbx.box.stressing.generator_script_parser import ScriptGeneratedInput


class TestGetGeneratorScriptHandler:
    """Test suite for the get_generator_script_handler factory function."""

    def test_get_rbx_handler(self):
        """Test creating an RBX format handler."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='rbx')
        script = 'gen1 arg1\ngen2 arg2'

        handler = get_generator_script_handler(
            script, GeneratorScriptHandlerParams(script_entry)
        )

        assert isinstance(handler, RbxGeneratorScriptHandler)
        assert handler.script == script
        assert handler.script_entry == script_entry

    def test_get_box_handler(self):
        """Test creating a BOX format handler."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='box')
        script = '1 ; gen1.exe arg1\n2 ; gen2.exe arg2'

        handler = get_generator_script_handler(
            script, GeneratorScriptHandlerParams(script_entry)
        )

        assert isinstance(handler, BoxGeneratorScriptHandler)
        assert handler.script == script
        assert handler.script_entry == script_entry

    def test_invalid_format_raises_exit(self):
        """Test that invalid format raises typer.Exit."""
        # Use a mock to bypass pydantic validation for invalid format
        mock_script_entry = mock.Mock()
        mock_script_entry.format = 'invalid'
        script = 'some content'

        with pytest.raises(typer.Exit) as exc_info:
            get_generator_script_handler(
                script, GeneratorScriptHandlerParams(mock_script_entry)
            )

        assert exc_info.value.exit_code == 1


class TestRbxGeneratorScriptHandler:
    """Test suite for RbxGeneratorScriptHandler."""

    def test_parse_simple_script(self):
        """Test parsing a simple RBX format script."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='rbx')
        script = """gen1 arg1 arg2
gen2 --flag value
gen3"""

        handler = RbxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )
        parsed = list(handler.parse())

        assert len(parsed) == 3
        assert parsed[0] == ScriptGeneratedInput(
            generator_call=GeneratorCall(name='gen1', args='arg1 arg2'),
            generator_script=GeneratorScriptEntry(
                path=pathlib.Path('script.txt'), line=1
            ),
            group=None,
        )
        assert parsed[1] == ScriptGeneratedInput(
            generator_call=GeneratorCall(name='gen2', args='--flag value'),
            generator_script=GeneratorScriptEntry(
                path=pathlib.Path('script.txt'), line=2
            ),
            group=None,
        )
        assert parsed[2] == ScriptGeneratedInput(
            generator_call=GeneratorCall(name='gen3', args=None),
            generator_script=GeneratorScriptEntry(
                path=pathlib.Path('script.txt'), line=3
            ),
            group=None,
        )

    def test_parse_with_comments_and_empty_lines(self):
        """Test parsing script with comments and empty lines."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='rbx')
        script = """// This is a comment
gen1 arg1

// Another comment
gen2 arg2
"""

        handler = RbxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )
        parsed = list(handler.parse())

        assert len(parsed) == 2
        assert parsed[0] == ScriptGeneratedInput(
            generator_call=GeneratorCall(name='gen1', args='arg1'),
            generator_script=GeneratorScriptEntry(
                path=pathlib.Path('script.txt'), line=2
            ),
            group=None,
        )
        assert parsed[1] == ScriptGeneratedInput(
            generator_call=GeneratorCall(name='gen2', args='arg2'),
            generator_script=GeneratorScriptEntry(
                path=pathlib.Path('script.txt'), line=5
            ),
            group=None,
        )

    def test_parse_with_quoted_arguments(self):
        """Test parsing script with quoted arguments."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='rbx')
        script = 'gen1 "quoted arg" \'single quoted\''

        handler = RbxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )
        parsed = list(handler.parse())

        assert len(parsed) == 1
        # Arguments are parsed as-is without quote normalization
        assert parsed[0] == ScriptGeneratedInput(
            generator_call=GeneratorCall(
                name='gen1', args='"quoted arg" \'single quoted\''
            ),
            generator_script=GeneratorScriptEntry(
                path=pathlib.Path('script.txt'), line=1
            ),
            group=None,
        )

    def test_append_single_call(self):
        """Test appending a single generator call."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='rbx')
        script = 'existing_gen arg'
        handler = RbxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )

        call = GeneratorCall(name='new_gen', args='new_arg')
        handler.append([call])

        assert handler.script == 'existing_gen arg\nnew_gen new_arg'

    def test_append_multiple_calls_with_comment(self):
        """Test appending multiple calls with a comment."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='rbx')
        script = 'existing_gen'
        handler = RbxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )

        calls = [
            GeneratorCall(name='gen1', args='arg1'),
            GeneratorCall(name='gen2', args=None),
        ]
        handler.append(calls, comment='Added by stress test')

        expected = 'existing_gen\n# Added by stress test\ngen1 arg1\ngen2 '
        assert handler.script == expected

    def test_append_with_root_normalization(self):
        """Test appending calls with path normalization."""
        script_entry = GeneratorScript(
            path=pathlib.Path('script.txt'),
            format='rbx',
            root=pathlib.Path('generators'),
        )
        script = ''
        handler = RbxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )

        call = GeneratorCall(name='generators/subdir/gen', args='arg')
        handler.append([call])

        assert handler.script == '\nsubdir/gen arg'

    def test_parse_with_group_filter(self):
        """Test parsing script with group filter applied."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='rbx')
        script = """// Ungrouped generator
gen1 arg1

@testgroup group-a {
    gen2 arg2
    gen3 arg3
}

@testgroup group-b {
    gen4 arg4
}

// Another ungrouped generator
gen5 arg5
"""

        # Parse with group filter for 'group-a'
        handler = RbxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry, group='group-a')
        )
        parsed = list(handler.parse())

        # Should include ungrouped generators (gen1, gen5) and group-a generators (gen2, gen3)
        # Should exclude group-b generators (gen4)
        assert len(parsed) == 4

        # Verify the generator names
        generator_names = [
            p.generator_call.name for p in parsed if p.generator_call is not None
        ]
        assert generator_names == ['gen1', 'gen2', 'gen3', 'gen5']

        # Verify groups (cast to ScriptGeneratedInput for type safety)
        assert isinstance(parsed[0], ScriptGeneratedInput)
        assert isinstance(parsed[1], ScriptGeneratedInput)
        assert isinstance(parsed[2], ScriptGeneratedInput)
        assert isinstance(parsed[3], ScriptGeneratedInput)
        assert parsed[0].group is None  # gen1 - ungrouped
        assert parsed[1].group == 'group-a'  # gen2
        assert parsed[2].group == 'group-a'  # gen3
        assert parsed[3].group is None  # gen5 - ungrouped

    def test_parse_with_different_group_filter(self):
        """Test parsing with a different group filter."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='rbx')
        script = """gen1 arg1

@testgroup group-a {
    gen2 arg2
}

@testgroup group-b {
    gen3 arg3
}
"""

        # Parse with group filter for 'group-b'
        handler = RbxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry, group='group-b')
        )
        parsed = list(handler.parse())

        # Should include ungrouped (gen1) and group-b (gen3)
        # Should exclude group-a (gen2)
        assert len(parsed) == 2

        generator_names = [
            p.generator_call.name for p in parsed if p.generator_call is not None
        ]
        assert generator_names == ['gen1', 'gen3']

        # Verify groups (cast to ScriptGeneratedInput for type safety)
        assert isinstance(parsed[0], ScriptGeneratedInput)
        assert isinstance(parsed[1], ScriptGeneratedInput)
        assert parsed[0].group is None  # gen1 - ungrouped
        assert parsed[1].group == 'group-b'  # gen3

    def test_parse_with_group_filter_no_matches(self):
        """Test parsing with group filter that has no matches (only ungrouped remain)."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='rbx')
        script = """gen1 arg1

@testgroup group-a {
    gen2 arg2
}
"""

        # Parse with group filter for 'non-existent-group'
        handler = RbxGeneratorScriptHandler(
            script,
            GeneratorScriptHandlerParams(script_entry, group='non-existent-group'),
        )
        parsed = list(handler.parse())

        # Should only include ungrouped generators
        assert len(parsed) == 1
        assert parsed[0].generator_call is not None
        assert parsed[0].generator_call.name == 'gen1'
        # Verify group (cast to ScriptGeneratedInput for type safety)
        assert isinstance(parsed[0], ScriptGeneratedInput)
        assert parsed[0].group is None


class TestBoxGeneratorScriptHandler:
    """Test suite for BoxGeneratorScriptHandler."""

    def test_parse_simple_script(self):
        """Test parsing a simple BOX format script."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='box')
        script = """1 ; gen1.exe arg1 arg2
1 ; gen2.exe --flag value
2 ; gen3.exe"""

        handler = BoxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )
        parsed = list(handler.parse())

        assert len(parsed) == 3
        assert parsed[0] == GenerationInput(
            generator_call=GeneratorCall(name='gen1', args='arg1 arg2'),
            generator_script=GeneratorScriptEntry(
                path=pathlib.Path('script.txt'), line=1
            ),
        )
        assert parsed[1] == GenerationInput(
            generator_call=GeneratorCall(name='gen2', args='--flag value'),
            generator_script=GeneratorScriptEntry(
                path=pathlib.Path('script.txt'), line=2
            ),
        )
        assert parsed[2] == GenerationInput(
            generator_call=GeneratorCall(name='gen3', args=''),
            generator_script=GeneratorScriptEntry(
                path=pathlib.Path('script.txt'), line=3
            ),
        )

    def test_parse_with_comments_and_empty_lines(self):
        """Test parsing BOX script with comments and empty lines."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='box')
        script = """# This is a comment
1 ; gen1.exe arg1

# Another comment
2 ; gen2.exe arg2
"""

        handler = BoxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )
        parsed = list(handler.parse())

        assert len(parsed) == 2
        assert parsed[0] == GenerationInput(
            generator_call=GeneratorCall(name='gen1', args='arg1'),
            generator_script=GeneratorScriptEntry(
                path=pathlib.Path('script.txt'), line=2
            ),
        )
        assert parsed[1] == GenerationInput(
            generator_call=GeneratorCall(name='gen2', args='arg2'),
            generator_script=GeneratorScriptEntry(
                path=pathlib.Path('script.txt'), line=5
            ),
        )

    def test_parse_copy_command(self):
        """Test parsing special copy command."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='box')
        script = '1 ; copy file1 file2'

        handler = BoxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )
        parsed = list(handler.parse())

        assert len(parsed) == 1
        assert parsed[0] == GenerationInput(
            copied_from=Testcase(inputPath=pathlib.Path('file1 file2')),
            generator_script=GeneratorScriptEntry(
                path=pathlib.Path('script.txt'), line=1
            ),
        )

    def test_parse_invalid_format_raises_exit(self):
        """Test parsing invalid BOX format raises typer.Exit."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='box')
        # Missing semicolon
        script = '1 gen1.exe arg1'

        handler = BoxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )

        with pytest.raises(typer.Exit) as exc_info:
            list(handler.parse())

        assert exc_info.value.exit_code == 1

    def test_parse_invalid_group_number_raises_exit(self):
        """Test parsing invalid group number raises typer.Exit."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='box')
        # Non-integer group number
        script = 'abc ; gen1.exe arg1'

        handler = BoxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )

        with pytest.raises(typer.Exit) as exc_info:
            list(handler.parse())

        assert exc_info.value.exit_code == 1

    def test_append_single_call(self):
        """Test appending a single generator call to BOX script."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='box')
        script = '1 ; existing.exe arg'
        handler = BoxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )

        call = GeneratorCall(name='new_gen', args='new_arg')
        handler.append([call])

        # Should increment group number
        assert handler.script == '1 ; existing.exe arg\n2 ; new_gen.exe new_arg'

    def test_append_multiple_calls_same_group(self):
        """Test appending multiple calls with same group number."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='box')
        script = '3 ; existing.exe'
        handler = BoxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )

        calls = [
            GeneratorCall(name='gen1', args='arg1'),
            GeneratorCall(name='gen2', args=None),
        ]
        handler.append(calls, comment='Batch addition')

        expected = (
            '3 ; existing.exe\n# Batch addition\n4 ; gen1.exe arg1\n4 ; gen2.exe '
        )
        assert handler.script == expected

    def test_append_with_root_normalization(self):
        """Test appending calls with path normalization for BOX format."""
        script_entry = GeneratorScript(
            path=pathlib.Path('script.txt'),
            format='box',
            root=pathlib.Path('generators'),
        )
        script = ''
        handler = BoxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )

        call = GeneratorCall(name='generators/subdir/gen', args='arg')
        handler.append([call])

        assert handler.script == '\n1 ; subdir/gen.exe arg'

    def test_normalize_call_name_invalid_path_raises_exit(self):
        """Test normalize_call_name with invalid path raises typer.Exit."""
        script_entry = GeneratorScript(
            path=pathlib.Path('script.txt'),
            format='box',
            root=pathlib.Path('generators'),
        )
        handler = BoxGeneratorScriptHandler(
            '', GeneratorScriptHandlerParams(script_entry)
        )

        with pytest.raises(typer.Exit) as exc_info:
            handler.normalize_call_name('other_dir/gen')

        assert exc_info.value.exit_code == 1

    def test_append_empty_script_starts_at_group_1(self):
        """Test appending to empty script starts at group 1."""
        script_entry = GeneratorScript(path=pathlib.Path('script.txt'), format='box')
        script = ''
        handler = BoxGeneratorScriptHandler(
            script, GeneratorScriptHandlerParams(script_entry)
        )

        call = GeneratorCall(name='gen', args='arg')
        handler.append([call])

        assert handler.script == '\n1 ; gen.exe arg'
