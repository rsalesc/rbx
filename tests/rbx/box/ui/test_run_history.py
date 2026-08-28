"""Tests for persisted `each`/`on` run history (`rbx.box.ui.run_history`).

The format is ANSI text written back through `Terminal.write()`, so most of
these assert on a *restored* pane behaving like a live one -- that equivalence
is the whole reason for the format.
"""

import asyncio
import datetime
import pathlib
import sys
from typing import List, Optional

import pytest

from rbx.box.ui import clipboard, run_history
from rbx.box.ui._vendor.toad.widgets.command_pane import CommandPane
from rbx.box.ui.command_app import CommandEntry, rbxCommandApp
from rbx.box.ui.command_status import CommandStatus


def _print(*lines: str) -> List[str]:
    body = '\n'.join(f'print({line!r})' for line in lines)
    return [sys.executable, '-c', body]


def _styled(text: str) -> List[str]:
    """A command that writes SGR colours, so styles have to survive the trip."""
    return [sys.executable, '-c', f'print("\\x1b[1;31m{text}\\x1b[0m plain")']


async def _finished(pilot, app, panes_expected: int = 1) -> List[CommandPane]:
    for _ in range(200):
        await pilot.pause()
        await asyncio.sleep(0.05)
        panes = list(app.query(CommandPane))
        if len(panes) == panes_expected and all(
            p.return_code is not None for p in panes
        ):
            return panes
    raise AssertionError('commands did not finish in time')


def _store(tmp_path: pathlib.Path) -> run_history.ContestRunStore:
    return run_history.ContestRunStore(tmp_path / 'runs')


def _new_handle(
    store: run_history.ContestRunStore, when: Optional[datetime.datetime] = None
) -> run_history.RunHandle:
    when = when or datetime.datetime.now()
    return store.create_run(
        run_history.RunManifest(
            run_id=run_history.new_run_id(when), started_at=when, updated_at=when
        )
    )


def _buffer_lines(pane: CommandPane) -> List[str]:
    return [line.content.plain for line in pane.state.scrollback_buffer.lines]


def _buffer_spans(pane: CommandPane) -> List[list]:
    return [
        [(span.start, span.end, str(span.style)) for span in line.content.spans]
        for line in pane.state.scrollback_buffer.lines
    ]


async def test_pane_output_is_dumped_and_restores_byte_for_byte(tmp_path):
    """The core round trip: colours and text both survive."""
    store = _store(tmp_path)
    handle = _new_handle(store)
    app = rbxCommandApp(
        [CommandEntry(argvs=[_styled('HELLO')], name='a')],
        parallel=True,
        run_handle=handle,
    )
    async with app.run_test() as pilot:
        (pane,) = await _finished(pilot, app)
        await pilot.pause()
        original_lines = _buffer_lines(pane)
        original_spans = _buffer_spans(pane)

    assert 'HELLO plain' in '\n'.join(original_lines)
    dumped = handle.read_pane(0, 0)
    assert dumped is not None and 'HELLO' in dumped

    reopened = store.open_run(handle.run_id)
    assert reopened is not None
    restored_app = rbxCommandApp(
        [CommandEntry(argvs=[], name='a')], run_handle=reopened, restored=True
    )
    async with restored_app.run_test() as pilot:
        for _ in range(100):
            await pilot.pause()
            await asyncio.sleep(0.02)
            panes = list(restored_app.query(CommandPane))
            if panes and 'HELLO plain' in '\n'.join(_buffer_lines(panes[0])):
                break
        (restored,) = list(restored_app.query(CommandPane))
        assert _buffer_lines(restored) == original_lines
        assert _buffer_spans(restored) == original_spans


@pytest.fixture
def copied(monkeypatch) -> List[str]:
    """Record what a pane copies, at the seam the clipboard is written from."""
    writes: List[str] = []
    monkeypatch.setattr(clipboard, 'copy', lambda app, text: writes.append(text))
    return writes


