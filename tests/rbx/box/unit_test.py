from unittest import mock

import pytest

from rbx.box import unit
from rbx.box.schema import ExpectedOutcome, ValidatorOutcome
from rbx.box.testing import testing_package
from rbx.utils import StatusProgress


@pytest.fixture
def mock_progress():
    """Fixture for creating mock StatusProgress objects."""
    return mock.Mock(spec=StatusProgress)


class TestValidatorUnitTests:
    """Test validator unit test functionality."""

    async def test_no_validator_unit_tests(
        self, testing_pkg: testing_package.TestingPackage, mock_progress, capsys
    ):
        """Test behavior when no validator unit tests are defined."""
        # No unit tests defined, should print message and return
        await unit.run_validator_unit_tests(mock_progress)

        captured = capsys.readouterr()
        assert 'No validator unit tests found.' in captured.out

    async def test_validator_unit_tests_with_valid_inputs(
        self, testing_pkg: testing_package.TestingPackage, mock_progress, capsys
    ):
        """Test validator unit tests with valid inputs."""
        # Set up validator
        testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')

        # Add validator unit tests with inline files
        testing_pkg.add_validator_unit_test(
            glob='unit/validator/valid_*.in',
            outcome=ValidatorOutcome.VALID,
            files={
                'unit/validator/valid_simple.in': '5\n',
                'unit/validator/valid_complex.in': '42\n',
            },
        )

        await unit.run_validator_unit_tests(mock_progress)

        captured = capsys.readouterr()
        # Should print rule and success messages
        assert 'Validator tests' in captured.out
        assert 'OK Unit test #1' in captured.out
        assert 'OK Unit test #2' in captured.out
        assert 'Expected VALID' in captured.out

    async def test_validator_unit_tests_with_invalid_inputs(
        self, testing_pkg: testing_package.TestingPackage, mock_progress, capsys
    ):
        """Test validator unit tests with invalid inputs."""
        # Set up validator
        testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')

        # Add validator unit tests with inline files
        testing_pkg.add_validator_unit_test(
            glob='unit/validator/invalid_*.in',
            outcome=ValidatorOutcome.INVALID,
            files={
                'unit/validator/invalid_string.in': 'hello\n',
                'unit/validator/invalid_multiple.in': '1 2 3\n',  # Multiple integers when expecting one
            },
        )

        await unit.run_validator_unit_tests(mock_progress)

        captured = capsys.readouterr()
        # Should print rule and success messages
        assert 'Validator tests' in captured.out
        assert 'OK Unit test #1' in captured.out
        assert 'OK Unit test #2' in captured.out
        assert 'Expected INVALID' in captured.out

    async def test_validator_unit_tests_with_mixed_outcomes(
        self, testing_pkg: testing_package.TestingPackage, mock_progress, capsys
    ):
        """Test validator unit tests with both valid and invalid inputs."""
        # Set up validator
        testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')

        # Add valid tests
        testing_pkg.add_validator_unit_test(
            glob='unit/validator/valid_*.in',
            outcome=ValidatorOutcome.VALID,
            files={
                'unit/validator/valid_number.in': '123\n',
            },
        )

        # Add invalid tests
        testing_pkg.add_validator_unit_test(
            glob='unit/validator/invalid_*.in',
            outcome=ValidatorOutcome.INVALID,
            files={
                'unit/validator/invalid_text.in': 'not_a_number\n',
            },
        )

        await unit.run_validator_unit_tests(mock_progress)

        captured = capsys.readouterr()
        # Should print rule and success messages
        assert 'Validator tests' in captured.out
        assert 'OK Unit test #1' in captured.out
        assert 'OK Unit test #2' in captured.out
        assert 'Expected VALID' in captured.out
        assert 'Expected INVALID' in captured.out

    async def test_validator_unit_tests_with_custom_validator(
        self, testing_pkg: testing_package.TestingPackage, mock_progress, capsys
    ):
        """Test validator unit tests with a custom validator specified."""
        # Set up main validator
        testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')

        # Add a custom validator file using existing testdata
        testing_pkg.add_file('custom-validator.cpp', src='validators/int-validator.cpp')

        # Add validator unit tests with custom validator
        testing_pkg.add_validator_unit_test(
            glob='unit/validator/custom_*.in',
            outcome=ValidatorOutcome.VALID,
            validator='custom-validator.cpp',
            files={
                'unit/validator/custom_test.in': '50\n',
            },
        )

        await unit.run_validator_unit_tests(mock_progress)

        captured = capsys.readouterr()
        # Should print rule and success messages
        assert 'Validator tests' in captured.out
        assert 'OK Unit test #1' in captured.out
        assert 'Expected VALID' in captured.out


