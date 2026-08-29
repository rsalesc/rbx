"""`rbx vars`.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.

This command is deliberately read-only: it loads `problem.rbx.yml` and
expands its vars, and touches nothing else. The VS Code extension spawns it
while the user edits, so anything that creates or locks the package cache
would make it unsafe to call. `--render` holds to the same bargain: it renders
expressions in-process through the statement Jinja environment, and builds no
statement. See
`docs/plans/2026-08-28-vscode-statement-var-hints-design.md`.
"""

import json
import math
import sys
from typing import Annotated, Dict, List

import jinja2
import rich.markup
import typer

from rbx import annotations, console
from rbx.box import fields, package
from rbx.box.statements import latex_jinja

app = typer.Typer(cls=annotations.AliasGroup)


@app.command(
    'vars',
    rich_help_panel='Configuration',
    help='Show the expanded vars of this problem.',
)
@package.within_problem
def vars_command(
    json_output: Annotated[
        bool,
        typer.Option(
            '--json',
            help='Print the vars as a JSON object of dotted keys and string values.',
        ),
    ] = False,
    render: Annotated[
        bool,
        typer.Option(
            '--render',
            help='Read statement expressions from stdin, one per line, and print '
            'a JSON object mapping each to what it renders to.',
        ),
    ] = False,
    target: Annotated[
        latex_jinja.FilterTarget,
        typer.Option(
            '--target',
            help='What the rendered expressions are being formatted for.',
        ),
        # TEXT, because the only caller is the VS Code inlay hint, which cannot
        # typeset maths. A caller that wants the statement's own spelling asks
        # for it; one that forgets gets the answer that is at least readable.
    ] = latex_jinja.FilterTarget.TEXT,
):
    if render and json_output:
        # They name two different output shapes over the same stdout. Letting
        # one win silently would hand the caller a map it did not ask for.
        console.console.print(
            '[error]--render and --json cannot be used together.[/error]'
        )
        raise typer.Exit(1)

    expanded = package.find_problem_package_or_die().expanded_vars
    if render:
        typer.echo(_render_from_stdin(expanded, target))
        return
    if json_output:
        typer.echo(_dump_json(expanded))
        return
    for name, value in sorted(expanded.items()):
        # Both halves are setter-controlled YAML rendered as markup, so a var
        # named or valued with brackets would otherwise style the output or
        # blow up with a MarkupError.
        escaped_name = rich.markup.escape(name)
        escaped_value = rich.markup.escape(str(value))
        console.console.print(f'[item]{escaped_name}[/item] = {escaped_value}')


def _read_expressions() -> List[str]:
    """Read the expressions to render off stdin, one per line.

    Stdin rather than a repeatable flag: `|` is a quoting trap in every shell,
    and a statement with two dozen filtered references should cost one spawn.
    Blank lines are dropped and the order of first appearance is kept, so a
    bound repeated across a statement is rendered once and keyed once.

    Reading from a terminal blocks until EOF, which is the usual bargain for a
    filter (`cat`, `jq`); a human poking at it by hand ends the list with
    Ctrl-D.
    """
    seen: Dict[str, None] = {}
    for line in sys.stdin.read().splitlines():
        expression = line.strip()
        if expression:
            seen.setdefault(expression, None)
    return list(seen)


def _render_environment(target: latex_jinja.FilterTarget) -> jinja2.Environment:
    """The environment a statement renders under, minus the file loader.

    Same delimiters, same strict undefined, same filters -- the badge is only
    worth showing if it agrees with the statement, and the way to guarantee
    that is to render under the same environment rather than a lookalike.

    This environment is **not** sandboxed, exactly like the statement one: an
    expression can reach whatever the namespace exposes. That is not a new
    boundary. Anyone who can pipe expressions in can already run arbitrary
    Python through a ``py`...``` var in `problem.rbx.yml`, which this command
    expands before it renders anything.
    """
    env = jinja2.Environment(
        **latex_jinja.J2_ARGS,  # type: ignore[arg-type]
        undefined=latex_jinja.StrictChainableUndefined,
    )
    latex_jinja.add_builtin_filters(env, target=target)
    latex_jinja.add_builtin_tests(env)
    return env


def _render_from_stdin(expanded: fields.Vars, target: latex_jinja.FilterTarget) -> str:
    """Render each expression read from stdin, dropping the ones that fail.

    An expression that does not render -- an unknown filter, a bad argument, a
    name that is not there -- is simply absent from the map, and the command
    still exits 0. The consumer draws no badge for what it does not get back,
    which is always a safe answer; a non-zero exit is reserved for a package
    that could not be read at all, and would cost every other badge too.
    """
    env = _render_environment(target)
    # `\VAR{N.max}` is shorthand for `\VAR{vars.N.max}` (see
    # `statements/context._lift`), and the scanner may send either spelling.
    wrapper = latex_jinja.JinjaDictWrapper.from_dict(dict(expanded), wrapper_key='vars')
    namespace = {**wrapper, 'vars': wrapper}

    rendered: Dict[str, str] = {}
    for expression in _read_expressions():
        try:
            # Wrapped in the statement's own `\VAR{...}`, not `{{ ... }}`: an
            # expression is only worth a badge if a statement could hold it, so
            # it is lexed by the delimiters a statement is lexed by.
            rendered[expression] = env.from_string(f'\\VAR{{{expression}}}').render(
                **namespace
            )
        except Exception:
            continue
    # `ensure_ascii=False` so `10⁵` crosses as itself; the consumer reads UTF-8.
    return json.dumps(rendered, ensure_ascii=False)


def _dump_json(expanded: fields.Vars) -> str:
    """Serialize the vars as a flat map of dotted name to *display string*.

    Every value crosses as a JSON string holding the text the statement would
    show, never as a JSON number. The only consumer -- the VS Code extension --
    wants display text and never does arithmetic on these, and a JSON number
    cannot carry the text losslessly: `JSON.parse` produces IEEE doubles, so
    `10**18 + 7` (a plausible bound) would come back as `1000000000000000000`
    and the extension would badge a *wrong* value with full confidence, and
    `10**21` would come back spelled `1e+21`. Rendering here is exact for
    arbitrarily large ints and keeps float formatting out of the boundary.

    `str` is the right renderer because it is what Jinja itself calls on a
    value with no filter, so the badge shows exactly what an unfiltered
    `\\VAR{...}` will (a filtered one renders differently by design -- the
    badge answers "what number is this?", not "what will this typeset as"):
    an `int` becomes its full decimal expansion, a `str` itself, a `float` its
    `repr`, and a `bool` `True`/`False`. Note that last one is deliberately
    *not* the `1`/`0` of `fields.render_var_on_command_line`: that spelling
    exists for testlib/jngen argument parsing, not for statement display.
    """
    offenders = sorted(
        name
        for name, value in expanded.items()
        if isinstance(value, float) and not math.isfinite(value)
    )
    if offenders:
        # `str(float('inf'))` is a perfectly good JSON string, so this no longer
        # has to be rejected -- but an infinite bound is a package bug, and the
        # consumer degrades cleanly on a non-zero exit, so keep surfacing it.
        detail = (
            f'{offenders[0]} has a non-finite value'
            if len(offenders) == 1
            else f'{", ".join(offenders)} have non-finite values'
        )
        console.console.print(
            f'[error]Cannot serialize the vars of this problem to JSON: '
            f'{rich.markup.escape(detail)}.[/error]'
        )
        raise typer.Exit(1)
    return json.dumps({name: str(value) for name, value in expanded.items()})
