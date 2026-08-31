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
from typing import Annotated, Any, Dict, List, NamedTuple, Optional

import rich.markup
import typer

from rbx import annotations, console
from rbx.box import fields, package
from rbx.box.statements import latex_jinja

app = typer.Typer(cls=annotations.AliasGroup)

# What separates a group name from the expression it is to be rendered against,
# on a line of `--render` stdin. A tab rather than a colon or a space because a
# group name cannot hold one (`fields.NameField` allows only word characters and
# dashes) and neither can any expression a scanner extracts, so the split is
# unambiguous without quoting. A line with no tab is a root expression, which is
# what keeps the pre-group protocol a strict subset of this one.
GROUP_SEPARATOR = '\t'


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
    groups: Annotated[
        bool,
        typer.Option(
            '--groups',
            help='Also show the resolved vars of each testcase group. '
            'Ignored with --render, which takes the group per expression.',
        ),
    ] = False,
    target: Annotated[
        latex_jinja.FilterTarget,
        typer.Option(
            '--target',
            help='What the --render expressions are being formatted for. '
            'Ignored without --render.',
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
        typer.echo(_render_from_stdin(target))
        return
    group_vars = _group_vars() if groups else None
    if json_output:
        typer.echo(_dump_json(expanded, group_vars))
        return
    _print_vars(expanded)
    for group_name, vars in (group_vars or {}).items():
        console.console.print(
            f'[status]groups.{rich.markup.escape(group_name)}[/status]'
        )
        _print_vars(vars, indent='  ')


def _print_vars(vars: fields.Vars, indent: str = '') -> None:
    for name, value in sorted(vars.items()):
        # Both halves are setter-controlled YAML rendered as markup, so a var
        # named or valued with brackets would otherwise style the output or
        # blow up with a MarkupError.
        escaped_name = rich.markup.escape(name)
        escaped_value = rich.markup.escape(str(value))
        console.console.print(f'{indent}[item]{escaped_name}[/item] = {escaped_value}')


def _declared_group_names() -> List[str]:
    """The names of the package's top-level testcase groups, in declared order.

    Only top-level groups can carry `vars` (a subgroup name never reaches the
    validator), so this is the whole set a group reference can name.
    """
    return [group.name for group in package.find_problem_package_or_die().testcases]


def _group_vars() -> Dict[str, fields.Vars]:
    """Each group's *resolved* var set: the package vars with its overrides on top.

    Resolved rather than raw, for the reason `statements.context.GroupView`
    spells out: a subtasks table reads the same name for every group, and a
    group that overrides nothing would otherwise answer nothing at all.
    """
    return {
        name: package.get_expanded_vars_for_group(name)
        for name in _declared_group_names()
    }


def _vars_for_group(group: str) -> Optional[fields.Vars]:
    """The resolved set of `group`, or `None` if no such group is declared.

    The existence check is not a formality. `Package.expanded_vars_for_group`
    falls back to the *package* vars for a name it does not know -- the right
    answer for a sample or a unit test, and exactly the wrong one here: a
    statement still naming a group that has since been renamed would badge the
    package value under the old name, confidently and wrongly. D5 asks for an
    absent badge instead.
    """
    if group not in _declared_group_names():
        return None
    return package.get_expanded_vars_for_group(group)


class _Line(NamedTuple):
    """One line of `--render` stdin, split into the parts it names.

    `raw` is kept because it is the key the caller gets its answer back under:
    the consumer holds the line it sent, not a re-derived spelling of it.
    """

    raw: str
    group: Optional[str]
    expression: str


def _read_expressions() -> List[_Line]:
    """Read the expressions to render off stdin, one per line.

    Stdin rather than a repeatable flag: `|` is a quoting trap in every shell,
    and a statement with two dozen filtered references should cost one spawn.
    Blank lines are dropped and the order of first appearance is kept, so a
    bound repeated across a statement is rendered once and keyed once.

    Reading from a terminal blocks until EOF, which is the usual bargain for a
    filter (`cat`, `jq`); a human poking at it by hand ends the list with
    Ctrl-D.

    A line may name the testcase group to resolve against, ahead of a tab:
    `sub1\\tAB.max`. Without one it is a package-level expression, which is what
    every line was before groups were addressable. Deduplication is on the whole
    line, so the same expression against two groups is two requests -- they are
    two different questions with two different answers.
    """
    seen: Dict[str, _Line] = {}
    for raw in sys.stdin.read().splitlines():
        line = raw.strip()
        if not line:
            continue
        group, separator, expression = line.partition(GROUP_SEPARATOR)
        parsed = (
            _Line(line, group.strip(), expression.strip())
            if separator
            else _Line(line, None, line)
        )
        # A line whose expression half is empty (`sub1\t`) names nothing to
        # render, and passing it on would only cost a Jinja error per keystroke
        # of a half-typed reference.
        if parsed.expression:
            seen.setdefault(line, parsed)
    return list(seen.values())


def _render_from_stdin(target: latex_jinja.FilterTarget) -> str:
    """Render each expression read from stdin, dropping the ones that fail.

    An expression that does not render -- an unknown filter, a bad argument, a
    name that is not there -- is simply absent from the map, and the command
    still exits 0. The consumer draws no badge for what it does not get back,
    which is always a safe answer; a non-zero exit is reserved for a package
    that could not be read at all, and would cost every other badge too.
    """
    # The statement's own environment, minus the file loader: the badge is only
    # worth showing if it agrees with the statement, and the way to guarantee
    # that is to build it with the statement's factory rather than a lookalike.
    # Not sandboxed, exactly like the statement one -- an expression can reach
    # whatever the namespace exposes. That is not a new boundary: anyone who can
    # pipe expressions in can already run arbitrary Python through a
    # ``py`...``` var in `problem.rbx.yml`, which this command expands before it
    # renders anything.
    env = latex_jinja.make_jinja_env(target, syntax=latex_jinja.JinjaSyntax.LATEX)
    # Half of `statements/context._lift`: the vars wrapper bound both under
    # `vars` and lifted to the top level, because `\VAR{N.max}` is shorthand for
    # `\VAR{vars.N.max}` and the scanner may send either spelling. The other
    # half -- the `lang`/`languages`/`params`/`contest`/`problem` names that
    # `problem_jinja_kwargs` lifts alongside it -- is out of reach here: those
    # come from a resolved statement, which this command deliberately does not
    # load. So `problem.title` and `params.foo` render to nothing and are
    # dropped. That gap cannot reach a badge: the extension's scanner rejects a
    # `problem.`/`contest.`/`p.`-prefixed expression, and every loop-bound `g.`
    # one, before it is ever sent. A *group* reference does reach here, but it
    # arrives already split: the group rides on the line and the expression is
    # the same plain dotted name a root reference sends.
    #
    # One namespace per group named on stdin, built on first mention: a
    # statement usually names two or three groups and the expansion behind each
    # is cached anyway, so building them all up front would only pay for the
    # ones no expression asks about.
    namespaces: Dict[Optional[str], Optional[Dict[str, Any]]] = {}

    def namespace_for(group: Optional[str]) -> Optional[Dict[str, Any]]:
        if group not in namespaces:
            namespaces[group] = _make_namespace(group)
        return namespaces[group]

    rendered: Dict[str, str] = {}
    for line in _read_expressions():
        namespace = namespace_for(line.group)
        if namespace is None:
            # Said out loud for the same reason a failed render is: from the
            # consumer's side a renamed group and a mistyped filter are both
            # just a badge that never appears.
            console.stderr_console.print(
                f'[warning]Could not render[/warning] '
                f'{rich.markup.escape(line.expression)}[warning]: no testcase '
                f'group named[/warning] {rich.markup.escape(str(line.group))}[warning].[/warning]'
            )
            continue
        try:
            # Wrapped in `\VAR{...}` rather than `{{ ... }}` because an rbxTeX
            # statement holds it that way. This is not universal -- a Markdown
            # statement renders under `JinjaSyntax.PLAIN`, so `--target markdown`
            # lexes with delimiters that statement does not use -- but the two
            # lexers differ only in where the expression ends, and Jinja balances
            # brackets before honouring an end delimiter, so an expression that
            # closes its own brackets (every expression a scanner can extract)
            # lexes identically either way.
            # Keyed by the *raw line*, group prefix and all, because that is
            # what the caller sent and what it will look the answer up under.
            rendered[line.raw] = env.from_string(f'\\VAR{{{line.expression}}}').render(
                **namespace
            )
        except Exception as err:
            # stdout is the JSON map, so stderr is free: name the expression and
            # the error. Without this a bug inside a filter is indistinguishable
            # from a typo in the expression -- both are just a badge that never
            # appears -- and neither leaves a trace to diagnose.
            console.stderr_console.print(
                f'[warning]Could not render[/warning] '
                f'{rich.markup.escape(line.raw)}[warning]:[/warning] '
                f'{type(err).__name__}: {rich.markup.escape(str(err))}'
            )
            continue
    # `ensure_ascii=False` so `10⁵` crosses as itself; the consumer reads UTF-8.
    return json.dumps(rendered, ensure_ascii=False)


def _make_namespace(group: Optional[str]) -> Optional[Dict[str, Any]]:
    """The template namespace an expression for `group` renders against.

    Half of `statements/context._lift`: the vars wrapper bound both under
    `vars` and lifted to the top level, because `\\VAR{N.max}` is shorthand for
    `\\VAR{vars.N.max}` and the scanner may send either spelling -- and the same
    holds inside a group, where `problem.groups.sub1.AB.max` and
    `problem.groups.sub1.vars.AB.max` are one reference.

    `None` for a group the package does not declare, which the caller reports.
    """
    vars = (
        package.find_problem_package_or_die().expanded_vars
        if group is None
        else _vars_for_group(group)
    )
    if vars is None:
        return None
    wrapper = latex_jinja.JinjaDictWrapper.from_dict(
        dict(vars), wrapper_key='vars' if group is None else f'groups.{group}.vars'
    )
    return {**wrapper, 'vars': wrapper}


def _dump_json(
    expanded: fields.Vars, groups: Optional[Dict[str, fields.Vars]] = None
) -> str:
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

    With `groups`, the flat map is nested one level down instead, under `vars`,
    beside a `groups` map of the same shape per testcase group. A separate shape
    behind an opt-in flag rather than an extra key on the flat map, so that an
    rbx too old to know about groups *fails* on the flag instead of answering
    the root vars to a caller that would read the silence as "this package has
    no groups".
    """
    offenders = sorted(
        _offenders(expanded)
        + [
            f'groups.{group}.{name}'
            for group, vars in (groups or {}).items()
            for name in _offenders(vars)
        ]
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
    if groups is None:
        return json.dumps(_stringify(expanded))
    return json.dumps(
        {
            'vars': _stringify(expanded),
            'groups': {group: _stringify(vars) for group, vars in groups.items()},
        }
    )


def _offenders(vars: fields.Vars) -> List[str]:
    return sorted(
        name
        for name, value in vars.items()
        if isinstance(value, float) and not math.isfinite(value)
    )


def _stringify(vars: fields.Vars) -> Dict[str, str]:
    return {name: str(value) for name, value in vars.items()}
