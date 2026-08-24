"""Copied text has to reach the clipboard as UTF-8.

Textual copies over OSC 52: the terminal is handed base64 and decides for itself
what encoding the bytes were. A terminal that guesses latin-1 -- xterm.js, which
VS Code's integrated terminal is built on, decoded the payload with `atob` --
turns rbx's verdict markers into mojibake the moment they are pasted anywhere:
`✓` comes out as `â`, `⧖` as `â§`, `·` as `Â·`.

Writing the clipboard ourselves takes that guess out of the loop.
"""

import asyncio
import shutil
import sys

import pytest

from rbx.box.ui import clipboard
from rbx.box.ui._vendor.toad.widgets.command_pane import CommandPane
from rbx.box.ui.command_app import CommandEntry, rbxCommandApp

# The characters rbx prints for verdicts, and the mojibake each turns into when
# its UTF-8 bytes are read back as latin-1.
_VERDICTS = '✓✗⧖⊘·'


@pytest.fixture
def clean_env(monkeypatch):
    for name in (
        'SSH_CONNECTION',
        'SSH_TTY',
        'WAYLAND_DISPLAY',
        'DISPLAY',
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_a_remote_session_has_no_local_clipboard(clean_env):
    # Over SSH the local tools would write the *server's* clipboard, which the
    # user cannot paste from. OSC 52 is the only channel that reaches them.
    clean_env.setenv('SSH_CONNECTION', '10.0.0.1 22 10.0.0.2 22')
    assert clipboard.is_remote_session()
    assert clipboard.native_clipboard_command() is None


def test_a_local_session_is_not_remote(clean_env):
    assert not clipboard.is_remote_session()


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS clipboard')
def test_macos_uses_pbcopy(clean_env):
    assert clipboard.native_clipboard_command() == ['pbcopy']


def test_a_display_less_linux_session_has_no_clipboard(clean_env, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    assert clipboard.native_clipboard_command() is None


def test_linux_picks_the_tool_for_the_display(clean_env, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setenv('DISPLAY', ':0')
    monkeypatch.setattr(
        shutil, 'which', lambda name: '/usr/bin/xclip' if name == 'xclip' else None
    )
    assert clipboard.native_clipboard_command() == ['xclip', '-selection', 'clipboard']


def test_wayland_is_preferred_when_it_is_the_session(clean_env, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setenv('WAYLAND_DISPLAY', 'wayland-0')
    monkeypatch.setenv('DISPLAY', ':0')
    monkeypatch.setattr(shutil, 'which', lambda name: f'/usr/bin/{name}')
    assert clipboard.native_clipboard_command() == ['wl-copy']


async def test_the_bytes_handed_over_are_utf_8(tmp_path):
    # The whole point: what the clipboard command receives on stdin is UTF-8,
    # not whatever a terminal would have guessed.
    written = tmp_path / 'clipboard'
    command = [
        sys.executable,
        '-c',
        f'import sys; open({str(written)!r}, "wb").write(sys.stdin.buffer.read())',
    ]

    assert await clipboard.write_native(command, f'manual (20) 1/{_VERDICTS}')

    assert written.read_bytes() == f'manual (20) 1/{_VERDICTS}'.encode('utf-8')
    assert written.read_bytes().decode('utf-8') == f'manual (20) 1/{_VERDICTS}'


async def test_a_failing_clipboard_command_is_reported():
    assert not await clipboard.write_native(
        [sys.executable, '-c', 'raise SystemExit(1)'], 'text'
    )


async def test_a_missing_clipboard_command_is_reported():
    assert not await clipboard.write_native(['rbx-no-such-clipboard-tool'], 'text')


async def test_osc_52_carries_the_copy_when_there_is_no_local_clipboard(monkeypatch):
    monkeypatch.setattr(clipboard, 'native_clipboard_command', lambda: None)
    fallback: list[str] = []

    class _App:
        def copy_to_clipboard(self, text: str) -> None:
            fallback.append(text)

    await clipboard._copy(_App(), _VERDICTS)  # noqa: SLF001

    assert fallback == [_VERDICTS]


async def test_the_terminal_is_not_asked_when_the_clipboard_took_it(monkeypatch):
    # Both would race for the clipboard, and the terminal is the one that gets
    # the encoding wrong -- so it is only used when nothing else worked.
    monkeypatch.setattr(clipboard, 'native_clipboard_command', lambda: ['true'])

    async def _accept(command, text):
        return True

    monkeypatch.setattr(clipboard, 'write_native', _accept)
    fallback: list[str] = []

    class _App:
        def copy_to_clipboard(self, text: str) -> None:
            fallback.append(text)

    await clipboard._copy(_App(), _VERDICTS)  # noqa: SLF001

    assert fallback == []


async def test_pressing_ctrl_y_writes_utf_8_to_the_clipboard(tmp_path, monkeypatch):
    # The whole path, unpatched: pane -> clipboard.copy -> worker -> command.
    written = tmp_path / 'clipboard'
    monkeypatch.setattr(
        clipboard,
        'native_clipboard_command',
        lambda: [
            sys.executable,
            '-c',
            f'import sys; open({str(written)!r}, "wb").write(sys.stdin.buffer.read())',
        ],
    )

    body = f'print({_VERDICTS!r})'
    app = rbxCommandApp(
        [CommandEntry(argvs=[[sys.executable, '-c', body]], name='a')], parallel=True
    )
    async with app.run_test(size=(80, 20)) as pilot:
        pane = None
        for _ in range(100):
            await pilot.pause()
            await asyncio.sleep(0.05)
            panes = list(app.query(CommandPane))
            if panes and all(p.return_code is not None for p in panes):
                (pane,) = panes
                break
        assert pane is not None, 'command did not finish in time'

        app.set_focus(pane)
        await pilot.pause()
        await pilot.press('ctrl+y')
        for _ in range(100):
            await pilot.pause()
            await asyncio.sleep(0.05)
            if written.exists():
                break

    assert written.read_bytes() == _VERDICTS.encode('utf-8')
    assert written.read_bytes().decode('utf-8') == _VERDICTS
