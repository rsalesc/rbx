"""Lazy command registration for the `rbx` Typer app.

Typer registers a command by holding on to the function that implements it, so
importing the module that builds the app imports every command's
implementation -- and with it every module those commands touch. `rbx --help`
paid for `rbx package build`, `rbx stress` and the whole grading stack before
printing a line.

The group built here registers commands as `'module:attr'` strings instead. The
table carries what `--help` needs (name, short help, panel, hidden), so the help
screen renders from the table alone; a module is imported only when its command
is actually resolved for execution.

Two kinds of entries exist:

- a **command module** (`is_group=False`), whose `attr` is a `typer.Typer` app
  holding one or more commands registered the usual way. The entry's `name` is
  the raw registered name, aliases included (`'build, b'`).
- a **sub-app** (`is_group=True`), whose `attr` is the `typer.Typer` app mounted
  as a group -- what `app.add_typer(...)` used to do.
"""

import dataclasses
import importlib
from difflib import get_close_matches
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type

import click

from rbx.annotations import AliasGroup


@dataclasses.dataclass(frozen=True)
class LazyCommand:
    """One row of a lazy group's registration table."""

    name: str
    """Raw registered name, aliases included (e.g. `'build, b'`)."""

    target: str
    """`'module:attr'`, where `attr` is a `typer.Typer` app."""

    help: Optional[str] = None
    """Short help, as it would have been passed to `@app.command(help=...)`.

    Kept here so `--help` never imports the module. `lazy_cli_test.py` pins it
    against what the module actually declares.
    """

    rich_help_panel: Optional[str] = None
    hidden: bool = False
    is_group: bool = False


class LazyAliasGroup(AliasGroup):
    """A `TyperGroup` whose subcommands are resolved from import paths.

    Not used directly -- `lazy_group_cls` builds the subclass that carries the
    table, because Typer instantiates the group class itself and gives us no
    way to pass state in.
    """

    lazy_commands: Dict[str, LazyCommand] = {}
    lazy_pretty_exceptions_short: bool = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._lazy_resolved: Dict[str, click.Command] = {}
        self._lazy_help_only = False

    # -- Registration table -------------------------------------------------

    def list_commands(self, ctx: Optional[click.Context]) -> List[str]:
        # Registration order, like `TyperGroup.list_commands`: `AliasGroup`
        # resolves an ambiguous alias to the first command that claims it, so
        # the order here is part of the CLI's behaviour, not cosmetics.
        return [*self.lazy_commands, *self.commands]

    def _group_cmd_name(self, default_name: str) -> str:
        for name in self.lazy_commands:
            if default_name in self._CMD_SPLIT_P.split(name):
                return name
        return super()._group_cmd_name(default_name)

    # -- Resolution ---------------------------------------------------------

    def get_command(
        self, ctx: Optional[click.Context], cmd_name: str
    ) -> Optional[click.Command]:
        cmd_name = self._group_cmd_name(cmd_name)
        entry = self.lazy_commands.get(cmd_name)
        if entry is None:
            return super().get_command(ctx, cmd_name)
        if self._lazy_help_only:
            return _help_stub(entry)
        if cmd_name not in self._lazy_resolved:
            self._lazy_resolved[cmd_name] = self._materialize(entry)
        return self._lazy_resolved[cmd_name]

    def _materialize(self, entry: LazyCommand) -> click.Command:
        import typer.main
        from typer.models import TyperInfo

        module_name, _, attr = entry.target.partition(':')
        sub_app = getattr(importlib.import_module(module_name), attr)

        if entry.is_group:
            return typer.main.get_group_from_info(
                TyperInfo(
                    typer_instance=sub_app,
                    name=entry.name,
                    cls=AliasGroup,
                    help=entry.help,
                    rich_help_panel=entry.rich_help_panel,
                    hidden=entry.hidden,
                ),
                pretty_exceptions_short=self.lazy_pretty_exceptions_short,
                rich_markup_mode=self.rich_markup_mode,
                suggest_commands=self.suggest_commands,
            )

        group = typer.main.get_group_from_info(
            TyperInfo(typer_instance=sub_app),
            pretty_exceptions_short=self.lazy_pretty_exceptions_short,
            rich_markup_mode=self.rich_markup_mode,
            suggest_commands=self.suggest_commands,
        )
        command = group.commands.get(entry.name)
        if command is None:
            raise RuntimeError(
                f'{entry.target} declares no command named {entry.name!r} '
                f'(it has: {", ".join(sorted(group.commands)) or "none"})'
            )
        return command

    def materialize_all(self) -> None:
        """Import and register every lazy entry, in registration order.

        For the tools that need the whole tree at once -- the completion spec
        generator and the docs generator. Both run offline, where the import
        cost this module exists to avoid does not matter.
        """
        resolved = {
            name: self._materialize(e) for name, e in self.lazy_commands.items()
        }
        resolved.update(self.commands)
        self.commands = resolved
        # Shadows the class attribute, so nothing is resolved lazily any more.
        self.lazy_commands = {}
        self._lazy_resolved = {}

    # -- Help ---------------------------------------------------------------

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        # Both the rich and the plain renderer list subcommands by calling
        # `get_command` for each name; the flag makes those calls answer from
        # the table instead of importing.
        self._lazy_help_only = True
        try:
            super().format_help(ctx, formatter)
        finally:
            self._lazy_help_only = False

    # -- Errors -------------------------------------------------------------

    def resolve_command(
        self, ctx: click.Context, args: List[str]
    ) -> Tuple[Optional[str], Optional[click.Command], List[str]]:
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError as e:
            # `TyperGroup` builds its "did you mean" list from `self.commands`,
            # which holds nothing that has not been resolved yet.
            if (
                self.suggest_commands
                and args
                and self.lazy_commands
                and 'Did you mean' not in (e.message or '')
            ):
                matches = get_close_matches(args[0], self.list_commands(ctx))
                if matches:
                    suggestions = ', '.join(f'{m!r}' for m in matches)
                    e.message = f'{e.message.rstrip(".")}. Did you mean {suggestions}?'
            raise


def _help_stub(entry: LazyCommand) -> click.Command:
    """A command that carries everything the help screen reads, and no callback.

    Never reachable from an invocation: `get_command` only returns one while a
    help screen is rendering.
    """
    command = click.Command(
        name=entry.name,
        help=entry.help,
        hidden=entry.hidden,
        add_help_option=False,
    )
    command.rich_help_panel = entry.rich_help_panel  # type: ignore[attr-defined]
    return command


def lazy_group_cls(
    entries: Sequence[LazyCommand],
    *,
    pretty_exceptions_short: bool = True,
) -> Type[LazyAliasGroup]:
    """Build the `cls=` for a `typer.Typer` whose subcommands are `entries`.

    Typer constructs the group class itself, so the table has to travel as a
    class attribute of a purpose-built subclass.
    """
    table: Dict[str, LazyCommand] = {}
    for entry in entries:
        if entry.name in table:
            raise ValueError(f'duplicate lazy command name: {entry.name!r}')
        table[entry.name] = entry

    class _LazyGroup(LazyAliasGroup):
        lazy_commands = table
        lazy_pretty_exceptions_short = pretty_exceptions_short

    return _LazyGroup
