"""`builder.verify` on a subset of the test groups.

A solution's expected outcome is a claim about the *whole* testset: a solution
declared TLE is supposed to pass the samples and only die on the big tests. So a
build restricted to one group (`rbx package polygon -u` builds only `samples`,
since Polygon regenerates the rest server-side) cannot judge solutions -- doing
so failed every package with a non-AC solution (#865).
"""

import pytest

from rbx.box import builder
from rbx.box.environment import VerificationLevel
from rbx.box.schema import ExpectedOutcome
from rbx.box.testing import testing_package

pytestmark = pytest.mark.shared_cache

_SUM = (
    '#include <iostream>\n'
    'int main() { int a, b; std::cin >> a >> b; std::cout << a + b << std::endl; }\n'
)


def _add_manual_test(
    pkg: testing_package.TestingPackage, group: str, contents: str
) -> None:
    pkg.add_file(f'manual/{group}.in', src=None)
    (pkg.root / 'manual' / f'{group}.in').write_text(contents)
    pkg.add_testgroup_with_manual_testcases(
        group, [{'inputPath': f'manual/{group}.in'}]
    )


@pytest.fixture
def pkg(testing_pkg: testing_package.TestingPackage):
    """An AC main solution and a fast solution declared TLE, samples and main."""
    testing_pkg.add_solution('sols/ac.cpp', outcome=ExpectedOutcome.ACCEPTED)
    (testing_pkg.root / 'sols' / 'ac.cpp').write_text(_SUM)
    # Passes every test, which a TLE solution is entitled to do on the samples:
    # it is only supposed to be slow on tests this package does not even have.
    testing_pkg.add_solution(
        'sols/tle.cpp', outcome=ExpectedOutcome.TIME_LIMIT_EXCEEDED
    )
    (testing_pkg.root / 'sols' / 'tle.cpp').write_text(_SUM)
    _add_manual_test(testing_pkg, 'samples', '1 2\n')
    _add_manual_test(testing_pkg, 'main', '3 4\n')
    return testing_pkg


async def test_verify_on_a_subset_of_groups_does_not_judge_solutions(
    pkg: testing_package.TestingPackage,
):
    assert await builder.verify(
        verification=VerificationLevel.FULL.value, groups={'samples'}
    )


async def test_verify_on_the_full_testset_still_judges_solutions(
    pkg: testing_package.TestingPackage,
):
    assert not await builder.verify(verification=VerificationLevel.FULL.value)
