"""
Comprehensive tests for the rbx.box.safeeval module.
"""

import pytest
import simpleeval

from rbx.box import safeeval


class TestEval:
    """Test suite for the main eval function."""

    def test_eval_basic_arithmetic(self):
        """Test basic arithmetic expressions."""
        assert safeeval.eval('1 + 2') == 3
        assert safeeval.eval('10 - 5') == 5
        assert safeeval.eval('3 * 4') == 12
        assert safeeval.eval('8 / 2') == 4.0
        assert safeeval.eval('7 % 3') == 1
        assert safeeval.eval('2 ** 3') == 8

    def test_eval_with_names(self):
        """Test evaluation with variable substitution."""
        names = {'x': 5, 'y': 3}
        assert safeeval.eval('x + y', names) == 8
        assert safeeval.eval('x * y', names) == 15
        assert safeeval.eval('x - y', names) == 2

    def test_eval_builtin_math_functions(self):
        """Test built-in math functions."""
        assert safeeval.eval('int(3.14)') == 3
        assert safeeval.eval('float(42)') == 42.0
        assert safeeval.eval('str(123)') == '123'
        assert safeeval.eval('floor(3.7)') == 3
        assert safeeval.eval('ceil(3.2)') == 4
        assert safeeval.eval('abs(-5)') == 5

    def test_eval_step_functions(self):
        """Test step_up and step_down functions."""
        # step_down rounds down to nearest multiple
        assert safeeval.eval('step_down(123, 10)') == 120
        assert safeeval.eval('step_down(100, 10)') == 100
        assert safeeval.eval('step_down(7, 5)') == 5
        assert safeeval.eval('step_down(1, 10)') == 0

        # step_up rounds up to nearest multiple
        assert safeeval.eval('step_up(123, 10)') == 130
        assert safeeval.eval('step_up(100, 10)') == 100
        assert safeeval.eval('step_up(7, 5)') == 10
        assert safeeval.eval('step_up(1, 10)') == 10

    def test_eval_step_functions_with_string_input(self):
        """Test step functions with string inputs (should be converted to int)."""
        assert safeeval.eval('step_down("123", 10)') == 120
        assert safeeval.eval('step_up("123", 10)') == 130

    def test_eval_path_functions(self):
        """Test path manipulation functions."""
        # stem function
        assert safeeval.eval('stem("test.txt")') == 'test'
        assert safeeval.eval('stem("/path/to/file.cpp")') == 'file'

        # parent function
        assert safeeval.eval('parent("/path/to/file.txt")') == '/path/to'
        assert safeeval.eval('parent("file.txt")') == '.'

        # suffix function
        assert safeeval.eval('suffix("file.txt")') == '.txt'
        assert safeeval.eval('suffix("archive.tar.gz")') == '.gz'

        # ext function (suffix without dot)
        assert safeeval.eval('ext("file.txt")') == 'txt'
        assert safeeval.eval('ext("archive.tar.gz")') == 'gz'

        # with_suffix function
        assert safeeval.eval('with_suffix("file.txt", ".cpp")') == 'file.cpp'
        assert safeeval.eval('with_suffix("test", ".py")') == 'test.py'

        # with_stem function
        assert safeeval.eval('with_stem("file.txt", "newname")') == 'newname.txt'
        assert safeeval.eval('with_stem("test.cpp", "solution")') == 'solution.cpp'

        # with_ext function
        assert safeeval.eval('with_ext("file.txt", "cpp")') == 'file.cpp'
        assert safeeval.eval('with_ext("test.py", "exe")') == 'test.exe'

    def test_eval_custom_functions(self):
        """Test evaluation with custom functions."""
        custom_functions = {
            'double': lambda x: x * 2,
            'square': lambda x: x**2,
        }

        assert safeeval.eval('double(5)', functions=custom_functions) == 10
        assert safeeval.eval('square(3)', functions=custom_functions) == 9

        # Custom functions should work alongside built-in functions
        assert safeeval.eval('double(int(3.7))', functions=custom_functions) == 6

    def test_eval_complex_expressions(self):
        """Test complex expressions combining multiple features."""
        names = {'base': 100, 'step': 25}

        # Complex arithmetic with variables
        assert safeeval.eval('step_up(base + 13, step)', names) == 125
        assert safeeval.eval('step_down(base - 7, step)', names) == 75

        # String and path operations
        assert safeeval.eval('ext(with_suffix("file.txt", ".cpp"))') == 'cpp'

        # Math operations
        assert safeeval.eval('floor(3.8) + ceil(2.1)') == 6

    def test_eval_edge_cases(self):
        """Test edge cases and boundary conditions."""
        # Empty variable dict
        assert safeeval.eval('1 + 2', {}) == 3

        # None variables
        assert safeeval.eval('1 + 2', None) == 3

        # Division by zero should raise an error
        with pytest.raises(ZeroDivisionError):
            safeeval.eval('1 / 0')

    def test_eval_with_boolean_logic(self):
        """Test boolean expressions and logic."""
        assert safeeval.eval('True and False') is False
        assert safeeval.eval('True or False') is True
        assert safeeval.eval('not True') is False
        assert safeeval.eval('1 < 2') is True
        assert safeeval.eval('5 > 10') is False
        assert safeeval.eval('3 == 3') is True
        assert safeeval.eval('4 != 4') is False


