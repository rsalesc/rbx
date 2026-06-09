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
