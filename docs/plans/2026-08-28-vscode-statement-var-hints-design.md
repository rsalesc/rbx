# VS Code: show expanded vars inline in statements (#797)

A constraints block is the densest use of vars in the whole package:

```latex
\begin{itemize}
  \item $1 \le N \le \VAR{N.max}$
  \item $1 \le a_i \le \VAR{A.max}$
\end{itemize}
```

Reading that file, a setter cannot see the one thing that matters -- the
numbers. `N.max` may be a literal, may be `` py`10**5` ``, may be derived from
another var. Answering "what does this actually say?" means leaving the editor
for `problem.rbx.yml`, and then mentally re-running the expansion.

This design puts the value beside the reference, as an inlay hint.

## D1. The badge shows the value, and nothing else

Scope of v1, in the order the alternatives were rejected:

**Values, not constraint provenance.** A badge could also carry what validation
learned about the var -- `min_hit`/`max_hit` coverage from `validation[].bounds`,
or the range the validator truly enforces. The latter does not exist yet:
`validators.py:75` reads testlib's overview log and *skips* the
`constant-bounds` lines, which are the only place the real `readInt(lo, hi)`
numbers appear. Both are worth surfacing one day; neither is what makes a
statement file unreadable today.

**Root scope only.** `\VAR{N.max}` and `\VAR{vars.N.max}` resolve against the
package var set and have exactly one value. `\VAR{g.N.max}` does not: it almost
always sits inside a `\BLOCK{for ...}` loop, so one source line renders a
different value per group. Showing a list, a range, or a group-labelled value
all trade the badge's terseness for a case the constraints block does not have.
Group, `problem`/`p.`, and `contest.` scopes get no badge at all -- an absent
badge is never wrong.

**Raw value, even under a filter.** `\VAR{N.max | sci}` renders `10^{5}`, via
`scientific_notation` (`latex_jinja.py:107`) and its several non-obvious
retreats: it declines to abbreviate `100007`, declines `532`, and switches
between `10^{5}` and `2 \times 10^{5}`. Porting that to TypeScript duplicates
logic that can drift, to produce LaTeX source rather than a number. The filter
decides typesetting; the badge answers "what number is this?", so it shows
`100000` regardless of the pipeline.

## D2. The value comes from rbx, not from an artifact

Var values cannot be computed by the extension. A value may be
`` py`<expr>` ``, evaluated by `rbx.box.safeeval` against the other vars in a
fixpoint loop (`fields.py:180`). Nested blocks flatten to dotted keys. A reader
that re-implements this is a second, diverging expander.

`build/testset.yml` carries expanded vars already, but only per group, and says
so itself:

> The vars the group was actually validated against -- package vars with the
> group's overrides already merged and expanded. A reader cannot redo this
> merge, since expansion re-evaluates interpolated vars.

There is no package-level var set in the manifest. Adding one is five lines,
and was rejected on freshness rather than effort: the badge would then exist
only after a build, and after an edit to `problem.rbx.yml` it would show the
*previous* build's number until the next build. A silently stale value is worse
than no value for a feature whose entire job is showing the right one --
especially since the moment a setter most wants the badge is the moment they
are changing the var. Gating badges on manifest mtime avoids the lie but
removes the badge exactly then.

So: a new command, `rbx vars`, dumping the expanded package vars, spawned by
the extension.

### Why this may spawn rbx when the extension otherwise must not

The testset-view design states the rule: the extension is a pure reader, it
never spawns rbx, "because every rbx invocation has side effects on the package
cache and could race a run already in flight".

That rule is about side effects, and `rbx vars` has none. It needs
`find_problem_package_or_die` (`package.py:77`), which reaches
`find_problem_package` -- `load_yaml_model` on the file, nothing more -- and
`Package.expanded_vars` (`schema.py:1407`), which is pure computation over that
model. Nothing on the path calls `get_problem_cache_dir` (`package.py:145`, the
function that does the `mkdir` and holds the fingerprint), takes a file lock, or
writes anything. `within_problem` only changes directory and sets an issue
level.

