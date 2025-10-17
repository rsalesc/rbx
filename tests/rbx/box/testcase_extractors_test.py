import pathlib

import pytest
import typer

from rbx.box.schema import GeneratorScript, TestcaseGroup
from rbx.box.testcase_extractors import (
    TestcaseGroupVisitor,
    TestcaseVisitor,
    extract_generation_testcases,
    extract_generation_testcases_from_groups,
    extract_generation_testcases_from_patterns,
    run_testcase_visitor,
)
from rbx.box.testcase_utils import TestcaseEntry, TestcasePattern
from rbx.box.testing import testing_package


class TestVisitorPatterns:
    """Test visitor pattern implementations."""

    def test_testcase_group_visitor_no_groups(self):
        """Test TestcaseGroupVisitor with no group filtering."""

        class ConcreteGroupVisitor(TestcaseGroupVisitor):
            async def visit(self, entry):
                pass

        visitor = ConcreteGroupVisitor()
        assert visitor.should_visit_group('any_group')

    def test_testcase_group_visitor_with_groups(self):
        """Test TestcaseGroupVisitor with specific groups."""

        class ConcreteGroupVisitor(TestcaseGroupVisitor):
            async def visit(self, entry):
                pass

        visitor = ConcreteGroupVisitor({'group1', 'group2'})
        assert visitor.should_visit_group('group1')
        assert visitor.should_visit_group('group2')
        assert not visitor.should_visit_group('group3')

    def test_testcase_visitor_default_methods(self):
        """Test default implementations of TestcaseVisitor methods."""

        class ConcreteVisitor(TestcaseVisitor):
            async def visit(self, entry):
                pass

        visitor = ConcreteVisitor()
        assert visitor.should_visit_group('any_group')
        assert visitor.should_visit_subgroup('any_subgroup')
        assert visitor.should_visit_generator_scripts('group', 'subgroup')


