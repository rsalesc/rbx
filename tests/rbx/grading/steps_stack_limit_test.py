from rbx.box.sanitizers.issue_stack import IssueSeverity
from rbx.grading.steps import StackLimitNotHonoredIssue


class TestStackLimitNotHonoredIssue:
    def test_issue_is_a_warning_not_an_error(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=8 * 1024 * 1024)

        assert issue.get_severity() == IssueSeverity.WARNING

    def test_detailed_message_names_both_limits_and_links_the_docs(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=8 * 1024 * 1024)

        message = issue.get_detailed_message()

        assert '256 MiB' in message
        assert '8 MiB' in message
        assert 'https://rsalesc.github.io/rbx/stack-limit' in message

    def test_detailed_message_says_unenforced_when_there_is_no_hard_limit(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=None)

        message = issue.get_detailed_message()

        assert '256 MiB' in message
        assert 'macOS' in message
        assert 'https://rsalesc.github.io/rbx/stack-limit' in message

    def test_both_reports_file_the_issue_under_the_same_section(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=None)

        assert issue.get_detailed_section() == ('stack limit',)
        assert issue.get_overview_section() == ('stack limit',)

    def test_overview_message_is_present_and_links_the_docs(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=8 * 1024 * 1024)

        assert (
            'https://rsalesc.github.io/rbx/stack-limit' in issue.get_overview_message()
        )

    def test_two_issues_with_the_same_values_produce_the_same_message(self):
        """The issue stack dedupes on the message string, so this is what makes
        the warning print once per run rather than once per program."""
        first = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=8 * 1024 * 1024)
        second = StackLimitNotHonoredIssue(
            requested_mib=256, hard_limit=8 * 1024 * 1024
        )

        assert first.get_detailed_message() == second.get_detailed_message()
        assert first.get_overview_message() == second.get_overview_message()
