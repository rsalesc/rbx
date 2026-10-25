"""How CMS judges an rbx interactive problem.

CMS's Communication task type runs a single program, the manager, against the
contestant. rbx's manager (`cms_manager.cpp`) compiles the problem's testlib
interactor in, and for a legacy interactor hands its output to the problem's
checker (`cms_checker.cpp`), as rbx does locally. Both sources expect the
problem's `interactor.cpp` / `check.cpp`, `testlib.h` and `rbx.h` next to them.
"""

import pathlib
import shutil
from typing import List, Union

from rbx.box.schema import Package, TaskType
from rbx.config import get_resources_dir

TASK_TYPE = 'Communication'
# One contestant process, compiled alone, speaking through stdin/stdout.
TASK_TYPE_PARAMETERS: List[Union[int, str]] = [1, 'alone', 'std_io']


def task_type_parameters(pkg: Package) -> List[Union[int, str]]:
    """With a grader, the contestant is compiled with it: CMS 1.5.1 calls that
    `stub` (and the source `stub.cpp`); later versions renamed both `grader`."""
    if pkg.grader is not None:
        return [1, 'stub', 'std_io']
    return TASK_TYPE_PARAMETERS


MANAGER_SOURCE = 'cms_manager.cpp'
CHECKER_RUNNER_SOURCE = 'cms_checker.cpp'
_SOURCES = [MANAGER_SOURCE, CHECKER_RUNNER_SOURCE, 'rbx_cms_report.h']

_INPUT_HEADER = b'RBX-CMS-INPUT'


def is_communication(pkg: Package) -> bool:
    return pkg.type == TaskType.COMMUNICATION


def needs_checker(pkg: Package) -> bool:
    """Whether the problem's checker grades the interactor's output.

    Only a legacy interactor has a real checker; a modern one is the sole judge.
    The checker reads the answer, which CMS never gives the manager, so its
    tests must carry it (`pack_input`).
    """
    return (
        is_communication(pkg) and pkg.interactor is not None and pkg.interactor.legacy
    )


def pack_input(data: bytes, answer: bytes) -> bytes:
    """A test input that also carries its answer, as the manager reads it."""
    header = b'%s %d %d\n' % (_INPUT_HEADER, len(data), len(answer))
    return header + data + answer


def write_sources(into: pathlib.Path):
    """Write the manager and checker runner sources into `into`."""
    resources = get_resources_dir(pathlib.Path('packagers') / 'cms')
    into.mkdir(parents=True, exist_ok=True)
    for name in _SOURCES:
        shutil.copyfile(resources / name, into / name)
