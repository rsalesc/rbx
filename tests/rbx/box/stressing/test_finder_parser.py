import lark
import pytest
import typer

from rbx.box.schema import ExpectedOutcome
from rbx.box.stressing.finder_parser import (
    LARK_PARSER,
    get_all_checker_items,
    get_all_checkers,
    get_all_solution_items,
    get_all_solutions,
    needs_expected_output,
    parse,
    validate,
)
from rbx.box.testing import testing_package


class TestParseFunction:
    """Test suite for the parse function behavior."""

    def test_parse_returns_lark_parse_tree(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that parse returns a valid Lark ParseTree for simple expressions."""
        # Setup a basic problem package with solution and checker
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text(
            '#include <iostream>\nint main() { std::cout << "Hello" << std::endl; return 0; }'
        )
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        # Parse a simple expression
        result = parse('sol.cpp')

        # Should return a ParseTree
        assert isinstance(result, lark.Tree)
        assert result.data == 'start'

    def test_parse_simple_solution_name(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test parsing simple solution file names."""
        testing_pkg.add_solution(
            'main.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('main.cpp')

        # Should successfully parse and validate
        assert tree is not None
        # Check that it can find solution nodes
        solution_nodes = list(tree.find_data('solution'))
        assert len(solution_nodes) > 0

    def test_parse_solution_with_checker_expression(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test parsing solution with checker specification."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('check.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('[sol.cpp on check.cpp]')

        assert tree is not None
        # Should have both eval and checking nodes
        eval_nodes = list(tree.find_data('eval'))
        assert len(eval_nodes) > 0

    def test_parse_matching_expression(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test parsing solution matching against expected outcomes."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('[sol.cpp] ~ CORRECT')

        assert tree is not None
        matching_nodes = list(tree.find_data('matching'))
        assert len(matching_nodes) > 0

    def test_parse_equality_expression(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test parsing solution equality comparisons."""
        testing_pkg.add_solution(
            'sol1.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.add_solution(
            'sol2.cpp', outcome=ExpectedOutcome.WRONG_ANSWER
        ).write_text('#include <iostream>\nint main() { return 1; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('[sol1.cpp] == [sol2.cpp]')

        assert tree is not None
        equating_nodes = list(tree.find_data('equating'))
        assert len(equating_nodes) > 0

    def test_parse_complex_logical_expression(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test parsing complex expressions with logical operators."""
        testing_pkg.add_solution(
            'sol1.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.add_solution(
            'sol2.cpp', outcome=ExpectedOutcome.WRONG_ANSWER
        ).write_text('#include <iostream>\nint main() { return 1; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('[sol1.cpp] ~ CORRECT && [sol2.cpp] ~ INCORRECT')

        assert tree is not None
        conjunction_nodes = list(tree.find_data('conjunction'))
        assert len(conjunction_nodes) > 0

    def test_parse_disjunction_expression(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test parsing expressions with OR operators."""
        testing_pkg.add_solution(
            'sol1.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.add_solution(
            'sol2.cpp', outcome=ExpectedOutcome.WRONG_ANSWER
        ).write_text('#include <iostream>\nint main() { return 1; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('[sol1.cpp] ~ CORRECT || [sol2.cpp] ~ CORRECT')

        assert tree is not None
        disjunction_nodes = list(tree.find_data('disjunction'))
        assert len(disjunction_nodes) > 0

    def test_parse_negation_expression(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test parsing expressions with negation."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('!([sol.cpp] ~ CORRECT)')

        assert tree is not None
        negation_nodes = list(tree.find_data('negation'))
        assert len(negation_nodes) > 0

    def test_parse_wildcard_solution(self, testing_pkg: testing_package.TestingPackage):
        """Test parsing expressions with wildcard solution references."""
        testing_pkg.add_solution(
            'main.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('$')

        assert tree is not None
        # Should successfully parse wildcard
        solution_nodes = list(tree.find_data('solution'))
        assert len(solution_nodes) > 0

    def test_parse_two_way_checking_mode(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test parsing expressions with explicit two-way checking mode."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('[sol.cpp on 2:checker.cpp]')

        assert tree is not None
        checking_nodes = list(tree.find_data('checking'))
        assert len(checking_nodes) > 0

    def test_parse_nil_checker(self, testing_pkg: testing_package.TestingPackage):
        """Test parsing expressions with nil checker specification."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.save()

        tree = parse('[sol.cpp on :nil]')

        assert tree is not None
        checking_nodes = list(tree.find_data('checking'))
        assert len(checking_nodes) > 0

    def test_parse_quoted_filenames(self, testing_pkg: testing_package.TestingPackage):
        """Test parsing expressions with quoted file names."""
        solution_file = testing_pkg.add_solution(
            'sol-file.cpp', outcome=ExpectedOutcome.ACCEPTED
        )
        solution_file.write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('"sol-file.cpp"')

        assert tree is not None
        solution_nodes = list(tree.find_data('solution'))
        assert len(solution_nodes) > 0

    def test_parse_validation_fails_for_missing_solution(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that parse validation fails when referencing non-existing solutions."""
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        with pytest.raises(typer.Exit):
            parse('nonexistent.cpp')

    def test_parse_validation_fails_for_missing_checker(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that parse validation fails when referencing non-existing checkers."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.save()

        with pytest.raises(typer.Exit):
            parse('[sol.cpp on nonexistent.cpp]')

    def test_parse_validation_fails_for_three_way_without_main_solution(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that parse validation fails for three-way checking without main solution."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.WRONG_ANSWER
        ).write_text(  # Not main solution
            '#include <iostream>\nint main() { return 1; }'
        )
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        with pytest.raises(typer.Exit):
            parse('[sol.cpp on checker.cpp]')  # Default is three-way checking

    def test_parse_validation_succeeds_for_two_way_without_main_solution(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that parse validation succeeds for two-way checking without main solution."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.WRONG_ANSWER
        ).write_text(  # Not main solution
            '#include <iostream>\nint main() { return 1; }'
        )
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        # Should not raise an exception
        tree = parse('[sol.cpp on 2:checker.cpp]')
        assert tree is not None

    def test_parse_syntax_error_raises_lark_exception(self):
        """Test that invalid syntax raises appropriate Lark parsing exceptions."""
        with pytest.raises(lark.exceptions.LarkError):
            parse('invalid syntax [[[')

    def test_parse_empty_string_raises_lark_exception(self):
        """Test that empty input raises appropriate parsing exception."""
        with pytest.raises(lark.exceptions.LarkError):
            parse('')

    def test_parse_preserves_grammar_structure(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that parse preserves the expected grammar structure."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        expression = '[sol.cpp on checker.cpp] ~ CORRECT'
        tree = parse(expression)

        # Verify the tree structure matches what we expect from the grammar
        assert tree.data == 'start'
        # Should be able to parse the same expression with raw parser
        raw_tree = LARK_PARSER.parse(expression)
        assert raw_tree.data == tree.data

    def test_parse_at_prefix_solution(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test parsing solution names with @ prefix."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('@sol.cpp')

        assert tree is not None
        solution_nodes = list(tree.find_data('solution'))
        assert len(solution_nodes) > 0

    def test_parse_different_outcome_types(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test parsing with different outcome and expected outcome types."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        # Test various outcome types
        expressions = [
            '[sol.cpp] ~ ACCEPTED',
            '[sol.cpp] ~ WRONG_ANSWER',
            '[sol.cpp] ~ TIME_LIMIT_EXCEEDED',
            '[sol.cpp] ~ RUNTIME_ERROR',
            '[sol.cpp] !~ INCORRECT',
        ]

        for expr in expressions:
            tree = parse(expr)
            assert tree is not None, f'Failed to parse expression: {expr}'


class TestParseTreeMethods:
    """Test suite for methods that work with ParseTree objects."""

    def test_get_all_solutions_single_solution(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test get_all_solutions with a single solution."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('sol.cpp')
        solutions = get_all_solutions(tree)

        assert 'sol.cpp' in solutions
        assert len(solutions) == 1

    def test_get_all_solutions_multiple_solutions(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test get_all_solutions with multiple solutions in expression."""
        testing_pkg.add_solution(
            'sol1.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.add_solution(
            'sol2.cpp', outcome=ExpectedOutcome.WRONG_ANSWER
        ).write_text('#include <iostream>\nint main() { return 1; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('[sol1.cpp] == [sol2.cpp]')
        solutions = get_all_solutions(tree)

        assert 'sol1.cpp' in solutions
        assert 'sol2.cpp' in solutions
        assert len(solutions) == 2

    def test_get_all_solutions_with_wildcard(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test get_all_solutions with wildcard reference."""
        testing_pkg.add_solution(
            'main.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('$')
        solutions = get_all_solutions(tree)

        assert 'main.cpp' in solutions
        assert len(solutions) == 1

    def test_get_all_solutions_with_three_way_checking_adds_main_solution(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that get_all_solutions adds main solution when three-way checking is needed."""
        testing_pkg.add_solution(
            'main.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.add_solution(
            'other.cpp', outcome=ExpectedOutcome.WRONG_ANSWER
        ).write_text('#include <iostream>\nint main() { return 1; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        # Three-way checking (default) should include main solution
        tree = parse('[other.cpp on checker.cpp]')
        solutions = get_all_solutions(tree)

        assert 'other.cpp' in solutions
        assert 'main.cpp' in solutions  # Main solution should be added
        assert len(solutions) == 2

    def test_get_all_solution_items_returns_code_items(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test get_all_solution_items returns proper CodeItem objects."""
        testing_pkg.add_solution(
            'sol1.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.add_solution(
            'sol2.cpp', outcome=ExpectedOutcome.WRONG_ANSWER
        ).write_text('#include <iostream>\nint main() { return 1; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('[sol1.cpp] == [sol2.cpp]')
        solution_items = get_all_solution_items(tree)

        assert len(solution_items) == 2
        # Should be CodeItem objects with path attributes
        solution_paths = [str(item.path) for item in solution_items]
        assert 'sol1.cpp' in solution_paths
        assert 'sol2.cpp' in solution_paths

    def test_get_all_solution_items_main_solution_first(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that get_all_solution_items puts main solution first."""
        testing_pkg.add_solution(
            'main.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.add_solution(
            'other.cpp', outcome=ExpectedOutcome.WRONG_ANSWER
        ).write_text('#include <iostream>\nint main() { return 1; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('[other.cpp] == [main.cpp]')
        solution_items = get_all_solution_items(tree)

        # Main solution should be first regardless of order in expression
        assert str(solution_items[0].path) == 'main.cpp'

    def test_get_all_checkers_single_checker(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test get_all_checkers with a single checker."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('mycheck.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('[sol.cpp on mycheck.cpp]')
        checkers = get_all_checkers(tree)

        assert 'mycheck.cpp' in checkers
        assert len(checkers) == 1

    def test_get_all_checkers_multiple_checkers(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test get_all_checkers with multiple different checkers."""
        testing_pkg.add_solution(
            'sol1.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.add_solution(
            'sol2.cpp', outcome=ExpectedOutcome.WRONG_ANSWER
        ).write_text('#include <iostream>\nint main() { return 1; }')
        testing_pkg.set_checker('check1.cpp', src='checkers/checker.cpp')
        testing_pkg.add_file('check2.cpp').write_text(
            '#include <iostream>\nint main() { return 0; }'  # Simple checker
        )
        testing_pkg.save()

        tree = parse('[sol1.cpp on check1.cpp] && [sol2.cpp on check2.cpp]')
        checkers = get_all_checkers(tree)

        assert 'check1.cpp' in checkers
        assert 'check2.cpp' in checkers
        assert len(checkers) == 2

    def test_get_all_checkers_with_wildcard_checker(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test get_all_checkers with wildcard checker reference."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('main-checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('[sol.cpp on $]')
        checkers = get_all_checkers(tree)

        assert 'main-checker.cpp' in checkers
        assert len(checkers) == 1

    def test_get_all_checkers_with_nil_checker(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test get_all_checkers with nil checker specification."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.save()

        tree = parse('[sol.cpp on :nil]')
        checkers = get_all_checkers(tree)

        # Should return empty list for nil checker
        assert len(checkers) == 0

    def test_get_all_checker_items_returns_code_items(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test get_all_checker_items returns proper CodeItem objects."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('mycheck.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('[sol.cpp on mycheck.cpp]')
        checker_items = get_all_checker_items(tree)

        assert len(checker_items) == 1
        # Should be CodeItem object with path attribute
        assert str(checker_items[0].path) == 'mycheck.cpp'

    def test_needs_expected_output_true_for_three_way_checking(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test needs_expected_output returns True for three-way checking."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('[sol.cpp on checker.cpp]')  # Default is three-way
        result = needs_expected_output(tree)

        assert result is True

    def test_needs_expected_output_false_for_two_way_checking(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test needs_expected_output returns False for two-way checking."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = parse('[sol.cpp on 2:checker.cpp]')  # Explicit two-way
        result = needs_expected_output(tree)

        assert result is False

    def test_needs_expected_output_false_for_nil_checker(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test needs_expected_output returns False for nil checker."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.save()

        tree = parse('[sol.cpp on :nil]')
        result = needs_expected_output(tree)

        assert result is False

    def test_needs_expected_output_mixed_checking_modes(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test needs_expected_output returns True if any checker uses three-way checking."""
        testing_pkg.add_solution(
            'sol1.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.add_solution(
            'sol2.cpp', outcome=ExpectedOutcome.WRONG_ANSWER
        ).write_text('#include <iostream>\nint main() { return 1; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        # Mix of two-way and three-way checking
        tree = parse('[sol1.cpp on 2:checker.cpp] && [sol2.cpp on checker.cpp]')
        result = needs_expected_output(tree)

        # Should return True because at least one uses three-way checking
        assert result is True

    def test_validate_passes_for_valid_expression(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test validate passes for valid expressions without raising exceptions."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = LARK_PARSER.parse('[sol.cpp on checker.cpp]')

        # Should not raise any exception
        validate(tree)

    def test_validate_fails_for_missing_main_solution_three_way(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test validate fails when three-way checking is needed but no main solution exists."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.WRONG_ANSWER
        ).write_text('#include <iostream>\nint main() { return 1; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = LARK_PARSER.parse('[sol.cpp on checker.cpp]')

        with pytest.raises(typer.Exit):
            validate(tree)

    def test_validate_passes_for_two_way_without_main_solution(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test validate passes for two-way checking even without main solution."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.WRONG_ANSWER
        ).write_text('#include <iostream>\nint main() { return 1; }')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = LARK_PARSER.parse('[sol.cpp on 2:checker.cpp]')

        # Should not raise any exception
        validate(tree)

    def test_validate_fails_for_nonexistent_checker(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test validate fails when referenced checker doesn't exist."""
        testing_pkg.add_solution(
            'sol.cpp', outcome=ExpectedOutcome.ACCEPTED
        ).write_text('#include <iostream>\nint main() { return 0; }')
        testing_pkg.save()

        tree = LARK_PARSER.parse('[sol.cpp on nonexistent.cpp]')

        with pytest.raises(typer.Exit):
            validate(tree)

    def test_validate_fails_for_nonexistent_solution(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test validate fails when referenced solution doesn't exist."""
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')
        testing_pkg.save()

        tree = LARK_PARSER.parse('nonexistent.cpp')

        with pytest.raises(typer.Exit):
            validate(tree)
