"""Tests for chained commands (`rbx each build :: run`) in the command app."""

import asyncio
import pathlib
import shlex
from typing import List

from textual.widgets import Input, Select

from rbx.box.ui._vendor.toad.widgets.command_pane import CommandPane
from rbx.box.ui.command_app import CommandEntry, rbxCommandApp


def _gate(path: pathlib.Path, exit_code: int = 0) -> List[str]:
    """A command that blocks until the test creates ``path``.

    Sleeping for a fixed time instead makes these tests race the scheduler on a
    loaded machine, so every command whose lifetime matters is gated explicitly.
    """
    quoted = shlex.quote(str(path))
    return [
        'sh',
        '-c',
        f'while [ ! -f {quoted} ]; do sleep 0.02; done; exit {exit_code}',
    ]


def _release(path: pathlib.Path) -> None:
    path.write_text('')


def _panes(app) -> List[CommandPane]:
    return list(app.query(CommandPane))


def _settled(panes: List[CommandPane]) -> bool:
    return all(
        p.return_code is not None or p.border_subtitle == 'Skipped' for p in panes
    )


async def _wait_until(pilot, predicate, what: str) -> None:
    for _ in range(200):
        await pilot.pause()
        await asyncio.sleep(0.05)
        if predicate():
            return
    raise AssertionError(f'timed out waiting for {what}')


async def _wait_until_settled(app, pilot, panes_expected: int) -> List[CommandPane]:
    await _wait_until(
        pilot,
        lambda: len(_panes(app)) == panes_expected and _settled(_panes(app)),
        'commands to settle',
    )
    return _panes(app)


def _selected_index(app) -> int:
    return app.query_one('#command-select', Select).value


def _visible_pane(app) -> CommandPane:
    visible = [p for p in _panes(app) if p.display]
    assert len(visible) == 1
    return visible[0]


async def test_chain_queues_one_pane_per_command_in_order():
    app = rbxCommandApp(
        [CommandEntry(argvs=[['echo', 'first'], ['echo', 'second']], name='A')]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        panes = await _wait_until_settled(app, pilot, panes_expected=2)
        assert [p.border_title for p in panes] == ['echo first', 'echo second']
        assert [p.return_code for p in panes] == [0, 0]


async def test_failed_chain_skips_the_rest_of_the_chain():
    app = rbxCommandApp(
        [CommandEntry(argvs=[['sh', '-c', 'exit 3'], ['echo', 'never']], name='A')]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        failed, skipped = await _wait_until_settled(app, pilot, panes_expected=2)
        assert failed.return_code == 3
        assert failed.border_subtitle == 'Exit code: 3'
        # The skipped command must never have been spawned at all.
        assert skipped.return_code is None
        assert skipped.border_subtitle == 'Skipped'


async def test_keep_going_runs_the_whole_chain():
    app = rbxCommandApp(
        [
            CommandEntry(
                argvs=[['sh', '-c', 'exit 3'], ['echo', 'still runs']], name='A'
            )
        ],
        keep_going=True,
    )
    async with app.run_test(size=(100, 30)) as pilot:
        failed, after = await _wait_until_settled(app, pilot, panes_expected=2)
        assert failed.return_code == 3
        assert after.return_code == 0


async def test_failure_does_not_skip_interactively_queued_commands(
    tmp_path: pathlib.Path,
):
    # Commands typed into the app are never part of a chain, so a failing chain
    # must not swallow them -- they keep going by design.
    gate = tmp_path / 'gate'
    app = rbxCommandApp(
        [CommandEntry(argvs=[_gate(gate, exit_code=3), ['echo', 'never']], name='A')]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press('shift+tab')
        await pilot.pause()
        # Queue an extra command while the chain is still on its first command.
        await pilot.press('!')
        await pilot.pause()
        app.query_one('#command-input', Input).value = 'echo interactive'
        await pilot.press('enter')
        await pilot.pause()
        # Menu: "Run in this tab".
        await pilot.press('1')
        await pilot.pause()

        _release(gate)
        failed, skipped, interactive = await _wait_until_settled(
            app, pilot, panes_expected=3
        )
        assert failed.return_code == 3
        assert skipped.border_subtitle == 'Skipped'
        assert interactive.return_code == 0


async def test_view_opens_on_the_running_command_not_the_last_queued(
    tmp_path: pathlib.Path,
):
    # The tail of a chain has not started yet; the useful pane is the one
    # actually executing.
    gate = tmp_path / 'gate'
    app = rbxCommandApp(
        [CommandEntry(argvs=[_gate(gate), ['echo', 'later']], name='A')]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert _selected_index(app) == 0
        assert _visible_pane(app) is _panes(app)[0]

        _release(gate)
        await _wait_until_settled(app, pilot, panes_expected=2)


async def test_switching_tabs_lands_on_that_tab_s_running_command(
    tmp_path: pathlib.Path,
):
    gate = tmp_path / 'gate'
    app = rbxCommandApp(
        [
            CommandEntry(argvs=[['echo', 'a1'], ['echo', 'a2']], name='A'),
            CommandEntry(argvs=[_gate(gate), ['echo', 'b2']], name='B'),
        ],
        parallel=True,
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        # The sidebar is focused at mount, so `down` moves to tab B.
        await pilot.press('down')
        await pilot.pause()

        assert _selected_index(app) == 0
        assert _visible_pane(app).border_title.startswith('sh -c')

        _release(gate)
        await _wait_until_settled(app, pilot, panes_expected=4)


async def test_view_follows_the_chain_as_it_advances(tmp_path: pathlib.Path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    app = rbxCommandApp([CommandEntry(argvs=[_gate(first), _gate(second)], name='A')])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert _selected_index(app) == 0

        # Once the first command finishes, the view moves onto the second.
        _release(first)
        await _wait_until(
            pilot, lambda: _selected_index(app) == 1, 'the view to follow the chain'
        )
        assert _visible_pane(app) is _panes(app)[1]

        _release(second)
        await _wait_until_settled(app, pilot, panes_expected=2)


async def test_view_stays_put_when_parked_on_a_pending_command(
    tmp_path: pathlib.Path,
):
    # Looking ahead at a queued command is deliberate; the app must not yank
    # the view away when the next one starts.
    first, second = tmp_path / 'first', tmp_path / 'second'
    app = rbxCommandApp(
        [CommandEntry(argvs=[_gate(first), _gate(second), ['echo', 'third']], name='A')]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.query_one('#command-select', Select).value = 2
        await pilot.pause()

        _release(first)
        await _wait_until(
            pilot,
            lambda: _panes(app)[0].return_code is not None,
            'the first command to finish',
        )
        assert _selected_index(app) == 2

        _release(second)
        await _wait_until_settled(app, pilot, panes_expected=3)
