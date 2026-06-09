"""Reference completion via the real Typer app (slow, correct). Test-only oracle."""

import functools
from typing import List

import click
import typer.main
from click.shell_completion import CompletionItem


@functools.lru_cache(maxsize=1)
def _real_cli() -> click.Command:
    from rbx.box.cli import app  # heavy import — fine in tests

    return typer.main.get_command(app)


def typer_completions(args: List[str], incomplete: str) -> List[CompletionItem]:
    """Run Click's native completion resolution against the real app."""
    from click.shell_completion import ShellComplete

    cli = _real_cli()
    # `ctx_args` is forwarded to `cli.make_context(...)`, so it must only carry
    # real Context kwargs; `prog_name` is the dedicated positional below.
    ctx_args: dict = {}

    comp = ShellComplete(cli, ctx_args, 'rbx', '_RBX_COMPLETE')
    return comp.get_completions(list(args), incomplete)
