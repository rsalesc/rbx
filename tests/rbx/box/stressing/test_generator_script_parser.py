import pathlib

from rbx.box.stressing.generator_script_parser import (
    ScriptGeneratedInput,
    parse_and_transform,
)


class TestParseAndTransformFunction:
    """Test suite for the parse_and_transform function behavior."""

    def test_parse_and_transform_returns_list_of_script_generated_inputs(self):
        """Test that parse_and_transform returns a list of ScriptGeneratedInput objects."""
        script = 'gens/generator --arg=value'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ScriptGeneratedInput)

    def test_parse_and_transform_empty_script(self):
        """Test transforming empty script returns empty list."""
        script = ''
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert result == []

    def test_parse_and_transform_only_comments(self):
        """Test that comments are filtered out and don't produce results."""
        script = """
// Comment 1
// Comment 2
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert result == []

    def test_parse_and_transform_only_newlines(self):
        """Test that newlines alone don't produce results."""
        script = '\n\n\n'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert result == []

    def test_parse_and_transform_simple_generator_call(self):
        """Test transforming a simple generator call."""
        script = 'gens/generator'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 1
        assert result[0].generator_call is not None
        assert result[0].generator_call.name == 'gens/generator'
        assert result[0].generator_call.args is None
        assert result[0].copied_from is None
        assert result[0].group is None

    def test_parse_and_transform_generator_call_with_args(self):
        """Test transforming generator call with arguments."""
        script = 'gens/generator --MAX_N=100 --MIN_N=30 extra'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 1
        gen_call = result[0].generator_call
        assert gen_call is not None
        assert gen_call.name == 'gens/generator'
        assert gen_call.args == '--MAX_N=100 --MIN_N=30 extra'

    def test_parse_and_transform_generator_call_strips_args_whitespace(self):
        """Test that argument whitespace is stripped."""
        script = 'gens/generator    --arg=value   '
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        gen_call = result[0].generator_call
        assert gen_call is not None
        assert gen_call.args == '--arg=value'

    def test_parse_and_transform_multiple_generator_calls(self):
        """Test transforming multiple generator calls."""
        script = """
gens/gen1 --A=1
gens/gen2 --B=2
gens/gen3 --C=3
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 3
        gen_call_0 = result[0].generator_call
        assert gen_call_0 is not None
        assert gen_call_0.name == 'gens/gen1'
        assert gen_call_0.args == '--A=1'
        gen_call_1 = result[1].generator_call
        assert gen_call_1 is not None
        assert gen_call_1.name == 'gens/gen2'
        assert gen_call_1.args == '--B=2'
        gen_call_2 = result[2].generator_call
        assert gen_call_2 is not None
        assert gen_call_2.name == 'gens/gen3'
        assert gen_call_2.args == '--C=3'

    def test_parse_and_transform_copy_directive(self):
        """Test transforming @copy directive."""
        script = '@copy tests/manual.in'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 1
        assert result[0].copied_from is not None
        assert result[0].copied_from.inputPath == pathlib.Path('tests/manual.in')
        assert result[0].generator_call is None
        assert result[0].group is None

    def test_parse_and_transform_multiple_copy_directives(self):
        """Test transforming multiple @copy directives."""
        script = """
@copy tests/sample1.in
@copy tests/sample2.in
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 2
        copied_0 = result[0].copied_from
        assert copied_0 is not None
        assert copied_0.inputPath == pathlib.Path('tests/sample1.in')
        copied_1 = result[1].copied_from
        assert copied_1 is not None
        assert copied_1.inputPath == pathlib.Path('tests/sample2.in')

    def test_parse_and_transform_tracks_line_numbers(self):
        """Test that line numbers are tracked correctly in generator_script."""
        script = """
// Comment on line 2
gens/gen1 --A=1
gens/gen2 --B=2
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 2
        gen_script_0 = result[0].generator_script
        assert gen_script_0 is not None
        assert gen_script_0.path == script_path
        assert gen_script_0.line == 3
        gen_script_1 = result[1].generator_script
        assert gen_script_1 is not None
        assert gen_script_1.path == script_path
        assert gen_script_1.line == 4

    def test_parse_and_transform_tracks_copy_line_numbers(self):
        """Test that line numbers are tracked for @copy directives."""
        script = """
