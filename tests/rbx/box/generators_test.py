import pathlib
from typing import List

import pytest
import typer

from rbx import testing_utils
from rbx.box import schema
from rbx.box import validators as validators_mod
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.generators import (
    ValidationError,
    generate_standalone,
    generate_testcases,
)
from rbx.box.sanitizers import warning_stack
from rbx.box.schema import CodeItem, GeneratorCall, Testcase
from rbx.box.testcase_extractors import (
    GenerationMetadata,
    extract_generation_testcases_from_groups,
)
from rbx.box.testing import testing_package
from rbx.box.testset_findings import DuplicateTest
from rbx.grading import steps

# These tests recompile the same handful of generators and validators in every
# fresh problem directory; sharing the problem cache across them takes the file
# from 58s to 21s. They only care about the generated testcases, not about a
# compilation actually running -- the one test that does opts back out below.
pytestmark = pytest.mark.shared_cache


async def test_generator_in_testplan(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan(
        'main',
        """
gens/gen.cpp 123
gens/gen.cpp 424242
""",
    )
    await generate_testcases()

    testing_pkg.print_debug()

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.in'
    ).read_text() == '123\n'
    assert (
        testing_pkg.get_build_testgroup_path('main') / '001.in'
    ).read_text() == '424242\n'


async def test_generator_in_testplan_without_extension(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen 123\n')
    await generate_testcases()

    testing_pkg.print_debug()

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.in'
    ).read_text() == '123\n'


async def test_aliased_generator_in_testplan(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_generator(
        'gens/gen.cpp', alias='gen_alias', src='generators/gen-id.cpp'
    )
    testing_pkg.add_testgroup_from_plan('main', 'gen_alias 123\n')
    await generate_testcases()

    testing_pkg.print_debug()

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.in'
    ).read_text() == '123\n'


async def test_generator_in_testplan_with_multiple_generators(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_generator('gens/gen2.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan(
        'main',
        """
gens/gen.cpp 123
gens/gen2.cpp 424242
""",
    )
    await generate_testcases()

    testing_pkg.print_debug()

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.in'
    ).read_text() == '123\n'
    assert (
        testing_pkg.get_build_testgroup_path('main') / '001.in'
    ).read_text() == '424242\n'


async def test_generator_with_multiple_groups(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan(
        'main',
        """
gens/gen.cpp 123
""",
    )
    testing_pkg.add_testgroup_from_plan(
        'secondary',
        """
gens/gen.cpp 424242
""",
    )
    await generate_testcases()

    testing_pkg.print_debug()

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.in'
    ).read_text() == '123\n'
    assert (
        testing_pkg.get_build_testgroup_path('secondary') / '000.in'
    ).read_text() == '424242\n'


async def test_generator_with_script(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_script(
        'main',
        """
for i in range(3):
    print(f'gens/gen.cpp 123 {i}')
print('gens/gen.cpp 456')
""",
    )
    await generate_testcases()

    testing_pkg.print_debug()

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.in'
    ).read_text() == '123\n'
    assert (
        testing_pkg.get_build_testgroup_path('main') / '001.in'
    ).read_text() == '123\n'
    assert (
        testing_pkg.get_build_testgroup_path('main') / '002.in'
    ).read_text() == '123\n'
    assert (
        testing_pkg.get_build_testgroup_path('main') / '003.in'
    ).read_text() == '456\n'


async def test_generator_only_necessary_groups(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan(
        'main',
        """
gens/gen.cpp 123
""",
    )
    testing_pkg.add_testgroup_from_plan(
        'secondary',
        """
gens/gen.cpp 424242
""",
    )
    testing_pkg.add_testgroup_from_plan(
        'non_existent',
        """
gens/gen_non_existent.cpp 424242
""",
    )
    await generate_testcases(groups={'main'})

    testing_pkg.print_debug()

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.in'
    ).read_text() == '123\n'
    assert not (testing_pkg.get_build_testgroup_path('secondary') / '000.in').exists()


