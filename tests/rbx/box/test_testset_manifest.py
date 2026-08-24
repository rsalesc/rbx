import pathlib
from typing import Any, Dict

import pytest
import yaml

from rbx import utils
from rbx.box import builder, package, testset_manifest
from rbx.box.environment import VerificationLevel
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
from rbx.box.testing import testing_package

# The manifest is written at the end of a real build, so every test here runs
# generation and validation over the same handful of C++ sources.
pytestmark = pytest.mark.shared_cache


def _add_two_groups(testing_pkg: testing_package.TestingPackage) -> None:
    # Whole-field assignment, not `set_var`: the yml is dumped with
    # `exclude_unset`, so mutating `vars` in place never reaches disk.
    testing_pkg.set_vars({'MAX_N': 100})

    testing_pkg.add_testgroup_from_glob('main', 'manual_tests/main/*.in')
    testing_pkg.add_file('manual_tests/main/000.in').write_text('1\n')
    testing_pkg.add_file('manual_tests/main/001.in').write_text('100\n')

    testing_pkg.add_testgroup_from_glob('extra', 'manual_tests/extra/*.in')
    testing_pkg.add_file('manual_tests/extra/000.in').write_text('42\n')

    testing_pkg.set_validator(
        'validator.cpp', src='validators/int-validator-bounded.cpp'
    )


async def _build(**kwargs) -> None:
    assert await builder.build(
        verification=VerificationLevel.VALIDATE.value,
        # No main solution in these packages: outputs are not what the manifest
        # is about, and generating them would need one.
        output=False,
        **kwargs,
    )


def _raw_manifest() -> Dict[str, Any]:
    return yaml.safe_load(testset_manifest.get_manifest_path().read_text())


def _manifest() -> testset_manifest.TestsetManifest:
    return utils.model_from_yaml(
        testset_manifest.TestsetManifest,
        testset_manifest.get_manifest_path().read_text(),
    )


def _built_inputs() -> set:
    """Every input file `build/tests` actually holds, as `group/stem`."""
    tests_path = package.get_build_tests_path()
    return {f'{path.parent.name}/{path.stem}' for path in tests_path.glob('*/*.in')}


async def test_build_writes_manifest_matching_generated_testcases(
    testing_pkg: testing_package.TestingPackage,
):
    _add_two_groups(testing_pkg)

    await _build()

    manifest = _manifest()
    assert manifest.version == testset_manifest.MANIFEST_VERSION

    # The whole point of `entries`: it round-trips into exactly the list the
    # build had in hand, so a reader can share its `skeleton.yml` parser.
    assert manifest.entries == await extract_generation_testcases_from_groups()

    assert [(group.name, group.subgroups) for group in manifest.groups] == [
        ('main', []),
        ('extra', []),
    ]
    # The effective vars each group was validated against, already merged and
    # expanded -- a reader cannot redo that merge.
    assert all(group.vars == {'MAX_N': 100} for group in manifest.groups)
    assert [(test.group, test.index) for test in manifest.tests] == [
        ('main', 0),
        ('main', 1),
        ('extra', 0),
    ]
    assert [test.input_size for test in manifest.tests] == [2, 4, 3]
    assert all(
        test.validation is not None and test.validation.ok for test in manifest.tests
    )
    assert all(
        test.validation is not None
        and test.validation.validator == pathlib.Path('validator.cpp')
        and test.validation.message is None
        for test in manifest.tests
    )

    assert manifest.validation is not None
    assert {v.group: v.bounds for v in manifest.validation} == {
        'main': {'"x"': (True, True)},
        'extra': {'"x"': (False, False)},
    }


async def test_subset_build_describes_only_the_groups_that_survived(
    testing_pkg: testing_package.TestingPackage,
):
    """A subset build replaces the manifest; it does not merge into it.

    `generate_testcases` rmtree's the whole of `build/tests` before it looks at
    the group filter, so `extra`'s testcases are gone from disk after a
    `--groups main` build. Carrying its rows over would make the manifest
    assert testcases that no longer exist.
    """
    _add_two_groups(testing_pkg)

    await _build()
    assert _built_inputs() == {'main/000', 'main/001', 'extra/000'}

    await _build(groups={'main'})

    # The filesystem first: this is the fact the manifest has to agree with, and
    # asserting it here is what makes the test fail if the wipe ever narrows.
    assert _built_inputs() == {'main/000', 'main/001'}

    manifest = _manifest()
    assert [group.name for group in manifest.groups] == ['main']
    assert [(test.group, test.index) for test in manifest.tests] == [
        ('main', 0),
        ('main', 1),
    ]
    assert [
        (entry.group_entry.group, entry.group_entry.index) for entry in manifest.entries
    ] == [('main', 0), ('main', 1)]
    assert manifest.validation is not None
    assert {v.group for v in manifest.validation} == {'main'}


async def test_build_without_validation_omits_the_validation_key(
    testing_pkg: testing_package.TestingPackage,
):
    _add_two_groups(testing_pkg)

    await _build(validate=False)

    raw = _raw_manifest()
    assert 'validation' not in raw
    assert all('validation' not in test for test in raw['tests'])

    assert _manifest().validation is None


async def test_corrupt_previous_manifest_is_overwritten_cleanly(
    testing_pkg: testing_package.TestingPackage,
):
    """A manifest nobody can parse must never be able to fail a build."""
    _add_two_groups(testing_pkg)

    await _build()

    path = testset_manifest.get_manifest_path()
    path.write_text('entries: [[[ not yaml at all\n')

    await _build()

    manifest = _manifest()
    assert [group.name for group in manifest.groups] == ['main', 'extra']
    assert [(test.group, test.index) for test in manifest.tests] == [
        ('main', 0),
        ('main', 1),
        ('extra', 0),
    ]