async def test_restored_pane_supports_copying(tmp_path, copied):
    """Selection is why the format is ANSI rather than a bespoke snapshot."""
    store = _store(tmp_path)
    handle = _new_handle(store)
    app = rbxCommandApp(
        [CommandEntry(argvs=[_print('alpha', 'beta')], name='a')],
        parallel=True,
        run_handle=handle,
    )
    async with app.run_test() as pilot:
        await _finished(pilot, app)
        await pilot.pause()

    reopened = store.open_run(handle.run_id)
    assert reopened is not None
    restored_app = rbxCommandApp(
        [CommandEntry(argvs=[], name='a')], run_handle=reopened, restored=True
    )
    async with restored_app.run_test() as pilot:
        for _ in range(100):
            await pilot.pause()
            await asyncio.sleep(0.02)
            panes = list(restored_app.query(CommandPane))
            if panes and 'beta' in '\n'.join(_buffer_lines(panes[0])):
                break
        (pane,) = list(restored_app.query(CommandPane))
        restored_app.set_focus(pane)
        await pilot.pause()
        # ctrl+y with no selection copies the whole buffer -- of a pane that was
        # never driven by a process, only written to from disk.
        await pilot.press('ctrl+y')
        await pilot.pause()
        assert copied == ['alpha\nbeta']


async def test_history_is_flushed_as_each_command_finishes(tmp_path):
    """The incremental guarantee: a finished command is on disk immediately."""
    store = _store(tmp_path)
    handle = _new_handle(store)
    app = rbxCommandApp(
        [CommandEntry(argvs=[_print('one'), _print('two')], name='a')],
        parallel=True,
        run_handle=handle,
    )
    async with app.run_test() as pilot:
        await _finished(pilot, app, panes_expected=2)
        await pilot.pause()
        assert handle.read_pane(0, 0) is not None
        assert 'one' in handle.read_pane(0, 0)

    reopened = store.open_run(handle.run_id)
    assert reopened is not None
    statuses = [sub.status for sub in reopened.manifest.tabs[0].sub_commands]
    assert statuses == [CommandStatus.SUCCESS, CommandStatus.SUCCESS]


async def test_quitting_mid_run_keeps_what_was_on_screen(tmp_path):
    """The unmount dump: a command still running is not lost, only unfinished."""
    store = _store(tmp_path)
    handle = _new_handle(store)
    app = rbxCommandApp(
        [
            CommandEntry(
                argvs=[
                    [
                        sys.executable,
                        '-u',
                        '-c',
                        'print("partial"); import time; time.sleep(30)',
                    ]
                ],
                name='a',
            )
        ],
        parallel=True,
        run_handle=handle,
    )
    async with app.run_test() as pilot:
        for _ in range(200):
            await pilot.pause()
            await asyncio.sleep(0.05)
            panes = list(app.query(CommandPane))
            if panes and 'partial' in '\n'.join(_buffer_lines(panes[0])):
                break
        else:
            raise AssertionError('command never printed')

    # The app is gone; the still-running command left its output behind.
    dumped = handle.read_pane(0, 0)
    assert dumped is not None and 'partial' in dumped

    reopened = store.open_run(handle.run_id)
    assert reopened is not None
    assert reopened.manifest.tabs[0].sub_commands[0].status is CommandStatus.RUNNING
    # ... and reloads as interrupted rather than as something still going.
    restored = rbxCommandApp(
        [CommandEntry(argvs=[], name='a')], run_handle=reopened, restored=True
    )
    assert (
        restored._tabs[0].sub_commands[0].status  # noqa: SLF001
        is CommandStatus.INTERRUPTED
    )


def test_pending_and_running_load_as_terminal_states(tmp_path):
    store = _store(tmp_path)
    handle = _new_handle(store)
    handle.manifest.tabs = [
        run_history.TabRecord(
            name='A',
            sub_commands=[
                run_history.SubCommandRecord(
                    name='build', shell_command='true', status=CommandStatus.RUNNING
                ),
                run_history.SubCommandRecord(
                    name='run', shell_command='true', status=CommandStatus.PENDING
                ),
            ],
        )
    ]
    handle.save()

    reopened = store.open_run(handle.run_id)
    assert reopened is not None
    app = rbxCommandApp(
        [CommandEntry(argvs=[], name='A')], run_handle=reopened, restored=True
    )
    statuses = [sub.status for sub in app._tabs[0].sub_commands]  # noqa: SLF001
    assert statuses == [CommandStatus.INTERRUPTED, CommandStatus.SKIPPED]
    # Nothing is executing, so the tab must not report itself busy.
    assert app._tabs[0].is_idle  # noqa: SLF001


