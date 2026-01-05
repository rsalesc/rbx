import pathlib

import pytest
import typer

from rbx.box import validators as validators_mod
from rbx.box.generators import (
    ValidationError,
    generate_standalone,
    generate_testcases,
)
from rbx.box.schema import CodeItem, GeneratorCall, Testcase
from rbx.box.testcase_extractors import GenerationMetadata
from rbx.box.testing import testing_package
from rbx.grading import steps


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
    assert 'Failed compiling generator gens/gen.cpp' in out


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
    all_validators = validators_mod.compile_validators(
        validators=[
            CodeItem(path=pathlib.Path('validator.cpp')),
            CodeItem(path=pathlib.Path('extra-validator-odd.cpp')),
        ]
    )

    calls = []

    def fake_compile_validators(validators, progress=None):
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

    from rbx.utils import strip_ansi_codes

    out = strip_ansi_codes(capsys.readouterr().out)
    assert 'Test main/1 is a hash duplicate of main/0.' in out


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

    out = capsys.readouterr().out
    assert 'is a hash duplicate of' not in out