class TestEvalInt:
    """Test suite for eval_int function."""

    def test_eval_int_basic(self):
        """Test basic integer evaluation."""
        assert safeeval.eval_int('42') == 42
        assert safeeval.eval_int('1 + 2') == 3
        assert safeeval.eval_int('10 - 3') == 7

    def test_eval_int_conversion_from_float(self):
        """Test integer conversion from float expressions."""
        assert safeeval.eval_int('3.14') == 3
        assert safeeval.eval_int('7.9') == 7
        assert safeeval.eval_int('10.0') == 10

    def test_eval_int_with_functions(self):
        """Test integer evaluation with functions."""
        assert safeeval.eval_int('ceil(3.2)') == 4
        assert safeeval.eval_int('floor(7.8)') == 7
        assert safeeval.eval_int('abs(-15)') == 15

    def test_eval_int_with_names(self):
        """Test integer evaluation with variable names."""
        names = {'x': 5.7, 'y': 2.3}
        assert safeeval.eval_int('x + y', names) == 8

    def test_eval_int_step_functions(self):
        """Test integer evaluation with step functions."""
        assert safeeval.eval_int('step_up(123, 10)') == 130
        assert safeeval.eval_int('step_down(127, 10)') == 120

    def test_eval_int_boolean_conversion(self):
        """Test integer conversion from boolean expressions."""
        assert safeeval.eval_int('True') == 1
        assert safeeval.eval_int('False') == 0
        assert safeeval.eval_int('1 < 2') == 1
        assert safeeval.eval_int('1 > 2') == 0


class TestEvalFloat:
    """Test suite for eval_float function."""

    def test_eval_float_basic(self):
        """Test basic float evaluation."""
        assert safeeval.eval_float('3.14') == 3.14
        assert safeeval.eval_float('1.5 + 2.3') == 3.8
        assert safeeval.eval_float('10.0 / 3.0') == 10.0 / 3.0

    def test_eval_float_conversion_from_int(self):
        """Test float conversion from integer expressions."""
        assert safeeval.eval_float('42') == 42.0
        assert safeeval.eval_float('1 + 2') == 3.0

    def test_eval_float_with_functions(self):
        """Test float evaluation with functions."""
        assert safeeval.eval_float('float(42)') == 42.0
        assert safeeval.eval_float('abs(-3.5)') == 3.5

    def test_eval_float_with_names(self):
        """Test float evaluation with variable names."""
        names = {'pi': 3.14159, 'radius': 2}
        result = safeeval.eval_float('pi * radius', names)
        assert abs(result - 6.28318) < 0.001

    def test_eval_float_boolean_conversion(self):
        """Test float conversion from boolean expressions."""
        assert safeeval.eval_float('True') == 1.0
        assert safeeval.eval_float('False') == 0.0


