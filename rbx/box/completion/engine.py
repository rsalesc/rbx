"""Static-spec completion resolver. Light imports only -- never the heavy app."""

import os
from typing import Any, Dict, List, Optional, Set, Tuple

from click.shell_completion import CompletionItem

from rbx.box.completion import context
from rbx.box.completion.registry import CompletionContext, load_completer

FILE = [CompletionItem('', type='file')]
DIR = [CompletionItem('', type='dir')]


def _match_names(raw_name: str) -> List[str]:
    # AliasGroup splits the registered name on the regex `', ?'`; for the canonical
    # `'a, b'` spelling, `split(',') + strip()` is equivalent (and also tolerates a
    # bare `','` separator), so descent stays faithful to AliasGroup resolution.
    return [s.strip() for s in raw_name.split(',')]


def _first_match(names: List[str], incomplete: str) -> Optional[str]:
    """The first name (in declaration order) that the cursor could be completing.

    This is how we collapse aliases to a SINGLE candidate per command/option: for
    a broad prefix (`''`, `-`, `--`) it returns the canonical first-declared name
    (the full `build` / `--verification-level` form); for a prefix typed toward a
    specific alias or `--no-` form it returns that exact spelling (so `pkg`, `-v`,
    `--no-check` still complete). Returns None when no alias matches.
    """
    return next((n for n in names if n.startswith(incomplete)), None)


def _command_name_items(node: Dict[str, Any], incomplete: str) -> List[CompletionItem]:
    """Completions for a subcommand position.

    Each command contributes ONE candidate (not one per alias): the first of its
    names that matches the incomplete (`_first_match`). So `rbx <tab>` lists the
    canonical names only (`build`, `package`, …) instead of every alias
    (`build b package pkg …`), while `pkg<tab>` still completes the `pkg` alias.
    This is a deliberate divergence from Typer (which offers the raw
    ``'name, alias'`` string); aliases sharing a representative are deduped in
    registration order, matching how AliasGroup resolves an ambiguous prefix.
    """
    out: List[CompletionItem] = []
    seen: Set[str] = set()
    for child in node.get('children', []):
        name = _first_match(_match_names(child['name']), incomplete)
        if name is not None and name not in seen:
            seen.add(name)
            out.append(CompletionItem(name, help=child.get('help')))
    return out


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
) -> Tuple[Dict[str, Any], list, dict, Optional[Dict[str, Any]], int, Set[str]]:
    node = spec
    command: list = []
    option_values: dict = {}
    pending: Optional[Dict[str, Any]] = None
    positional = 0
    no_more_opts = False
    # Canonical names of every option already supplied. Click does not re-offer a
    # non-`multiple` option that was already given, so we mirror that filtering.
    seen_options: Set[str] = set()
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
            if opt is not None:
                # Record by canonical id for BOTH flags and value-taking options:
                # `_find_option` matches any alias (and strips `=val`), so keying on
                # `names[0]` identifies the option regardless of which alias was typed.
                seen_options.add(opt['names'][0])
                if opt['takes_value']:
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
    return node, command, option_values, pending, positional, seen_options


def _value_items(
    value: Dict[str, Any], ctx: CompletionContext, incomplete: str
) -> List[CompletionItem]:
    kind = value.get('kind')
    if kind == 'choice':
        return [CompletionItem(c) for c in value['choices'] if c.startswith(incomplete)]
    if kind == 'completer':
        # Prefix-filter the dynamic candidates by the incomplete, exactly like
        # Click/Typer do. The shell scripts add these with `-U` (no re-filtering),
        # so without this, typing a prefix would offer everything and reset the
        # word instead of narrowing. Filtering here keeps every shell consistent.
        items = [
            item
            for item in load_completer(value['completer'])(ctx, incomplete)
            if item.value.startswith(incomplete)
        ]
        # A file-union completer hands off to the shell's default file completion
        # AFTER its dynamic candidates (e.g. `rbx run` solutions + arbitrary paths).
        # The directive is appended unfiltered -- the shell matches files itself.
        if value.get('file'):
            items = items + FILE
        return items
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