def test_only_non_successful_commands_are_resumable(tmp_path):
    store = _store(tmp_path)
    handle = _new_handle(store)
    handle.manifest.tabs = [
        run_history.TabRecord(
            name='A',
            sub_commands=[
                run_history.SubCommandRecord(
                    name='ok', shell_command='true', status=CommandStatus.SUCCESS
                ),
                run_history.SubCommandRecord(
                    name='bad', shell_command='false', status=CommandStatus.FAILED
                ),
                run_history.SubCommandRecord(
                    name='never', shell_command='true', status=CommandStatus.SKIPPED
                ),
            ],
        )
    ]
    handle.save()
    reopened = store.open_run(handle.run_id)
    assert reopened is not None
    app = rbxCommandApp(
        [CommandEntry(argvs=[], name='A')], run_handle=reopened, restored=True
    )
    resumable = app._resumable_in_tab(0)  # noqa: SLF001
    assert [sub.name for _, sub in resumable] == ['bad', 'never']


async def test_resume_reruns_only_what_did_not_succeed(tmp_path):
    store = _store(tmp_path)
    handle = _new_handle(store)
    app = rbxCommandApp(
        [
            CommandEntry(
                argvs=[_print('first'), ['sh', '-c', 'exit 3']],
                name='a',
            )
        ],
        parallel=True,
        run_handle=handle,
    )
    async with app.run_test() as pilot:
        await _finished(pilot, app, panes_expected=2)
        await pilot.pause()
        subs = app._tabs[0].sub_commands  # noqa: SLF001
        assert [s.status for s in subs] == [
            CommandStatus.SUCCESS,
            CommandStatus.FAILED,
        ]
        assert subs[1].exit_code == 3

        await app._resume_tabs([0])  # noqa: SLF001
        # Only the failing one was re-queued; the successful one is untouched.
        assert subs[0].status is CommandStatus.SUCCESS
        assert subs[1].status is not CommandStatus.FAILED
        await _finished(pilot, app, panes_expected=2)
        assert subs[1].status is CommandStatus.FAILED


async def test_retry_gives_the_command_a_clean_pane(tmp_path):
    """`execute()` appends, so a retry must swap the pane, not reuse it."""
    store = _store(tmp_path)
    handle = _new_handle(store)
    app = rbxCommandApp(
        [CommandEntry(argvs=[_print('only-once')], name='a')],
        parallel=True,
        run_handle=handle,
    )
    async with app.run_test() as pilot:
        await _finished(pilot, app)
        await pilot.pause()
        sub = app._tabs[0].sub_commands[0]  # noqa: SLF001

        await app._reset_pane(0, 0, sub)  # noqa: SLF001
        app._enqueue_sub(0, sub)  # noqa: SLF001
        (pane,) = await _finished(pilot, app)
        await pilot.pause()

        text = '\n'.join(_buffer_lines(pane))
        assert text.count('only-once') == 1


def test_list_runs_is_newest_first_and_prunes(tmp_path):
    store = _store(tmp_path)
    base = datetime.datetime(2026, 8, 28, 10, 0, 0)
    handles = []
    for i in range(4):
        handle = _new_handle(store, base + datetime.timedelta(minutes=i))
        # `save()` stamps updated_at with the wall clock, so pin it explicitly.
        handle.manifest.started_at = base + datetime.timedelta(minutes=i)
        handle.manifest.updated_at = base + datetime.timedelta(minutes=i)
        handle.path.mkdir(parents=True, exist_ok=True)
        import yaml

        (handle.path / run_history.MANIFEST_NAME).write_text(
            yaml.safe_dump(handle.manifest.model_dump(mode='json'), sort_keys=False)
        )
        handles.append(handle)

    listed = store.list_runs()
    assert [m.run_id for m in listed] == [h.run_id for h in reversed(handles)]

    store.prune(keep=2)
    assert [m.run_id for m in store.list_runs()] == [
        handles[3].run_id,
        handles[2].run_id,
    ]


def test_unreadable_run_is_skipped_not_fatal(tmp_path):
    store = _store(tmp_path)
    good = _new_handle(store)
    broken = store.root / 'broken-run'
    broken.mkdir(parents=True, exist_ok=True)
    (broken / run_history.MANIFEST_NAME).write_text('{not: valid: yaml')

    listed = store.list_runs()
    assert [m.run_id for m in listed] == [good.run_id]


@pytest.mark.parametrize(
    'status,expected',
    [
        (CommandStatus.SUCCESS, False),
        (CommandStatus.FAILED, True),
        (CommandStatus.SKIPPED, True),
        (CommandStatus.INTERRUPTED, True),
    ],
)
def test_resume_includes_everything_that_did_not_succeed(status, expected):
    from rbx.box.ui import command_status

    assert command_status.is_resumable(status) is expected