class TestEvalString:
    """Test suite for eval_string function."""

    def test_eval_string_basic(self):
        """Test basic string evaluation."""
        assert safeeval.eval_string('42') == '42'
        assert safeeval.eval_string('3.14') == '3.14'
        assert safeeval.eval_string('True') == 'True'

    def test_eval_string_arithmetic_conversion(self):
        """Test string conversion of arithmetic results."""
        assert safeeval.eval_string('1 + 2') == '3'
        assert safeeval.eval_string('10.5 / 2') == '5.25'

    def test_eval_string_with_str_function(self):
        """Test string evaluation with str function."""
        assert safeeval.eval_string('str(123)') == '123'
        assert safeeval.eval_string('str(3.14)') == '3.14'

    def test_eval_string_with_names(self):
        """Test string evaluation with variable names."""
        names = {'value': 42, 'result': True}
        assert safeeval.eval_string('value', names) == '42'
        assert safeeval.eval_string('result', names) == 'True'

    def test_eval_string_path_functions(self):
        """Test string evaluation with path functions."""
        assert safeeval.eval_string('stem("test.cpp")') == 'test'
        assert safeeval.eval_string('ext("file.txt")') == 'txt'

    def test_eval_string_boolean_expressions(self):
        """Test string conversion of boolean expressions."""
        assert safeeval.eval_string('1 < 2') == 'True'
        assert safeeval.eval_string('5 > 10') == 'False'


class TestEvalAsFstring:
    """Test suite for eval_as_fstring function."""

    def test_eval_as_fstring_basic(self):
        """Test basic f-string evaluation."""
        names = {'name': 'World'}
        assert safeeval.eval_as_fstring('Hello {name}!', names) == 'Hello World!'

    def test_eval_as_fstring_arithmetic(self):
        """Test f-string evaluation with arithmetic expressions."""
        names = {'x': 5, 'y': 3}
        assert safeeval.eval_as_fstring('{x} + {y} = {x + y}', names) == '5 + 3 = 8'

    def test_eval_as_fstring_functions(self):
        """Test f-string evaluation with functions."""
        names = {'value': 3.7}
        assert (
            safeeval.eval_as_fstring('ceil({value}) = {ceil(value)}', names)
            == 'ceil(3.7) = 4'
        )

    def test_eval_as_fstring_path_operations(self):
        """Test f-string evaluation with path operations."""
        names = {'filename': 'test.cpp'}
        result = safeeval.eval_as_fstring(
            'File: {filename}, Extension: {ext(filename)}', names
        )
        assert result == 'File: test.cpp, Extension: cpp'

    def test_eval_as_fstring_step_functions(self):
        """Test f-string evaluation with step functions."""
        names = {'value': 123, 'step': 10}
        result = safeeval.eval_as_fstring('Rounded up: {step_up(value, step)}', names)
        assert result == 'Rounded up: 130'

    def test_eval_as_fstring_complex_expressions(self):
        """Test f-string evaluation with complex expressions."""
        names = {'base_name': 'solution.cpp', 'time_ms': 1234}
        result = safeeval.eval_as_fstring(
            '{stem(base_name)}.{ext(base_name)} - {step_up(time_ms, 100)}ms', names
        )
        assert result == 'solution.cpp - 1300ms'

    def test_eval_as_fstring_no_variables(self):
        """Test f-string evaluation with no variables."""
        assert safeeval.eval_as_fstring('Static text') == 'Static text'
        assert safeeval.eval_as_fstring('Result: {1 + 1}') == 'Result: 2'

    def test_eval_as_fstring_with_custom_functions(self):
        """Test f-string evaluation with custom functions."""
        names = {'value': 5}
        functions = {'double': lambda x: x * 2}
        result = safeeval.eval_as_fstring(
            'Double {value} = {double(value)}', names, functions
        )
        assert result == 'Double 5 = 10'


