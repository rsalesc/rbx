import contextlib
import pathlib
import resource
import sys
from unittest import mock

import pytest

from rbx.box import state
from rbx.box.sanitizers.issue_stack import (
    IssueAccumulator,
    IssueSeverity,
    issue_stack_var,
)
from rbx.grading import steps
from rbx.grading.judge.sandbox import SandboxBase, SandboxParams
from rbx.grading.steps import (
    GradingArtifacts,
    GradingFileInput,
    GradingFileOutput,
    GradingLogsHolder,
    StackLimitNotHonoredIssue,
    _maybe_complain_about_stack_limit,
)


@contextlib.contextmanager
def _fresh_issue_stack():
    """Isolate the issue stack, so a test sees exactly the issues it caused."""
    accumulator = IssueAccumulator()
    token = issue_stack_var.set([accumulator])
    try:
        yield accumulator
    finally:
        issue_stack_var.reset(token)


def _fake_stack_rlimit(soft: int, hard: int):
    """Report `(soft, hard)` for RLIMIT_STACK only, leaving every other rlimit
    query -- including the ones the sandbox makes while spawning -- untouched."""
    real_getrlimit = resource.getrlimit

    def getrlimit(which: int):
        if which == resource.RLIMIT_STACK:
            return (soft, hard)
        return real_getrlimit(which)

    return mock.patch('resource.getrlimit', side_effect=getrlimit)


@pytest.fixture(autouse=True)
def clear_stack_limit_cache():
    """`_complain_about_stack_limit` is cached, so a verdict reached under one
    test's mocked platform/config must not carry into the next."""
    steps._complain_about_stack_limit.cache_clear()  # noqa: SLF001
    yield
    steps._complain_about_stack_limit.cache_clear()  # noqa: SLF001


@pytest.fixture
def cli_mode():
    """The probe only runs under the CLI; pin the flag on and put it back."""
    original = state.STATE.run_through_cli
    state.STATE.run_through_cli = True
    try:
        yield
    finally:
        state.STATE.run_through_cli = original


@pytest.fixture
def stack_check_enabled():
    """`_maybe_complain_about_stack_limit` reads the setter config; pin it on."""
    with mock.patch('rbx.box.setter_config.get_setter_config') as mock_config:
        mock_config.return_value.judging.check_stack = True
        yield mock_config


class TestStackLimitNotHonoredIssue:
    def test_issue_is_a_warning_not_an_error(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=8 * 1024 * 1024)

        assert issue.get_severity() == IssueSeverity.WARNING

    def test_detailed_message_names_both_limits_and_links_the_docs(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=8 * 1024 * 1024)

        message = issue.get_detailed_message()

        assert '256 MiB' in message
        assert '8 MiB' in message
        assert 'https://rbx.rsalesc.dev/stack-limit/' in message

    def test_detailed_message_says_unenforced_when_there_is_no_hard_limit(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=None)

        message = issue.get_detailed_message()

        assert '256 MiB' in message
        assert 'macOS' in message
        assert 'https://rbx.rsalesc.dev/stack-limit/' in message

    def test_both_reports_file_the_issue_under_the_same_section(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=None)

        assert issue.get_detailed_section() == ('stack limit',)
        assert issue.get_overview_section() == ('stack limit',)

    def test_overview_message_is_present_and_links_the_docs(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=8 * 1024 * 1024)

        assert 'https://rbx.rsalesc.dev/stack-limit/' in issue.get_overview_message()

    def test_two_issues_with_the_same_values_produce_the_same_message(self):
        """The issue stack dedupes on the message string, so this is what makes
        the warning print once per run rather than once per program."""
        first = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=8 * 1024 * 1024)
        second = StackLimitNotHonoredIssue(
            requested_mib=256, hard_limit=8 * 1024 * 1024
        )

        assert first.get_detailed_message() == second.get_detailed_message()
        assert first.get_overview_message() == second.get_overview_message()


