import pathlib

import lark
import pytest

from rbx.box.schema import ExpectedOutcome, ValidatorOutcome
from rbx.box.stressing.unit_parser import (
    ParsedUnitTest,
    UnitTestMode,
    parse_and_transform,
)


class TestParseAndTransformFunction:
    """Test suite for the parse_and_transform function behavior."""

    def test_parse_and_transform_returns_list_of_parsed_unit_tests(self):
        """Test that parse_and_transform returns a list of ParsedUnitTest objects."""
        script = '@input valid "test input"'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.VALIDATOR)

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], ParsedUnitTest)
        assert result[0].expectation == ValidatorOutcome.VALID

    def test_parse_and_transform_empty_script(self):
        """Test transforming empty script returns empty list."""
        script = ''
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.VALIDATOR)

        assert result == []

    def test_parse_and_transform_only_comments(self):
        """Test that comments are filtered out and don't produce results."""
        script = """
// Comment 1
# Comment 2
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.VALIDATOR)

        assert result == []

    def test_parse_and_transform_only_newlines(self):
        """Test that newlines alone don't produce results."""
        script = '\n\n\n'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.VALIDATOR)

        assert result == []


class TestInputOnlySyntax:
    """Test suite for simplified @input syntax."""

    def test_input_with_string_literal(self):
        """Test @input with string literal."""
        script = '@input ac "test input"'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].name is None
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[0].input == 'test input'
        assert result[0].output is None
        assert result[0].answer is None
        assert result[0].script_path == script_path
        assert result[0].line == 1

    def test_input_with_single_quoted_string(self):
        """Test @input with single-quoted string literal."""
        script = "@input wa 'test input'"
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].expectation == ExpectedOutcome.WRONG_ANSWER
        assert result[0].input == 'test input'

    def test_input_with_escaped_characters(self):
        """Test @input with escaped characters in string."""
        script = r'@input tle "line1\nline2\ttab"'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].expectation == ExpectedOutcome.TIME_LIMIT_EXCEEDED
        assert result[0].input == 'line1\nline2\ttab'

    def test_input_with_brace_block(self):
        """Test @input with brace block syntax."""
        script = """@input ac {
line 1
line 2
line 3
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[0].input == 'line 1\nline 2\nline 3\n'

    def test_input_with_name_and_brace_block(self):
        """Test @input with name and brace block."""
        script = """@input test_name ac {
content here
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].name == 'test_name'
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[0].input == 'content here\n'

    def test_input_with_name_and_string_literal(self):
        """Test @input with name and string literal."""
        script = '@input test_name rte "content here"'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].name == 'test_name'
        assert result[0].expectation == ExpectedOutcome.RUNTIME_ERROR
        assert result[0].input == 'content here'

    def test_input_with_triple_quoted_string(self):
        """Test @input with triple-quoted string."""
        script = '''@input ac """
line 1
line 2
"""'''
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[0].input == 'line 1\nline 2\n'

    def test_multiple_input_only_blocks(self):
        """Test multiple @input blocks."""
        script = """
@input ac "input 1"
@input wa "input 2"
@input test_3 tle "input 3"
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 3
        assert result[0].input == 'input 1'
        assert result[0].name is None
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[1].input == 'input 2'
        assert result[1].name is None
        assert result[1].expectation == ExpectedOutcome.WRONG_ANSWER
        assert result[2].input == 'input 3'
        assert result[2].name == 'test_3'
        assert result[2].expectation == ExpectedOutcome.TIME_LIMIT_EXCEEDED


class TestTestBlockSyntax:
    """Test suite for @test block syntax."""

    def test_test_block_with_input_only(self):
        """Test @test block with only @input."""
        script = """@test ac {
    @input "test input"
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].name is None
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[0].input == 'test input'
        assert result[0].output is None
        assert result[0].answer is None
        assert result[0].script_path == script_path

    def test_test_block_with_name(self):
        """Test @test block with name."""
        script = """@test my_test wa {
    @input "test input"
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].name == 'my_test'
        assert result[0].expectation == ExpectedOutcome.WRONG_ANSWER
        assert result[0].input == 'test input'

    def test_test_block_with_input_and_output(self):
        """Test @test block with @input and @output."""
        script = """@test ac {
    @input "5 10"
    @output "15"
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[0].input == '5 10'
        assert result[0].output == '15'
        assert result[0].answer is None

    def test_test_block_with_input_and_answer(self):
        """Test @test block with @input and @answer."""
        script = """@test rte {
    @input "5 10"
    @answer "15"
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].expectation == ExpectedOutcome.RUNTIME_ERROR
        assert result[0].input == '5 10'
        assert result[0].output is None
        assert result[0].answer == '15'

    def test_test_block_with_all_fields(self):
        """Test @test block with @input, @output, and @answer."""
        script = """@test complete_test ac {
    @input "5 10"
    @output "15"
    @answer "15"
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].name == 'complete_test'
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[0].input == '5 10'
        assert result[0].output == '15'
        assert result[0].answer == '15'

    def test_test_block_with_brace_blocks(self):
        """Test @test block with brace block syntax for all fields."""
        script = """@test tle {
    @input {
1 2 3
    }
    @output {
6
    }
    @answer {
6
    }
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].expectation == ExpectedOutcome.TIME_LIMIT_EXCEEDED
        assert result[0].input == '1 2 3\n'
        assert result[0].output == '6\n'
        assert result[0].answer == '6\n'

    def test_test_block_without_input_raises_error(self):
        """Test that @test block without @input raises VisitError with ValueError."""
        script = """@test ac {
    @output "15"
}"""
        script_path = pathlib.Path('test_script.txt')

        with pytest.raises(lark.exceptions.VisitError, match='missing required @input'):
            parse_and_transform(script, script_path, UnitTestMode.CHECKER)

    def test_test_block_with_comments(self):
        """Test @test block with comments inside."""
        script = """@test ac {
    // This is a comment
    @input "test input"
    # Another comment
    @output "test output"
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[0].input == 'test input'
        assert result[0].output == 'test output'

    def test_multiple_test_blocks(self):
        """Test multiple @test blocks."""
        script = """
@test test1 ac {
    @input "input1"
    @output "output1"
}

@test test2 wa {
    @input "input2"
    @answer "answer2"
}

@test tle {
    @input "input3"
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 3
        assert result[0].name == 'test1'
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[0].input == 'input1'
        assert result[0].output == 'output1'
        assert result[0].answer is None

        assert result[1].name == 'test2'
        assert result[1].expectation == ExpectedOutcome.WRONG_ANSWER
        assert result[1].input == 'input2'
        assert result[1].output is None
        assert result[1].answer == 'answer2'

        assert result[2].name is None
        assert result[2].expectation == ExpectedOutcome.TIME_LIMIT_EXCEEDED
        assert result[2].input == 'input3'
        assert result[2].output is None
        assert result[2].answer is None


class TestMixedSyntax:
    """Test suite for mixed @test and @input syntax."""

    def test_mixed_test_and_input_blocks(self):
        """Test mixing @test blocks and @input blocks."""
        script = """
@input ac "simple input"

@test test1 wa {
    @input "complex input"
    @output "output"
}

@input named_simple tle "another simple"

@test rte {
    @input "unnamed test"
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 4
        assert result[0].input == 'simple input'
        assert result[0].name is None
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[0].output is None

        assert result[1].input == 'complex input'
        assert result[1].name == 'test1'
        assert result[1].expectation == ExpectedOutcome.WRONG_ANSWER
        assert result[1].output == 'output'

        assert result[2].input == 'another simple'
        assert result[2].name == 'named_simple'
        assert result[2].expectation == ExpectedOutcome.TIME_LIMIT_EXCEEDED
        assert result[2].output is None

        assert result[3].input == 'unnamed test'
        assert result[3].name is None
        assert result[3].expectation == ExpectedOutcome.RUNTIME_ERROR

    def test_script_with_comments_between_tests(self):
        """Test script with comments between test definitions."""
        script = """
// Initial comment
@input ac "first"

// Comment between
@test wa {
    @input "second"
}

# Another comment style
@input tle "third"
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 3
        assert result[0].input == 'first'
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[1].input == 'second'
        assert result[1].expectation == ExpectedOutcome.WRONG_ANSWER
        assert result[2].input == 'third'
        assert result[2].expectation == ExpectedOutcome.TIME_LIMIT_EXCEEDED


class TestLineNumbers:
    """Test suite for line number tracking."""

    def test_line_numbers_for_input_blocks(self):
        """Test that line numbers are correctly tracked for @input blocks."""
        script = """
@input ac "first"
@input wa "second"
@input tle "third"
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 3
        assert result[0].line == 2
        assert result[1].line == 3
        assert result[2].line == 4

    def test_line_numbers_for_test_blocks(self):
        """Test that line numbers are correctly tracked for @test blocks."""
        script = """// Comment
@test ac {
    @input "first"
}

@test wa {
    @input "second"
}
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 2
        assert result[0].line == 2
        assert result[1].line == 6

    def test_line_numbers_mixed(self):
        """Test line numbers in mixed syntax."""
        script = """@input ac "first"

@test wa {
    @input "second"
}

@input tle "third"
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 3
        assert result[0].line == 1
        assert result[1].line == 3
        assert result[2].line == 7


class TestScriptPath:
    """Test suite for script_path tracking."""

    def test_script_path_is_stored(self):
        """Test that script_path is correctly stored in results."""
        script = '@input ac "test"'
        script_path = pathlib.Path('my/test/script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].script_path == script_path

    def test_script_path_in_all_results(self):
        """Test that all results have the same script_path."""
        script = """
@input ac "first"
@test wa { @input "second" }
@input tle "third"
"""
        script_path = pathlib.Path('test_file.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 3
        assert all(r.script_path == script_path for r in result)


class TestWhitespaceHandling:
    """Test suite for whitespace handling."""

    def test_indented_test_blocks(self):
        """Test that indented test blocks are parsed correctly."""
        script = """
    @test ac {
        @input "test"
    }
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].input == 'test'

    def test_indented_input_blocks(self):
        """Test that indented input blocks are parsed correctly."""
        script = """
    @input ac "test1"
        @input wa "test2"
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 2
        assert result[0].input == 'test1'
        assert result[1].input == 'test2'

    def test_brace_block_preserves_content_whitespace(self):
        """Test that whitespace in brace blocks is normalized (leading whitespace stripped)."""
        script = """@input ac {
  spaces
    more spaces
	tab
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].input == 'spaces\nmore spaces\ntab\n'

    def test_empty_lines_in_brace_block(self):
        """Test that empty lines in brace blocks are preserved."""
        script = """@input ac {
line1

line3
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        # Empty line is preserved as a newline
        assert 'line1\n' in result[0].input
        assert 'line3\n' in result[0].input


class TestEdgeCases:
    """Test suite for edge cases and special scenarios."""

    def test_test_name_with_underscores_and_dashes(self):
        """Test that test names can contain underscores and dashes."""
        script = """
@test test-name_123 ac {
    @input "test"
}

@input input-name_456 wa "content"
"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 2
        assert result[0].name == 'test-name_123'
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[1].name == 'input-name_456'
        assert result[1].expectation == ExpectedOutcome.WRONG_ANSWER

    def test_empty_string_input(self):
        """Test that empty string input is handled."""
        script = '@input ac ""'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].input == ''

    def test_empty_brace_block(self):
        """Test that empty brace block is handled."""
        script = """@input ac {
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].input == ''

    def test_test_block_with_empty_brace_blocks(self):
        """Test @test with empty brace blocks."""
        script = """@test wa {
    @input {
    }
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].expectation == ExpectedOutcome.WRONG_ANSWER
        assert result[0].input == ''

    def test_quoted_string_with_quotes_inside(self):
        """Test string with escaped quotes."""
        script = r'@input tle "He said \"hello\""'
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].input == 'He said "hello"'

    def test_triple_quoted_with_quotes_inside(self):
        """Test triple-quoted string with quotes inside."""
        script = '''@input rte """He said "hello" and 'goodbye'"""'''
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].input == """He said "hello" and 'goodbye'\n"""

    def test_multiline_with_trailing_newline(self):
        """Test that multiline content ends with newline."""
        script = """@test ac {
    @input {
line1
line2
    }
    @output {
out1
out2
    }
    @answer {
ans1
ans2
    }
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[0].input.endswith('\n')
        assert result[0].output.endswith('\n')
        assert result[0].answer.endswith('\n')


class TestComplexScenarios:
    """Test suite for complex real-world scenarios."""

    def test_comprehensive_test_file(self):
        """Test a comprehensive test file with various syntax styles."""
        script = """
// Test file for problem X
// Author: Test Author

# Simple test cases
@input simple1 ac "1 2"
@input simple2 wa "3 4"

// Complex test with expected output
@test test_addition ac {
    @input "5 10"
    @output "15"
}

// Test with answer for checking
@test test_multiplication tle {
    @input {
2 3
    }
    @answer {
6
    }
}

// Edge case
@test edge_case ac {
    @input "0 0"
    @output "0"
    @answer "0"
}

// Additional simple cases
@input rte {
100 200
}

@input final_test ac {
999 1
}
"""
        script_path = pathlib.Path('tests/problem_x.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 7

        # Check simple cases
        assert result[0].name == 'simple1'
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[0].input == '1 2'
        assert result[0].output is None

        assert result[1].name == 'simple2'
        assert result[1].expectation == ExpectedOutcome.WRONG_ANSWER
        assert result[1].input == '3 4'

        # Check test with output
        assert result[2].name == 'test_addition'
        assert result[2].expectation == ExpectedOutcome.ACCEPTED
        assert result[2].input == '5 10'
        assert result[2].output == '15'
        assert result[2].answer is None

        # Check test with answer
        assert result[3].name == 'test_multiplication'
        assert result[3].expectation == ExpectedOutcome.TIME_LIMIT_EXCEEDED
        assert result[3].input == '2 3\n'
        assert result[3].output is None
        assert result[3].answer == '6\n'

        # Check edge case
        assert result[4].name == 'edge_case'
        assert result[4].expectation == ExpectedOutcome.ACCEPTED
        assert result[4].input == '0 0'
        assert result[4].output == '0'
        assert result[4].answer == '0'

        # Check unnamed tests
        assert result[5].name is None
        assert result[5].expectation == ExpectedOutcome.RUNTIME_ERROR
        assert result[5].input == '100 200\n'

        assert result[6].name == 'final_test'
        assert result[6].expectation == ExpectedOutcome.ACCEPTED
        assert result[6].input == '999 1\n'

        # Verify all have correct script_path
        assert all(r.script_path == script_path for r in result)

    def test_ordering_of_fields_in_test_block(self):
        """Test that field order doesn't matter in @test blocks."""
        script = """@test ac {
    @output "output"
    @input "input"
    @answer "answer"
}"""
        script_path = pathlib.Path('test_script.txt')

        result = parse_and_transform(script, script_path, UnitTestMode.CHECKER)

        assert len(result) == 1
        assert result[0].expectation == ExpectedOutcome.ACCEPTED
        assert result[0].input == 'input'
        assert result[0].output == 'output'
        assert result[0].answer == 'answer'