This is a property to keep, not merely to observe, so it is a test: running
`rbx vars` in a package with no `.box/` leaves it with no `.box/`.

`rbx visualize` is the extension's existing precedent for spawning at all
(`visualize.ts:19`), and brings the discovery path this feature reuses.

## D3. Components

Python, one new lazy command:

| piece | where |
| --- | --- |
| `rbx vars [--json]` | new module under `rbx/box/cli/commands/` |
| `ENTRIES` row | `rbx/box/cli/__init__.py`, mirroring `help=`/`rich_help_panel=`/`hidden=` |

The `ENTRIES` row is not optional bookkeeping -- `tests/rbx/box/lazy_cli_test.py`
pins the table against the modules, and `--help` renders from the table without
importing the module. Output is the flat dotted-key map,
`{"N.max": 100000, "A.max": 1000000000}`, i.e. `Package.expanded_vars` verbatim.

Extension, following the pure/impure split every `src/rbx/*.ts` module already
observes:

| piece | where | kind |
| --- | --- | --- |
| ref scanner | `src/rbx/statementVars.ts` + `.test.ts` | pure, `node --test` |
| vars cache | alongside `ArtifactStore` | impure |
| hint provider | new host file | impure |

The scanner takes document text and a var map and returns `{offset, text}`. It
finds `\VAR{...}` occurrences, and accepts an expression only when it is a plain
dotted name, optionally `vars.`-prefixed, optionally followed by a filter
pipeline it ignores. Anything else -- a `g.`/`p.`/`problem.`/`contest.`/`groups.`
prefix, arithmetic, a call, a conditional -- yields no hint. A name absent from
the map also yields no hint, which incidentally makes a typo visible as the one
reference on the line that has no badge.

The provider is an `InlayHintsProvider`: a native affordance, so it obeys the
user's editor-wide inlay setting and toggle. It is gated twice -- on a new
`rbx.statementVarHints` boolean in `contributes.configuration`, and on
`declared.assetFor(uri)?.role === 'statement'`, since the manifest is the
authority on which files are statements (and covers `tutorials` too) in a way
globbing `*.rbx.tex` is not.

The vars cache memoizes per package root, resolves the binary through
`rbx/executable.ts` (setting, then `PATH`, then a login-shell probe, validated
by `--version`, cached per root), and is invalidated by the **existing**
`**/problem.rbx.yml` watcher and its 200 ms debounce. The spawn is therefore
paid on save, not on keystroke.

## D4. Data flow

```
problem.rbx.yml saved
  -> existing watcher, 200 ms debounce
  -> vars cache invalidated for that root
  -> onDidChangeInlayHints fires
  -> VS Code re-requests hints for visible statement editors
  -> provider reads cached vars (spawning rbx vars once if cold)
  -> scanner maps refs to values
  -> hints render after each \VAR{...}
```

## D5. Every failure is an absent badge

There is no error surface. A missing rbx binary, a non-zero exit (invalid YAML,
or the var cycle `expand_vars` detects), unparseable JSON, and an unknown var
name all resolve to "no hint". The feature is a reading aid; a wrong number
defeats it, and a diagnostic for it would duplicate what `rbx build` already
reports properly.

## D6. Testing

`statementVars.test.ts` covers the scanner: shorthand and long form, a filter
pipeline, several refs on one line, the `%#` comment prefix, an escaped `\\VAR`,
each rejected scope prefix, and an unknown name.

Python covers the command's contract: the JSON shape and dotted-key flattening
over a `pkg_from_testdata` package, and the no-side-effect property from D2.

## Not in v1

Markdown statements (`rbxmd` uses `{{ }}`, a different delimiter set), group and
contest scopes, and validation-derived constraint info. `rbx vars` is shaped so
that each is an extension of the same path rather than a redesign: a group flag
serves group scope, and the scanner's rejected-prefix list is where the others
would be admitted.