@copy tests/sample1.in
@copy tests/sample2.in
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        gen_script_0 = result[0].generator_script
        assert gen_script_0 is not None
        assert gen_script_0.line == 2
        gen_script_1 = result[1].generator_script
        assert gen_script_1 is not None
        assert gen_script_1.line == 3

    def test_parse_and_transform_inline_input_single_quotes(self):
        """Test transforming @input directive with single-quoted string."""
        script = "@input 'test data'"
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 1
        assert result[0].content == 'test data'
        assert result[0].generator_call is None
        assert result[0].copied_from is None
        assert result[0].group is None

    def test_parse_and_transform_inline_input_double_quotes(self):
        """Test transforming @input directive with double-quoted string."""
        script = '@input "test data"'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 1
        assert result[0].content == 'test data'

    def test_parse_and_transform_inline_input_with_escape_sequences(self):
        """Test transforming @input directive with escape sequences."""
        script = r"@input '123\n456\n789\n'"
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 1
        assert result[0].content == '123\n456\n789\n'

    def test_parse_and_transform_inline_input_with_escaped_quotes(self):
        """Test transforming @input directive with escaped quotes."""
        script = r"@input 'it\'s a test'"
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 1
        assert result[0].content == "it's a test"

    def test_parse_and_transform_inline_input_triple_quoted(self):
        """Test transforming @input directive with triple-quoted string."""
        script = '''@input """
123
456
789
"""'''
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 1
        assert result[0].content == '\n123\n456\n789\n'

    def test_parse_and_transform_multiple_inline_inputs(self):
        """Test transforming multiple @input directives."""
        script = """
@input 'first input'
@input "second input"
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 2
        assert result[0].content == 'first input'
        assert result[1].content == 'second input'

    def test_parse_and_transform_tracks_inline_input_line_numbers(self):
        """Test that line numbers are tracked for @input directives."""
        script = """
@input 'first'
@input "second"
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        gen_script_0 = result[0].generator_script
        assert gen_script_0 is not None
        assert gen_script_0.line == 2
        gen_script_1 = result[1].generator_script
        assert gen_script_1 is not None
        assert gen_script_1.line == 3

    def test_parse_and_transform_inline_input_in_testgroup(self):
        """Test transforming @input directive inside a testgroup."""
        script = """
@testgroup group1 {
    @input 'test data in group'
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 1
        assert result[0].group == 'group1'
        assert result[0].content == 'test data in group'

    def test_parse_and_transform_simple_testgroup(self):
        """Test transforming a simple testgroup."""
        script = """