class TestCheckerUnitTests:
    """Test checker unit test functionality."""

    async def test_no_checker_unit_tests(
        self, testing_pkg: testing_package.TestingPackage, mock_progress, capsys
    ):
        """Test behavior when no checker unit tests are defined."""
        # Set up checker
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')

        # No unit tests defined, should print message and return
        await unit.run_checker_unit_tests(mock_progress)

        captured = capsys.readouterr()
        assert 'No checker unit tests found.' in captured.out

    async def test_no_checker_defined(
        self, testing_pkg: testing_package.TestingPackage, mock_progress, capsys
    ):
        """Test behavior when no checker is defined."""
        # No checker defined, should print warning and return
        await unit.run_checker_unit_tests(mock_progress)

        captured = capsys.readouterr()
        # Should either download default checker or print no checker message
        assert (
            'No checker found, skipping checker unit tests.' in captured.out
            or 'No checker unit tests found.' in captured.out
        )

    async def test_checker_unit_tests_with_accepted_outcome(
        self, testing_pkg: testing_package.TestingPackage, mock_progress, capsys
    ):
        """Test checker unit tests with accepted outcome."""
        # Set up checker
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')

        # Add checker unit tests with inline files
        testing_pkg.add_checker_unit_test(
            glob='unit/checker/ac_*',
            outcome=ExpectedOutcome.ACCEPTED,
            files={
                'unit/checker/ac_simple.in': '3 5\n',
                'unit/checker/ac_simple.out': '8\n',
                'unit/checker/ac_simple.ans': '8\n',
            },
        )

        await unit.run_checker_unit_tests(mock_progress)

        captured = capsys.readouterr()
        # Should print rule and success messages
        assert 'Checker tests' in captured.out
        assert 'OK Unit test #1' in captured.out
        assert 'Expected ACCEPTED' in captured.out

    async def test_checker_unit_tests_with_wrong_answer_outcome(
        self, testing_pkg: testing_package.TestingPackage, mock_progress, capsys
    ):
        """Test checker unit tests with wrong answer outcome."""
        # Set up checker
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')

        # Add checker unit tests with inline files
        testing_pkg.add_checker_unit_test(
            glob='unit/checker/wa_*',
            outcome=ExpectedOutcome.WRONG_ANSWER,
            files={
                'unit/checker/wa_wrong.in': '7 2\n',
                'unit/checker/wa_wrong.out': '10\n',
                'unit/checker/wa_wrong.ans': '9\n',
            },
        )

        await unit.run_checker_unit_tests(mock_progress)

        captured = capsys.readouterr()
        # Should print rule and success messages
        assert 'Checker tests' in captured.out
        assert 'OK Unit test #1' in captured.out
        assert 'Expected WRONG_ANSWER' in captured.out

    async def test_checker_unit_tests_with_mixed_outcomes(
        self, testing_pkg: testing_package.TestingPackage, mock_progress, capsys
    ):
        """Test checker unit tests with both accepted and wrong answer outcomes."""
        # Set up checker
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')

        # Add accepted tests
        testing_pkg.add_checker_unit_test(
            glob='unit/checker/ac_*',
            outcome=ExpectedOutcome.ACCEPTED,
            files={
                'unit/checker/ac_correct.in': '1 1\n',
                'unit/checker/ac_correct.out': '2\n',
                'unit/checker/ac_correct.ans': '2\n',
            },
        )

        # Add wrong answer tests
        testing_pkg.add_checker_unit_test(
            glob='unit/checker/wa_*',
            outcome=ExpectedOutcome.WRONG_ANSWER,
            files={
                'unit/checker/wa_incorrect.in': '1 1\n',
                'unit/checker/wa_incorrect.out': '3\n',
                'unit/checker/wa_incorrect.ans': '2\n',
            },
        )

        await unit.run_checker_unit_tests(mock_progress)

        captured = capsys.readouterr()
        # Should print rule and success messages
        assert 'Checker tests' in captured.out
        assert 'OK Unit test #1' in captured.out
        assert 'OK Unit test #2' in captured.out
        assert 'Expected ACCEPTED' in captured.out
        assert 'Expected WRONG_ANSWER' in captured.out

    async def test_checker_unit_tests_with_missing_files(
        self, testing_pkg: testing_package.TestingPackage, mock_progress, capsys
    ):
        """Test checker unit tests with missing input/output/answer files."""
        # Set up checker
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')

        # Add checker unit tests with only some files (missing .ans)
        # This should expect WRONG_ANSWER since there's no answer file to compare against
        testing_pkg.add_checker_unit_test(
            glob='unit/checker/partial_*',
            outcome=ExpectedOutcome.WRONG_ANSWER,
            files={
                'unit/checker/partial_test.in': '5 3\n',
                'unit/checker/partial_test.out': '8\n',
                # No .ans file - should use empty file, causing WRONG_ANSWER
            },
        )

        await unit.run_checker_unit_tests(mock_progress)

        captured = capsys.readouterr()
        # Should print rule and success messages
        assert 'Checker tests' in captured.out
        assert 'OK Unit test #1' in captured.out
        assert 'Expected WRONG_ANSWER' in captured.out


