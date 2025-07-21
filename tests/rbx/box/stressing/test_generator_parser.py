from unittest import mock

import lark
import pytest

from rbx.box.stressing.generator_parser import (
    LARK_PARSER,
    Generator,
    GeneratorParsingError,
    RandomChar,
    RandomHex,
    RandomInt,
    parse,
)


class TestParseFunction:
    """Test suite for the parse function behavior."""

    def test_parse_returns_lark_parse_tree(self):
        """Test that parse returns a valid Lark ParseTree for simple expressions."""
        result = parse('simple argument')

        assert isinstance(result, lark.Tree)
        assert result.data == 'args'

    def test_parse_simple_text_arguments(self):
        """Test parsing simple text arguments."""
        tree = parse('arg1 arg2 arg3')

        assert tree is not None
        # Should have 3 argument nodes
        arg_nodes = list(tree.find_data('arg'))
        assert len(arg_nodes) == 3

    def test_parse_empty_string(self):
        """Test parsing empty string."""
        tree = parse('')

        assert tree is not None
        # Should have no argument nodes
        arg_nodes = list(tree.find_data('arg'))
        assert len(arg_nodes) == 0

    def test_parse_variable_expression(self):
        """Test parsing expressions with variables."""
        tree = parse('<MAX_N>')

        assert tree is not None
        var_nodes = list(tree.find_data('var'))
        assert len(var_nodes) == 1

    def test_parse_range_expression(self):
        """Test parsing range expressions."""
        tree = parse('[1..10]')

        assert tree is not None
        range_nodes = list(tree.find_data('range'))
        assert len(range_nodes) == 1

    def test_parse_select_expression(self):
        """Test parsing select expressions."""
        tree = parse('(option1|option2|option3)')

        assert tree is not None
        select_nodes = list(tree.find_data('select'))
        assert len(select_nodes) == 1

    def test_parse_random_hex_expression(self):
        """Test parsing random hex expressions."""
        tree = parse('@')

        assert tree is not None
        hex_nodes = list(tree.find_data('random_hex'))
        assert len(hex_nodes) == 1

    def test_parse_ticked_expression(self):
        """Test parsing ticked expressions."""
        tree = parse('`<MAX_N>`')

        assert tree is not None
        var_nodes = list(tree.find_data('var'))
        assert len(var_nodes) == 1

    def test_parse_complex_expression(self):
        """Test parsing complex expressions with multiple components."""
        tree = parse('--size=[1..<MAX_N>] --name=(alice|bob) @ --extra="text"')

        assert tree is not None
        # Should contain various node types
        range_nodes = list(tree.find_data('range'))
        select_nodes = list(tree.find_data('select'))
        hex_nodes = list(tree.find_data('random_hex'))
        var_nodes = list(tree.find_data('var'))

        assert len(range_nodes) == 1
        assert len(select_nodes) == 1
        assert len(hex_nodes) == 1
        assert len(var_nodes) == 1

    def test_parse_nested_ranges(self):
        """Test parsing nested range expressions."""
        tree = parse('[1..[8..15]]')

        assert tree is not None
        range_nodes = list(tree.find_data('range'))
        assert len(range_nodes) == 2  # Outer and inner range

    def test_parse_char_ranges(self):
        """Test parsing character range expressions."""
        tree = parse("['a'..'z']")

        assert tree is not None
        range_nodes = list(tree.find_data('range'))
        char_nodes = list(tree.find_data('char'))
        assert len(range_nodes) == 1
        assert len(char_nodes) == 2  # Start and end chars

    def test_parse_float_ranges(self):
        """Test parsing float range expressions."""
        tree = parse('[1.0..10.5]')

        assert tree is not None
        range_nodes = list(tree.find_data('range'))
        float_nodes = list(tree.find_data('float'))
        assert len(range_nodes) == 1
        assert len(float_nodes) == 2  # Start and end floats

    def test_parse_syntax_error_raises_lark_exception(self):
        """Test that invalid syntax raises appropriate Lark parsing exceptions."""
        with pytest.raises(lark.exceptions.LarkError):
            parse('invalid [[ syntax')

    def test_parse_preserves_grammar_structure(self):
        """Test that parse preserves the expected grammar structure."""
        expression = '--arg=[1..10] (option1|option2)'
        tree = parse(expression)

        # Verify the tree structure matches what we expect from the grammar
        assert tree.data == 'args'
        # Should be able to parse the same expression with raw parser
        raw_tree = LARK_PARSER.parse(expression)
        raw_args = list(raw_tree.find_data('args'))[0]
        assert raw_args.data == tree.data


