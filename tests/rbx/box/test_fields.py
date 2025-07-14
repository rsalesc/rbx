from typing import Dict

import pytest

from rbx.box.fields import Primitive, expand_var, expand_vars


class TestExpandVar:
    """Tests for the expand_var function."""

    def test_expand_var_non_string_values(self):
        """Test that non-string values are returned unchanged."""
        assert expand_var(42) == 42
        assert expand_var(3.14) == 3.14
        assert expand_var(True) is True
        assert expand_var(False) is False

    def test_expand_var_escaped_strings(self):
        """Test that strings starting with backslash are unescaped."""
        assert expand_var('\\hello') == 'hello'
        assert expand_var('\\py`1+1`') == 'py`1+1`'
        assert expand_var('\\\\escaped') == '\\escaped'
        assert expand_var('\\') == ''

    def test_expand_var_regular_strings(self):
        """Test that regular strings without backticks are returned unchanged."""
        assert expand_var('hello') == 'hello'
        assert expand_var('world') == 'world'
        assert expand_var('py`incomplete') == 'py`incomplete'
        assert expand_var('incomplete`') == 'incomplete`'
        assert expand_var('') == ''

    def test_expand_var_python_expressions_string(self):
        """Test Python expressions that evaluate to strings."""
        assert expand_var('py`"hello"`') == 'hello'
        assert expand_var('py`"world" + "!"`') == 'world!'
        assert expand_var('py`str(42)`') == '42'
        assert expand_var('py`"multi\\nline"`') == 'multi\nline'

    def test_expand_var_python_expressions_int(self):
        """Test Python expressions that evaluate to integers."""
        assert expand_var('py`42`') == 42
        assert expand_var('py`1 + 1`') == 2
        assert expand_var('py`10 * 5`') == 50
        assert expand_var('py`-123`') == -123

    def test_expand_var_python_expressions_float(self):
        """Test Python expressions that evaluate to floats."""
        assert expand_var('py`3.14`') == 3.14
        assert expand_var('py`1.5 + 2.5`') == 4.0
        assert expand_var('py`float(42)`') == 42.0

    def test_expand_var_python_expressions_bool(self):
        """Test Python expressions that evaluate to booleans."""
        assert expand_var('py`True`') is True
        assert expand_var('py`False`') is False
        assert expand_var('py`1 == 1`') is True
        assert expand_var('py`1 == 2`') is False

    def test_expand_var_python_expressions_complex_calculations(self):
        """Test more complex Python expressions."""
        assert expand_var('py`len("hello")`') == 5
        assert expand_var('py`max(1, 2, 3)`') == 3
        assert expand_var('py`"test".upper()`') == 'TEST'
        assert expand_var('py`bool(42)`') is True

    def test_expand_var_unsupported_types_raise_error(self):
        """Test that unsupported types raise TypeError."""
        with pytest.raises(
            TypeError,
            match='Variable with backticks should evaluate to a primitive Python type',
        ):
            expand_var('py`[1, 2, 3]`')

        with pytest.raises(
            TypeError,
            match='Variable with backticks should evaluate to a primitive Python type',
        ):
            expand_var('py`{"key": "value"}`')

        with pytest.raises(
            TypeError,
            match='Variable with backticks should evaluate to a primitive Python type',
        ):
            expand_var('py`None`')

    def test_expand_var_invalid_python_expressions(self):
        """Test that invalid Python expressions raise appropriate errors."""
        with pytest.raises(SyntaxError):
            expand_var('py`1 +`')

        with pytest.raises(NameError):
            expand_var('py`undefined_variable`')

        with pytest.raises(ZeroDivisionError):
            expand_var('py`1 / 0`')

    def test_expand_var_edge_cases(self):
        """Test edge cases with backtick expressions."""
        # Empty expression
        with pytest.raises(SyntaxError):
            expand_var('py``')

        # py` without closing backtick - doesn't match the pattern, returned as-is
        assert expand_var('py`hello') == 'py`hello'

        # Single backtick - doesn't match the pattern
        assert expand_var('`') == '`'

        # Nested backticks in string
        assert expand_var('py`"py`nested`"`') == 'py`nested`'


class TestExpandVars:
    """Tests for the expand_vars function."""

    def test_expand_vars_empty_dict(self):
        """Test that empty dictionary returns empty dictionary."""
        assert expand_vars({}) == {}

    def test_expand_vars_mixed_types(self):
        """Test expanding variables with mixed primitive types."""
        input_vars: Dict[str, Primitive] = {
            'string_var': 'hello',
            'int_var': 42,
            'float_var': 3.14,
            'bool_var': True,
        }
        expected: Dict[str, Primitive] = {
            'string_var': 'hello',
            'int_var': 42,
            'float_var': 3.14,
            'bool_var': True,
        }
        assert expand_vars(input_vars) == expected

    def test_expand_vars_python_expressions(self):
        """Test expanding variables with Python expressions."""
        input_vars: Dict[str, Primitive] = {
            'calculated_int': 'py`1 + 1`',
            'calculated_string': 'py`"hello" + " world"`',
            'calculated_float': 'py`3.14 * 2`',
            'calculated_bool': 'py`True and False`',
        }
        expected: Dict[str, Primitive] = {
            'calculated_int': 2,
            'calculated_string': 'hello world',
            'calculated_float': 6.28,
            'calculated_bool': False,
        }
        assert expand_vars(input_vars) == expected

    def test_expand_vars_escaped_strings(self):
        """Test expanding variables with escaped strings."""
        input_vars: Dict[str, Primitive] = {
            'escaped1': '\\hello',
            'escaped2': '\\py`1+1`',
            'regular': 'world',
        }
        expected: Dict[str, Primitive] = {
            'escaped1': 'hello',
            'escaped2': 'py`1+1`',
            'regular': 'world',
        }
        assert expand_vars(input_vars) == expected

    def test_expand_vars_comprehensive_example(self):
        """Test a comprehensive example with various variable types."""
        input_vars: Dict[str, Primitive] = {
            'name': 'py`"John"`',
            'age': 'py`25 + 5`',
            'height': 'py`180.5`',
            'is_student': 'py`False`',
            'escaped_value': '\\py`not_evaluated`',
            'regular_string': 'just a string',
            'raw_number': 42,
        }
        expected: Dict[str, Primitive] = {
            'name': 'John',
            'age': 30,
            'height': 180.5,
            'is_student': False,
            'escaped_value': 'py`not_evaluated`',
            'regular_string': 'just a string',
            'raw_number': 42,
        }
        assert expand_vars(input_vars) == expected

    def test_expand_vars_error_propagation(self):
        """Test that errors in individual variables are propagated."""
        input_vars: Dict[str, Primitive] = {
            'good_var': 'py`42`',
            'bad_var': 'py`[1, 2, 3]`',  # Unsupported type
        }

        with pytest.raises(
            TypeError,
            match='Variable with backticks should evaluate to a primitive Python type',
        ):
            expand_vars(input_vars)

    def test_expand_vars_preserves_key_order(self):
        """Test that the function preserves the order of keys."""
        input_vars: Dict[str, Primitive] = {
            'first': 'py`1`',
            'second': 'py`2`',
            'third': 'py`3`',
        }
        result = expand_vars(input_vars)
        assert list(result.keys()) == ['first', 'second', 'third']
        assert result == {'first': 1, 'second': 2, 'third': 3}