class TestIntegration:
    """Integration tests combining multiple functions and real-world scenarios."""

    def test_timing_formula_evaluation(self):
        """Test evaluation of timing formulas (common use case)."""
        # Simulate timing calculation
        names = {'fastest': 100, 'slowest': 800, 'average': 450}

        # Common timing formulas
        assert safeeval.eval_int('slowest * 2', names) == 1600
        assert safeeval.eval_int('step_up(slowest * 1.5, 100)', names) == 1200
        assert safeeval.eval_int('step_down(fastest * 10, 50)', names) == 1000

    def test_file_mapping_evaluation(self):
        """Test evaluation of file mappings (common use case)."""
        names = {'compilable': 'solution', 'ext': 'cpp', 'id': 5}

        # Simulate file mapping expressions
        executable = safeeval.eval_as_fstring('{stem(compilable)}.exe', names)
        assert executable == 'solution.exe'

        input_file = safeeval.eval_as_fstring('{compilable}_{id:02d}.in', names)
        assert input_file == 'solution_05.in'

        output_file = safeeval.eval_as_fstring('{with_ext(compilable, "out")}', names)
        assert output_file == 'solution.out'

    def test_error_handling(self):
        """Test proper error handling for invalid expressions."""
        # Undefined variable
        with pytest.raises(simpleeval.NameNotDefined):
            safeeval.eval('undefined_var')

        # Invalid syntax
        with pytest.raises((simpleeval.InvalidExpression, SyntaxError)):
            safeeval.eval('1 +')

        # Division by zero
        with pytest.raises(ZeroDivisionError):
            safeeval.eval('1 / 0')

    def test_path_function_edge_cases(self):
        """Test edge cases for path functions."""
        # Files without extensions
        assert safeeval.eval('ext("README")') == ''
        assert safeeval.eval('suffix("README")') == ''

        # Complex paths
        assert safeeval.eval('stem("/very/long/path/to/file.test.cpp")') == 'file.test'
        assert safeeval.eval('ext("/very/long/path/to/file.test.cpp")') == 'cpp'

        # Root path
        assert safeeval.eval('parent("/")') == '/'

    def test_function_overrides(self):
        """Test that custom functions can override built-in functions."""
        # Override step_up with custom implementation
        custom_functions = {
            'step_up': lambda x, step: x + step,  # Different behavior
        }

        # Should use custom implementation, not built-in
        result = safeeval.eval('step_up(123, 10)', functions=custom_functions)
        assert result == 133  # 123 + 10, not rounded up to 130

    def test_type_consistency(self):
        """Test that type-specific eval functions maintain consistency."""
        expression = '3.7 + 2.3'
        names = {}

        # All functions should work with the same expression
        generic_result = safeeval.eval(expression, names)
        int_result = safeeval.eval_int(expression, names)
        float_result = safeeval.eval_float(expression, names)
        string_result = safeeval.eval_string(expression, names)

        assert generic_result == 6.0
        assert int_result == 6
        assert float_result == 6.0
        assert string_result == '6.0'

    def test_real_world_use_cases(self):
        """Test patterns commonly used in the codebase."""
        # Variable expansion patterns
        names = {
            'problem_name': 'example',
            'time_limit': 2000,
            'test_id': 42,
        }

        # File name generation
        test_input = safeeval.eval_as_fstring('{problem_name}_{test_id:03d}.in', names)
        assert test_input == 'example_042.in'

        # Time limit calculation
        adjusted_limit = safeeval.eval_int('step_up(time_limit * 1.5, 100)', names)
        assert adjusted_limit == 3000

        # Path manipulation
        base_name = 'test.solution.cpp'
        output_name = safeeval.eval_string('with_ext(stem("' + base_name + '"), "out")')
        assert output_name == 'test.out'
