import contextlib
import resource
from unittest import mock

import pytest

from rbx.box import state
from rbx.box.sanitizers.issue_stack import (
    IssueAccumulator,
    IssueSeverity,
    issue_stack_var,
)
from rbx.grading import steps
from rbx.grading.judge.sandbox import SandboxParams
from rbx.grading.steps import (
    MemoryLimitNotHonoredIssue,
    _maybe_complain_about_memory_limit,
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


def _fake_as_rlimit(soft: int, hard: int):
    """Report `(soft, hard)` for RLIMIT_AS only, leaving every other rlimit query
    -- including the ones the sandbox makes while spawning -- untouched."""
    real_getrlimit = resource.getrlimit

    def getrlimit(which: int):
        if which == resource.RLIMIT_AS:
            return (soft, hard)
        return real_getrlimit(which)

    return mock.patch('resource.getrlimit', side_effect=getrlimit)


@pytest.fixture(autouse=True)
def clear_memory_limit_cache():
    """`_complain_about_memory_limit` is cached, so a verdict reached under one
    test's mocked platform must not carry into the next."""
    steps._complain_about_memory_limit.cache_clear()  # noqa: SLF001
    yield
    steps._complain_about_memory_limit.cache_clear()  # noqa: SLF001


@pytest.fixture
def cli_mode():
    """The probe only runs under the CLI; pin the flag on and put it back."""
    original = state.STATE.run_through_cli
    state.STATE.run_through_cli = True
    try:
        yield
    finally:
        state.STATE.run_through_cli = original


class TestMemoryLimitNotHonoredIssue:
    def test_issue_is_a_warning_not_an_error(self):
        issue = MemoryLimitNotHonoredIssue(
            requested_mib=1024, hard_limit=256 * 1024 * 1024
        )

        assert issue.get_severity() == IssueSeverity.WARNING

    def test_detailed_message_names_both_limits_and_links_the_docs(self):
        issue = MemoryLimitNotHonoredIssue(
            requested_mib=1024, hard_limit=256 * 1024 * 1024
        )

        message = issue.get_detailed_message()

        assert '1 GiB' in message or '1024 MiB' in message
        assert '256 MiB' in message
        assert 'https://rbx.rsalesc.dev/memory-limit/' in message

    def test_both_reports_file_the_issue_under_the_same_section(self):
        issue = MemoryLimitNotHonoredIssue(
            requested_mib=1024, hard_limit=256 * 1024 * 1024
        )

        assert issue.get_detailed_section() == ('memory limit',)
        assert issue.get_overview_section() == ('memory limit',)

    def test_overview_message_is_present_and_links_the_docs(self):
        issue = MemoryLimitNotHonoredIssue(
            requested_mib=1024, hard_limit=256 * 1024 * 1024
        )

        assert 'https://rbx.rsalesc.dev/memory-limit/' in issue.get_overview_message()

    def test_two_issues_with_the_same_values_produce_the_same_message(self):
        """The issue stack dedupes on the message string, so this is what makes
        the warning print once per run rather than once per program."""
        first = MemoryLimitNotHonoredIssue(
            requested_mib=1024, hard_limit=256 * 1024 * 1024
        )
        second = MemoryLimitNotHonoredIssue(
            requested_mib=1024, hard_limit=256 * 1024 * 1024
        )

        assert first.get_detailed_message() == second.get_detailed_message()
        assert first.get_overview_message() == second.get_overview_message()


class TestMaybeComplainAboutMemoryLimit:
    @mock.patch('sys.platform', 'linux')
    def test_warns_on_linux_when_the_hard_limit_is_below_the_request(self, cli_mode):
        params = SandboxParams(address_space=1024)

        with _fake_as_rlimit(256 * 1024 * 1024, 256 * 1024 * 1024):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_memory_limit(params)

        assert len(accumulator.issues) == 1
        issue = accumulator.issues[0]
        assert isinstance(issue, MemoryLimitNotHonoredIssue)
        assert issue.requested_mib == 1024
        assert issue.hard_limit == 256 * 1024 * 1024

    @mock.patch('sys.platform', 'linux')
    def test_is_quiet_when_the_hard_limit_accommodates_the_request(self, cli_mode):
        params = SandboxParams(address_space=256)

        with _fake_as_rlimit(1024 * 1024 * 1024, 1024 * 1024 * 1024):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_memory_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'linux')
    def test_is_quiet_when_there_is_no_hard_limit(self, cli_mode):
        params = SandboxParams(address_space=1024)

        with _fake_as_rlimit(resource.RLIM_INFINITY, resource.RLIM_INFINITY):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_memory_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'darwin')
    def test_is_quiet_on_darwin_where_the_watchdog_enforces_the_limit(self, cli_mode):
        """Unlike the stack limit, a `memoryLimit` off Linux is still enforced --
        by the RSS watchdog -- so there is nothing to warn about."""
        params = SandboxParams(address_space=1024)

        with _fake_as_rlimit(256 * 1024 * 1024, 256 * 1024 * 1024):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_memory_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'linux')
    def test_is_quiet_when_no_memory_limit_is_configured(self, cli_mode):
        """A limit dropped by the JVM carve-out or by a sanitizer arrives here as
        `None`, and a limit that was dropped is not one worth warning about."""
        params = SandboxParams(address_space=None)

        with _fake_as_rlimit(256 * 1024 * 1024, 256 * 1024 * 1024):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_memory_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'linux')
    def test_is_quiet_outside_the_cli(self):
        """Reading the report -- and creating `setter_config.yml` on the way --
        is not a side effect the grading layer may have as a library."""
        original = state.STATE.run_through_cli
        state.STATE.run_through_cli = False
        params = SandboxParams(address_space=1024)

        try:
            with _fake_as_rlimit(256 * 1024 * 1024, 256 * 1024 * 1024):
                with _fresh_issue_stack() as accumulator:
                    _maybe_complain_about_memory_limit(params)
        finally:
            state.STATE.run_through_cli = original

        assert not accumulator.issues

    @mock.patch('sys.platform', 'linux')
    def test_files_the_issue_once_across_many_programs(self, cli_mode):
        """A stress run spawns tens of thousands of programs; the cache is what
        keeps that from growing a list nothing reads."""
        params = SandboxParams(address_space=1024)

        with _fake_as_rlimit(256 * 1024 * 1024, 256 * 1024 * 1024):
            with _fresh_issue_stack() as accumulator:
                for _ in range(5):
                    _maybe_complain_about_memory_limit(params)

        assert len(accumulator.issues) == 1
