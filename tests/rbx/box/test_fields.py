import pytest
import simpleeval

from rbx.box.fields import RecVars, expand_var, expand_vars


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
            simpleeval.FeatureNotAvailable,
        ):
            expand_var('py`[1, 2, 3]`')

        with pytest.raises(
            simpleeval.FeatureNotAvailable,
        ):
            expand_var('py`{"key": "value"}`')

        with pytest.raises(
            TypeError,
        ):
            expand_var('py`None`')

    def test_expand_var_invalid_python_expressions(self):
        """Test that invalid Python expressions raise appropriate errors."""
        with pytest.raises(SyntaxError):
            expand_var('py`1 +`')

        with pytest.raises(simpleeval.NameNotDefined):
            expand_var('py`undefined_variable`')

        with pytest.raises(ZeroDivisionError):
            expand_var('py`1 / 0`')

    def test_expand_var_edge_cases(self):
        """Test edge cases with backtick expressions."""
        # Empty expression
        with pytest.raises(simpleeval.InvalidExpression):
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

    def test_expand_vars_flat_primitive_values(self):
        """Test expanding flat dictionary with primitive values."""
        input_vars: RecVars = {
            'string_var': 'hello',
            'int_var': 42,
            'float_var': 3.14,
            'bool_var': True,
        }
        expected = {
            'string_var': 'hello',
            'int_var': 42,
            'float_var': 3.14,
            'bool_var': True,
        }
        assert expand_vars(input_vars) == expected

    def test_expand_vars_flat_python_expressions(self):
        """Test expanding flat dictionary with Python expressions."""
        input_vars: RecVars = {
            'calculated_int': 'py`1 + 1`',
            'calculated_string': 'py`"hello" + " world"`',
            'calculated_float': 'py`3.14 * 2`',
            'calculated_bool': 'py`True and False`',
        }
        expected = {
            'calculated_int': 2,
            'calculated_string': 'hello world',
            'calculated_float': 6.28,
            'calculated_bool': False,
        }
        assert expand_vars(input_vars) == expected

    def test_expand_vars_flat_escaped_strings(self):
        """Test expanding flat dictionary with escaped strings."""
        input_vars: RecVars = {
            'escaped1': '\\hello',
            'escaped2': '\\py`1+1`',
            'regular': 'world',
        }
        expected = {
            'escaped1': 'hello',
            'escaped2': 'py`1+1`',
            'regular': 'world',
        }
        assert expand_vars(input_vars) == expected

    def test_expand_vars_single_level_nesting(self):
        """Test expanding dictionary with one level of nesting."""
        input_vars: RecVars = {
            'root_var': 'py`42`',
            'config': {
                'name': 'py`"test"`',
                'timeout': 'py`30`',
                'enabled': 'py`True`',
            },
        }
        expected = {
            'root_var': 42,
            'config.name': 'test',
            'config.timeout': 30,
            'config.enabled': True,
        }
        assert expand_vars(input_vars) == expected

    def test_expand_vars_multiple_level_nesting(self):
        """Test expanding dictionary with multiple levels of nesting."""
        input_vars: RecVars = {
            'app': {
                'database': {
                    'host': 'localhost',
                    'port': 'py`5432`',
                    'credentials': {
                        'username': 'admin',
                        'password': 'py`"secret"`',
                    },
                },
                'cache': {
                    'enabled': 'py`True`',
                    'ttl': 'py`3600`',
                },
            },
            'debug': 'py`False`',
        }
        expected = {
            'app.database.host': 'localhost',
            'app.database.port': 5432,
            'app.database.credentials.username': 'admin',
            'app.database.credentials.password': 'secret',
            'app.cache.enabled': True,
            'app.cache.ttl': 3600,
            'debug': False,
        }
        assert expand_vars(input_vars) == expected

    def test_expand_vars_mixed_nested_and_flat(self):
        """Test expanding dictionary with both nested and flat variables."""
        input_vars: RecVars = {
            'name': 'py`"John"`',
            'age': 'py`25 + 5`',
            'profile': {
                'height': 'py`180.5`',
                'is_student': 'py`False`',
                'address': {
                    'city': 'New York',
                    'zip_code': 'py`10001`',
                },
            },
            'escaped_value': '\\py`not_evaluated`',
            'regular_string': 'just a string',
            'raw_number': 42,
        }
        expected = {
            'name': 'John',
            'age': 30,
            'profile.height': 180.5,
            'profile.is_student': False,
            'profile.address.city': 'New York',
            'profile.address.zip_code': 10001,
            'escaped_value': 'py`not_evaluated`',
            'regular_string': 'just a string',
            'raw_number': 42,
        }
        assert expand_vars(input_vars) == expected

    def test_expand_vars_empty_nested_dict(self):
        """Test expanding dictionary with empty nested dictionaries."""
        input_vars: RecVars = {
            'config': {},
            'settings': {
                'nested': {},
            },
            'value': 'py`42`',
        }
        expected = {
            'value': 42,
        }
        assert expand_vars(input_vars) == expected

    def test_expand_vars_deep_nesting(self):
        """Test expanding dictionary with very deep nesting."""
        input_vars: RecVars = {
            'level1': {
                'level2': {
                    'level3': {
                        'level4': {
                            'level5': {
                                'deep_value': 'py`"deep"`',
                            },
                        },
                    },
                },
            },
        }
        expected = {
            'level1.level2.level3.level4.level5.deep_value': 'deep',
        }
        assert expand_vars(input_vars) == expected

    def test_expand_vars_special_key_names(self):
        """Test expanding dictionary with special characters in keys."""
        input_vars: RecVars = {
            'key_with_underscore': 'py`1`',
            'key-with-dash': 'py`2`',
            'nested': {
                'CamelCase': 'py`3`',
                'UPPER_CASE': 'py`4`',
                'with123numbers': 'py`5`',
            },
        }
        expected = {
            'key_with_underscore': 1,
            'key-with-dash': 2,
            'nested.CamelCase': 3,
            'nested.UPPER_CASE': 4,
            'nested.with123numbers': 5,
        }
        assert expand_vars(input_vars) == expected

    def test_expand_vars_error_propagation_nested(self):
        """Test that errors in nested variables are propagated."""
        input_vars: RecVars = {
            'good_var': 'py`42`',
            'nested': {
                'bad_var': 'py`[1, 2, 3]`',  # Unsupported type
            },
        }

        with pytest.raises(
            simpleeval.FeatureNotAvailable,
        ):
            expand_vars(input_vars)

    def test_expand_vars_error_propagation_deep_nested(self):
        """Test that errors in deeply nested variables are propagated."""
        input_vars: RecVars = {
            'level1': {
                'level2': {
                    'good_var': 'py`"hello"`',
                    'bad_var': 'py`undefined_variable`',  # NameError
                },
            },
        }

        with pytest.raises(simpleeval.NameNotDefined):
            expand_vars(input_vars)

    def test_expand_vars_preserves_key_order_flat(self):
        """Test that the function preserves the order of keys in flat dictionaries."""
        input_vars: RecVars = {
            'first': 'py`1`',
            'second': 'py`2`',
            'third': 'py`3`',
        }
        result = expand_vars(input_vars)
        assert list(result.keys()) == ['first', 'second', 'third']
        assert result == {'first': 1, 'second': 2, 'third': 3}

    def test_expand_vars_preserves_key_order_nested(self):
        """Test that the function preserves the order of keys in nested dictionaries."""
        input_vars: RecVars = {
            'first': 'py`1`',
            'nested': {
                'alpha': 'py`"a"`',
                'beta': 'py`"b"`',
            },
            'second': 'py`2`',
        }
        result = expand_vars(input_vars)
        expected_keys = ['first', 'nested.alpha', 'nested.beta', 'second']
        assert list(result.keys()) == expected_keys

    def test_expand_vars_comprehensive_example(self):
        """Test a comprehensive example showcasing all features."""
        input_vars: RecVars = {
            'app_name': 'py`"MyApp"`',
            'version': 'py`1.0`',
            'server': {
                'host': 'localhost',
                'port': 'py`8080`',
                'ssl': {
                    'enabled': 'py`True`',
                    'cert_path': '\\py`not_expanded`',  # Escaped
                    'config': {
                        'timeout': 'py`30 * 1000`',  # 30 seconds in ms
                    },
                },
            },
            'features': {
                'auth': 'py`True`',
                'cache': 'py`False`',
            },
            'raw_config': 'not_a_python_expression',
            'calculated': 'py`len("hello") * 2`',
        }
        expected = {
            'app_name': 'MyApp',
            'version': 1.0,
            'server.host': 'localhost',
            'server.port': 8080,
            'server.ssl.enabled': True,
            'server.ssl.cert_path': 'py`not_expanded`',
            'server.ssl.config.timeout': 30000,
            'features.auth': True,
            'features.cache': False,
            'raw_config': 'not_a_python_expression',
            'calculated': 10,
        }
        assert expand_vars(input_vars) == expected