# Custom zsh completion function. Two deliberate departures from Click's native
# template (issue #575):
#   1. The file/dir handoff (`_path_files`) is deferred until AFTER the dynamic
#      candidates are added, so in a file-union position (e.g. `rbx run`) the
#      solutions/`@`-prefixes rank ahead of the directory listing.
#   2. Described candidates are added via `compadd -d` (parallel display array)
#      instead of `_describe`, which re-sorts items that share a description
#      (e.g. several "ACCEPTED" solutions) alphabetically -- that reordering is
#      what pushed `@boca` ahead of `@main`. `compadd -V` preserves the engine's
#      insertion order (`@main`, then solutions, then `@boca`).
# Placeholders match Click's `.source()` (`prog_name`, `complete_func`, `complete_var`).
_ZSH_SOURCE_TEMPLATE = """#compdef %(prog_name)s

%(complete_func)s() {
    local -a completions
    local -a desc_values desc_displays
    local -a response
    local want_files want_dirs
    (( ! $+commands[%(prog_name)s] )) && return 1

    response=("${(@f)$(env COMP_WORDS="${words[*]}" COMP_CWORD=$((CURRENT-1)) %(complete_var)s=zsh_complete %(prog_name)s)}")

    for type key descr in ${response}; do
        if [[ "$type" == "plain" ]]; then
            if [[ "$descr" == "_" ]]; then
                completions+=("$key")
            else
                desc_values+=("$key")
                desc_displays+=("$key -- $descr")
            fi
        elif [[ "$type" == "dir" ]]; then
            want_dirs=1
        elif [[ "$type" == "file" ]]; then
            want_files=1
        fi
    done

    # Add dynamic candidates (preserving insertion order) BEFORE the file handoff.
    if [ -n "$desc_values" ]; then
        compadd -U -V unsorted -l -d desc_displays -a desc_values
    fi
    if [ -n "$completions" ]; then
        compadd -U -V unsorted -a completions
    fi
    [[ -n "$want_dirs" ]] && _path_files -/
    [[ -n "$want_files" ]] && _path_files -f
}

if [[ $zsh_eval_context[-1] == loadautofunc ]]; then
    # autoload from fpath, call function directly
    %(complete_func)s "$@"
else
    # eval/source/. command, register function for later
    compdef %(complete_func)s %(prog_name)s
fi
"""


def source_to_string(shell: str) -> str:
    """Render the shell completion install script (the `source_<shell>` instruction)."""
    import click

    base = _completion_class(shell)
    if base is None:
        return ''
    comp = base(click.Command('rbx'), {}, 'rbx', '_RBX_COMPLETE')
    if shell == 'zsh':
        # Use our reordered template (solutions before file completion); everything
        # else is Click's native source.
        comp.source_template = _ZSH_SOURCE_TEMPLATE
    return comp.source()


def resolve(
    spec: Dict[str, Any], args: List[str], incomplete: str
) -> List[CompletionItem]:
    try:
        node, command, option_values, pending, positional, seen_options = _walk(
            spec, list(args)
        )
        ctx = CompletionContext(
            args=list(args),
            command=tuple(command),
            option_values=option_values,
            package_root=context.find_package_root(),
        )
        if pending is not None:
            return _value_items(pending['value'], ctx, incomplete)
        if incomplete.startswith('-') and '=' in incomplete:
            # Click special-cases `--opt=partial`: complete the option's VALUE, not
            # an option name. The value to complete is the part AFTER `=`.
            name, _, partial = incomplete.partition('=')
            opt = _find_option(node, name)
            if opt is not None and opt['takes_value']:
                return _value_items(opt['value'], ctx, partial)
        if incomplete.startswith('-'):
            out: List[CompletionItem] = []
            for p in node['params']:
                if p['kind'] != 'option':
                    continue
                # Click does not re-offer a non-`multiple` option already supplied.
                if not p.get('multiple', False) and p['names'][0] in seen_options:
                    continue
                # ONE candidate per option (not one per alias): the first matching
                # name. `-` shows the canonical `--verification-level`; `-v` still
                # completes `-v`; `--no-check` still completes when typed toward.
                name = _first_match(p['names'], incomplete)
                if name is not None:
                    out.append(CompletionItem(name, help=p.get('help')))
            return out
        if node.get('is_group'):
            return _command_name_items(node, incomplete)
        arguments = [p for p in node['params'] if p['kind'] == 'argument']
        if positional < len(arguments):
            return _value_items(arguments[positional]['value'], ctx, incomplete)
        if arguments and arguments[-1].get('variadic'):
            # A variadic last argument keeps consuming positionals, so the real CLI
            # re-offers its completer at every position past it.
            return _value_items(arguments[-1]['value'], ctx, incomplete)
        return FILE
    except Exception:
        if os.environ.get('_RBX_COMPLETE_DEBUG'):
            raise
        return FILE
