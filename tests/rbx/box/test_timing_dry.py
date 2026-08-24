"""`rbx time --dry` runs the whole flow but leaves the disk untouched.

The flag exists to exercise the estimation -- the build, the runs, the picker,
the upper-bound check -- without committing to what it produced, so every path
of `rbx time` that would write something must become a no-op under it: the
limits profile the estimation writes, the profile the `inherit` and `custom`
strategies write, and the `problem.rbx.yml` that `--integrate` rewrites.
"""

import asyncio
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box import cli, package, timing
from rbx.box.schema import ExpectedOutcome
from rbx.box.testing import testing_package


@pytest.fixture
def runner() -> CliRunner:
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    return CliRunner()


@pytest.fixture(autouse=True)
def _skip_preset_check():
    with mock.patch('rbx.box.presets.check_active_preset_compatibility'):
        yield


async def _build_ok(*args, **kwargs):
    return True


def test_dry_reaches_the_estimation(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    seen = {}

    async def compute_time_limits(*args, **kwargs):
        seen.update(kwargs)
        return timing.TimingProfile(timeLimit=1000)

    with (
        mock.patch('rbx.box.builder.build', _build_ok),
        mock.patch('rbx.box.timing.compute_time_limits', compute_time_limits),
    ):
        result = runner.invoke(cli.app, ['time', '--auto', '--dry'])

    assert result.exit_code == 0, result.output
    assert seen['dry'] is True


def test_the_estimation_writes_the_profile_unless_it_is_dry(
    runner: CliRunner,
    testing_pkg: testing_package.TestingPackage,
):
    seen = {}

    async def compute_time_limits(*args, **kwargs):
        seen.update(kwargs)
        return timing.TimingProfile(timeLimit=1000)

    with (
        mock.patch('rbx.box.builder.build', _build_ok),
        mock.patch('rbx.box.timing.compute_time_limits', compute_time_limits),
    ):
        result = runner.invoke(cli.app, ['time', '--auto'])

    assert result.exit_code == 0, result.output
    assert seen['dry'] is False


def test_inherit_writes_nothing_when_dry(
    testing_pkg: testing_package.TestingPackage,
):
    limits_path = package.get_limits_file('local')

    timing.inherit_time_limits(profile='local', dry=True)

    assert not limits_path.exists()


def test_a_custom_limit_writes_nothing_when_dry(
    testing_pkg: testing_package.TestingPackage,
):
    limits_path = package.get_limits_file('local')

    timing.set_time_limit(1234, profile='local', dry=True)

    assert not limits_path.exists()


def test_integrate_leaves_the_package_untouched_when_dry(
    testing_pkg: testing_package.TestingPackage,
):
    # A saved profile the package does not carry yet: without --dry this would
    # rewrite `problem.rbx.yml` with its time limit.
    timing.set_time_limit(4242, profile='local')
    before = testing_pkg.yml_path.read_text()

    timing.integrate('local', dry=True)

    assert testing_pkg.yml_path.read_text() == before


def test_integrate_rewrites_the_package_when_not_dry(
    testing_pkg: testing_package.TestingPackage,
):
    timing.set_time_limit(4242, profile='local')

    timing.integrate('local')

    assert package.find_problem_package_or_die().timeLimit == 4242


@pytest.fixture
def _stub_estimation(testing_pkg: testing_package.TestingPackage):
    """The estimation, reduced to the profile it produced.

    Everything `compute_time_limits` does before the write -- the inference run,
    the grouping, the upper-bound check -- has its own tests; what is under test
    here is only what happens to the profile afterwards.
    """
    testing_pkg.add_solution('sol.cpp', ExpectedOutcome.ACCEPTED)

    async def run_for_inference(*args, **kwargs):
        return mock.MagicMock()

    async def build_estimation_context(*args, **kwargs):
        return mock.MagicMock()

    async def estimate_and_validate(*args, **kwargs):
        return timing.TimingProfile(timeLimit=1000)

    with (
        mock.patch('rbx.box.timing._run_for_inference', run_for_inference),
        mock.patch('rbx.box.timing.build_estimation_context', build_estimation_context),
        mock.patch('rbx.box.timing._estimate_and_validate', estimate_and_validate),
        mock.patch('rbx.box.timing.get_inference_solutions', return_value=[]),
    ):
        yield


@pytest.mark.usefixtures('_stub_estimation')
def test_the_estimated_profile_is_not_written_when_dry():
    limits_path = package.get_limits_file('local')

    estimated = asyncio.get_event_loop().run_until_complete(
        timing.compute_time_limits(check=False, detailed=False, dry=True)
    )

    # The command still succeeds and still reports the limit it estimated --
    # only the file is missing.
    assert estimated is not None
    assert not limits_path.exists()


@pytest.mark.usefixtures('_stub_estimation')
def test_the_estimated_profile_is_written_when_not_dry():
    limits_path = package.get_limits_file('local')

    estimated = asyncio.get_event_loop().run_until_complete(
        timing.compute_time_limits(check=False, detailed=False)
    )

    assert estimated is not None
    assert limits_path.exists()
