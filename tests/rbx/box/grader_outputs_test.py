import pathlib
from unittest import mock

from rbx.box import graders
from rbx.box.generators import generate_outputs_for_testcases, generate_testcases
from rbx.box.schema import ExpectedOutcome, Grader
from rbx.box.testcase_schema import TestcaseEntry
from rbx.box.testing import testing_package

_GRADER = """
#include <cstdio>

#include "rbx.h"
#include "twice.h"

int main() {
  rbx::grader::Grader grader;
  long long x;
  if (std::scanf("%lld", &x) != 1) return 1;
  long long r = grader.run([&] { return twice(x); });
  std::printf("%lld\\n", r);
}
"""

_HEADER = 'long long twice(long long x);\n'

_SOLUTION = """
#include "twice.h"

long long twice(long long x) { return 2 * x; }
"""


async def test_public_build_is_compiled_once_for_every_sample(
    testing_pkg: testing_package.TestingPackage,
):
    # Several samples: each one used to compile the public build on its own,
    # in parallel, which stored the same binary concurrently.
    testing_pkg.add_file('graders/grader.cpp').write_text(_GRADER)
    testing_pkg.add_file('graders/twice.h').write_text(_HEADER)
    testing_pkg.add_solution('sol.cpp', outcome=ExpectedOutcome.ACCEPTED).write_text(
        _SOLUTION
    )
    for i, x in enumerate([3, 5, 7, 11]):
        testing_pkg.add_file(f'samples/{i:03d}.in').write_text(f'{x}\n')
    testing_pkg.add_testgroup_from_glob('samples', 'samples/*.in')
    testing_pkg.yml.grader = Grader(
        path=pathlib.Path('graders/grader.cpp'), secret='twice-0123456789abcdef'
    )
    testing_pkg.save()

    await generate_testcases()
    entries = [TestcaseEntry(group='samples', index=i) for i in range(4)]
    with mock.patch.object(
        graders, 'compile_public', wraps=graders.compile_public
    ) as compile_public:
        await generate_outputs_for_testcases(entries)

    assert compile_public.call_count == 1
    build = testing_pkg.get_build_testgroup_path('samples')
    answers = [(build / f'{i:03d}.out.statement').read_text().strip() for i in range(4)]
    assert answers == ['6', '10', '14', '22']