class TestRunTestcaseVisitor:
    """Test the main run_testcase_visitor function."""

    async def test_run_testcase_visitor_empty_package(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test running visitor on empty package."""
        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 0

    async def test_run_testcase_visitor_with_manual_testcases(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test running visitor with manually defined testcases."""
        # Create test files
        testing_pkg.add_file('tests/001.in').write_text('test input 1')
        testing_pkg.add_file('tests/002.in').write_text('test input 2')

        # Add testgroup with manual testcases
        testing_pkg.add_testgroup_with_manual_testcases(
            'manual',
            [
                {'inputPath': 'tests/001.in'},
                {'inputPath': 'tests/002.in', 'outputPath': 'tests/002.out'},
            ],
        )

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 2
        assert visited_entries[0].group_entry.group == 'manual'
        assert visited_entries[0].group_entry.index == 0
        assert visited_entries[1].group_entry.group == 'manual'
        assert visited_entries[1].group_entry.index == 1

    async def test_run_testcase_visitor_with_glob_testcases(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test running visitor with glob testcases."""
        # Create test files
        testing_pkg.add_file('tests/sample_001.in').write_text('sample 1')
        testing_pkg.add_file('tests/sample_002.in').write_text('sample 2')
        testing_pkg.add_file('tests/other.txt').write_text('not a test')

        # Add testgroup with glob
        testing_pkg.add_testgroup_from_glob('samples', 'tests/sample_*.in')

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 2
        assert all(entry.group_entry.group == 'samples' for entry in visited_entries)

    async def test_run_testcase_visitor_with_generators(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test running visitor with generator calls."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroup with generators
        testing_pkg.add_testgroup_with_generators(
            'generated',
            [{'name': 'gen1', 'args': 'arg1'}, {'name': 'gen1', 'args': 'arg2'}],
        )

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 2
        assert all(entry.group_entry.group == 'generated' for entry in visited_entries)
        assert visited_entries[0].metadata.generator_call.name == 'gen1'
        assert visited_entries[0].metadata.generator_call.args == 'arg1'
        assert visited_entries[1].metadata.generator_call.args == 'arg2'

    async def test_run_testcase_visitor_with_generator_script(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test running visitor with generator script."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroup with generator script
        testing_pkg.add_testgroup_from_plan('scripted', 'gen1 123\ngen1 456')

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 2
        assert all(entry.group_entry.group == 'scripted' for entry in visited_entries)
        assert visited_entries[0].metadata.generator_call.name == 'gen1'
        assert visited_entries[0].metadata.generator_call.args == '123'
        assert visited_entries[1].metadata.generator_call.args == '456'
        assert visited_entries[0].metadata.generator_script is not None
        assert visited_entries[1].metadata.generator_script is not None

    async def test_run_testcase_visitor_with_subgroups(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test running visitor with subgroups."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroup with subgroups
        testing_pkg.add_testgroup_with_subgroups(
            'main',
            [
                {'name': 'sub1', 'generators': [{'name': 'gen1', 'args': 'arg1'}]},
                {'name': 'sub2', 'generators': [{'name': 'gen1', 'args': 'arg2'}]},
            ],
        )

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 2
        assert visited_entries[0].group_entry.group == 'main'
        assert visited_entries[0].subgroup_entry.group == 'main/sub1'
        assert visited_entries[1].subgroup_entry.group == 'main/sub2'

    async def test_run_testcase_visitor_with_validators(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test running visitor with validators."""
        # Add validators
        testing_pkg.set_validator(
            'main_validator.cpp', src='validators/int-validator.cpp'
        )
        testing_pkg.add_file(
            'extra_validator.cpp', src='validators/int-validator-bounded.cpp'
        )

        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroup with validators
        testing_pkg.add_testgroup_with_generators(
            'validated',
            [{'name': 'gen1', 'args': 'arg1'}],
            extra_validators=['extra_validator.cpp'],
        )

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 1
        assert visited_entries[0].validator is not None
        assert visited_entries[0].validator.path == pathlib.Path('main_validator.cpp')
        assert len(visited_entries[0].extra_validators) == 1
        assert visited_entries[0].extra_validators[0].path == pathlib.Path(
            'extra_validator.cpp'
        )

    async def test_run_testcase_visitor_group_filtering(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test visitor group filtering."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add multiple testgroups
        testing_pkg.add_testgroup_with_generators(
            'group1', [{'name': 'gen1', 'args': 'arg1'}]
        )
        testing_pkg.add_testgroup_with_generators(
            'group2', [{'name': 'gen1', 'args': 'arg2'}]
        )
        testing_pkg.add_testgroup_with_generators(
            'group3', [{'name': 'gen1', 'args': 'arg3'}]
        )

        visited_entries = []

        class FilteringVisitor(TestcaseVisitor):
            def should_visit_group(self, group_name: str) -> bool:
                return group_name in {'group1', 'group3'}

            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = FilteringVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 2
        visited_groups = {entry.group_entry.group for entry in visited_entries}
        assert visited_groups == {'group1', 'group3'}

    async def test_run_testcase_visitor_subgroup_filtering(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test visitor subgroup filtering."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroup with subgroups
        testing_pkg.add_testgroup_with_subgroups(
            'main',
            [
                {'name': 'sub1', 'generators': [{'name': 'gen1', 'args': 'arg1'}]},
                {'name': 'sub2', 'generators': [{'name': 'gen1', 'args': 'arg2'}]},
            ],
        )

        visited_entries = []

        class FilteringVisitor(TestcaseVisitor):
            def should_visit_subgroup(self, subgroup_path: str) -> bool:
                return subgroup_path == 'main/sub1'

            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = FilteringVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 1
        assert visited_entries[0].subgroup_entry.group == 'main/sub1'

    async def test_run_testcase_visitor_generator_script_filtering(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test visitor generator script filtering."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroup with both generators and generator script
        testing_pkg.add_testgroup_with_subgroups(
            'main',
            [{'name': 'sub1', 'generators': [{'name': 'gen1', 'args': 'direct_call'}]}],
        )

        # Also add a generator script to the main group
        testing_pkg.add_testgroup_from_plan('scripted', 'gen1 script_call')

        visited_entries = []

        class FilteringVisitor(TestcaseVisitor):
            def should_visit_generator_scripts(
                self, group_name: str, subgroup_path: str
            ) -> bool:
                return group_name == 'scripted'

            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = FilteringVisitor()
        await run_testcase_visitor(visitor)

        # Should visit the direct generator call from main/sub1 but not the script from scripted
        # Actually, let me fix this test - it should visit both but filter out script generation
        direct_calls = [
            e for e in visited_entries if e.metadata.generator_script is None
        ]
        script_calls = [
            e for e in visited_entries if e.metadata.generator_script is not None
        ]

        assert len(direct_calls) == 1  # from main/sub1
        assert len(script_calls) == 1  # from scripted (because we allow scripted group)

    async def test_run_testcase_visitor_with_glob_validators(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test running visitor with glob patterns in extra validators."""
        # Create multiple validator files
        testing_pkg.add_file(
            'validators/int_validator.cpp', src='validators/int-validator.cpp'
        )
        testing_pkg.add_file(
            'validators/bounded_validator.cpp',
            src='validators/int-validator-bounded.cpp',
        )
        testing_pkg.add_file(
            'validators/odd_validator.cpp', src='validators/extra-validator-odd.cpp'
        )
        testing_pkg.add_file(
            'other/not_validator.cpp', src='validators/int-validator.cpp'
        )

        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroup with glob pattern for extra validators
        testing_pkg.add_testgroup_with_generators(
            'validated',
            [{'name': 'gen1', 'args': 'test'}],
            extra_validators=['validators/*.cpp'],  # Should match 3 files
        )

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 1
        # Should have expanded the glob to include all 3 validators
        assert len(visited_entries[0].extra_validators) == 3
        validator_paths = {v.path for v in visited_entries[0].extra_validators}
        expected_paths = {
            pathlib.Path('validators/int_validator.cpp'),
            pathlib.Path('validators/bounded_validator.cpp'),
            pathlib.Path('validators/odd_validator.cpp'),
        }
        assert validator_paths == expected_paths

    async def test_run_testcase_visitor_validator_deduplication(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that extra validators don't duplicate the main validator."""
        # Set main validator
        testing_pkg.set_validator(
            'validators/main.cpp', src='validators/int-validator.cpp'
        )

        # Create additional validator files
        testing_pkg.add_file(
            'validators/extra1.cpp', src='validators/int-validator-bounded.cpp'
        )
        testing_pkg.add_file(
            'validators/extra2.cpp', src='validators/extra-validator-odd.cpp'
        )

        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroup with extra validators including the main validator path
        testing_pkg.add_testgroup_with_generators(
            'deduplicated',
            [{'name': 'gen1', 'args': 'test'}],
            extra_validators=[
                'validators/main.cpp',
                'validators/extra1.cpp',
                'validators/extra2.cpp',
            ],
        )

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 1
        # Main validator should be set
        assert visited_entries[0].validator.path == pathlib.Path('validators/main.cpp')
        # Extra validators should not include the main validator (deduplicated)
        assert len(visited_entries[0].extra_validators) == 2
        extra_paths = {v.path for v in visited_entries[0].extra_validators}
        assert pathlib.Path('validators/main.cpp') not in extra_paths
        assert pathlib.Path('validators/extra1.cpp') in extra_paths
        assert pathlib.Path('validators/extra2.cpp') in extra_paths

    async def test_run_testcase_visitor_nested_glob_expansion(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that nested subgroups properly expand and deduplicate glob patterns."""
        # Create validator files in different directories
        testing_pkg.add_file('validators/base1.cpp', src='validators/int-validator.cpp')
        testing_pkg.add_file(
            'validators/base2.cpp', src='validators/int-validator-bounded.cpp'
        )
        testing_pkg.add_file(
            'validators/sub1.cpp', src='validators/extra-validator-odd.cpp'
        )
        testing_pkg.add_file('validators/sub2.cpp', src='validators/int-validator.cpp')

        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Create a complex hierarchy where group has glob validators
        # and subgroup adds more glob validators
        testing_pkg.add_testgroup_with_subgroups(
            'main',
            [
                {
                    'name': 'subgroup1',
                    'generators': [{'name': 'gen1', 'args': 'test1'}],
                    # This will add to the group's glob pattern
                    'extraValidators': ['validators/sub*.cpp'],
                },
            ],
            # Group level glob pattern
            extra_validators=['validators/base*.cpp'],
        )

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 1

        # Should have all validators: base1, base2 (from group) + sub1, sub2 (from subgroup)
        # The glob expansion should happen for both levels
        assert len(visited_entries[0].extra_validators) == 4
        validator_paths = {v.path for v in visited_entries[0].extra_validators}
        expected_paths = {
            pathlib.Path('validators/base1.cpp'),
            pathlib.Path('validators/base2.cpp'),
            pathlib.Path('validators/sub1.cpp'),
            pathlib.Path('validators/sub2.cpp'),
        }
        assert validator_paths == expected_paths

    async def test_run_testcase_visitor_overlapping_glob_deduplication(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that overlapping glob patterns between levels are properly deduplicated."""
        # Create validator files that match multiple patterns
        testing_pkg.add_file(
            'validators/common1.cpp', src='validators/int-validator.cpp'
        )
        testing_pkg.add_file(
            'validators/common2.cpp', src='validators/int-validator-bounded.cpp'
        )
        testing_pkg.add_file(
            'validators/specific.cpp', src='validators/extra-validator-odd.cpp'
        )

        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Create hierarchy with overlapping glob patterns
        testing_pkg.add_testgroup_with_subgroups(
            'main',
            [
                {
                    'name': 'subgroup1',
                    'generators': [{'name': 'gen1', 'args': 'test1'}],
                    # This glob overlaps with the group level glob
                    'extraValidators': [
                        'validators/common*.cpp',
                        'validators/specific.cpp',
                    ],
                },
            ],
            # Group level glob that will match common1.cpp and common2.cpp
            extra_validators=['validators/common*.cpp'],
        )

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 1

        # Should have 3 validators total, with common files deduplicated
        assert len(visited_entries[0].extra_validators) == 3
        validator_paths = {v.path for v in visited_entries[0].extra_validators}
        expected_paths = {
            pathlib.Path('validators/common1.cpp'),
            pathlib.Path('validators/common2.cpp'),
            pathlib.Path('validators/specific.cpp'),
        }
        assert validator_paths == expected_paths


class TestExtractionFunctions:
    """Test the main extraction functions."""

    async def test_extract_generation_testcases(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test extract_generation_testcases function."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroups
        testing_pkg.add_testgroup_with_generators(
            'group1',
            [{'name': 'gen1', 'args': 'arg1'}, {'name': 'gen1', 'args': 'arg2'}],
        )
        testing_pkg.add_testgroup_with_generators(
            'group2', [{'name': 'gen1', 'args': 'arg3'}]
        )

        # Extract specific entries
        entries = [
            TestcaseEntry(group='group1', index=0),
            TestcaseEntry(group='group1', index=1),
            TestcaseEntry(group='group2', index=0),
        ]

        result = await extract_generation_testcases(entries)

        assert len(result) == 3
        assert result[0].group_entry.group == 'group1'
        assert result[0].group_entry.index == 0
        assert result[1].group_entry.index == 1
        assert result[2].group_entry.group == 'group2'

    async def test_extract_generation_testcases_partial(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test extract_generation_testcases with partial entries."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroup with 3 testcases
        testing_pkg.add_testgroup_with_generators(
            'group1',
            [
                {'name': 'gen1', 'args': 'arg1'},
                {'name': 'gen1', 'args': 'arg2'},
                {'name': 'gen1', 'args': 'arg3'},
            ],
        )

        # Extract only specific entries
        entries = [
            TestcaseEntry(group='group1', index=0),
            TestcaseEntry(group='group1', index=2),
        ]

        result = await extract_generation_testcases(entries)

        assert len(result) == 2
        assert result[0].group_entry.index == 0
        assert result[1].group_entry.index == 2

    async def test_extract_generation_testcases_from_groups(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test extract_generation_testcases_from_groups function."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroups
        testing_pkg.add_testgroup_with_generators(
            'group1',
            [{'name': 'gen1', 'args': 'arg1'}, {'name': 'gen1', 'args': 'arg2'}],
        )
        testing_pkg.add_testgroup_with_generators(
            'group2', [{'name': 'gen1', 'args': 'arg3'}]
        )

        # Extract all testcases
        result = await extract_generation_testcases_from_groups()

        assert len(result) == 3
        groups = {entry.group_entry.group for entry in result}
        assert groups == {'group1', 'group2'}

    async def test_extract_generation_testcases_from_groups_filtered(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test extract_generation_testcases_from_groups with group filtering."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroups
        testing_pkg.add_testgroup_with_generators(
            'group1', [{'name': 'gen1', 'args': 'arg1'}]
        )
        testing_pkg.add_testgroup_with_generators(
            'group2', [{'name': 'gen1', 'args': 'arg2'}]
        )
        testing_pkg.add_testgroup_with_generators(
            'group3', [{'name': 'gen1', 'args': 'arg3'}]
        )

        # Extract only specific groups
        result = await extract_generation_testcases_from_groups({'group1', 'group3'})

        assert len(result) == 2
        groups = {entry.group_entry.group for entry in result}
        assert groups == {'group1', 'group3'}

    async def test_extract_generation_testcases_from_patterns(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test extract_generation_testcases_from_patterns function."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroups
        testing_pkg.add_testgroup_with_generators(
            'samples',
            [{'name': 'gen1', 'args': 'arg1'}, {'name': 'gen1', 'args': 'arg2'}],
        )
        testing_pkg.add_testgroup_with_generators(
            'secret', [{'name': 'gen1', 'args': 'arg3'}]
        )

        # Create patterns
        patterns = [
            TestcasePattern(group_prefix=['samples']),
            TestcasePattern(group_prefix=['secret'], index=0),
        ]

        result = await extract_generation_testcases_from_patterns(patterns)

        # Should match all samples + first secret testcase
        assert len(result) == 3

        # Check that we have the right entries
        samples_entries = [e for e in result if e.group_entry.group == 'samples']
        secret_entries = [e for e in result if e.group_entry.group == 'secret']

        assert len(samples_entries) == 2
        assert len(secret_entries) == 1
        assert secret_entries[0].group_entry.index == 0

    async def test_generator_script_parsing_behavior(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that generator scripts are correctly parsed through the public API."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Create a complex generator script to test parsing behavior
        script_content = """# This is a comment
gen1 simple_arg
gen1 "quoted arg" normal_arg

# Another comment
gen1 final_arg"""

        testing_pkg.add_testgroup_from_plan('scripted', script_content)

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        # Should have 3 entries (comments and empty lines ignored)
        assert len(visited_entries) == 3

        # Check that arguments are correctly parsed
        assert visited_entries[0].metadata.generator_call.args == 'simple_arg'
        assert (
            visited_entries[1].metadata.generator_call.args == "'quoted arg' normal_arg"
        )
        assert visited_entries[2].metadata.generator_call.args == 'final_arg'

        # Check that line numbers are tracked
        assert visited_entries[0].metadata.generator_script.line == 2
        assert visited_entries[1].metadata.generator_script.line == 3
        assert visited_entries[2].metadata.generator_script.line == 6

    async def test_testcase_path_generation_behavior(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that testcase paths are correctly generated through the public API."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroup with subgroups to test path generation
        testing_pkg.add_testgroup_with_subgroups(
            'main',
            [
                {'name': 'sub1', 'generators': [{'name': 'gen1', 'args': 'arg1'}]},
                {'name': 'sub2', 'generators': [{'name': 'gen1', 'args': 'arg2'}]},
            ],
        )

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 2

        # Check that paths are correctly generated with subgroup prefixes
        # The paths should follow the pattern: build/tests/{group}/{subgroup_index}-{subgroup_name}-{testcase_index:03d}.{ext}
        entry1 = visited_entries[0]
        entry2 = visited_entries[1]

        # Both should be in the main group build directory
        assert 'build/tests/main' in str(entry1.metadata.copied_to.inputPath)
        assert 'build/tests/main' in str(entry2.metadata.copied_to.inputPath)

        # Should have different prefixes for different subgroups
        assert '1-sub1-000.in' in str(entry1.metadata.copied_to.inputPath)
        assert '2-sub2-000.in' in str(entry2.metadata.copied_to.inputPath)

        # Output paths should match input paths but with .out extension
        assert str(entry1.metadata.copied_to.outputPath).endswith('1-sub1-000.out')
        assert str(entry2.metadata.copied_to.outputPath).endswith('2-sub2-000.out')


class TestNewFeatures:
    """Test new features for box format and generator resolution."""

    async def test_box_format_script_parsing(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that box format scripts are correctly parsed with semicolon syntax."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Create a box format generator script
        box_script_content = """# Comment line
1; gen1 first_test
2; gen1 "quoted arg" second_arg

# Another comment
3; gen1 final_test"""

        # Create the testplan file and modify the package to use box format
        plan_path = testing_pkg.add_testplan('box_script')
        plan_path.write_text(box_script_content)

        # Manually modify the package to set box format
        pkg = testing_pkg.yml
        from rbx.box.schema import GeneratorScript

        pkg.testcases = pkg.testcases + [
            TestcaseGroup(
                name='box_formatted',
                generatorScript=GeneratorScript(path=plan_path, format='box'),
            )
        ]
        testing_pkg.save()

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        # Should have 3 entries (comments and empty lines ignored)
        assert len(visited_entries) == 3

        # Check that arguments are correctly parsed
        assert visited_entries[0].metadata.generator_call.args == 'first_test'
        assert (
            visited_entries[1].metadata.generator_call.args == "'quoted arg' second_arg"
        )
        assert visited_entries[2].metadata.generator_call.args == 'final_test'

        # Check that line numbers are tracked correctly
        assert visited_entries[0].metadata.generator_script.line == 2
        assert visited_entries[1].metadata.generator_script.line == 3
        assert visited_entries[2].metadata.generator_script.line == 6

    async def test_box_format_exe_stripping(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that .exe extensions are stripped in box format."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Create a box format script with .exe extensions
        box_script_content = """1; gen1.exe test_arg
2; gen1 normal_arg"""

        plan_path = testing_pkg.add_testplan('box_exe_script')
        plan_path.write_text(box_script_content)

        # Manually modify the package to set box format
        pkg = testing_pkg.yml
        from rbx.box.schema import GeneratorScript

        pkg.testcases = pkg.testcases + [
            TestcaseGroup(
                name='box_exe_test',
                generatorScript=GeneratorScript(path=plan_path, format='box'),
            )
        ]
        testing_pkg.save()

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 2
        # Both should resolve to 'gen1' (without .exe)
        assert visited_entries[0].metadata.generator_call.name == 'gen1'
        assert visited_entries[1].metadata.generator_call.name == 'gen1'

    async def test_box_format_copy_command(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that 'copy' is converted to '@copy' in box format."""
        # Create test file
        testing_pkg.add_file('tests/manual.in').write_text('manual test')

        # Create box format script with 'copy' command
        box_script_content = """1; copy tests/manual.in"""

        plan_path = testing_pkg.add_testplan('box_copy_script')
        plan_path.write_text(box_script_content)

        pkg = testing_pkg.yml
        from rbx.box.schema import GeneratorScript

        pkg.testcases = pkg.testcases + [
            TestcaseGroup(
                name='box_copy_test',
                generatorScript=GeneratorScript(path=plan_path, format='box'),
            )
        ]
        testing_pkg.save()

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 1

        assert visited_entries[0].metadata.generator_script is not None
        assert visited_entries[0].metadata.copied_from is not None

    async def test_generator_resolution_with_alias(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that generator aliases are resolved correctly."""
        # Add generator with alias
        testing_pkg.add_generator(
            'gens/my_gen.cpp', alias='gen_alias', src='generators/gen-id.cpp'
        )

        # Create script using the alias
        script_content = """gen_alias test_arg"""

        # Create the testplan file
        plan_path = testing_pkg.add_testplan('alias_test')
        plan_path.write_text(script_content)

        # Manually create the testgroup with GeneratorScript
        pkg = testing_pkg.yml
        pkg.testcases = pkg.testcases + [
            TestcaseGroup(
                name='alias_test', generatorScript=GeneratorScript(path=plan_path)
            )
        ]
        testing_pkg.save()

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 1
        # The alias should be resolved to the actual generator name
        assert visited_entries[0].metadata.generator_call.name == 'gen_alias'

    async def test_generator_resolution_rejects_at_prefix(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that generator names starting with @ are rejected."""
        # This test verifies the error path, so we need to catch the exit
        script_content = """@invalid_gen test_arg"""

        # Create the testplan file
        plan_path = testing_pkg.add_testplan('invalid_test')
        plan_path.write_text(script_content)

        # Manually create the testgroup with GeneratorScript
        pkg = testing_pkg.yml
        pkg.testcases = pkg.testcases + [
            TestcaseGroup(
                name='invalid_test', generatorScript=GeneratorScript(path=plan_path)
            )
        ]
        testing_pkg.save()

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                pass

        visitor = CollectingVisitor()

        # The _resolve_generator_name function should raise typer.Exit(1) for @ prefix
        with pytest.raises(typer.Exit) as exc_info:
            await run_testcase_visitor(visitor)

        assert exc_info.value.exit_code == 1


class TestComplexScenarios:
    """Test complex scenarios combining multiple features."""

    async def test_mixed_testcase_types(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test package with mixed testcase types."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add glob testcases first (samples must be first group)
        testing_pkg.add_file('samples/sample1.in').write_text('sample 1')
        testing_pkg.add_file('samples/sample2.in').write_text('sample 2')
        testing_pkg.add_testgroup_from_glob('samples', 'samples/*.in')

        # Add manual testcases
        testing_pkg.add_file('manual/001.in').write_text('manual input')
        testing_pkg.add_testgroup_with_manual_testcases(
            'manual', [{'inputPath': 'manual/001.in'}]
        )

        # Add generated testcases
        testing_pkg.add_testgroup_with_generators(
            'generated', [{'name': 'gen1', 'args': 'gen_arg'}]
        )

        # Add scripted testcases
        testing_pkg.add_testgroup_from_plan('scripted', 'gen1 script_arg')

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert (
            len(visited_entries) == 5
        )  # 2 samples + 1 manual + 1 generated + 1 scripted

        # Check that we have all expected groups
        groups = {entry.group_entry.group for entry in visited_entries}
        expected_groups = {'manual', 'samples', 'generated', 'scripted'}
        assert groups == expected_groups

    async def test_subgroups_with_mixed_types(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test subgroups with different testcase types."""
        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Create manual testcase files
        testing_pkg.add_file('manual/001.in').write_text('manual input')

        # Add testgroup with subgroups of different types
        testing_pkg.add_testgroup_with_subgroups(
            'main',
            [
                {'name': 'manual_sub', 'testcases': [{'inputPath': 'manual/001.in'}]},
                {
                    'name': 'generated_sub',
                    'generators': [{'name': 'gen1', 'args': 'gen_arg'}],
                },
            ],
        )

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 2

        # Check subgroup paths
        subgroup_paths = {entry.subgroup_entry.group for entry in visited_entries}
        assert subgroup_paths == {'main/manual_sub', 'main/generated_sub'}

    async def test_validators_inheritance(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test validator inheritance from package to groups to subgroups."""
        # Set up validators
        testing_pkg.set_validator(
            'main_validator.cpp', src='validators/int-validator.cpp'
        )
        testing_pkg.add_file(
            'group_validator.cpp', src='validators/int-validator-bounded.cpp'
        )
        testing_pkg.add_file(
            'extra_validator.cpp', src='validators/extra-validator-odd.cpp'
        )

        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroup with group-level validator and subgroups with extra validators
        testing_pkg.add_testgroup_with_subgroups(
            'main',
            [
                {
                    'name': 'sub1',
                    'generators': [{'name': 'gen1', 'args': 'arg1'}],
                    'extraValidators': ['extra_validator.cpp'],
                },
                {'name': 'sub2', 'generators': [{'name': 'gen1', 'args': 'arg2'}]},
            ],
            validator='group_validator.cpp',
        )

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 2

        # Both should use group validator (not package validator)
        for entry in visited_entries:
            assert entry.validator.path == pathlib.Path('group_validator.cpp')

        # First subgroup should have extra validator
        sub1_entry = next(
            e for e in visited_entries if e.subgroup_entry.group == 'main/sub1'
        )
        sub2_entry = next(
            e for e in visited_entries if e.subgroup_entry.group == 'main/sub2'
        )

        assert len(sub1_entry.extra_validators) == 1
        assert sub1_entry.extra_validators[0].path == pathlib.Path(
            'extra_validator.cpp'
        )
        assert len(sub2_entry.extra_validators) == 0

    async def test_subgroup_validators_with_globs_inheritance(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that subgroups properly inherit and expand glob patterns in validators."""
        # Create multiple validator files
        testing_pkg.add_file('validators/base1.cpp', src='validators/int-validator.cpp')
        testing_pkg.add_file(
            'validators/base2.cpp', src='validators/int-validator-bounded.cpp'
        )
        testing_pkg.add_file(
            'validators/sub_extra.cpp', src='validators/extra-validator-odd.cpp'
        )
        testing_pkg.add_file('validators/ignored.txt').write_text('not a validator')

        # Add generator
        testing_pkg.add_generator('gen1', src='generators/gen-id.cpp')

        # Add testgroup with glob pattern extra validators at group level
        # and additional validators at subgroup level
        testing_pkg.add_testgroup_with_subgroups(
            'main',
            [
                {
                    'name': 'sub1',
                    'generators': [{'name': 'gen1', 'args': 'arg1'}],
                    'extraValidators': [
                        'validators/sub_extra.cpp'
                    ],  # Additional validator
                },
                {
                    'name': 'sub2',
                    'generators': [{'name': 'gen1', 'args': 'arg2'}],
                    # No additional validators
                },
            ],
            extra_validators=['validators/base*.cpp'],  # Glob pattern at group level
        )

        visited_entries = []

        class CollectingVisitor(TestcaseVisitor):
            async def visit(self, entry):
                visited_entries.append(entry)

        visitor = CollectingVisitor()
        await run_testcase_visitor(visitor)

        assert len(visited_entries) == 2

        # Get entries for each subgroup
        sub1_entry = next(
            e for e in visited_entries if e.subgroup_entry.group == 'main/sub1'
        )
        sub2_entry = next(
            e for e in visited_entries if e.subgroup_entry.group == 'main/sub2'
        )

        # Sub1 should have group validators (expanded from glob) + its own extra validator
        sub1_paths = {v.path for v in sub1_entry.extra_validators}
        expected_sub1 = {
            pathlib.Path('validators/base1.cpp'),
            pathlib.Path('validators/base2.cpp'),
            pathlib.Path('validators/sub_extra.cpp'),
        }
        assert sub1_paths == expected_sub1
        assert len(sub1_entry.extra_validators) == 3

        # Sub2 should only have group validators (expanded from glob)
        sub2_paths = {v.path for v in sub2_entry.extra_validators}
        expected_sub2 = {
            pathlib.Path('validators/base1.cpp'),
            pathlib.Path('validators/base2.cpp'),
        }
        assert sub2_paths == expected_sub2
        assert len(sub2_entry.extra_validators) == 2
