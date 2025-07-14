import pathlib

import pytest

from rbx.box import header
from rbx.box.testing import testing_package


class TestHeader:
    """Tests for the header.py module."""

    def test_generate_header_with_no_variables(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test generate_header with a package that has no variables."""
        # Generate header with no variables
        header.generate_header()

        # Check that rbx.h file was created
        rbx_header_path = pathlib.Path('rbx.h')
        assert rbx_header_path.exists()

        # Read the generated header
        generated_content = rbx_header_path.read_text()

        # Check that the header contains the expected structure
        assert (
            'std::optional<std::string> getStringVar(std::string name)'
            in generated_content
        )
        assert 'std::optional<int64_t> getIntVar(std::string name)' in generated_content
        assert 'std::optional<float> getFloatVar(std::string name)' in generated_content
        assert 'std::optional<bool> getBoolVar(std::string name)' in generated_content

        # Since there are no variables, the functions should only return nullopt
        assert 'return std::nullopt;' in generated_content

    def test_generate_header_with_string_variables(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test generate_header with string variables."""
        # Set some string variables
        testing_pkg.set_vars(
            {
                'str_var1': 'hello',
                'str_var2': 'world with spaces',
                'str_var3': 'special"chars',
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Check that string variables are properly escaped and included
        assert (
            'if (name == "str_var1") {\n    return "hello";\n  }' in generated_content
        )
        assert (
            'if (name == "str_var2") {\n    return "world with spaces";\n  }'
            in generated_content
        )
        assert (
            'if (name == "str_var3") {\n    return "special\\"chars";\n  }'
            in generated_content
        )

    def test_generate_header_with_int_variables(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test generate_header with integer variables."""
        testing_pkg.set_vars(
            {
                'int_var1': 42,
                'int_var2': -100,
                'int_var3': 0,
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Check that integer variables are properly included
        assert (
            'if (name == "int_var1") {\n    return static_cast<int64_t>(42);\n  }'
            in generated_content
        )
        assert (
            'if (name == "int_var2") {\n    return static_cast<int64_t>(-100);\n  }'
            in generated_content
        )
        assert (
            'if (name == "int_var3") {\n    return static_cast<int64_t>(0);\n  }'
            in generated_content
        )

    def test_generate_header_with_float_variables(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test generate_header with float variables."""
        testing_pkg.set_vars(
            {
                'float_var1': 3.14,
                'float_var2': -2.5,
                'float_var3': 0.0,
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Check that float variables are properly included
        assert 'if (name == "float_var1") {\n    return 3.14;\n  }' in generated_content
        assert 'if (name == "float_var2") {\n    return -2.5;\n  }' in generated_content
        assert 'if (name == "float_var3") {\n    return 0.0;\n  }' in generated_content

    def test_generate_header_with_bool_variables(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test generate_header with boolean variables."""
        testing_pkg.set_vars(
            {
                'bool_var1': True,
                'bool_var2': False,
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Check that boolean variables are properly included
        assert 'if (name == "bool_var1") {\n    return true;\n  }' in generated_content
        assert 'if (name == "bool_var2") {\n    return false;\n  }' in generated_content

    def test_generate_header_with_mixed_variables(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test generate_header with variables of different types."""
        testing_pkg.set_vars(
            {
                'str_var': 'test',
                'int_var': 123,
                'float_var': 45.67,
                'bool_var': True,
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Check that all variable types are included in their respective functions
        assert 'if (name == "str_var") {\n    return "test";\n  }' in generated_content
        assert (
            'if (name == "int_var") {\n    return static_cast<int64_t>(123);\n  }'
            in generated_content
        )
        assert 'if (name == "float_var") {\n    return 45.67;\n  }' in generated_content
        assert 'if (name == "bool_var") {\n    return true;\n  }' in generated_content

    def test_generate_header_with_override_file(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test generate_header with an override file."""
        override_content = '// This is an override header\n'
        override_path = pathlib.Path('rbx.override.h')
        override_path.write_text(override_content)

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Should use the override content exactly
        assert generated_content == override_content

    def test_get_header_creates_and_returns_path(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test get_header function creates the header and returns the path."""
        result = header.get_header()

        assert isinstance(result, pathlib.Path)
        assert result.name == 'rbx.h'
        assert result.exists()

    def test_get_header_caching(self, testing_pkg: testing_package.TestingPackage):
        """Test that get_header is cached properly."""
        # First call should create the file
        result1 = header.get_header()

        # Modify the file to test caching
        result1.write_text('modified content')

        # Second call should return the same path (cached)
        result2 = header.get_header()

        assert result1 == result2
        assert result2.read_text() == 'modified content'

    def test_check_int_bounds_valid_values(self):
        """Test _check_int_bounds with valid integer values."""
        # These should not raise exceptions
        header.check_int_bounds(0)
        header.check_int_bounds(100)
        header.check_int_bounds(-100)
        header.check_int_bounds(2**63 - 1)  # Max int64_t
        header.check_int_bounds(-(2**63))  # Min int64_t

    def test_check_int_bounds_too_large(self):
        """Test _check_int_bounds with values that are too large."""
        with pytest.raises(
            ValueError, match='too large to fit in a C\\+\\+ 64-bit integer'
        ):
            header.check_int_bounds(2**64)

    def test_check_int_bounds_too_small(self):
        """Test _check_int_bounds with values that are too small."""
        with pytest.raises(
            ValueError, match='too small to fit in a C\\+\\+ 64-bit signed integer'
        ):
            header.check_int_bounds(-(2**63) - 1)

    def test_generate_header_with_large_int_fails(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that generate_header fails with integers that are too large."""
        testing_pkg.set_vars(
            {
                'large_int': 2**64,  # Too large for int64_t
            }
        )

        with pytest.raises(
            ValueError, match='too large to fit in a C\\+\\+ 64-bit integer'
        ):
            header.generate_header()

    def test_generate_header_with_small_int_fails(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that generate_header fails with integers that are too small."""
        testing_pkg.set_vars(
            {
                'small_int': -(2**63) - 1,  # Too small for int64_t
            }
        )

        with pytest.raises(
            ValueError, match='too small to fit in a C\\+\\+ 64-bit signed integer'
        ):
            header.generate_header()

    def test_generate_header_deterministic_order(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that generate_header produces variables in deterministic order."""
        testing_pkg.set_vars(
            {
                'z_var': 'last',
                'a_var': 'first',
                'm_var': 'middle',
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Variables should be in alphabetical order
        a_pos = generated_content.find('if (name == "a_var")')
        m_pos = generated_content.find('if (name == "m_var")')
        z_pos = generated_content.find('if (name == "z_var")')

        assert a_pos < m_pos < z_pos

    def test_string_repr_escaping(self, testing_pkg: testing_package.TestingPackage):
        """Test that string variables with special characters are properly escaped in generated header."""
        # Set variables with various special characters that need escaping
        testing_pkg.set_vars(
            {
                'simple_string': 'simple',
                'string_with_spaces': 'with spaces',
                'string_with_quotes': 'with"quotes',
                'string_with_backslash': 'with\\backslash',
                'string_with_newline': 'with\nnewline',
                'string_with_tab': 'with\ttab',
                'string_with_return': 'with\rreturn',
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Check that all string variables are properly escaped in the generated header
        assert (
            'if (name == "simple_string") {\n    return "simple";\n  }'
            in generated_content
        )
        assert (
            'if (name == "string_with_spaces") {\n    return "with spaces";\n  }'
            in generated_content
        )
        assert (
            'if (name == "string_with_quotes") {\n    return "with\\"quotes";\n  }'
            in generated_content
        )
        assert (
            'if (name == "string_with_backslash") {\n    return "with\\\\backslash";\n  }'
            in generated_content
        )
        assert (
            'if (name == "string_with_newline") {\n    return "with\\nnewline";\n  }'
            in generated_content
        )
        assert (
            'if (name == "string_with_tab") {\n    return "with\\ttab";\n  }'
            in generated_content
        )
        assert (
            'if (name == "string_with_return") {\n    return "with\\rreturn";\n  }'
            in generated_content
        )

    def test_generate_header_bool_as_int_in_int_block(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that bool variables are handled correctly in int context."""
        testing_pkg.set_vars(
            {
                'bool_true': True,
                'bool_false': False,
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Booleans should appear in both bool and int blocks
        # In int block, they should be converted to 1/0
        assert (
            'if (name == "bool_true") {\n    return static_cast<int64_t>(1);\n  }'
            in generated_content
        )
        assert (
            'if (name == "bool_false") {\n    return static_cast<int64_t>(0);\n  }'
            in generated_content
        )

        # In bool block, they should be true/false
        assert 'if (name == "bool_true") {\n    return true;\n  }' in generated_content
        assert (
            'if (name == "bool_false") {\n    return false;\n  }' in generated_content
        )
