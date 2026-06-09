"""Static-spec completion resolver. Light imports only -- never the heavy app."""

from typing import Any, Dict, List, Optional, Tuple

from click.shell_completion import CompletionItem

from rbx.box.completion import context
from rbx.box.completion.registry import CompletionContext, load_completer

FILE = [CompletionItem('', type='file')]
DIR = [CompletionItem('', type='dir')]


def _match_names(raw_name: str) -> List[str]:
    return [s.strip() for s in raw_name.split(',')]


def _find_child(node: Dict[str, Any], token: str) -> Optional[Dict[str, Any]]:
    for c in node.get('children', []):
        if token in _match_names(c['name']):
            return c
    return None


def _find_option(node: Dict[str, Any], token: str) -> Optional[Dict[str, Any]]:
    name = token.split('=', 1)[0]
    for p in node['params']:
        if p['kind'] == 'option' and name in p['names']:
            return p
    return None


def _walk(
    spec: Dict[str, Any], args: List[str]
) -> Tuple[Dict[str, Any], list, dict, Optional[Dict[str, Any]], int]:
    node = spec
    command: list = []
    option_values: dict = {}
    pending: Optional[Dict[str, Any]] = None
    positional = 0
    no_more_opts = False
    for tok in args:
        if pending is not None:
            option_values[pending['names'][0]] = tok
            pending = None
            continue
        if tok == '--' and not no_more_opts:
            no_more_opts = True
            continue
        if not no_more_opts and tok.startswith('-') and tok != '-':
            opt = _find_option(node, tok)
            if opt is not None and opt['takes_value']:
                if '=' in tok:
                    option_values[opt['names'][0]] = tok.split('=', 1)[1]
                else:
                    pending = opt
            continue
        child = _find_child(node, tok) if node.get('is_group') else None
        if child is not None:
            node = child
            command.append(_match_names(child['name'])[0])
        else:
            positional += 1
    return node, command, option_values, pending, positional


def _value_items(
    value: Dict[str, Any], ctx: CompletionContext, incomplete: str
) -> List[CompletionItem]:
    kind = value.get('kind')
    if kind == 'choice':
        return [CompletionItem(c) for c in value['choices'] if c.startswith(incomplete)]
    if kind == 'completer':
        return list(load_completer(value['completer'])(ctx, incomplete))
    if kind == 'path':
        return DIR if value.get('path') == 'dir' else FILE
    return FILE  # 'none'/unknown -> shell default file completion


def _completion_class(shell: str):
    """Return the Click ShellComplete class for `shell` (or None if unknown).

    We deliberately use Click's *native* completion classes. The real `rbx` CLI
    dispatches completion via `typer.completion.shell_complete`, which calls
    `click.shell_completion.get_completion_class(shell)` -- and at that point
    Typer's enhanced classes have NOT been registered (`completion_init` only
    runs while building the `--install/--show-completion` params, which the
    completion dispatch short-circuits before reaching). So the real CLI emits
    Click-native output (bash: ``plain,ui``; zsh: ``plain\nui\n<help>``). To be
    byte-compatible we must match that, i.e. NOT call `completion_init()`.

    We resolve the native classes by name rather than via the global
    `get_completion_class` registry: importing the heavy app elsewhere (e.g. in
    tests) calls `completion_init()`, which overwrites that registry with
    Typer's enhanced classes whose output format differs. Binding the native
    class directly keeps us faithful to the real dispatch regardless of any such
    global pollution.
    """
    import click.shell_completion

    native = {
        'bash': click.shell_completion.BashComplete,
        'zsh': click.shell_completion.ZshComplete,
        'fish': click.shell_completion.FishComplete,
    }
    cls = native.get(shell)
    if cls is not None:
        return cls
    # Shells Click does not define natively (e.g. powershell/pwsh): fall back to
    # whatever is registered.
    return click.shell_completion.get_completion_class(shell)


def complete_to_string(shell: str, spec) -> str:
    """Render completions for `shell` by reusing Click's formatter, but
    resolving against the static spec instead of the live app."""
    import click

    base = _completion_class(shell)
    if base is None:
        return 'file,\n'  # unknown shell: best-effort, let the shell default-complete

    class _Fast(base):  # type: ignore[misc, valid-type]
        def get_completions(self, args, incomplete):
            return resolve(spec, args, incomplete)

    comp = _Fast(click.Command('rbx'), {}, 'rbx', '_RBX_COMPLETE')
    return comp.complete()


def source_to_string(shell: str) -> str:
    """Render the shell completion install script (the `source_<shell>` instruction)."""
    import click

    base = _completion_class(shell)
    if base is None:
        return ''
    comp = base(click.Command('rbx'), {}, 'rbx', '_RBX_COMPLETE')
    return comp.source()


def resolve(
    spec: Dict[str, Any], args: List[str], incomplete: str
) -> List[CompletionItem]:
    try:
        node, command, option_values, pending, positional = _walk(spec, list(args))
        ctx = CompletionContext(
            args=list(args),
            command=tuple(command),
            option_values=option_values,
            package_root=context.find_package_root(),
        )
        if pending is not None:
            return _value_items(pending['value'], ctx, incomplete)
        if incomplete.startswith('-'):
            out: List[CompletionItem] = []
            for p in node['params']:
                if p['kind'] != 'option':
                    continue
                out += [
                    CompletionItem(n, help=p.get('help'))
                    for n in p['names']
                    if n.startswith(incomplete)
                ]
            return out
        if node.get('is_group'):
            return [
                CompletionItem(c['name'], help=c.get('help'))
                for c in node['children']
                if c['name'].startswith(incomplete)
            ]
        arguments = [p for p in node['params'] if p['kind'] == 'argument']
        if positional < len(arguments):
            return _value_items(arguments[positional]['value'], ctx, incomplete)
        return FILE
    except Exception:
        return FILE
