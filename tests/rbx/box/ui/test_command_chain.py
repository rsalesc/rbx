"""Tests for chained commands (`rbx each build :: run`) in the command app."""

import asyncio
from typing import List

from textual.widgets import Input

from rbx.box.ui._vendor.toad.widgets.command_pane import CommandPane
from rbx.box.ui.command_app import CommandEntry, rbxCommandApp


def _panes(app) -> List[CommandPane]:
    return list(app.query(CommandPane))


def _settled(panes: List[CommandPane]) -> bool:
    return all(
        p.return_code is not None or p.border_subtitle == 'Skipped' for p in panes
    )


async def _wait_until_settled(app, pilot, panes_expected: int) -> List[CommandPane]:
    for _ in range(200):
        await pilot.pause()
        await asyncio.sleep(0.05)
        panes = _panes(app)
        if len(panes) == panes_expected and _settled(panes):
            return panes
    raise AssertionError('commands did not settle in time')


async def test_chain_queues_one_pane_per_command_in_order():
    app = rbxCommandApp(
        [
            CommandEntry(
                argvs=[['echo', 'first'], ['echo', 'second']],
                name='A',
            )
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        panes = await _wait_until_settled(app, pilot, panes_expected=2)
        assert [p.border_title for p in panes] == ['echo first', 'echo second']
        assert [p.return_code for p in panes] == [0, 0]


async def test_failed_chain_skips_the_rest_of_the_chain():
    app = rbxCommandApp(
        [
            CommandEntry(
                argvs=[['sh', '-c', 'exit 3'], ['echo', 'never']],
                name='A',
            )
        ]
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
                argvs=[['sh', '-c', 'exit 3'], ['echo', 'still runs']],
                name='A',
            )
        ],
        keep_going=True,
    )
    async with app.run_test(size=(100, 30)) as pilot:
        failed, after = await _wait_until_settled(app, pilot, panes_expected=2)
        assert failed.return_code == 3
        assert after.return_code == 0


async def test_failure_does_not_skip_interactively_queued_commands():
    # Commands typed into the app are never part of a chain, so a failing chain
    # must not swallow them -- they keep going by design.
    app = rbxCommandApp(
        [
            CommandEntry(
                argvs=[['sh', '-c', 'sleep 0.6; exit 3'], ['echo', 'never']],
                name='A',
            )
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press('shift+tab')
        await pilot.pause()
        # Queue an extra command while the first one is still sleeping.
        await pilot.press('!')
        await pilot.pause()
        app.query_one('#command-input', Input).value = 'echo interactive'
        await pilot.press('enter')
        await pilot.pause()
        # Menu: "Run in this tab".
        await pilot.press('1')

        failed, skipped, interactive = await _wait_until_settled(
            app, pilot, panes_expected=3
        )
        assert failed.return_code == 3
        assert skipped.border_subtitle == 'Skipped'
        assert interactive.return_code == 0