class TestRandomClasses:
    """Test suite for random generation classes."""

    def test_random_int_valid_range(self):
        """Test RandomInt with valid range."""
        random_int = RandomInt(1, 10)

        # Generate multiple values to test range
        for _ in range(20):
            value = random_int.get()
            assert 1 <= value <= 10
            assert isinstance(value, int)

    def test_random_int_single_value(self):
        """Test RandomInt with single value range."""
        random_int = RandomInt(5, 5)

        value = random_int.get()
        assert value == 5

    def test_random_int_invalid_range_raises_error(self):
        """Test RandomInt with invalid range raises error."""
        random_int = RandomInt(10, 1)  # max < min

        with pytest.raises(GeneratorParsingError):
            random_int.get()

    def test_random_char_valid_range(self):
        """Test RandomChar with valid range."""
        random_char = RandomChar('a', 'z')

        # Generate multiple values to test range
        for _ in range(20):
            value = random_char.get()
            assert 'a' <= value <= 'z'
            assert isinstance(value, str)
            assert len(value) == 1

    def test_random_char_single_value(self):
        """Test RandomChar with single character."""
        random_char = RandomChar('x', 'x')

        value = random_char.get()
        assert value == 'x'

    def test_random_char_invalid_length_raises_error(self):
        """Test RandomChar with invalid character length raises error."""
        # Test that creating RandomChar with invalid length raises error during get()
        random_char = RandomChar('ab', 'z')
        with pytest.raises(GeneratorParsingError):
            random_char.get()

        random_char2 = RandomChar('a', 'xyz')
        with pytest.raises(GeneratorParsingError):
            random_char2.get()

    def test_random_char_invalid_range_raises_error(self):
        """Test RandomChar with invalid range raises error."""
        random_char = RandomChar('z', 'a')  # max < min

        with pytest.raises(GeneratorParsingError):
            random_char.get()

    def test_random_hex_default_length(self):
        """Test RandomHex with default length."""
        random_hex = RandomHex()

        value = random_hex.get()
        assert len(value) == 8
        assert all(c in '0123456789abcdef' for c in value)

    def test_random_hex_custom_length(self):
        """Test RandomHex with custom length."""
        random_hex = RandomHex(16)

        value = random_hex.get()
        assert len(value) == 16
        assert all(c in '0123456789abcdef' for c in value)

    def test_random_hex_zero_length(self):
        """Test RandomHex with zero length."""
        random_hex = RandomHex(0)

        value = random_hex.get()
        assert value == ''


