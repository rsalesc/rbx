import contextvars
import os
import re
from typing import Optional

VARIANT_ID_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9_-]*$')
ENV_VAR = 'RBX_CONTEST'

selected_variant_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    'rbx_selected_variant_id', default=None
)


def is_valid_variant_id(value: str) -> bool:
    return bool(VARIANT_ID_PATTERN.match(value))


def get_selected_variant_id() -> Optional[str]:
    return selected_variant_id_var.get()


def apply_cli_selection(contest_id: Optional[str]) -> None:
    """Validate and apply a contest variant id from the CLI/env, exiting on bad input.

    No-op when `contest_id` is None.
    """
    if contest_id is None:
        return
    if not is_valid_variant_id(contest_id):
        # Imported here to avoid a CLI dependency at import time.
        import typer

        from rbx.console import console

        console.print(f'[error]Invalid contest id: {contest_id!r}[/error]')
        raise typer.Exit(1)
    selected_variant_id_var.set(contest_id)


def resolve_explicit_selection() -> Optional[str]:
    """Returns the selected variant id, preferring contextvar over env var."""
    explicit = selected_variant_id_var.get()
    if explicit is not None:
        return explicit
    env_value = os.environ.get(ENV_VAR)
    if env_value:
        return env_value
    return None
