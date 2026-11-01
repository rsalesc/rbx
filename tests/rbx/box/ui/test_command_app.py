"""Tests for the rbx on / rbx each command app (rbx.box.ui.command_app)."""

import datetime
import pathlib
import subprocess

import pytest
from textual.widgets import Label, ListItem, ListView

from rbx.box import setter_config
from rbx.box.setter_config import ProblemLabelMode
from rbx.box.ui import run_history, run_picker
from rbx.box.ui.command_app import CommandEntry, rbxCommandApp


@pytest.fixture(autouse=True)
def _reset_label_mode():
    # `mock_app_path` is session-scoped, so the persisted setter config is shared
    # across tests; pin it to the default before each test for isolation.
    cfg = setter_config.get_setter_config()
    cfg.ui.problem_label = ProblemLabelMode.NAME
    setter_config.save_setter_config(cfg)
    yield


def _labeled_entry() -> CommandEntry:
    return CommandEntry(
        # Empty argvs => no sub-command is enqueued, so no subprocess is spawned.
        argvs=[],
        name='A. two-sum',
        labels={
            ProblemLabelMode.NAME: 'A. two-sum',
            ProblemLabelMode.TITLE: 'A. Two Sum',
            ProblemLabelMode.PATH: 'A. probs/a',
        },
    )


def _sidebar_text(app, index: int) -> str:
    label = app.query_one(f'#cmd-item-{index}', ListItem).query_one(Label)
    return str(label.render())


def _sidebar_subtitle(app) -> str:
    return str(app.query_one('#command-list', ListView).border_subtitle)


def _persisted_mode() -> ProblemLabelMode:
    return setter_config.get_setter_config().ui.problem_label


async def test_sidebar_uses_configured_label_mode():
    app = rbxCommandApp([_labeled_entry()])
    async with app.run_test() as pilot:
        await pilot.pause()
        # Default mode is `name`, shown both in the item and as a sidebar hint.
        assert 'A. two-sum' in _sidebar_text(app, 0)
        assert 'label: name' in _sidebar_subtitle(app)


async def test_l_cycles_and_persists_problem_label():
    app = rbxCommandApp([_labeled_entry()])
    async with app.run_test() as pilot:
        # shift+tab deterministically focuses the sidebar (public key path).
        await pilot.press('shift+tab')
        await pilot.pause()

        await pilot.press('l')
        await pilot.pause()
        assert _persisted_mode() is ProblemLabelMode.TITLE
        assert 'A. Two Sum' in _sidebar_text(app, 0)
        assert 'label: title' in _sidebar_subtitle(app)

        await pilot.press('l')
        await pilot.pause()
        assert _persisted_mode() is ProblemLabelMode.PATH
        assert 'A. probs/a' in _sidebar_text(app, 0)
        assert 'label: path' in _sidebar_subtitle(app)

        # Wraps back to name.
        await pilot.press('l')
        await pilot.pause()
        assert _persisted_mode() is ProblemLabelMode.NAME
        assert 'A. two-sum' in _sidebar_text(app, 0)
        assert 'label: name' in _sidebar_subtitle(app)


async def test_l_is_inert_without_labels():
    app = rbxCommandApp([CommandEntry(argvs=[], name='echo')])
    async with app.run_test() as pilot:
        await pilot.press('shift+tab')
        await pilot.pause()

        await pilot.press('l')
        await pilot.pause()
        # No labels => the key falls through; the persisted config is unchanged
        # and the sidebar shows no label hint.
        assert _persisted_mode() is ProblemLabelMode.NAME
        assert 'label:' not in _sidebar_subtitle(app)


def _shell_output(command: str) -> str:
    return subprocess.run(
        command, shell=True, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_entry_env_reaches_every_command_it_runs(tmp_path: pathlib.Path):
    entry = CommandEntry(
        argvs=[['sh', '-c', 'echo "$PWD $RBX_DOCKER_PRIORITY"']],
        cwd=str(tmp_path),
        env={'RBX_DOCKER_PRIORITY': '3'},
    )
    (chained,) = entry.shell_commands
    assert _shell_output(chained) == f'{tmp_path.resolve()} 3'
    # A command typed into the tab later gets it too.
    typed = entry.make_raw_shell_command('printenv RBX_DOCKER_PRIORITY')
    assert _shell_output(typed) == '3'


def test_entry_without_env_or_cwd_is_left_alone():
    assert CommandEntry(argvs=[]).make_shell_command(['rbx', 'build']) == 'rbx build'
    assert (
        CommandEntry(argvs=[], cwd='/x').make_shell_command(['rbx', 'build'])
        == 'cd /x && exec rbx build'
    )


def test_entry_env_survives_the_run_history():
    entry = CommandEntry(argvs=[], name='A', env={'RBX_DOCKER_PRIORITY': '1'})
    record = run_history.TabRecord(name=entry.display_name, env=entry.env)
    manifest = run_history.RunManifest.model_validate_json(
        run_history.RunManifest(
            run_id='r',
            started_at=datetime.datetime(2026, 1, 1),
            updated_at=datetime.datetime(2026, 1, 1),
            tabs=[record],
        ).model_dump_json()
    )
    (reopened,) = run_picker.entries_from_manifest(manifest)
    assert reopened.env == {'RBX_DOCKER_PRIORITY': '1'}
