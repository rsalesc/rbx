import dataclasses
import pathlib
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import ContentSwitcher

from rbx.box.ui.widgets.file_log import FileLog
from rbx.box.ui.widgets.rich_log_box import RichLogBox


@dataclasses.dataclass
class TestcaseRenderingData:
    input_path: Optional[pathlib.Path] = None
    output_path: Optional[pathlib.Path] = None
    stderr_path: Optional[pathlib.Path] = None
    log_path: Optional[pathlib.Path] = None
    rich_content: Optional[str] = None

    @classmethod
    def from_one_path(cls, path: pathlib.Path) -> 'TestcaseRenderingData':
        return cls(
            input_path=path.with_suffix('.in'),
            output_path=path.with_suffix('.out'),
            stderr_path=path.with_suffix('.err'),
            log_path=path.with_suffix('.log'),
        )


class TestBoxWidget(Widget, can_focus=False):
    data: reactive[TestcaseRenderingData] = reactive(
        default=lambda: TestcaseRenderingData(),
        bindings=True,
    )

    @dataclasses.dataclass
    class Logs:
        output: FileLog
        stderr: FileLog
        log: FileLog

    def logs(self) -> Logs:
        return self.Logs(
            output=self.query_one('#test-box-output', FileLog),
            stderr=self.query_one('#test-box-stderr', FileLog),
            log=self.query_one('#test-box-log', FileLog),
        )

    def compose(self) -> ComposeResult:
        with Vertical():
            with ContentSwitcher(initial='test-box-output', id='test-box-switcher'):
                yield FileLog(id='test-box-output')
                yield FileLog(id='test-box-stderr')
                yield FileLog(id='test-box-log')
            yield RichLogBox(id='test-box-metadata')

    def on_mount(self):
        logs = self.logs()
        logs.output.border_title = 'Output'
        logs.stderr.border_title = 'Stderr'
        logs.log.border_title = 'Log'

        metadata = self.query_one('#test-box-metadata', RichLogBox)
        metadata.display = False
        metadata.border_title = 'Metadata'
        metadata.wrap = True
        metadata.markup = True
        metadata.clear()
        metadata.write('No metadata')

        self.watch_data(self.data)

    def watch_data(self, data: TestcaseRenderingData):
        logs = self.logs()
        logs.output.path = data.output_path
        logs.stderr.path = data.stderr_path
        logs.log.path = data.log_path

        metadata = self.query_one('#test-box-metadata', RichLogBox)
        metadata.clear()
        if data.rich_content is not None:
            metadata.write(data.rich_content)
        else:
            metadata.write('No metadata')

    def reset(self):
        self.data = TestcaseRenderingData()

    def show_output(self):
        self.query_one(ContentSwitcher).current = 'test-box-output'

    def show_stderr(self):
        self.query_one(ContentSwitcher).current = 'test-box-stderr'

    def show_log(self):
        self.query_one(ContentSwitcher).current = 'test-box-log'

    def toggle_metadata(self):
        metadata = self.query_one('#test-box-metadata', RichLogBox)
        metadata.display = not metadata.display
        metadata.refresh()