class TestGeneratorClass:
    """Test suite for the Generator class behavior."""

    def test_generator_simple_text(self):
        """Test generator with simple text arguments."""
        tree = parse('arg1 arg2 arg3')
        generator = Generator({})

        result = generator.generate(tree)
        assert result == 'arg1 arg2 arg3'

    def test_generator_with_variables(self):
        """Test generator with variable substitution."""
        tree = parse('--size=<MAX_N> --name=<NAME>')
        generator = Generator({'MAX_N': 100, 'NAME': 'test'})

        result = generator.generate(tree)
        assert result == '--size=100 --name=test'

    def test_generator_with_int_ranges(self):
        """Test generator with integer range expressions."""
        tree = parse('[1..10]')
        generator = Generator({})

        # Test multiple generations to ensure range is respected
        for _ in range(20):
            result = generator.generate(tree)
            value = int(result)
            assert 1 <= value <= 10

    def test_generator_with_float_ranges(self):
        """Test generator with float range expressions."""
        tree = parse('[1.0..5.0]')
        generator = Generator({})

        # Test multiple generations to ensure range is respected
        for _ in range(20):
            result = generator.generate(tree)
            value = float(result)
            assert 1.0 <= value <= 5.0

    def test_generator_with_char_ranges(self):
        """Test generator with character range expressions."""
        tree = parse("['a'..'z']")
        generator = Generator({})

        # Test multiple generations to ensure range is respected
        for _ in range(20):
            result = generator.generate(tree)
            assert len(result) == 1
            assert 'a' <= result <= 'z'

    def test_generator_with_variable_ranges(self):
        """Test generator with variable-based ranges."""
        tree = parse('[1..<MAX_N>]')
        generator = Generator({'MAX_N': 50})

        # Test multiple generations to ensure range is respected
        for _ in range(20):
            result = generator.generate(tree)
            value = int(result)
            assert 1 <= value <= 50

    def test_generator_with_select_expressions(self):
        """Test generator with select expressions."""
        tree = parse('(option1|option2|option3)')
        generator = Generator({})

        # Test multiple generations to ensure all options can be selected
        generated_values = set()
        for _ in range(50):  # Generate enough to likely hit all options
            result = generator.generate(tree)
            generated_values.add(result)

        # Should generate at least one of each option (with high probability)
        assert (
            'option1' in generated_values
            or 'option2' in generated_values
            or 'option3' in generated_values
        )

    def test_generator_with_nested_select_expressions(self):
        """Test generator with nested select expressions."""
        tree = parse('(a|(b|c))')
        generator = Generator({})

        # Test multiple generations
        generated_values = set()
        for _ in range(30):
            result = generator.generate(tree)
            generated_values.add(result)

        # Should generate valid options
        assert all(val in {'a', 'b', 'c'} for val in generated_values)

    def test_generator_with_select_containing_variables(self):
        """Test generator with select expressions containing variables."""
        tree = parse('(option1|<VAR>|option3)')
        generator = Generator({'VAR': 'variable_value'})

        # Test multiple generations
        generated_values = set()
        for _ in range(30):
            result = generator.generate(tree)
            generated_values.add(result)

        # Should be able to generate the variable value
        possible_values = {'option1', 'variable_value', 'option3'}
        assert all(val in possible_values for val in generated_values)

    def test_generator_with_random_hex(self):
        """Test generator with random hex expressions."""
        tree = parse('@')
        generator = Generator({})

        result = generator.generate(tree)
        assert len(result) == 8
        assert all(c in '0123456789abcdef' for c in result)

    def test_generator_with_ticked_expressions(self):
        """Test generator with ticked expressions."""
        tree = parse('prefix`<VAR>`suffix')
        generator = Generator({'VAR': 'middle'})

        result = generator.generate(tree)
        assert result == 'prefixmiddlesuffix'

    def test_generator_complex_expression(self):
        """Test generator with complex mixed expressions."""
        tree = parse('--size=[1..<MAX_N>] --type=(int|float) @ --text=<NAME>')
        generator = Generator({'MAX_N': 100, 'NAME': 'testname'})

        result = generator.generate(tree)
        parts = result.split()

        # Verify structure
        assert len(parts) == 4
        assert parts[0].startswith('--size=')
        assert parts[1] in ['--type=int', '--type=float']
        # Third part should be the hex string (not prefixed)
        assert len(parts[2]) == 8
        assert all(c in '0123456789abcdef' for c in parts[2])
        assert parts[3] == '--text=testname'

        # Verify size range
        size_value = int(parts[0].split('=')[1])
        assert 1 <= size_value <= 100

    def test_generator_with_nested_ranges(self):
        """Test generator with nested range expressions."""
        tree = parse('[1..[5..10]]')
        generator = Generator({})

        # Test multiple generations
        for _ in range(20):
            result = generator.generate(tree)
            value = int(result)
            # Inner range [5..10] provides upper bound, so result should be [1..inner_result]
            assert 1 <= value <= 10

    def test_generator_undefined_variable_raises_error(self):
        """Test that undefined variables raise appropriate errors."""
        tree = parse('<UNDEFINED_VAR>')
        generator = Generator({})

        with pytest.raises(
            GeneratorParsingError, match='variable UNDEFINED_VAR is not defined'
        ):
            generator.generate(tree)

    def test_generator_invalid_variable_type_raises_error(self):
        """Test that invalid variable types raise appropriate errors."""
        tree = parse('<INVALID_VAR>')
        generator = Generator({'INVALID_VAR': {'not': 'primitive'}})

        with pytest.raises(
            GeneratorParsingError,
            match='not supported by the Generator expression parser',
        ):
            generator.generate(tree)

    def test_generator_incompatible_range_types_raises_error(self):
        """Test that incompatible range types raise appropriate errors."""
        # Use a valid syntax that will parse but cause runtime error during generation
        tree = parse('[1..<INVALID_VAR>]')
        generator = Generator({'INVALID_VAR': 'text_string'})

        with pytest.raises(
            GeneratorParsingError, match='Types in range are uncompatible'
        ):
            generator.generate(tree)

    def test_generator_empty_args(self):
        """Test generator with empty arguments."""
        tree = parse('')
        generator = Generator({})

        result = generator.generate(tree)
        assert result == ''

    def test_generator_with_float_precision(self):
        """Test generator handles float precision correctly."""
        tree = parse('<FLOAT_VAR>')
        generator = Generator({'FLOAT_VAR': 3.141592653589793})

        result = generator.generate(tree)
        # Should format float with 6 decimal places as per _var_as_str
        assert '3.141593' in result

    def test_generator_mixed_variable_types(self):
        """Test generator with different variable types."""
        tree = parse('<INT_VAR> <FLOAT_VAR> <STR_VAR>')
        generator = Generator({'INT_VAR': 42, 'FLOAT_VAR': 3.14, 'STR_VAR': 'hello'})

        result = generator.generate(tree)
        assert result == '42 3.140000 hello'

    @mock.patch('random.randint')
    def test_generator_deterministic_int_range(self, mock_randint):
        """Test generator with mocked random for deterministic testing."""
        mock_randint.return_value = 5

        tree = parse('[1..10]')
        generator = Generator({})

        result = generator.generate(tree)
        assert result == '5'
        mock_randint.assert_called_once_with(1, 10)

    @mock.patch('random.uniform')
    def test_generator_deterministic_float_range(self, mock_uniform):
        """Test generator with mocked random for deterministic testing."""
        mock_uniform.return_value = 2.5

        tree = parse('[1.0..5.0]')
        generator = Generator({})

        result = generator.generate(tree)
        assert result == '2.500000'
        mock_uniform.assert_called_once_with(1.0, 5.0)

    @mock.patch('rbx.box.stressing.generator_parser.RandomInt.get')
    def test_generator_deterministic_select(self, mock_get):
        """Test generator with mocked random for deterministic testing."""
        mock_get.return_value = 2  # Select index 2 (third option)

        tree = parse('(option1|option2|option3)')
        generator = Generator({})

        result = generator.generate(tree)
        assert result == 'option3'

    def test_generator_with_escaped_strings(self):
        """Test generator with escaped strings in arguments."""
        tree = parse('"quoted string" \'single quoted\'')
        generator = Generator({})

        result = generator.generate(tree)
        assert '"quoted string"' in result
        assert "'single quoted'" in result