@testgroup group1 {
    gens/generator --X=5
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 1
        assert result[0].group == 'group1'
        gen_call = result[0].generator_call
        assert gen_call is not None
        assert gen_call.name == 'gens/generator'
        assert gen_call.args == '--X=5'

    def test_parse_and_transform_testgroup_with_multiple_statements(self):
        """Test transforming testgroup with multiple statements."""
        script = """
@testgroup my_group {
    gens/gen1 --A=1
    gens/gen2 --B=2
    @copy tests/manual.in
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 3
        assert all(item.group == 'my_group' for item in result)
        gen_call_0 = result[0].generator_call
        assert gen_call_0 is not None
        assert gen_call_0.name == 'gens/gen1'
        gen_call_1 = result[1].generator_call
        assert gen_call_1 is not None
        assert gen_call_1.name == 'gens/gen2'
        copied_2 = result[2].copied_from
        assert copied_2 is not None
        assert copied_2.inputPath == pathlib.Path('tests/manual.in')

    def test_parse_and_transform_testgroup_filters_comments(self):
        """Test that comments inside testgroups are filtered out."""
        script = """
@testgroup group1 {
    // This is a comment
    gens/gen1 --A=1
    // Another comment
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 1
        assert result[0].group == 'group1'

    def test_parse_and_transform_nested_testgroups(self):
        """Test transforming nested testgroups."""
        script = """
@testgroup outer {
    gens/gen1 --X=1
    @testgroup inner {
        gens/gen2 --Y=2
    }
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 2
        assert result[0].group == 'outer'
        gen_call_0 = result[0].generator_call
        assert gen_call_0 is not None
        assert gen_call_0.name == 'gens/gen1'
        assert result[1].group == 'inner'
        gen_call_1 = result[1].generator_call
        assert gen_call_1 is not None
        assert gen_call_1.name == 'gens/gen2'

    def test_parse_and_transform_nested_testgroups_inner_takes_precedence(self):
        """Test that inner testgroup name takes precedence over outer."""
        script = """
@testgroup outer {
    @testgroup inner {
        gens/gen1 --X=1
    }
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 1
        # Inner group name should take precedence
        assert result[0].group == 'inner'

    def test_parse_and_transform_multiple_top_level_testgroups(self):
        """Test transforming multiple top-level testgroups."""
        script = """
@testgroup group1 {
    gens/gen1 --A=1
}

@testgroup group2 {
    gens/gen2 --B=2
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 2
        assert result[0].group == 'group1'
        assert result[1].group == 'group2'

    def test_parse_and_transform_empty_testgroup(self):
        """Test transforming empty testgroup."""
        script = """
@testgroup empty_group {
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert result == []

    def test_parse_and_transform_mixed_grouped_and_ungrouped(self):
        """Test transforming script with both grouped and ungrouped statements."""
        script = """
gens/gen_ungrouped --X=1

@testgroup group1 {
    gens/gen_grouped --Y=2
}

@copy tests/manual.in
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 3
        assert result[0].group is None
        gen_call_0 = result[0].generator_call
        assert gen_call_0 is not None
        assert gen_call_0.name == 'gens/gen_ungrouped'
        assert result[1].group == 'group1'
        gen_call_1 = result[1].generator_call
        assert gen_call_1 is not None
        assert gen_call_1.name == 'gens/gen_grouped'
        assert result[2].group is None
        assert result[2].copied_from is not None

    def test_parse_and_transform_testgroup_with_hyphenated_name(self):
        """Test transforming testgroup with hyphenated name."""
        script = """
@testgroup test-group-name {
    gens/gen --X=1
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert result[0].group == 'test-group-name'

    def test_parse_and_transform_testgroup_with_underscore_name(self):
        """Test transforming testgroup with underscore in name."""
        script = """
@testgroup test_group_name {
    gens/gen --X=1
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert result[0].group == 'test_group_name'

    def test_parse_and_transform_testgroup_with_numbers(self):
        """Test transforming testgroup with numbers in name."""
        script = """
@testgroup group123 {
    gens/gen --X=1
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert result[0].group == 'group123'

    def test_parse_and_transform_preserves_script_path(self):
        """Test that script path is preserved in all results."""
        script = """
gens/gen1
@copy tests/manual.in
"""
        script_path = pathlib.Path('custom/path/script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 2
        gen_script_0 = result[0].generator_script
        assert gen_script_0 is not None
        assert gen_script_0.path == script_path
        gen_script_1 = result[1].generator_script
        assert gen_script_1 is not None
        assert gen_script_1.path == script_path

    def test_parse_and_transform_generator_script_entry_str(self):
        """Test that GeneratorScriptEntry str representation is correct."""
        script = 'gens/gen --X=1'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert str(result[0].generator_script) == 'test_script.txt:1'

    def test_parse_and_transform_complex_real_world_script(self):
        """Test transforming a complex real-world style script."""
        script = """
// Generate small test cases
@testgroup small {
    gens/gen_random --MAX_N=10 --seed=1
    gens/gen_random --MAX_N=10 --seed=2
    gens/gen_edge --type=min
}

// Copy manual tests
@copy tests/manual/edge1.in
@copy tests/manual/edge2.in

// Generate large test cases
@testgroup large {
    gens/gen_random --MAX_N=100000 --seed=42
    gens/gen_edge --type=max
}

// Final edge case
gens/gen_special --config=final
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 8

        # Check small group
        small_items = [r for r in result if r.group == 'small']
        assert len(small_items) == 3
        small_gen_call_0 = small_items[0].generator_call
        assert small_gen_call_0 is not None
        assert small_gen_call_0.name == 'gens/gen_random'
        assert small_gen_call_0.args == '--MAX_N=10 --seed=1'

        # Check copied items
        copied_items = [r for r in result if r.copied_from is not None]
        assert len(copied_items) == 2
        copied_0 = copied_items[0].copied_from
        assert copied_0 is not None
        assert copied_0.inputPath == pathlib.Path('tests/manual/edge1.in')
        copied_1 = copied_items[1].copied_from
        assert copied_1 is not None
        assert copied_1.inputPath == pathlib.Path('tests/manual/edge2.in')

        # Check large group
        large_items = [r for r in result if r.group == 'large']
        assert len(large_items) == 2

        # Check ungrouped item
        ungrouped_items = [
            r for r in result if r.group is None and r.copied_from is None
        ]
        assert len(ungrouped_items) == 1
        ungrouped_gen_call = ungrouped_items[0].generator_call
        assert ungrouped_gen_call is not None
        assert ungrouped_gen_call.name == 'gens/gen_special'

    def test_parse_and_transform_maintains_order(self):
        """Test that transformation maintains statement order."""
        script = """
gens/gen1
gens/gen2
gens/gen3
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 3
        gen_call_0 = result[0].generator_call
        assert gen_call_0 is not None
        assert gen_call_0.name == 'gens/gen1'
        gen_call_1 = result[1].generator_call
        assert gen_call_1 is not None
        assert gen_call_1.name == 'gens/gen2'
        gen_call_2 = result[2].generator_call
        assert gen_call_2 is not None
        assert gen_call_2.name == 'gens/gen3'

    def test_parse_and_transform_testgroup_maintains_order(self):
        """Test that testgroup transformation maintains statement order."""
        script = """
@testgroup group1 {
    gens/gen1
    @copy tests/test1.in
    gens/gen2
    @copy tests/test2.in
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 4
        gen_call_0 = result[0].generator_call
        assert gen_call_0 is not None
        assert gen_call_0.name == 'gens/gen1'
        copied_1 = result[1].copied_from
        assert copied_1 is not None
        assert copied_1.inputPath == pathlib.Path('tests/test1.in')
        gen_call_2 = result[2].generator_call
        assert gen_call_2 is not None
        assert gen_call_2.name == 'gens/gen2'
        copied_3 = result[3].copied_from
        assert copied_3 is not None
        assert copied_3.inputPath == pathlib.Path('tests/test2.in')

    def test_parse_and_transform_line_numbers_with_comments(self):
        """Test that line numbers account for comments correctly."""
        script = """
// Line 2
// Line 3
gens/gen1
// Line 5
gens/gen2
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 2
        gen_script_0 = result[0].generator_script
        assert gen_script_0 is not None
        assert gen_script_0.line == 4
        gen_script_1 = result[1].generator_script
        assert gen_script_1 is not None
        assert gen_script_1.line == 6

    def test_parse_and_transform_deeply_nested_testgroups(self):
        """Test transforming deeply nested testgroups."""
        script = """
@testgroup level1 {
    gens/gen1
    @testgroup level2 {
        gens/gen2
        @testgroup level3 {
            gens/gen3
        }
    }
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 3
        assert result[0].group == 'level1'
        assert result[1].group == 'level2'
        assert result[2].group == 'level3'

    def test_parse_and_transform_generator_with_various_filepath_formats(self):
        """Test transforming generators with different filepath formats."""
        script = """
gen
gen.cpp
gens/gen
path/to/generator.py
../gen
../../parent/gen.py
./gen
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 7
        gen_call_0 = result[0].generator_call
        assert gen_call_0 is not None
        assert gen_call_0.name == 'gen'
        gen_call_1 = result[1].generator_call
        assert gen_call_1 is not None
        assert gen_call_1.name == 'gen.cpp'
        gen_call_2 = result[2].generator_call
        assert gen_call_2 is not None
        assert gen_call_2.name == 'gens/gen'
        gen_call_3 = result[3].generator_call
        assert gen_call_3 is not None
        assert gen_call_3.name == 'path/to/generator.py'
        gen_call_4 = result[4].generator_call
        assert gen_call_4 is not None
        assert gen_call_4.name == '../gen'
        gen_call_5 = result[5].generator_call
        assert gen_call_5 is not None
        assert gen_call_5.name == '../../parent/gen.py'
        gen_call_6 = result[6].generator_call
        assert gen_call_6 is not None
        assert gen_call_6.name == './gen'

    def test_parse_and_transform_copy_with_various_path_formats(self):
        """Test transforming @copy with different relative path formats."""
        script = """
@copy test.in
@copy tests/test.in
@copy path/to/deep/test.in
@copy ../test.in
@copy ../../parent/test.in
@copy ./test.in
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 6
        copied_0 = result[0].copied_from
        assert copied_0 is not None
        assert copied_0.inputPath == pathlib.Path('test.in')
        copied_1 = result[1].copied_from
        assert copied_1 is not None
        assert copied_1.inputPath == pathlib.Path('tests/test.in')
        copied_2 = result[2].copied_from
        assert copied_2 is not None
        assert copied_2.inputPath == pathlib.Path('path/to/deep/test.in')
        copied_3 = result[3].copied_from
        assert copied_3 is not None
        assert copied_3.inputPath == pathlib.Path('../test.in')
        copied_4 = result[4].copied_from
        assert copied_4 is not None
        assert copied_4.inputPath == pathlib.Path('../../parent/test.in')
        copied_5 = result[5].copied_from
        assert copied_5 is not None
        assert copied_5.inputPath == pathlib.Path('./test.in')

    def test_parse_and_transform_script_with_blank_lines(self):
        """Test that blank lines don't affect transformation."""
        script = """

gens/gen1


gens/gen2


"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 2

    def test_parse_and_transform_testgroup_line_numbers(self):
        """Test that line numbers inside testgroups are correct."""
        script = """
@testgroup group1 {
    gens/gen1
    gens/gen2
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 2
        gen_script_0 = result[0].generator_script
        assert gen_script_0 is not None
        assert gen_script_0.line == 3
        gen_script_1 = result[1].generator_script
        assert gen_script_1 is not None
        assert gen_script_1.line == 4

    def test_parse_and_transform_mixed_line_numbers(self):
        """Test line numbers in complex mixed script."""
        script = """
gens/gen1
@testgroup group1 {
    gens/gen2
}
@copy tests/test.in
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 3
        gen_script_0 = result[0].generator_script
        assert gen_script_0 is not None
        assert gen_script_0.line == 2
        gen_script_1 = result[1].generator_script
        assert gen_script_1 is not None
        assert gen_script_1.line == 4
        gen_script_2 = result[2].generator_script
        assert gen_script_2 is not None
        assert gen_script_2.line == 6

    def test_parse_and_transform_example_from_main_block(self):
        """Test the example script from the main block of the module."""
        script = """
// This is a comment
gens/generator --MAX_N=100 --MIN_N=30 abcdef

@copy test/in/disk.in

@testgroup my-group {
    // Comment inside group
    gens/generator2 --X=5
    gens/generator3 --Y=10 --Z=20 some more args
}

@testgroup group_2 {
    gens/generator4 --A=1
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        assert len(result) == 5

        # First generator (ungrouped)
        gen_call_0 = result[0].generator_call
        assert gen_call_0 is not None
        assert gen_call_0.name == 'gens/generator'
        assert gen_call_0.args == '--MAX_N=100 --MIN_N=30 abcdef'
        assert result[0].group is None

        # Copy directive (ungrouped)
        copied_1 = result[1].copied_from
        assert copied_1 is not None
        assert copied_1.inputPath == pathlib.Path('test/in/disk.in')
        assert result[1].group is None

        # my-group items
        gen_call_2 = result[2].generator_call
        assert gen_call_2 is not None
        assert gen_call_2.name == 'gens/generator2'
        assert result[2].group == 'my-group'
        gen_call_3 = result[3].generator_call
        assert gen_call_3 is not None
        assert gen_call_3.name == 'gens/generator3'
        assert result[3].group == 'my-group'

        # group_2 item
        gen_call_4 = result[4].generator_call
        assert gen_call_4 is not None
        assert gen_call_4.name == 'gens/generator4'
        assert result[4].group == 'group_2'

    def test_parse_and_transform_args_not_split_as_separate_calls(self):
        """Regression test: ensure args after generator name aren't parsed as separate calls.

        Previously, a line like 'gen1 456' would be incorrectly parsed as two calls:
        - gen1 (no args)
        - 456 (as a generator name)

        This test ensures 'gen1 456' is correctly parsed as one call with name='gen1' and args='456'.
        """
        # Using explicit line construction to avoid any whitespace issues
        script = 'gen1 123\ngen1 456'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path)

        # Should be 2 generator calls, not 4+
        assert len(result) == 2

        # First call - numeric arg
        gen_call_0 = result[0].generator_call
        assert gen_call_0 is not None
        assert gen_call_0.name == 'gen1'
        assert gen_call_0.args == '123'

        # Second call - numeric arg
        gen_call_1 = result[1].generator_call
        assert gen_call_1 is not None
        assert gen_call_1.name == 'gen1'
        assert gen_call_1.args == '456'
