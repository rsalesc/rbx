import contextlib
from typing import Optional, Tuple

from rbx import console as rconsole
from rbx.box.sanitizers.issue_stack import (
    Issue,
    IssueAccumulator,
    IssueLevel,
    add_issue,
    get_issue_accumulator,
    get_issue_stack,
    issue_level_var,
    issue_stack_var,
    pop_issue_accumulator,
    print_current_report,
    push_issue_accumulator,
)


class DummyIssue(Issue):
    def __init__(
        self,
        *,
        detailed_section: Optional[Tuple[str, ...]] = None,
        overview_section: Optional[Tuple[str, ...]] = None,
        detailed_message: str = '',
        overview_message: str = '',
    ):
        self._detailed_section = detailed_section
        self._overview_section = overview_section
        self._detailed_message = detailed_message
        self._overview_message = overview_message

    def get_detailed_section(self) -> Optional[Tuple[str, ...]]:
        return self._detailed_section

    def get_overview_section(self) -> Optional[Tuple[str, ...]]:
        return self._overview_section

    def get_detailed_message(self) -> str:
        return self._detailed_message

    def get_overview_message(self) -> str:
        return self._overview_message


@contextlib.contextmanager
def _fresh_issue_stack():
    token = issue_stack_var.set([IssueAccumulator()])
    try:
        yield
    finally:
        issue_stack_var.reset(token)


def _capture_print(fn):
    with rconsole.console.capture() as capture:
        fn()
    return capture.get()


def test_detailed_report_prints_nested_sections_and_messages():
    with _fresh_issue_stack():
        acc = get_issue_accumulator()
        acc.add_issue(
            DummyIssue(
                detailed_section=('Group1', 'Sub1'), detailed_message='Message A'
            )
        )
        acc.add_issue(
            DummyIssue(
                detailed_section=('Group1', 'Sub2'), detailed_message='Message B'
            )
        )
        acc.add_issue(
            DummyIssue(detailed_section=('Group2',), detailed_message='Message C')
        )

        output = _capture_print(acc.print_detailed_report)

        assert 'Issues' in output
        assert 'Group1' in output
        assert 'Message A' in output and 'Message B' in output and 'Message C' in output


def test_overview_report_prints_only_overview_sections():
    with _fresh_issue_stack():
        acc = get_issue_accumulator()
        acc.add_issue(
            DummyIssue(
                overview_section=('Summary', 'Outer'), overview_message='Overview 1'
            )
        )
        acc.add_issue(
            DummyIssue(
                overview_section=('Summary', 'Inner'), overview_message='Overview 2'
            )
        )
        acc.add_issue(
            DummyIssue(
                overview_section=None,
                detailed_section=('WillOnlyShowInDetailed',),
                detailed_message='SHOULD_NOT_APPEAR',
            )
        )

        # Ensure overview only shows overview issues
        output = _capture_print(acc.print_overview_report)

        assert 'Issues' in output
        assert 'Summary' in output
        assert 'Overview 1' in output and 'Overview 2' in output
        assert 'SHOULD_NOT_APPEAR' not in output


def test_add_issue_propagates_to_all_accumulators_in_stack():
    with _fresh_issue_stack():
        base_stack = list(get_issue_stack())
        assert len(base_stack) == 1
        base_acc = base_stack[0]

        push_issue_accumulator()
        top_acc = get_issue_accumulator()

        issue = DummyIssue(
            detailed_section=('Both',), detailed_message='Propagated Message'
        )
        add_issue(issue)

        out_base = _capture_print(base_acc.print_detailed_report)
        out_top = _capture_print(top_acc.print_detailed_report)

        assert 'Propagated Message' in out_base
        assert 'Propagated Message' in out_top

        # Clean up the stack change for safety within the context
        pop_issue_accumulator()


def test_print_current_report_respects_issue_level():
    with _fresh_issue_stack():
        acc = get_issue_accumulator()
        acc.add_issue(
            DummyIssue(
                detailed_section=('Sec',),
                overview_section=('Sec',),
                detailed_message='DetailedMsg',
                overview_message='OverviewMsg',
            )
        )

        # Default level is DETAILED
        out_detailed = _capture_print(print_current_report)
        assert 'DetailedMsg' in out_detailed and 'OverviewMsg' not in out_detailed

        # Switch to OVERVIEW and ensure it changes
        token = issue_level_var.set(IssueLevel.OVERVIEW)
        try:
            out_overview = _capture_print(print_current_report)
            assert 'OverviewMsg' in out_overview and 'DetailedMsg' not in out_overview
        finally:
            issue_level_var.reset(token)
