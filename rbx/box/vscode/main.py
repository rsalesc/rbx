import os
import shutil
import subprocess
from typing import Annotated, Optional

import typer

from rbx import annotations, console
from rbx.box.vscode import extension

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)


@app.callback()
def callback():
    """Manage the rbx editor extension."""
    # Without an explicit callback, Typer collapses a one-command app into that
    # command, so `rbx vscode` would install and `rbx vscode install` would be a
    # usage error.


def _editor_keys() -> str:
    return ', '.join(editor.key for editor in extension.EDITORS)


@app.command('install')
def install(
    editor_key: Annotated[
        Optional[str],
        typer.Option(
            '--editor',
            '-e',
            help=f'Editor to install into: {_editor_keys()}.',
        ),
    ] = None,
):
    """Install the rbx extension into VS Code (or Cursor, Windsurf, VSCodium)."""
    if editor_key is not None:
        editor = extension.editor_by_key(editor_key)
        if editor is None:
            console.console.print(
                f'[error]Unknown editor [item]{editor_key}[/item].[/error]'
            )
            console.console.print(f'Known editors: [item]{_editor_keys()}[/item].')
            raise typer.Exit(1)
    else:
        editor = extension.detect_editor(os.environ)
        if editor is None:
            console.console.print(
                '[error]Not running inside an editor terminal.[/error]'
            )
            console.console.print(
                "Run this from the editor's integrated terminal, or name one with "
                '[item]--editor[/item].'
            )
            raise typer.Exit(1)

    bundled = extension.bundled_vsix()
    if bundled is None:
        console.console.print(
            '[error]This rbx does not bundle the editor extension.[/error]'
        )
        console.console.print(
            'Running from a checkout? Build it with [item]mise run vscode:vsix[/item].'
        )
        raise typer.Exit(1)

    manual = f'{editor.binary} --install-extension {bundled.path} --force'
    if shutil.which(editor.binary) is None:
        console.console.print(
            f'[error]Could not find the [item]{editor.binary}[/item] command.[/error]'
        )
        console.console.print(
            f'Add it from {editor.label} with '
            f"[item]Shell Command: Install '{editor.binary}' command in PATH[/item], "
            f'or run it by hand: [item]{manual}[/item]'
        )
        raise typer.Exit(1)

    result = subprocess.run(
        [editor.binary, '--install-extension', str(bundled.path), '--force'],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.console.print(
            f'[error]{editor.label} failed to install the extension.[/error]'
        )
        console.console.print((result.stderr or result.stdout).strip())
        raise typer.Exit(1)

    console.console.print(
        f'[success]Installed the rbx extension ({bundled.version}) into '
        f'{editor.label}.[/success]'
    )
    # A freshly installed extension does not reliably activate in windows that
    # are already open, so do not pretend it is live.
    console.console.print('[info]Reload the window to start using it.[/info]')
