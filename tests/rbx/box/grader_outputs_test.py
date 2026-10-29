import pathlib
import tempfile
from unittest import mock

from rbx.box import compile, graders, package, solutions, unit
from rbx.box.generators import generate_outputs_for_testcases, generate_testcases
from rbx.box.schema import CodeItem, ExpectedOutcome, Grader
from rbx.box.testcase_schema import TestcaseEntry
from rbx.box.testing import testing_package
from rbx.utils import StatusProgress

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


# Reads the answer: what `irun --answer` hands it must carry the frame.
_ANSWER_CHECKER = """
#include "testlib.h"
#include "rbx.h"

int main(int argc, char *argv[]) {
  rbx::registerGraderChecker(argc, argv);
  long long expected = ans.readLong();
  long long got = ouf.readLong();
  if (expected != got) quitf(_wa, "expected %lld, got %lld", expected, got);
  quitf(_ok, "answer matched");
}
"""

# Never reads the answer, so a checker unit test can leave it out.
_INPUT_CHECKER = """
#include "testlib.h"
#include "rbx.h"

int main(int argc, char *argv[]) {
  rbx::registerGraderChecker(argc, argv);
  long long x = inf.readLong();
  long long got = ouf.readLong();
  if (got != 2 * x) quitf(_wa, "expected %lld, got %lld", 2 * x, got);
  quitf(_ok, "doubled");
}
"""


def _setup_grader_package(testing_pkg: testing_package.TestingPackage) -> None:
    testing_pkg.add_file('graders/grader.cpp').write_text(_GRADER)
    testing_pkg.add_file('graders/twice.h').write_text(_HEADER)
    testing_pkg.add_solution('sol.cpp', outcome=ExpectedOutcome.ACCEPTED).write_text(
        _SOLUTION
    )
    testing_pkg.yml.grader = Grader(
        path=pathlib.Path('graders/grader.cpp'), secret='twice-0123456789abcdef'
    )
    testing_pkg.save()


async def test_irun_answer_reaches_the_checker_framed(
    testing_pkg: testing_package.TestingPackage,
):
    _setup_grader_package(testing_pkg)
    testing_pkg.set_checker('checker.cpp').write_text(_ANSWER_CHECKER)
    testing_pkg.add_file('in.txt').write_text('21\n')
    testing_pkg.add_file('ans.txt').write_text('42\n')

    await solutions.run_and_print_interactive_solutions(
        tracked_solutions=['sol.cpp'],
        input_file=pathlib.Path('in.txt'),
        answer_file=pathlib.Path('ans.txt'),
    )

    evaluation = (package.get_problem_iruns_dir() / '0' / '000.eval').read_text()
    assert 'outcome: accepted' in evaluation
    assert 'answer matched' in evaluation


async def test_checker_unit_test_without_an_answer(
    testing_pkg: testing_package.TestingPackage, capsys
):
    _setup_grader_package(testing_pkg)
    testing_pkg.set_checker('checker.cpp').write_text(_INPUT_CHECKER)
    testing_pkg.add_checker_unit_test(
        glob='unit/wa/*.in',
        outcome=ExpectedOutcome.WRONG_ANSWER,
        files={'unit/wa/a.in': '3\n', 'unit/wa/a.out': '7\n'},
    )
    testing_pkg.add_checker_unit_test(
        glob='unit/ac/*.in',
        outcome=ExpectedOutcome.ACCEPTED,
        files={'unit/ac/a.in': '3\n', 'unit/ac/a.out': '6\n'},
    )

    with tempfile.TemporaryDirectory() as tmpd:
        await unit.run_checker_unit_tests(
            mock.Mock(spec=StatusProgress), pathlib.Path(tmpd)
        )

    out = capsys.readouterr().out
    assert 'FAIL' not in out
    assert out.count('OK Unit test') == 2


async def test_compile_links_an_unlisted_solution_with_the_grader(
    testing_pkg: testing_package.TestingPackage,
):
    _setup_grader_package(testing_pkg)
    # Not listed in problem.rbx.yml. It has no main of its own, so it only
    # links next to the grader.
    testing_pkg.add_file('atk/other.cpp').write_text(_SOLUTION)

    await compile.any('atk/other.cpp')

    assert (package.get_build_path() / 'exe').is_file()


async def test_compile_keeps_a_listed_extra_validator_off_the_grader(
    testing_pkg: testing_package.TestingPackage,
):
    _setup_grader_package(testing_pkg)
    testing_pkg.yml.extraValidators = [CodeItem(path=pathlib.Path('extra.cpp'))]
    testing_pkg.save()
    # A main of its own: linked with the grader, it would not link.
    testing_pkg.add_file('extra.cpp').write_text('int main() { return 0; }\n')

    await compile.any('extra.cpp')

    assert (package.get_build_path() / 'exe').is_file()


async def test_compile_builds_an_unlisted_file_without_a_grader(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_file('other.cpp').write_text('int main() { return 0; }\n')

    await compile.any('other.cpp')

    assert (package.get_build_path() / 'exe').is_file()