class TestRunUnitTests:
    """Test the main run_unit_tests function."""

    def test_run_unit_tests_calls_both_functions(
        self, testing_pkg: testing_package.TestingPackage, mock_progress, capsys
    ):
        """Test that run_unit_tests calls both validator and checker unit tests."""
        # Set up both validator and checker
        testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')
        testing_pkg.set_checker('checker.cpp', src='checkers/checker.cpp')

        # Add some unit tests
        testing_pkg.add_validator_unit_test(
            glob='unit/validator/valid_*.in',
            outcome=ValidatorOutcome.VALID,
            files={'unit/validator/valid_test.in': '42\n'},
        )

        testing_pkg.add_checker_unit_test(
            glob='unit/checker/ac_*',
            outcome=ExpectedOutcome.ACCEPTED,
            files={
                'unit/checker/ac_test.in': '1 1\n',
                'unit/checker/ac_test.out': '2\n',
                'unit/checker/ac_test.ans': '2\n',
            },
        )

        unit.run_unit_tests(mock_progress)

        captured = capsys.readouterr()
        # Should print rules for both validator and checker tests
        assert 'Validator tests' in captured.out
        assert 'Checker tests' in captured.out

    def test_run_unit_tests_with_progress(
        self, testing_pkg: testing_package.TestingPackage, mock_progress, capsys
    ):
        """Test that run_unit_tests works with progress reporting."""
        # Set up validator
        testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')

        # Add validator unit test
        testing_pkg.add_validator_unit_test(
            glob='unit/validator/valid_*.in',
            outcome=ValidatorOutcome.VALID,
            files={'unit/validator/valid_test.in': '42\n'},
        )

        unit.run_unit_tests(mock_progress)

        # Progress should be updated during the test
        mock_progress.update.assert_called()


class TestHelperFunctions:
    """Test helper functions in the unit module."""

    def test_extract_validator_test_entries(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test _extract_validator_test_entries function."""
        # Add validator unit tests
        testing_pkg.add_validator_unit_test(
            glob='unit/validator/valid_*.in',
            outcome=ValidatorOutcome.VALID,
            files={
                'unit/validator/valid_test1.in': '1\n',
                'unit/validator/valid_test2.in': '2\n',
            },
        )

        # Extract entries
        entries = unit.extract_validator_test_entries(
            testing_pkg.yml.unitTests.validator
        )

        # Should have 2 entries
        assert len(entries) == 2

        # Check entries are sorted by filename
        assert entries[0].input.name == 'valid_test1.in'
        assert entries[1].input.name == 'valid_test2.in'

        # Check outcomes
        assert all(entry.outcome == ValidatorOutcome.VALID for entry in entries)

    def test_extract_checker_test_entries(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test _extract_checker_test_entries function."""
        # Add checker unit tests
        testing_pkg.add_checker_unit_test(
            glob='unit/checker/test_*',
            outcome=ExpectedOutcome.ACCEPTED,
            files={
                'unit/checker/test_case.in': '1 1\n',
                'unit/checker/test_case.out': '2\n',
                'unit/checker/test_case.ans': '2\n',
            },
        )

        # Extract entries
        entries = unit.extract_checker_test_entries(testing_pkg.yml.unitTests.checker)

        # Should have 1 entry
        assert len(entries) == 1

        # Check entry properties
        entry = entries[0]
        assert entry.input is not None and entry.input.name == 'test_case.in'
        assert entry.output is not None and entry.output.name == 'test_case.out'
        assert entry.answer is not None and entry.answer.name == 'test_case.ans'
        assert entry.outcome == ExpectedOutcome.ACCEPTED

    def test_extract_checker_test_entries_with_missing_files(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test _extract_checker_test_entries with missing files."""
        # Add checker unit tests with only input file
        testing_pkg.add_checker_unit_test(
            glob='unit/checker/partial_*',
            outcome=ExpectedOutcome.ACCEPTED,
            files={
                'unit/checker/partial_test.in': '1 1\n',
                # No .out or .ans files
            },
        )

        # Extract entries
        entries = unit.extract_checker_test_entries(testing_pkg.yml.unitTests.checker)

        # Should have 1 entry
        assert len(entries) == 1

        # Check entry properties
        entry = entries[0]
        assert entry.input is not None and entry.input.name == 'partial_test.in'
        assert entry.output is None  # File doesn't exist
        assert entry.answer is None  # File doesn't exist
        assert entry.outcome == ExpectedOutcome.ACCEPTED
