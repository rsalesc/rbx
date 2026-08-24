"""Getting copied text onto the clipboard intact.

Textual copies by writing an OSC 52 escape sequence: the text, encoded as UTF-8
and then base64, handed to whatever terminal the app is running in. The terminal
decodes it and puts the result on the clipboard -- and that last step is where
the bytes stop being ours. A terminal that decodes them as latin-1 (xterm.js,
which VS Code's integrated terminal is built on, historically did exactly this
via `atob`) turns every character rbx prints outside ASCII into mojibake:

    ✓ (E2 9C 93) -> â  ⧖ (E2 A7 96) -> â§  · (C2 B7) -> Â·

which is what the copied output looks like when it is pasted anywhere else.

So when the clipboard is reachable without going through the terminal, write to
it directly -- `pbcopy` and friends take bytes, and we hand them UTF-8. OSC 52
stays the fallback, because over SSH it is the only channel that reaches the
machine the user is actually sitting at.
"""

import asyncio
import os
import shutil
import subprocess
import sys
from typing import List, Optional, Sequence

_MACOS_COMMAND = ['pbcopy']
_WINDOWS_COMMAND = ['clip']
_WAYLAND_COMMAND = ['wl-copy']
_X11_COMMANDS = [
    ['xclip', '-selection', 'clipboard'],
    ['xsel', '--clipboard', '--input'],
]


def is_remote_session() -> bool:
    """Is the app running over SSH?

    The local clipboard tools would then be the *server's*, which no one can
    paste from. OSC 52 travels back down the connection, so it is the only thing
    that reaches the user.
    """
    return bool(os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_TTY'))


def native_clipboard_command() -> Optional[List[str]]:
    """The command that writes this machine's clipboard, if there is one.

    Returns:
        A command to pipe UTF-8 bytes into, or `None` when the clipboard is only
        reachable through the terminal.
    """
    if is_remote_session():
        return None

    candidates: List[List[str]] = []
    if sys.platform == 'darwin':
        candidates.append(_MACOS_COMMAND)
    elif sys.platform == 'win32':
        candidates.append(_WINDOWS_COMMAND)
    else:
        # Asking a display-less session for its clipboard hangs or fails; both
        # tools want the display they were built for.
        if os.environ.get('WAYLAND_DISPLAY'):
            candidates.append(_WAYLAND_COMMAND)
        if os.environ.get('DISPLAY'):
            candidates.extend(_X11_COMMANDS)

    for candidate in candidates:
        if shutil.which(candidate[0]) is not None:
            return candidate
    return None


async def write_native(command: Sequence[str], text: str) -> bool:
    """Pipe `text` into a clipboard command as UTF-8.

    Args:
        command: Command to run.
        text: Text to copy.

    Returns:
        `True` if the command took it.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await process.communicate(text.encode('utf-8'))
    except (OSError, ValueError):
        return False
    return process.returncode == 0


async def _copy(app, text: str) -> None:
    command = native_clipboard_command()
    if command is not None and await write_native(command, text):
        return
    # No local clipboard, or the tool for it failed: let the terminal try.
    app.copy_to_clipboard(text)


def copy(app, text: str) -> None:
    """Copy text to the clipboard.

    Args:
        app: The running app.
        text: Text to copy.
    """
    app.run_worker(_copy(app, text), group='clipboard', exit_on_error=False)
