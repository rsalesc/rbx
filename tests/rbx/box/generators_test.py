import pathlib

import pytest

from rbx.box import package
from rbx.box.generators import (
    generate_outputs_for_testcases,
    generate_testcases,
)
from rbx.box.testcase_extractors import extract_generation_testcases_from_groups
from rbx.testing_utils import print_directory_tree


@pytest.mark.test_pkg('box1')
async def test_generator_works(pkg_from_testdata: pathlib.Path):
    await generate_testcases()
    entries = [
        entry.group_entry for entry in await extract_generation_testcases_from_groups()
    ]
    await generate_outputs_for_testcases(entries)

    # Debug when fail.
    print_directory_tree(pkg_from_testdata)

    assert (
        package.get_build_testgroup_path('gen1') / '0-000.in'
    ).read_text() == '777\n'
    assert (
        package.get_build_testgroup_path('gen1') / '1-gen-000.in'
    ).read_text() == '123\n'
    assert (
        package.get_build_testgroup_path('gen1') / '1-gen-001.in'
    ).read_text() == '424242\n'
    assert (
        package.get_build_testgroup_path('gen1') / '2-genScript-000.in'
    ).read_text() == '25\n'


@pytest.mark.test_pkg('box1')
async def test_generator_cache_works(
    pkg_from_testdata: pathlib.Path,
):
    # Run the first time.
    await generate_testcases()
    assert (
        package.get_build_testgroup_path('gen1') / '1-gen-000.in'
    ).read_text() == '123\n'
    assert (
        package.get_build_testgroup_path('gen1') / '1-gen-001.in'
    ).read_text() == '424242\n'

    # Change the generator `gen1`, but keep `gen2` as is.
    gen_path = pkg_from_testdata / 'gen1.cpp'
    gen_path.write_text(gen_path.read_text().replace('123', '4567'))

    # Run the second time.
    await generate_testcases()

    # Debug when fail.
    print_directory_tree(pkg_from_testdata)

    assert (
        package.get_build_testgroup_path('gen1') / '1-gen-000.in'
    ).read_text() == '4567\n'
    assert (
        package.get_build_testgroup_path('gen1') / '1-gen-001.in'
    ).read_text() == '424242\n'
