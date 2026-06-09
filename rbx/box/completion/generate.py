"""DEV/CI-time generator: introspect the real Typer/Click command tree and emit
a static "spec" dict describing the whole CLI.

This module imports the heavy app on purpose -- it only runs offline (or in tests)
to (re)generate the committed spec. The fast runtime engine resolves completions
from the spec without importing any of this.

Spec schema (minimal -- exactly these keys):

    Command = {
      'name': str,                # RAW registered name, e.g. 'package, pkg'
      'help': Optional[str],
      'panel': Optional[str],     # rich_help_panel
      'is_group': bool,
      'children': list[Command],  # only when is_group; sorted by name
      'params': list[Param],
    }
    Param = {
      'kind': 'option' | 'argument',
      'names': list[str],         # option opts; [] for positional argument
      'takes_value': bool,        # False for boolean flags
      'help': Optional[str],
      'value': dict,              # {'kind': 'choice'|'completer'|'path'|'none', ...}
    }
"""

from typing import Any, Callable, Dict, List, Optional

import click

from rbx.box.completion import registry


class UnregisteredCompleterError(RuntimeError):
    """Raised when a param has a custom completer that maps to no registry key.

    This forces every dynamic completer through the registry, so the static spec
    can always name the completer by key (and the fast engine can resolve it).
    """


def _completer_candidates(param: click.Parameter) -> List[Callable[..., Any]]:
    """Return the candidate callables that may carry the completer key.

    Empirically pinned against typer 0.21 / click 8.3: Typer stores the user's
    ``autocompletion=`` callback on ``param._custom_shell_complete`` as a
    ``compat_autocompletion`` closure. That closure closes over the wrapper
    produced by ``typer.main.get_param_completion``, which (via
    ``functools.update_wrapper``) carries the original callback's ``__dict__``
    (so ``_completer_key`` survives) and a ``__wrapped__`` pointer back to the
    original callback.

    We therefore collect, in order: the stored closure, every object found in
    its closure cells, and the full ``__wrapped__`` chain of each. The caller
    probes each candidate for ``_completer_key`` / registry membership.
    """
    csc = getattr(param, '_custom_shell_complete', None)
    if csc is None:
        return []

    candidates: List[Callable[..., Any]] = []
    seen: set = set()

    def add(fn: Any) -> None:
        if not callable(fn) or id(fn) in seen:
            return
        seen.add(id(fn))
        candidates.append(fn)
        # Follow the functools.update_wrapper chain.
        add(getattr(fn, '__wrapped__', None))

    add(csc)
    # The compat closure wraps the get_param_completion wrapper in a cell.
    for cell in getattr(csc, '__closure__', None) or ():
        try:
            add(cell.cell_contents)
        except ValueError:
            # Empty cell.
            continue
    return candidates


def _completer_key(param: click.Parameter) -> Optional[str]:
    candidates = _completer_candidates(param)
    if not candidates:
        return None
    for fn in candidates:
        key = getattr(fn, '_completer_key', None) or registry.key_for_function(fn)
        if key is not None:
            return key
    raise UnregisteredCompleterError(f'completer for {param.name!r} is not registered')


def _value_spec(param: click.Parameter) -> Dict[str, Any]:
    key = _completer_key(param)
    if key is not None:
        return {'kind': 'completer', 'completer': key}
    t = param.type
    choices = getattr(t, 'choices', None)
    if choices:
        return {'kind': 'choice', 'choices': [str(c) for c in choices]}
    if isinstance(t, (click.Path, click.File)):
        dir_only = bool(getattr(t, 'dir_okay', False)) and not bool(
            getattr(t, 'file_okay', True)
        )
        return {'kind': 'path', 'path': 'dir' if dir_only else 'file'}
    return {'kind': 'none'}


def _param_spec(param: click.Parameter) -> Dict[str, Any]:
    is_opt = isinstance(param, click.Option)
    is_flag = bool(getattr(param, 'is_flag', False))
    return {
        'kind': 'option' if is_opt else 'argument',
        'names': list(param.opts) if is_opt else [],
        'takes_value': not is_flag,
        'help': getattr(param, 'help', None) if is_opt else None,
        'value': {'kind': 'none'} if is_flag else _value_spec(param),
    }


def _panel(cmd: click.Command) -> Optional[str]:
    """Return the rich help panel as a plain ``Optional[str]``.

    Typer's click conversion can leave ``rich_help_panel`` as a
    ``typer.models.DefaultPlaceholder`` (whose ``.value`` is the real default,
    usually ``None``) rather than a bare string/``None``. Such an object does not
    ``repr`` to valid Python, which would break the serialized spec's round-trip,
    so we unwrap it here (duck-typed to avoid importing typer).
    """
    panel = getattr(cmd, 'rich_help_panel', None)
    if panel is not None and not isinstance(panel, str) and hasattr(panel, 'value'):
        panel = panel.value
    return panel if isinstance(panel, str) else None


def build_spec(cmd: click.Command, name: Optional[str] = None) -> Dict[str, Any]:
    node: Dict[str, Any] = {
        'name': name if name is not None else (cmd.name or ''),
        'help': cmd.get_short_help_str() or None,
        'panel': _panel(cmd),
        'is_group': isinstance(cmd, click.Group),
        'params': [
            _param_spec(p) for p in cmd.params if not getattr(p, 'hidden', False)
        ],
    }
    if isinstance(cmd, click.Group):
        # Iterate the raw command dict so comma-joined names (e.g. 'package, pkg')
        # are captured verbatim; the engine splits them on ', ' for descent.
        # Skip hidden commands -- Click's completion hides them too, so including
        # them would make the engine offer commands the real CLI never completes.
        children = [
            build_spec(sub, name=raw)
            for raw, sub in cmd.commands.items()
            if not getattr(sub, 'hidden', False)
        ]
        node['children'] = sorted(children, key=lambda c: c['name'])
    return node
