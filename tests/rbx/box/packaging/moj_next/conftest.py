import pathlib
from typing import List

import pytest

from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.packaging.moj_next.packager import MojNextPackager
from rbx.box.schema import Testcase
from rbx.box.testcase_schema import TestcaseEntry

CHECKER = '#include "testlib.h"\nint main(){ quitf(_ok, "ok"); }\n'
ACCEPTED_SOL = '#include <cstdio>\nint main(){ int a,b; scanf("%d %d",&a,&b); printf("%d\\n",a+b); }\n'
WRONG_SOL = '#include <cstdio>\nint main(){ printf("0\\n"); }\n'
SLOW_SOL = '#include <cstdio>\nint main(){ while(1); }\n'


def _entry(
    tmp_path: pathlib.Path, group: str, index: int, content: str
) -> GenerationTestcaseEntry:
    """A built testcase entry backed by real files.

    `find_built_testcases` only requires that `copied_to.inputPath` exists, so the
    packager can be exercised without a full sandboxed build.
    """
    group_dir = tmp_path / 'built' / group
    group_dir.mkdir(parents=True, exist_ok=True)
    input_path = group_dir / f'{index:03d}.in'
    output_path = group_dir / f'{index:03d}.out'
    input_path.write_text(content)
    output_path.write_text('42\n')
    entry = TestcaseEntry(group=group, index=index)
    return GenerationTestcaseEntry(
        group_entry=entry,
        subgroup_entry=entry,
        metadata=GenerationMetadata(
            copied_to=Testcase(inputPath=input_path, outputPath=output_path)
        ),
    )


def build_entries(
    tmp_path: pathlib.Path, groups: List[str]
) -> List[GenerationTestcaseEntry]:
    entries = []
    for group in groups:
        for index in range(2):
            entries.append(_entry(tmp_path, group, index, f'{group} {index}\n'))
    return entries


def run_packager(
    testing_pkg, tmp_path: pathlib.Path, entries: List[GenerationTestcaseEntry]
) -> pathlib.Path:
    into_path = tmp_path / 'package'
    build_path = tmp_path / 'build'
    build_path.mkdir(parents=True, exist_ok=True)
    MojNextPackager(testcase_entries=entries).package(build_path, into_path, [])
    return into_path


@pytest.fixture
def moj_next_binary_package(testing_pkg, tmp_path) -> pathlib.Path:
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text(ACCEPTED_SOL)
    testing_pkg.add_testgroup_with_manual_testcases('samples', [])
    testing_pkg.add_testgroup_with_manual_testcases('easy', [])
    testing_pkg.save()

    return run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples', 'easy'])
    )


@pytest.fixture
def moj_next_package(moj_next_binary_package) -> pathlib.Path:
    return moj_next_binary_package


@pytest.fixture
def moj_next_package_output(testing_pkg, tmp_path, capsys) -> str:
    """Console output of packaging a problem whose only accepted solution is C++."""
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text(ACCEPTED_SOL)
    testing_pkg.save()

    run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))
    return capsys.readouterr().out
