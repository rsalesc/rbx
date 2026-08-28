"""Pick a past `each`/`on` session to reopen.

`rbx contest each` / `rbx contest on` with no command to forward mean "show me
what I ran before" rather than being an error.
"""

import pathlib
from typing import List, Optional

from textual.app import ComposeResult
from textual.widgets import Footer, Header, Label, ListItem, ListView

from rbx import console
from rbx.box.setter_config import ProblemLabelMode
from rbx.box.ui import run_history
from rbx.box.ui.command_status import STATUS_MARKUP
from rbx.box.ui.main import rbxBaseApp

# The picker's first row: `each` with no args used to open a blank session to
# type commands into, and reopening history must not cost that.
NEW_SESSION = '__new__'

NO_HISTORY = 'none'
NEW_REQUESTED = 'new'
HANDLED = 'done'


def _row_markup(manifest: run_history.RunManifest) -> str:
    icon = STATUS_MARKUP[run_history.manifest_status(manifest)]
    when = manifest.started_at.strftime('%Y-%m-%d %H:%M')
    problems = ', '.join(manifest.problem_names)
    command = manifest.command_line or '(no commands)'
    return f'{icon} [b]{when}[/b]  {command}  [dim]{problems}[/dim]'


class RunPickerApp(rbxBaseApp):
    """A list of past runs; selecting one returns its id."""

    TITLE = 'rbx runs'
    CSS_PATH = 'css/app.tcss'
    BINDING_GROUP_TITLE = 'Runs'
    BINDINGS = [
        ('q', 'quit', 'Quit'),
        ('escape', 'quit', 'Quit'),
    ]

    DEFAULT_CSS = """
    #run-list {
        height: 1fr;
        border: solid $accent;
    }
    """

    def __init__(self, manifests: List[run_history.RunManifest]):
        super().__init__()
        self._manifests = manifests
        self.selected_run_id: Optional[str] = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        yield ListView(
            ListItem(Label('[b]+ Start a new session[/b]', markup=True)),
            *[
                ListItem(Label(_row_markup(manifest), markup=True))
                for manifest in self._manifests
            ],
            id='run-list',
        )

    def on_mount(self) -> None:
        run_list = self.query_one('#run-list', ListView)
        run_list.border_title = 'Recent runs'
        run_list.border_subtitle = '[b]enter[/b] open  [b]q[/b] quit'
        run_list.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if index is None:
            return
        if index == 0:
            self.selected_run_id = NEW_SESSION
            self.exit()
            return
        # Row 0 is the "new session" entry, so the manifests are offset by one.
        manifest_index = index - 1
        if not 0 <= manifest_index < len(self._manifests):
            return
        self.selected_run_id = self._manifests[manifest_index].run_id
        self.exit()


def pick_run(manifests: List[run_history.RunManifest]) -> Optional[str]:
    app = RunPickerApp(manifests)
    app.run()
    return app.selected_run_id


def entries_from_manifest(manifest: run_history.RunManifest) -> List['CommandEntry']:  # noqa: F821
    """Rebuild the tabs of a recorded run.

    `argvs` is left empty on purpose: a restored tab takes its sub-commands from
    the manifest verbatim, never by re-deriving them.
    """
    from rbx.box.ui.command_app import CommandEntry

    entries: List[CommandEntry] = []
    for tab in manifest.tabs:
        labels = None
        if tab.labels:
            labels = {}
            for raw_mode, label in tab.labels.items():
                try:
                    labels[ProblemLabelMode(raw_mode)] = label
                except ValueError:
                    continue
        entries.append(
            CommandEntry(
                argvs=[],
                name=tab.name,
                cwd=tab.cwd,
                prefix=tab.prefix,
                placeholder_prefix=tab.placeholder_prefix,
                labels=labels or None,
            )
        )
    return entries


def open_run_history(
    problem_names: Optional[List[str]] = None,
    root: pathlib.Path = pathlib.Path(),
) -> str:
    """Show the picker and reopen whatever is chosen.

    Returns `NO_HISTORY` when there is nothing recorded and `NEW_REQUESTED` when
    the user picked the new-session row -- in both cases the caller falls back to
    opening a blank session, which is what no-argument `each` has always done.
    """
    from rbx.box.ui.command_app import rbxCommandApp

    store = run_history.get_contest_run_store(root)
    if store is None:
        return NO_HISTORY

    manifests = store.list_runs()
    if problem_names is not None:
        wanted = set(problem_names)
        manifests = [m for m in manifests if wanted.intersection(m.problem_names)]
    manifests = manifests[: run_history.PICKER_LIMIT]
    if not manifests:
        return NO_HISTORY

    run_id = pick_run(manifests)
    if run_id is None:
        return HANDLED
    if run_id == NEW_SESSION:
        return NEW_REQUESTED

    handle = store.open_run(run_id)
    if handle is None:
        console.console.print(
            f'[error]Could not read run [item]{run_id}[/item].[/error]'
        )
        return HANDLED

    entries = entries_from_manifest(handle.manifest)
    app = rbxCommandApp(entries, run_handle=handle, restored=True)
    app.run()
    return HANDLED