class TestMaybeComplainAboutStackLimit:
    @mock.patch('sys.platform', 'linux')
    def test_warns_on_linux_when_the_hard_limit_is_below_the_request(
        self, stack_check_enabled, cli_mode
    ):
        params = SandboxParams(stack_space=256)

        with mock.patch(
            'resource.getrlimit', return_value=(8 * 1024 * 1024, 8 * 1024 * 1024)
        ):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert len(accumulator.issues) == 1
        issue = accumulator.issues[0]
        assert issue.requested_mib == 256
        assert issue.hard_limit == 8 * 1024 * 1024

    @mock.patch('sys.platform', 'linux')
    def test_silent_on_linux_when_the_hard_limit_is_above_the_request(
        self, stack_check_enabled, cli_mode
    ):
        params = SandboxParams(stack_space=64)

        with mock.patch(
            'resource.getrlimit', return_value=(8 * 1024 * 1024, 512 * 1024 * 1024)
        ):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'linux')
    def test_silent_on_linux_when_the_hard_limit_exactly_meets_the_request(
        self, stack_check_enabled, cli_mode
    ):
        """The boundary: a hard limit equal to the request is honored in full."""
        params = SandboxParams(stack_space=256)

        with mock.patch(
            'resource.getrlimit', return_value=(8 * 1024 * 1024, 256 * 1024 * 1024)
        ):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'linux')
    def test_silent_when_not_running_through_the_cli(self, stack_check_enabled):
        """Outside the CLI nothing reads the report, and reading the setter config
        would create `setter_config.yml` on disk."""
        params = SandboxParams(stack_space=256)
        original = state.STATE.run_through_cli
        state.STATE.run_through_cli = False

        try:
            with mock.patch(
                'resource.getrlimit', return_value=(8 * 1024 * 1024, 8 * 1024 * 1024)
            ):
                with _fresh_issue_stack() as accumulator:
                    _maybe_complain_about_stack_limit(params)
        finally:
            state.STATE.run_through_cli = original

        assert not accumulator.issues
        stack_check_enabled.assert_not_called()

    @mock.patch('sys.platform', 'linux')
    def test_silent_on_linux_when_the_hard_limit_is_unlimited(
        self, stack_check_enabled, cli_mode
    ):
        params = SandboxParams(stack_space=1024)

        with mock.patch(
            'resource.getrlimit',
            return_value=(8 * 1024 * 1024, resource.RLIM_INFINITY),
        ):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'linux')
    def test_the_soft_limit_is_irrelevant_on_linux(self, stack_check_enabled, cli_mode):
        """We raise the soft limit ourselves in the child; only the hard one caps us."""
        params = SandboxParams(stack_space=64)

        with mock.patch(
            'resource.getrlimit',
            return_value=(1 * 1024 * 1024, resource.RLIM_INFINITY),
        ):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'darwin')
    def test_warns_on_darwin_whenever_a_limit_is_configured(
        self, stack_check_enabled, cli_mode
    ):
        """macOS never applies RLIMIT_STACK, so the numbers do not matter."""
        params = SandboxParams(stack_space=256)

        with mock.patch(
            'resource.getrlimit',
            return_value=(resource.RLIM_INFINITY, resource.RLIM_INFINITY),
        ):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert len(accumulator.issues) == 1
        assert accumulator.issues[0].hard_limit is None

    @mock.patch('sys.platform', 'linux')
    def test_silent_when_no_limit_is_configured(self, stack_check_enabled, cli_mode):
        params = SandboxParams(stack_space=None)

        with mock.patch(
            'resource.getrlimit', return_value=(8 * 1024 * 1024, 8 * 1024 * 1024)
        ):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'linux')
    def test_silent_when_the_check_is_disabled_in_the_setter_config(self, cli_mode):
        params = SandboxParams(stack_space=256)

        with mock.patch('rbx.box.setter_config.get_setter_config') as mock_config:
            mock_config.return_value.judging.check_stack = False
            with mock.patch(
                'resource.getrlimit', return_value=(8 * 1024 * 1024, 8 * 1024 * 1024)
            ):
                with _fresh_issue_stack() as accumulator:
                    _maybe_complain_about_stack_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'linux')
    def test_repeated_calls_file_the_issue_only_once(
        self, stack_check_enabled, cli_mode
    ):
        """A stress run spawns tens of thousands of programs; the report dedupes
        the message anyway, so only the first call should accumulate an issue."""
        params = SandboxParams(stack_space=256)

        with mock.patch(
            'resource.getrlimit', return_value=(8 * 1024 * 1024, 8 * 1024 * 1024)
        ):
            with _fresh_issue_stack() as accumulator:
                for _ in range(5):
                    _maybe_complain_about_stack_limit(params)

        assert len(accumulator.issues) == 1

    @mock.patch('sys.platform', 'linux')
    def test_survives_a_getrlimit_that_raises(self, stack_check_enabled, cli_mode):
        params = SandboxParams(stack_space=256)

        with mock.patch('resource.getrlimit', side_effect=OSError('nope')):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert not accumulator.issues


class TestStackLimitProbeIsWired:
    # NOTE: these two patch `sys.platform` across a real fork/exec, so on a macOS
    # host the blast radius is wider than the intent: `get_memory_usage` and
    # `maxrss_inherits_parent` take their Linux branches too, and the child really
    # does attempt `setrlimit(RLIMIT_STACK)`. Nothing asserted below depends on
    # any of that, but a new assertion here might.
    @mock.patch('sys.platform', 'linux')
    async def test_a_run_with_an_unhonorable_limit_files_one_issue(
        self,
        sandbox: SandboxBase,
        cleandir: pathlib.Path,
        testdata_path: pathlib.Path,
        stack_check_enabled,
        cli_mode,
    ):
        script_file = testdata_path / 'steps_run_test' / 'simple_output.py'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=script_file, dest=pathlib.Path('script.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('output.txt'), stack_space=256)
        command = f'{sys.executable} script.py'

        with _fake_stack_rlimit(8 * 1024 * 1024, 8 * 1024 * 1024):
            with _fresh_issue_stack() as accumulator:
                result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert result.exitcode == 0
        assert len(accumulator.issues) == 1

    @mock.patch('sys.platform', 'linux')
    async def test_a_jvm_run_files_no_issue(
        self,
        sandbox: SandboxBase,
        cleandir: pathlib.Path,
        testdata_path: pathlib.Path,
        stack_check_enabled,
        cli_mode,
    ):
        """The JVM carve-out drops the limit, so there is nothing to warn about --
        this is the whole reason the probe cannot live in `rbx/box/code.py`.

        This pins the ordering inside `_finalize_limits`: the configured limit is
        above the mocked hard limit, so probing before the carve-out instead of
        after it would file an issue and fail the assertion below.
        """
        source_file = testdata_path / 'steps_run_test' / 'simple.java'
        artifacts = GradingArtifacts(root=cleandir)
        artifacts.inputs.append(
            GradingFileInput(src=source_file, dest=pathlib.Path('Simple.java'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('output.txt'), dest=pathlib.Path('output.txt')
            )
        )
        artifacts.logs = GradingLogsHolder()

        params = SandboxParams(stdout_file=pathlib.Path('output.txt'), stack_space=256)
        command = 'java Simple'

        with _fake_stack_rlimit(8 * 1024 * 1024, 8 * 1024 * 1024):
            with _fresh_issue_stack() as accumulator:
                result = await steps.run(command, params, sandbox, artifacts)

        assert result is not None
        assert not accumulator.issues
