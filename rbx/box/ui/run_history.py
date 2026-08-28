"""Persistence for `rbx contest each` / `rbx contest on` command panes.

Every command run in `rbxCommandApp` leaves its final screen on disk, so a
session can be reopened later with every pane redrawn -- and so the commands
that did not succeed can be re-queued.

The format is deliberately ANSI text. `Terminal.write()` feeds the very parser
that built the buffer in the first place, so restoring a pane is a plain write
and the restored buffer is indistinguishable from a live one -- which is what
keeps selection and copying working on it, for free.
"""

import datetime
import pathlib
import random
import string
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

from rbx.box.ui import command_status
from rbx.box.ui._vendor.toad.ansi import _ansi as ansi
from rbx.box.ui.command_status import CommandStatus

MANIFEST_NAME = 'run.yml'
RUNS_DIR_NAME = 'runs'
PANE_SUFFIX = '.ansi'

# How many runs to keep on disk. The picker shows fewer; the extra ones are
# cheap and mean a burst of short runs does not evict everything interesting.
DEFAULT_KEEP = 10
PICKER_LIMIT = 5


def dump_buffer(buffer: ansi.Buffer) -> str:
    """Render a terminal buffer's final state back to ANSI text.

    Lines are stored *unfolded*, so the result re-folds to whatever width the
    pane has when it is restored, rather than being frozen at the width the
    command happened to run at.
    """
    lines: List[str] = []
    for record in buffer.lines:
        parts: List[str] = []
        for text, style in record.content.render(end=''):
            if not text:
                continue
            parts.append(style.rich_style.render(text))
        lines.append(''.join(parts))
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ''
    return '\n'.join(lines) + '\n'


def to_terminal_input(dumped: str) -> str:
    """Adapt a dump for writing back into a terminal.

    The file is stored as ordinary text with `\\n`, but a terminal needs the
    carriage return to get back to column zero.
    """
    return dumped.replace('\n', '\r\n')


class SubCommandRecord(BaseModel):
    name: str
    shell_command: str
    status: CommandStatus = CommandStatus.PENDING
    exit_code: Optional[int] = None
    chained: bool = False


class TabRecord(BaseModel):
    name: str
    cwd: Optional[str] = None
    prefix: Optional[str] = None
    placeholder_prefix: Optional[str] = None
    labels: Optional[Dict[str, str]] = None
    sub_commands: List[SubCommandRecord] = Field(default_factory=list)


class RunManifest(BaseModel):
    run_id: str
    started_at: datetime.datetime
    updated_at: datetime.datetime
    contest_id: Optional[str] = None
    tabs: List[TabRecord] = Field(default_factory=list)

    @property
    def command_line(self) -> str:
        """A one-line description of what this run was started to do."""
        for tab in self.tabs:
            if tab.sub_commands:
                return ' :: '.join(sub.name for sub in tab.sub_commands)
        return ''

    @property
    def problem_names(self) -> List[str]:
        return [tab.name for tab in self.tabs]


def new_run_id(now: Optional[datetime.datetime] = None) -> str:
    """A run id that sorts chronologically and cannot collide.

    Two `each` invocations started in the same second must not share a
    directory, hence the suffix.
    """
    now = now or datetime.datetime.now()
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f'{now.strftime("%Y%m%d-%H%M%S")}-{suffix}'


class RunHandle:
    """One run's directory: its manifest plus a file per pane."""

    def __init__(self, path: pathlib.Path, manifest: RunManifest):
        self.path = path
        self.manifest = manifest

    @property
    def run_id(self) -> str:
        return self.manifest.run_id

    def pane_path(self, tab_index: int, sub_index: int) -> pathlib.Path:
        return self.path / str(tab_index) / f'{sub_index}{PANE_SUFFIX}'

    def write_pane(self, tab_index: int, sub_index: int, dumped: str) -> None:
        path = self.pane_path(tab_index, sub_index)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumped, encoding='utf-8')

    def read_pane(self, tab_index: int, sub_index: int) -> Optional[str]:
        path = self.pane_path(tab_index, sub_index)
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding='utf-8')
        except OSError:
            return None

    def clear_pane(self, tab_index: int, sub_index: int) -> None:
        """Drop a pane's stored output, for a command about to be re-run."""
        self.pane_path(tab_index, sub_index).unlink(missing_ok=True)

    def save(self) -> None:
        self.manifest.updated_at = datetime.datetime.now()
        self.path.mkdir(parents=True, exist_ok=True)
        data = self.manifest.model_dump(mode='json')
        (self.path / MANIFEST_NAME).write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding='utf-8',
        )


class ContestRunStore:
    """Run history kept beside the contest, under its cache directory.

    Everything that touches the filesystem lives here, so a future
    machine-global store -- keeping the last few runs regardless of which
    contest they came from, as redundancy against a wiped cache -- is another
    class implementing the same three methods, not a refactor of the app.
    """

    def __init__(self, root: pathlib.Path):
        self.root = root

    def _run_path(self, run_id: str) -> pathlib.Path:
        return self.root / run_id

    def create_run(self, manifest: RunManifest) -> RunHandle:
        handle = RunHandle(self._run_path(manifest.run_id), manifest)
        handle.save()
        return handle

    def open_run(self, run_id: str) -> Optional[RunHandle]:
        manifest = self._read_manifest(self._run_path(run_id))
        if manifest is None:
            return None
        return RunHandle(self._run_path(run_id), manifest)

    def list_runs(self, limit: Optional[int] = None) -> List[RunManifest]:
        """Newest first.

        Sorted by `updated_at`, not `started_at`: reopening an old run and
        adding a command to it should float it back to the top, even though the
        picker still shows when it originally started.
        """
        if not self.root.is_dir():
            return []
        manifests: List[RunManifest] = []
        for entry in self.root.iterdir():
            if not entry.is_dir():
                continue
            manifest = self._read_manifest(entry)
            if manifest is not None:
                manifests.append(manifest)
        manifests.sort(key=lambda m: m.updated_at, reverse=True)
        if limit is not None:
            manifests = manifests[:limit]
        return manifests

    def prune(self, keep: int = DEFAULT_KEEP) -> None:
        import shutil

        for manifest in self.list_runs()[keep:]:
            shutil.rmtree(self._run_path(manifest.run_id), ignore_errors=True)

    def _read_manifest(self, path: pathlib.Path) -> Optional[RunManifest]:
        """A run we cannot parse is skipped, never fatal.

        History is a convenience; a half-written manifest from a killed session
        must not stop the picker from listing the rest.
        """
        manifest_path = path / MANIFEST_NAME
        if not manifest_path.is_file():
            return None
        try:
            data = yaml.safe_load(manifest_path.read_text(encoding='utf-8'))
            return RunManifest.model_validate(data)
        except Exception:
            return None


def manifest_status(manifest: RunManifest) -> CommandStatus:
    """The one status that best describes a whole run, for the picker."""
    statuses = {
        command_status.on_load(sub.status)
        for tab in manifest.tabs
        for sub in tab.sub_commands
    }
    if not statuses:
        return CommandStatus.PENDING
    for status in command_status.AGGREGATE_PRECEDENCE:
        if status in statuses:
            return status
    return CommandStatus.SUCCESS


def get_contest_run_store(
    root: pathlib.Path = pathlib.Path(),
) -> Optional[ContestRunStore]:
    """The run store for the contest `root` sits in, if any."""
    from rbx.box.contest.contest_package import get_contest_cache_dir

    cache_dir = get_contest_cache_dir(root)
    if cache_dir is None:
        return None
    return ContestRunStore(cache_dir / RUNS_DIR_NAME)
