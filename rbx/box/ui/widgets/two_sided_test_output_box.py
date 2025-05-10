from typing import Optional

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widget import Widget

from rbx.box.ui.widgets.test_output_box import TestBoxWidget, TestcaseRenderingData


class TwoSidedTestBoxWidget(Widget, can_focus=False):
    data: reactive[TestcaseRenderingData] = reactive(
        default=lambda: TestcaseRenderingData(),
        bindings=True,
    )
    diff_with_data: reactive[Optional[TestcaseRenderingData]] = reactive(
        default=None,
        bindings=True,
    )

    def compose(self) -> ComposeResult:
        with Horizontal(id='two-sided-test-box'):
            yield TestBoxWidget(id='test-box-1')
            diff_box = TestBoxWidget(id='test-box-2')
            diff_box.display = False
            yield diff_box

    def watch_data(self, data: TestcaseRenderingData):
        self.query_one('#test-box-1', TestBoxWidget).data = data

    def watch_diff_with_data(self, diff_with_data: Optional[TestcaseRenderingData]):
        if diff_with_data is None:
            self.query_one('#test-box-2', TestBoxWidget).display = False
        else:
            self.query_one('#test-box-2', TestBoxWidget).display = True
            self.query_one('#test-box-2', TestBoxWidget).data = diff_with_data

    def reset(self):
        self.query_one('#test-box-1', TestBoxWidget).reset()
        self.query_one('#test-box-2', TestBoxWidget).reset()

    def show_output(self):
        self.query_one('#test-box-1', TestBoxWidget).show_output()
        self.query_one('#test-box-2', TestBoxWidget).show_output()

    def show_stderr(self):
        self.query_one('#test-box-1', TestBoxWidget).show_stderr()
        self.query_one('#test-box-2', TestBoxWidget).show_stderr()

    def show_log(self):
        self.query_one('#test-box-1', TestBoxWidget).show_log()
        self.query_one('#test-box-2', TestBoxWidget).show_log()

    def show_interaction(self):
        self.query_one('#test-box-1', TestBoxWidget).show_interaction()
        self.query_one('#test-box-2', TestBoxWidget).show_interaction()

    def toggle_metadata(self):
        self.query_one('#test-box-1', TestBoxWidget).toggle_metadata()
        self.query_one('#test-box-2', TestBoxWidget).toggle_metadata()
