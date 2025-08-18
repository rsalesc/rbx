import contextvars
import enum
from collections import OrderedDict
from typing import Callable, List, Optional, Tuple, Union

from rbx import console


class IssueLevel(enum.Enum):
    OVERVIEW = enum.auto()
    DETAILED = enum.auto()


class Issue:
    def get_detailed_section(self) -> Optional[Tuple[str, ...]]:
        return None

    def get_overview_section(self) -> Optional[Tuple[str, ...]]:
        return None

    def get_detailed_message(self) -> str:
        return ''

    def get_overview_message(self) -> str:
        return ''


IssueSection = OrderedDict[str, Union[List[Issue], 'IssueSection']]


class IssueAccumulator:
    def __init__(self):
        self.issues = []

    def add_issue(self, issue: Issue):
        self.issues.append(issue)

    def get_sections_by(
        self, key: Callable[[Issue], Optional[Tuple[str, ...]]]
    ) -> IssueSection:
        sections = OrderedDict()
        for issue in self.issues:
            section_key = key(issue)
            if section_key is None:
                continue
            current = sections
            for k in section_key[:-1]:
                current = current.setdefault(k, OrderedDict())
            current.setdefault(section_key[-1], [])
            current[section_key[-1]].append(issue)

        return sections

    def get_detailed_sections(self) -> IssueSection:
        return self.get_sections_by(lambda issue: issue.get_detailed_section())

    def get_overview_sections(self) -> IssueSection:
        return self.get_sections_by(lambda issue: issue.get_overview_section())

    def _print_report_by(
        self,
        section_fn: Callable[[], IssueSection],
        message_fn: Callable[[Issue], str],
    ):
        from rich.tree import Tree

        tree = Tree('Issues')
        sections = section_fn()

        def print_section(section: IssueSection, tree: Tree):
            for key, value in section.items():
                child = tree.add(key)
                if isinstance(value, OrderedDict):
                    print_section(value, child)
                    continue
                for issue in value:
                    child.add(f'[error]{message_fn(issue)}[/error]')

        print_section(sections, tree)

        if tree.children:
            console.console.rule('Issues', style='error')
            for child in tree.children:
                console.console.print(child)

    def print_detailed_report(self):
        self._print_report_by(
            self.get_detailed_sections, lambda issue: issue.get_detailed_message()
        )

    def print_overview_report(self):
        self._print_report_by(
            self.get_overview_sections, lambda issue: issue.get_overview_message()
        )


issue_stack_var = contextvars.ContextVar('issue_stack', default=[IssueAccumulator()])
issue_level_var = contextvars.ContextVar('issue_level', default=IssueLevel.DETAILED)


def get_issue_stack() -> list[IssueAccumulator]:
    return issue_stack_var.get()


def push_issue_accumulator():
    issue_stack_var.set(get_issue_stack() + [IssueAccumulator()])


def pop_issue_accumulator():
    issue_stack_var.set(get_issue_stack()[:-1])


def get_issue_accumulator() -> IssueAccumulator:
    return get_issue_stack()[-1]


def add_issue(issue: Issue):
    for acc in get_issue_stack():
        acc.add_issue(issue)


def print_current_report():
    acc = get_issue_accumulator()
    if issue_level_var.get() == IssueLevel.OVERVIEW:
        acc.print_overview_report()
    else:
        acc.print_detailed_report()
