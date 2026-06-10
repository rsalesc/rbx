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
      'children': list[Command],  # only when is_group; in registration order
      'params': list[Param],      # includes Click's auto '--help' flag
    }
    Param = {
      'kind': 'option' | 'argument',
      'names': list[str],         # option opts; [] for positional argument
      'takes_value': bool,        # False for boolean flags
      'multiple': bool,           # True if the option may be repeated (Click re-offers it)
      'help': Optional[str],
      'value': dict,              # {'kind': 'choice'|'completer'|'path'|'none', ...}
                                  # a 'completer' value may carry an optional
                                  # 'file'/'dir' key (file-union: append a shell
                                  # file/dir directive after the dynamic candidates)
      'variadic': bool,           # OPTIONAL, arguments only: True when nargs == -1
                                  # (the engine re-offers it past its position)
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


def _completer_file(param: click.Parameter) -> Optional[str]:
    """Return the file-union flag ('file'/'dir') a completer callback was tagged
    with via `_adapt(file=...)`, or None. Mirrors `_completer_key`'s candidate
    probe so it survives Typer's wrapper chain."""
    for fn in _completer_candidates(param):
        flag = getattr(fn, '_completer_file', None)
        if flag is not None:
            return flag
    return None


def _value_spec(param: click.Parameter) -> Dict[str, Any]:
    key = _completer_key(param)
    if key is not None:
        spec: Dict[str, Any] = {'kind': 'completer', 'completer': key}
        file_flag = _completer_file(param)
        if file_flag is not None:
            spec['file'] = file_flag
        return spec
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
    # Boolean flags declared as ``--check/--no-check`` carry the negation form in
    # ``secondary_opts``; Click completes BOTH, so include them in the names.
    names = list(param.opts) + list(getattr(param, 'secondary_opts', []))
    spec: Dict[str, Any] = {
        'kind': 'option' if is_opt else 'argument',
        'names': names if is_opt else [],
        'takes_value': not is_flag,
        'multiple': bool(getattr(param, 'multiple', False)),
        'help': getattr(param, 'help', None) if is_opt else None,
        'value': {'kind': 'none'} if is_flag else _value_spec(param),
    }
    if not is_opt and getattr(param, 'nargs', 1) == -1:
        spec['variadic'] = True
    return spec


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


def _help_param(cmd: click.Command) -> Optional[Dict[str, Any]]:
    """Spec entry for Click's auto-generated ``--help`` flag, if the command has
    one. Click materializes this option only at parse/completion time (it is NOT
    in ``cmd.params``), yet its native completion offers it, so the static spec
    must carry it to match. We ask Click for the real option to stay faithful to
    ``add_help_option`` / ``help_option_names``."""
    ctx = click.Context(cmd)
    help_option = cmd.get_help_option(ctx)
    if help_option is None or getattr(help_option, 'hidden', False):
        return None
    return {
        'kind': 'option',
        'names': list(help_option.opts) + list(help_option.secondary_opts),
        'takes_value': False,
        'multiple': False,
        'help': getattr(help_option, 'help', None),
        'value': {'kind': 'none'},
    }


def build_spec(cmd: click.Command, name: Optional[str] = None) -> Dict[str, Any]:
    params = [_param_spec(p) for p in cmd.params if not getattr(p, 'hidden', False)]
    help_param = _help_param(cmd)
    if help_param is not None:
        params.append(help_param)
    node: Dict[str, Any] = {
        'name': name if name is not None else (cmd.name or ''),
        'help': cmd.get_short_help_str() or None,
        'panel': _panel(cmd),
        'is_group': isinstance(cmd, click.Group),
        'params': params,
    }
    if isinstance(cmd, click.Group):
        # Iterate the raw command dict so comma-joined names (e.g. 'package, pkg')
        # are captured verbatim; the engine splits them on ', ' for descent.
        # Skip hidden commands -- Click's completion hides them too, so including
        # them would make the engine offer commands the real CLI never completes.
        #
        # Preserve INSERTION order (do not sort): for ambiguous aliases (e.g. the
        # token 't' registered by both 'time, t' and 'testcases, tc, t'), Click's
        # AliasGroup resolves to the FIRST command in registration order, so the
        # engine must descend in the same order to stay faithful.
        node['children'] = [
            build_spec(sub, name=raw)
            for raw, sub in cmd.commands.items()
            if not getattr(sub, 'hidden', False)
        ]
    return node