async def test_generator_with_glob_and_plan(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_glob('samples', 'manual_tests/*.in')
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen.cpp 424242')
    testing_pkg.add_file('manual_tests/000.in').write_text('123\n')
    testing_pkg.add_file('manual_tests/001.in').write_text('456\n')
    await generate_testcases()

    assert (
        testing_pkg.get_build_testgroup_path('samples') / '000.in'
    ).read_text() == '123\n'
    assert (
        testing_pkg.get_build_testgroup_path('samples') / '001.in'
    ).read_text() == '456\n'
    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.in'
    ).read_text() == '424242\n'


async def test_generator_copy_output_over(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_glob('samples', 'manual_tests/*.in')
    testing_pkg.add_file('manual_tests/000.in').write_text('123\n')
    testing_pkg.add_file('manual_tests/001.in').write_text('456\n')
    await generate_testcases()

    assert (
        testing_pkg.get_build_testgroup_path('samples') / '000.in'
    ).read_text() == '123\n'
    assert (
        testing_pkg.get_build_testgroup_path('samples') / '001.in'
    ).read_text() == '456\n'


async def test_generator_fix_crlf(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_glob('samples', 'manual_tests/*.in')
    testing_pkg.add_file('manual_tests/000.in').write_bytes(b'123\r\n\r\n456\r\n')
    testing_pkg.add_file('manual_tests/001.in').write_bytes(b'456\r\n')
    await generate_testcases()

    assert (
        testing_pkg.get_build_testgroup_path('samples') / '000.in'
    ).read_bytes() == b'123\n\n456\n'
    assert (
        testing_pkg.get_build_testgroup_path('samples') / '001.in'
    ).read_bytes() == b'456\n'


async def test_generator_erases_previously_built_testcases(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen.cpp 123')
    testing_pkg.add_testgroup_from_plan('secondary', 'gens/gen.cpp 456')
    await generate_testcases()

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.in'
    ).read_bytes() == b'123\n'
    assert (
        testing_pkg.get_build_testgroup_path('secondary') / '000.in'
    ).read_bytes() == b'456\n'

    # Regenerate but only with main group
    await generate_testcases(groups={'main'})

    # Ensure secondary group is not built
    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.in'
    ).read_bytes() == b'123\n'
    assert not (testing_pkg.get_build_testgroup_path('secondary') / '000.in').exists()


async def test_generator_non_existent(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen_non_existent.cpp 123\n')

    with pytest.raises(typer.Exit):
        await generate_testcases()

    out = capsys.readouterr().out
    assert 'Generator gens/gen_non_existent.cpp is not present in the package' in out
    assert (
        f'This generator is referenced from {testing_pkg.abspath("testplan/main.txt")}:1'
        in out
    )


# Asserts on the compilation output itself, so it needs a cold cache.
@pytest.mark.shared_cache(False)
async def test_generator_not_compile(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_generator('gens/gen.cpp').write_text(
        'int main() { cout << 3 << endl; }'
    )
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen.cpp 123')

    with pytest.raises(steps.CompilationError):
        await generate_testcases()

    out = capsys.readouterr().out

    testing_utils.has_columns(out, ['Compiling gens/gen.cpp...', 'FAILED'])


async def test_generate_standalone_copied_from(
    testing_pkg: testing_package.TestingPackage,
):
    input_file = testing_pkg.add_file('manual_tests/000.in')
    input_file.write_text('123\n')

    tmpd = testing_pkg.mkdtemp()
    spec = GenerationMetadata(
        copied_to=Testcase(inputPath=tmpd / '000.in'),
        copied_from=Testcase(
            inputPath=input_file,
        ),
    )
    await generate_standalone(spec)

    assert (tmpd / '000.in').read_bytes() == b'123\n'


async def test_generate_standalone_generator_call(
    testing_pkg: testing_package.TestingPackage,
):
    input_file = testing_pkg.add_file('manual_tests/000.in')
    input_file.write_text('123\n')

    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')

    tmpd = testing_pkg.mkdtemp()
    spec = GenerationMetadata(
        generator_call=GeneratorCall(
            name='gens/gen.cpp',
            args='456',
        ),
        copied_to=Testcase(inputPath=tmpd / '000.in'),
    )
    await generate_standalone(spec)

    assert (tmpd / '000.in').read_bytes() == b'456\n'


async def test_generate_standalone_validation_works(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')

    input_file = testing_pkg.add_file('manual_tests/000.in')
    input_file.write_text('123\n')

    tmpd = testing_pkg.mkdtemp()
    spec = GenerationMetadata(
        copied_to=Testcase(inputPath=tmpd / '000.in'),
        copied_from=Testcase(
            inputPath=input_file,
        ),
    )
    await generate_standalone(spec)

    assert (tmpd / '000.in').read_bytes() == b'123\n'


async def test_generate_standalone_validation_fails(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')

    input_file = testing_pkg.add_file('manual_tests/000.in')
    input_file.write_text('123 456\n')

    tmpd = testing_pkg.mkdtemp()
    spec = GenerationMetadata(
        copied_to=Testcase(inputPath=tmpd / '000.in'),
        copied_from=Testcase(
            inputPath=input_file,
        ),
    )

    with pytest.raises(ValidationError) as e:
        await generate_standalone(spec)

        assert 'failed validating testcase' in str(e)


async def test_generate_standalone_package_extra_validator_passes(
    testing_pkg: testing_package.TestingPackage,
):
    # Add a package-level extra validator that requires odd integers
    testing_pkg.add_from_testdata(
        'extra-validator-odd.cpp', src='validators/extra-validator-odd.cpp'
    )
    testing_pkg.yml.extraValidators = testing_pkg.yml.extraValidators + [
        CodeItem(path=pathlib.Path('extra-validator-odd.cpp'))
    ]
    testing_pkg.save()

    # Input satisfies odd constraint
    input_file = testing_pkg.add_file('manual_tests/000.in')
    input_file.write_text('123\n')

    tmpd = testing_pkg.mkdtemp()
    spec = GenerationMetadata(
        copied_to=Testcase(inputPath=tmpd / '000.in'),
        copied_from=Testcase(
            inputPath=input_file,
        ),
    )
    await generate_standalone(spec)

    assert (tmpd / '000.in').read_bytes() == b'123\n'


async def test_generate_standalone_package_extra_validator_fails(
    testing_pkg: testing_package.TestingPackage,
):
    # Add a package-level extra validator that requires odd integers
    testing_pkg.add_from_testdata(
        'extra-validator-odd.cpp', src='validators/extra-validator-odd.cpp'
    )
    testing_pkg.yml.extraValidators = testing_pkg.yml.extraValidators + [
        CodeItem(path=pathlib.Path('extra-validator-odd.cpp'))
    ]
    testing_pkg.save()

    # Input violates odd constraint
    input_file = testing_pkg.add_file('manual_tests/000.in')
    input_file.write_text('100\n')

    tmpd = testing_pkg.mkdtemp()
    spec = GenerationMetadata(
        copied_to=Testcase(inputPath=tmpd / '000.in'),
        copied_from=Testcase(
            inputPath=input_file,
        ),
    )

    with pytest.raises(ValidationError):
        await generate_standalone(spec)


async def test_generate_standalone_entry_validator_overrides_package(
    testing_pkg: testing_package.TestingPackage,
):
    # Package validator: any single integer is fine.
    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')
    # Group "strict" replaces the package validator with an "odd integer" validator.
    testing_pkg.add_from_testdata(
        'extra-validator-odd.cpp', src='validators/extra-validator-odd.cpp'
    )
    even_in = testing_pkg.add_file('tests/strict/000.in')
    even_in.write_text('100\n')
    testing_pkg.add_testgroup_from_glob(
        'strict', 'tests/strict/*.in', validator='extra-validator-odd.cpp'
    )

    [entry] = await extract_generation_testcases_from_groups({'strict'})

    # Sanity: the extracted entry carries the group-level validator.
    assert entry.validator is not None
    assert entry.validator.path == pathlib.Path('extra-validator-odd.cpp')

    with pytest.raises(ValidationError):
        await generate_standalone(entry.metadata, entry=entry)


async def test_generate_standalone_entry_validator_inherits_package(
    testing_pkg: testing_package.TestingPackage,
):
    # Package validator: any single integer is fine.
    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')
    # Group with no validator of its own -> inherits the package validator.
    loose_in = testing_pkg.add_file('tests/loose/000.in')
    loose_in.write_text('100\n')
    testing_pkg.add_testgroup_from_glob('loose', 'tests/loose/*.in')

    [entry] = await extract_generation_testcases_from_groups({'loose'})

    # '100\n' is a valid single integer -> no ValidationError.
    await generate_standalone(entry.metadata, entry=entry)


async def test_generate_standalone_entry_with_no_validators_skips_validation(
    testing_pkg: testing_package.TestingPackage,
):
    # Package has a validator that would reject this input...
    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')

    input_file = testing_pkg.add_file('manual_tests/000.in')
    input_file.write_text('not an int\n')

    tmpd = testing_pkg.mkdtemp()
    entry = GenerationTestcaseEntry.make_interactive(
        copied_to=Testcase(inputPath=tmpd / '000.in')
    )
    entry.metadata.copied_from = Testcase(inputPath=input_file)
    assert entry.validator is None and entry.extra_validators == []

    # ...but the entry declares no validators, so generate_standalone runs none.
    await generate_standalone(entry.metadata, entry=entry)

    # Whereas without an entry it falls back to the package validator and fails.
    with pytest.raises(ValidationError):
        await generate_standalone(entry.metadata)


async def test_generate_standalone_reuses_validators_digests_cache(
    testing_pkg: testing_package.TestingPackage, monkeypatch: pytest.MonkeyPatch
):
    # Configure main and extra validators
    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')
    testing_pkg.add_from_testdata(
        'extra-validator-odd.cpp', src='validators/extra-validator-odd.cpp'
    )
    testing_pkg.yml.extraValidators = testing_pkg.yml.extraValidators + [
        CodeItem(path=pathlib.Path('extra-validator-odd.cpp'))
    ]
    testing_pkg.save()

    # Precompile digests before monkeypatching
    all_validators = await validators_mod.compile_validators(
        validators=[
            CodeItem(path=pathlib.Path('validator.cpp')),
            CodeItem(path=pathlib.Path('extra-validator-odd.cpp')),
        ]
    )

    calls = []

    async def fake_compile_validators(validators, progress=None):
        paths = [str(v.path) for v in validators]
        calls.append(paths)
        return {p: all_validators[p] for p in paths}

    monkeypatch.setattr(
        validators_mod, 'compile_validators', fake_compile_validators, raising=True
    )

    # Input satisfies all validators
    input_file = testing_pkg.add_file('manual_tests/000.in')
    input_file.write_text('123\n')

    tmpd = testing_pkg.mkdtemp()
    spec = GenerationMetadata(
        copied_to=Testcase(inputPath=tmpd / '000.in'),
        copied_from=Testcase(
            inputPath=input_file,
        ),
    )

    # 1) Provide only main validator digest -> extra should be compiled once
    await generate_standalone(
        spec,
        validators_digests={'validator.cpp': all_validators['validator.cpp']},
    )
    assert calls == [['extra-validator-odd.cpp']]

    # 2) Provide both digests -> no compilation should happen
    calls.clear()
    await generate_standalone(
        spec,
        validators_digests=all_validators,
    )
    assert calls == []


async def test_generator_hash_duplicate_warning(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    # This generator ignores arguments and always outputs "123"
    testing_pkg.add_generator('gens/gen.cpp').write_text(
        '#include <bits/stdc++.h>\nusing namespace std;\nint main() { cout << 123 << endl; }'
    )
    testing_pkg.add_testgroup_from_plan(
        'main',
        """
gens/gen.cpp 1
gens/gen.cpp 2
""",
    )
    await generate_testcases()

    assert _duplicates() == [
        DuplicateTest(
            test='main/1 (gens/gen.cpp 2)', of='main/0 (gens/gen.cpp 1)', reason='input'
        )
    ]
    # Recorded for the end of the command, not printed mid-build.
    assert 'main/1' not in capsys.readouterr().out


async def test_generator_no_hash_duplicate_warning(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    # This generator outputs its argument
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan(
        'main',
        """
gens/gen.cpp 1
gens/gen.cpp 2
""",
    )
    await generate_testcases()

    assert _duplicates() == []


_CONSTANT_GENERATOR = '#include <bits/stdc++.h>\nusing namespace std;\nint main() { cout << 123 << endl; }'


def _duplicates() -> List[DuplicateTest]:
    return list(warning_stack.get_warning_stack().duplicate_tests)


async def test_allow_duplicate_annotation_is_stripped_from_args(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan(
        'main',
        """
gens/gen.cpp 123 @allow-duplicate
""",
    )
    await generate_testcases()

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.in'
    ).read_text() == '123\n'


@pytest.mark.parametrize(
    'plan',
    [
        'gens/gen.cpp 1\ngens/gen.cpp 2 @allow-duplicate\n',
        'gens/gen.cpp 1 @allow-duplicate\ngens/gen.cpp 2\n',
        '@input "123\\n" @allow-duplicate\ngens/gen.cpp 2\n',
    ],
)
async def test_allow_duplicate_annotation_on_either_test_silences_hash_duplicate(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
    plan: str,
):
    testing_pkg.add_generator('gens/gen.cpp').write_text(_CONSTANT_GENERATOR)
    testing_pkg.add_testgroup_from_plan('main', plan)
    await generate_testcases()

    assert _duplicates() == []


async def test_allow_duplicate_annotation_silences_same_call_duplicate(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan(
        'main',
        """
gens/gen.cpp 1
gens/gen.cpp 1 @allow-duplicate
""",
    )
    await generate_testcases()

    assert _duplicates() == []


async def test_allow_duplicate_still_warns_about_pairs_neither_allows(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_generator('gens/gen.cpp').write_text(_CONSTANT_GENERATOR)
    testing_pkg.add_testgroup_from_plan(
        'main',
        """
gens/gen.cpp 1 @allow-duplicate
gens/gen.cpp 2
gens/gen.cpp 3
""",
    )
    await generate_testcases()

    assert _duplicates() == [
        DuplicateTest(
            test='main/2 (gens/gen.cpp 3)', of='main/1 (gens/gen.cpp 2)', reason='input'
        )
    ]


async def test_allow_duplicate_group_silences_duplicates_across_groups(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_generator('gens/gen.cpp').write_text(_CONSTANT_GENERATOR)
    testing_pkg.add_testgroup_from_plan('first', 'gens/gen.cpp 1\n')
    testing_pkg.add_testgroup_from_plan('second', 'gens/gen.cpp 1\ngens/gen.cpp 2\n')
    testing_pkg.yml.testcases[-1].allowDuplicate = True
    testing_pkg.save()
    await generate_testcases()

    assert _duplicates() == []


async def test_allow_duplicate_subgroup_overrides_group(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    testing_pkg.add_generator('gens/gen.cpp').write_text(_CONSTANT_GENERATOR)
    testing_pkg.yml.testcases = testing_pkg.yml.testcases + [
        schema.TestcaseGroup(
            name='main',
            allowDuplicate=True,
            subgroups=[
                schema.TestcaseSubgroup(
                    name='inherits',
                    generators=[GeneratorCall(name='gens/gen.cpp', args='1')],
                ),
                schema.TestcaseSubgroup(
                    name='strict',
                    allowDuplicate=False,
                    generators=[
                        GeneratorCall(name='gens/gen.cpp', args='2'),
                        GeneratorCall(name='gens/gen.cpp', args='3'),
                    ],
                ),
            ],
        )
    ]
    testing_pkg.save()
    await generate_testcases()

    # The first `strict` test duplicates the `inherits` one, which allows it; the
    # second duplicates the first, and neither of them does. Indices restart per
    # subgroup.
    assert _duplicates() == [
        DuplicateTest(
            test='main/1 (gens/gen.cpp 3)', of='main/0 (gens/gen.cpp 2)', reason='input'
        )
    ]


async def test_generator_determinism_check_detects_nondeterministic_generator(
    testing_pkg: testing_package.TestingPackage,
):
    from rbx.box.environment import VerificationLevel
    from rbx.box.generators import GenerationError

    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-nondet.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen.cpp 123\n')

    with pytest.raises(GenerationError):
        await generate_testcases(verification=VerificationLevel.VALIDATE)


async def test_generator_determinism_check_passes_for_deterministic_generator(
    testing_pkg: testing_package.TestingPackage,
):
    from rbx.box.environment import VerificationLevel

    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen.cpp 123\n')

    # Should not raise.
    await generate_testcases(verification=VerificationLevel.VALIDATE)

    assert (
        testing_pkg.get_build_testgroup_path('main') / '000.in'
    ).read_text() == '123\n'


async def test_generator_determinism_check_skipped_at_verification_none(
    testing_pkg: testing_package.TestingPackage,
):
    from rbx.box.environment import VerificationLevel

    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-nondet.cpp')
    testing_pkg.add_testgroup_from_plan('main', 'gens/gen.cpp 123\n')

    # No verification → no determinism check → no error even though the
    # generator is non-deterministic.
    await generate_testcases(verification=VerificationLevel.NONE)


async def test_generate_standalone_warn_returns_the_rejection_instead_of_raising(
    testing_pkg: testing_package.TestingPackage,
    capsys: pytest.CaptureFixture[str],
):
    from rbx.box.run_validation import OnInvalid

    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')
    input_file = testing_pkg.add_file('manual_tests/000.in')
    input_file.write_text('123 456\n')

    tmpd = testing_pkg.mkdtemp()
    spec = GenerationMetadata(
        copied_to=Testcase(inputPath=tmpd / '000.in'),
        copied_from=Testcase(inputPath=input_file),
    )
    infos = await generate_standalone(spec, on_invalid=OnInvalid.WARN)

    assert infos is not None
    assert [(info.ok, str(info.validator.path)) for info in infos] == [
        (False, 'validator.cpp')
    ]
    # Still generated: the run goes on with it.
    assert (tmpd / '000.in').read_bytes() == b'123 456\n'
    out = ' '.join(capsys.readouterr().out.split())
    assert 'Running it anyway' in out


async def test_generate_standalone_without_validation_returns_none(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')
    input_file = testing_pkg.add_file('manual_tests/000.in')
    input_file.write_text('123 456\n')

    tmpd = testing_pkg.mkdtemp()
    spec = GenerationMetadata(
        copied_to=Testcase(inputPath=tmpd / '000.in'),
        copied_from=Testcase(inputPath=input_file),
    )

    assert await generate_standalone(spec, validate=False) is None


async def test_same_call_duplicate_is_recorded_with_its_call(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_generator('gens/gen.cpp', src='generators/gen-id.cpp')
    testing_pkg.add_testgroup_from_plan(
        'main',
        """
gens/gen.cpp 1
gens/gen.cpp 1
""",
    )
    await generate_testcases()

    (duplicate,) = _duplicates()
    assert duplicate.reason == 'call'
    assert duplicate.call == 'gens/gen.cpp 1'
    assert duplicate.test.startswith('main/1')
    assert duplicate.of.startswith('main/0')
