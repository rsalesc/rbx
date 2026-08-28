# Inline statement var hints Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show the expanded value of a package var beside each `\VAR{...}` reference in a statement file, as a VS Code inlay hint.

**Architecture:** A new read-only `rbx vars --json` command dumps `Package.expanded_vars` as a flat dotted-key map. The VS Code extension spawns it once per package root, caches the result, invalidates on the existing `problem.rbx.yml` watcher, and an `InlayHintsProvider` renders values beside root-scope references. All decidable logic lives in `vscode`-free modules under `src/rbx/` with `node --test` coverage.

**Tech Stack:** Python 3 / Typer / Pydantic v2 / pytest on the rbx side; TypeScript / VS Code API / `node --test` on the extension side.

**Design:** `docs/plans/2026-08-28-vscode-statement-var-hints-design.md`. Read it before starting; it records why the badge shows only the raw value at problem-root scope.

---

## Background you need

**What a var is.** `problem.rbx.yml` has a `vars:` block of nested primitives. rbx flattens it to dotted keys and expands `` py`<expr>` `` values against the other vars:

```yaml
vars:
  N:
    max: "py`10**5`"
  A:
    max: 1000000000
```

becomes `{"N.max": 100000, "A.max": 1000000000}` via `Package.expanded_vars` (`rbx/box/schema.py:1406`).

**What a statement looks like.** rbxTeX is LaTeX-flavoured Jinja. `\VAR{...}` is an expression, `%#` a line comment (`rbx/box/statements/latex_jinja.py:23-33`). Both `\VAR{N.max}` and `\VAR{vars.N.max}` mean the same package var.

**Lazy CLI.** `rbx/box/cli/__init__.py` holds `ENTRIES`, a table of `LazyCommand` rows naming `'module:attr'`. A command's module is imported only when invoked. **A new command needs a row there**, carrying the same `help=`/`rich_help_panel=`/`hidden=` the module declares — `tests/rbx/box/lazy_cli_test.py::test_table_matches_what_the_target_declares` fails otherwise.

**Extension shape.** Every `src/rbx/*.ts` module is `vscode`-free and unit-tested; host files import `vscode` and are not. Run extension tests with `npm test` from `vscode/` (it builds to `out-test/` first).

---

## Task 1: `rbx vars --json` command

**Files:**
- Create: `rbx/box/cli/commands/vars_cmd.py`
- Modify: `rbx/box/cli/__init__.py` (add one `ENTRIES` row)
- Test: `tests/rbx/box/vars_cmd_test.py`

**Step 1: Look at the conventions you must match**

Read `rbx/box/cli/commands/config_cmds.py:1-30` — note the module docstring stating it is registered lazily, `app = typer.Typer(cls=annotations.AliasGroup)`, and the `@app.command(...)` decorator carrying `rich_help_panel` and `help`.

Read `rbx/box/cli/__init__.py:115` (the `header` row) as the shape to copy.

**Step 2: Write the failing test**

Test packages live in `rbx/testdata/`, and the marker takes the path under it —
`@pytest.mark.test_pkg('problems/interactive')`. That package's block is:

```yaml
vars:
  N:
    min: 1
    max: 1000000
```

so the expanded map is exactly `{'N.min': 1, 'N.max': 1000000}`.

Create `tests/rbx/box/vars_cmd_test.py`:

```python
import json
import pathlib

import pytest
from typer.testing import CliRunner

from rbx.box.cli import app

runner = CliRunner()


@pytest.mark.test_pkg('problems/interactive')
def test_vars_json_dumps_expanded_dotted_keys(pkg_from_testdata: pathlib.Path):
    result = runner.invoke(app, ['vars', '--json'])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {'N.min': 1, 'N.max': 1000000}


@pytest.mark.test_pkg('problems/interactive')
def test_vars_json_creates_no_cache_dir(pkg_from_testdata: pathlib.Path):
    """The extension spawns this while the user types; it must stay read-only.

    `get_problem_cache_dir` is what mkdirs the cache; nothing on the
    `rbx vars` path may reach it.
    """
    from rbx.box.package import get_problem_cache_path

    cache = get_problem_cache_path(pkg_from_testdata)
    assert not cache.exists()

    result = runner.invoke(app, ['vars', '--json'])

    assert result.exit_code == 0, result.output
    assert not cache.exists()
```

Note that `pkg_from_testdata` copies the package to a clean dir, `cd`s into it,
and calls `clear_all_functools_cache()` — which matters here, because both
`find_problem_package` and `get_expanded_vars_for_group` are `functools.cache`d.

**Step 3: Run the test to verify it fails**

```bash
uv run pytest tests/rbx/box/vars_cmd_test.py -v
```

Expected: FAIL — `rbx vars` is not a command yet, so the runner exits non-zero with a "No such command" style message.

**Step 4: Write the command**

Create `rbx/box/cli/commands/vars_cmd.py`:

```python
"""`rbx vars`.

Registered lazily from `rbx.box.cli.ENTRIES`, so this module is imported
only when one of its commands is invoked. A command added here needs a row
there too.

This command is deliberately read-only: it loads `problem.rbx.yml` and
expands its vars, and touches nothing else. The VS Code extension spawns it
while the user edits, so anything that creates or locks the package cache
would make it unsafe to call. See
`docs/plans/2026-08-28-vscode-statement-var-hints-design.md`.
"""

import json
from typing import Annotated

import typer

from rbx import annotations, console
from rbx.box import package

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
            help='Print the vars as a JSON object of dotted keys.',
        ),
    ] = False,
):
    expanded = package.find_problem_package_or_die().expanded_vars
    if json_output:
        typer.echo(json.dumps(expanded))
        return
    for name, value in sorted(expanded.items()):
        console.console.print(f'[item]{name}[/item] = {value}')
```

**Step 5: Add the `ENTRIES` row**

In `rbx/box/cli/__init__.py`, next to the `header` row:

```python
    LazyCommand(
        'vars',
        'rbx.box.cli.commands.vars_cmd:app',
        help='Show the expanded vars of this problem.',
        rich_help_panel='Configuration',
    ),
```

The `help=` string must match the module's `help=` **character for character**.

**Step 6: Run the tests**

```bash
uv run pytest tests/rbx/box/vars_cmd_test.py tests/rbx/box/lazy_cli_test.py -v
```

Expected: PASS. If `test_table_matches_what_the_target_declares[vars]` fails, the two `help=`/`rich_help_panel=` strings disagree.

**Step 7: Verify by hand**

```bash
cd rbx/testdata/problems/interactive && uv run rbx vars --json && ls -a | grep -c '^\.box$' || echo "no .box created"
```

Expected: a JSON object on stdout, and no `.box` directory.

**Step 8: Lint and commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/cli/commands/vars_cmd.py rbx/box/cli/__init__.py tests/rbx/box/vars_cmd_test.py
git commit -m "feat(cli): add rbx vars to dump the expanded package vars"
```

---

## Task 2: The pure reference scanner

**Files:**
- Create: `vscode/src/rbx/statementVars.ts`
- Test: `vscode/src/rbx/statementVars.test.ts`

**Step 1: Read the pattern you are copying**

`vscode/src/rbx/decoration.ts` + `decoration.test.ts` — a pure decide-function and its `node --test` suite. Yours has the same shape: data in, plain objects out, no `vscode` import.

**Step 2: Write the failing test**

Create `vscode/src/rbx/statementVars.test.ts`:

```typescript
import * as assert from 'assert';
import { test } from 'node:test';

import { scanStatementVars } from './statementVars';

const VARS = { 'N.max': 100000, 'A.max': 1000000000, flag: true, name: 'foo' };

const scan = (text: string) => scanStatementVars(text, VARS);

test('the shorthand and the long form both resolve', () => {
  assert.deepStrictEqual(scan('$N \\le \\VAR{N.max}$'), [
    { end: 20, text: '100000' },
  ]);
  assert.deepStrictEqual(
    scan('$N \\le \\VAR{vars.N.max}$').map((hint) => hint.text),
    ['100000'],
  );
});

test('a filter pipeline is ignored, the raw value is shown', () => {
  assert.deepStrictEqual(
    scan('\\VAR{N.max | sci}').map((hint) => hint.text),
    ['100000'],
  );
});

test('several references on one line each get a hint', () => {
  assert.deepStrictEqual(
    scan('$\\VAR{N.max}$ and $\\VAR{A.max}$').map((hint) => hint.text),
    ['100000', '1000000000'],
  );
});

test('non-root scopes are left alone', () => {
  for (const expression of [
    'g.N.max',
    'groups.g.vars.N.max',
    'p.N.max',
    'problem.N.max',
    'contest.year',
  ]) {
    assert.deepStrictEqual(scan(`\\VAR{${expression}}`), [], expression);
  }
});

test('expressions that are not a plain name are left alone', () => {
  for (const expression of ['N.max + 1', 'len(x)', "N.max if x else 'y'", '']) {
    assert.deepStrictEqual(scan(`\\VAR{${expression}}`), [], expression);
  }
});

test('an unknown name gets no hint, which is how a typo shows up', () => {
  assert.deepStrictEqual(scan('\\VAR{N.mx}'), []);
});

test('a commented line is skipped', () => {
  assert.deepStrictEqual(scan('%# $\\VAR{N.max}$'), []);
});

test('an escaped VAR is not a reference', () => {
  assert.deepStrictEqual(scan('\\\\VAR{N.max}'), []);
});

test('non-numeric values render as themselves', () => {
  assert.deepStrictEqual(
    scan('\\VAR{flag} \\VAR{name}').map((hint) => hint.text),
    ['true', 'foo'],
  );
});

test('the hint sits just after the closing brace', () => {
  const text = 'abc \\VAR{N.max} def';
  const [hint] = scan(text);
  assert.strictEqual(text[hint.end - 1], '}');
});
```

**Step 3: Run it to verify it fails**

```bash
cd vscode && npm test
```

Expected: FAIL — `Cannot find module './statementVars'`.

**Step 4: Write the implementation**

Create `vscode/src/rbx/statementVars.ts`:

```typescript
/**
 * Which `\VAR{...}` references in a statement get a value badge.
 *
 * Pure: no `vscode` import, so `node --test` covers it directly.
 *
 * Only *problem-root* references are badged -- `\VAR{N.max}` and
 * `\VAR{vars.N.max}`. A group reference (`\VAR{g.N.max}`) renders a different
 * value per loop iteration, so a single badge would have to lie or to name the
 * group; contest and problem scopes resolve against var sets this map does not
 * hold. Every one of those, and every expression that is not a plain dotted
 * name, yields no hint: an absent badge is never wrong.
 *
 * See docs/plans/2026-08-28-vscode-statement-var-hints-design.md (D1).
 */

/** A var value, as `rbx vars --json` emits it. */
export type VarValue = number | boolean | string;

/** The expanded package vars, keyed by dotted name. */
export type Vars = Readonly<Record<string, VarValue>>;

export interface VarHint {
  /** Offset just past the reference's closing brace. */
  readonly end: number;
  /** The value, rendered for display. */
  readonly text: string;
}

/** Scopes whose values this map does not hold. See the module comment. */
const FOREIGN_SCOPE = /^(vars\.)?(g|p|problem|contest|groups)\./;

/** A plain dotted name, with an optional filter pipeline we ignore. */
const REFERENCE = /^\s*([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)\s*(\|[^}]*)?$/;

const OCCURRENCE = /\\VAR\{([^}]*)\}/g;

function isCommented(text: string, offset: number): boolean {
  const lineStart = text.lastIndexOf('\n', offset - 1) + 1;
  return /^\s*%/.test(text.slice(lineStart, offset));
}

function isEscaped(text: string, offset: number): boolean {
  let backslashes = 0;
  for (let i = offset - 1; i >= 0 && text[i] === '\\'; i -= 1) {
    backslashes += 1;
  }
  // The match itself consumed one backslash, so an odd count before it means
  // the `\VAR` was written as a literal `\\VAR`.
  return backslashes % 2 === 1;
}

function render(value: VarValue): string {
  return typeof value === 'string' ? value : String(value);
}

export function scanStatementVars(text: string, vars: Vars): VarHint[] {
  const hints: VarHint[] = [];
  OCCURRENCE.lastIndex = 0;

  for (let match = OCCURRENCE.exec(text); match; match = OCCURRENCE.exec(text)) {
    const start = match.index;
    if (isEscaped(text, start) || isCommented(text, start)) {
      continue;
    }

    const expression = match[1];
    if (FOREIGN_SCOPE.test(expression.trim())) {
      continue;
    }

    const parsed = REFERENCE.exec(expression);
    if (!parsed) {
      continue;
    }

    const name = parsed[1].replace(/^vars\./, '');
    const value = Object.prototype.hasOwnProperty.call(vars, name)
      ? vars[name]
      : undefined;
    if (value === undefined) {
      continue;
    }

    hints.push({ end: start + match[0].length, text: render(value) });
  }

  return hints;
}
```

**Step 5: Run the tests**

```bash
cd vscode && npm test
```

Expected: PASS, all cases.

**Step 6: Typecheck, lint and commit**

```bash
cd vscode && npm run typecheck && npm run lint
git add vscode/src/rbx/statementVars.ts vscode/src/rbx/statementVars.test.ts
git commit -m "feat(vscode): scan statement files for root-scope var references"
```

---

## Task 3: Extract the rbx spawn helper

`visualize.ts` holds the `run()` spawn wrapper, the `resolved` per-root cache, `validate()` and `resolveCandidate()`. Task 4 needs all of them. Copying them would create a second executable-resolution path that can drift.

**Files:**
- Create: `vscode/src/rbxProcess.ts`
- Modify: `vscode/src/visualize.ts`

**Step 1: Read what you are moving**

`vscode/src/visualize.ts:19-125` — `SpawnResult`, `run()`, `PROBE_TIMEOUT_MS`, the `resolved` map, `resetRbxExecutables()`, `validate()`, `resolveCandidate()`, and whatever follows `resolveCandidate` up to the point where visualize-specific logic starts (read past line 125 to find the boundary; the exported "resolve an rbx for this root" function is the last thing to move).

**Step 2: Move them verbatim**

Create `vscode/src/rbxProcess.ts` containing exactly those pieces, exporting `SpawnResult`, `run`, `resetRbxExecutables`, and the per-root resolver. Keep the doc comments; move the doctrine paragraph from `visualize.ts`'s header into the new module, since it is now the shared justification.

Delete them from `visualize.ts` and import from `./rbxProcess` instead.

**Step 3: Verify nothing else referenced them**

```bash
cd vscode && grep -rn "resetRbxExecutables" src/
```

Every hit must now import from `./rbxProcess`. Check `extension.ts` and `commands.ts` in particular.

**Step 4: Typecheck and test**

```bash
cd vscode && npm run typecheck && npm run lint && npm test
```

Expected: PASS, with no behaviour change — this is a pure move.

**Step 5: Commit**

```bash
git add vscode/src/rbxProcess.ts vscode/src/visualize.ts
git commit -m "refactor(vscode): extract the rbx spawn and discovery helper"
```

---

## Task 4: The vars cache

**Files:**
- Create: `vscode/src/statementVarsIndex.ts`
- Test: `vscode/src/rbx/varsPayload.test.ts` (+ `vscode/src/rbx/varsPayload.ts`)

Parsing and validating the command's stdout is decidable without `vscode`, so it goes in a pure module; the spawning and caching do not.

**Step 1: Write the failing test for the payload parser**

Create `vscode/src/rbx/varsPayload.test.ts`:

```typescript
import * as assert from 'assert';
import { test } from 'node:test';

import { parseVarsPayload } from './varsPayload';

test('a flat dotted map is accepted', () => {
  assert.deepStrictEqual(parseVarsPayload('{"N.max": 100000, "ok": true}'), {
    'N.max': 100000,
    ok: true,
  });
});

test('malformed or unexpected output yields no vars, never a throw', () => {
  for (const stdout of ['', 'not json', '[]', 'null', '{"a": {"b": 1}}', '{"a": [1]}']) {
    assert.strictEqual(parseVarsPayload(stdout), undefined, stdout);
  }
});

test('leading noise before the object is tolerated', () => {
  // A shell wrapper or a venv activation can print before rbx does.
  assert.deepStrictEqual(parseVarsPayload('warning: x\n{"N.max": 5}'), {
    'N.max': 5,
  });
});
```

**Step 2: Run it to verify it fails**

```bash
cd vscode && npm test
```

Expected: FAIL — module not found.

**Step 3: Implement the parser**

Create `vscode/src/rbx/varsPayload.ts`:

```typescript
/**
 * Reading `rbx vars --json`.
 *
 * Every malformed shape resolves to `undefined` rather than throwing: the
 * feature degrades to "no badges", never to an error the user has to dismiss.
 */
import { VarValue, Vars } from './statementVars';

function isVarValue(value: unknown): value is VarValue {
  return (
    typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string'
  );
}

export function parseVarsPayload(stdout: string): Vars | undefined {
  const start = stdout.indexOf('{');
  if (start < 0) {
    return undefined;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout.slice(start));
  } catch {
    return undefined;
  }

  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return undefined;
  }

  const entries = Object.entries(parsed as Record<string, unknown>);
  if (!entries.every(([, value]) => isVarValue(value))) {
    return undefined;
  }
  return Object.fromEntries(entries) as Vars;
}
```

**Step 4: Run the tests**

```bash
cd vscode && npm test
```

Expected: PASS.

**Step 5: Write the cache**

Create `vscode/src/statementVarsIndex.ts`. Model it on `src/declared.ts` (a `Map` keyed by package root, an `onDidChange` `EventEmitter`, a lookup method, `dispose`). It must:

- hold `Map<string, Promise<Vars | undefined>>` keyed by package root;
- on a miss, resolve the rbx binary for that root and `run(rbx, ['vars', '--json'], root, TIMEOUT)`, then `parseVarsPayload(result.stdout)`; a spawn error, a non-zero exit code, or an unparseable payload all store `undefined`;
- expose `varsFor(root: string): Promise<Vars | undefined>`;
- expose `invalidate(root: string)` clearing that entry and firing `onDidChange`;
- log failures once per root via `./log` — this is the only place a failure is visible, and it must not repeat on every keystroke.

Use a 10 s timeout constant; `rbx vars` only parses YAML.

**Step 6: Wire invalidation**

In `vscode/src/extension.ts`, find the existing `**/problem.rbx.yml` watcher (near the other watchers, ~lines 200-320) and add `statementVars.invalidate(root)` beside the existing `data.invalidate(root)`. Do not add a new watcher.

**Step 7: Typecheck and commit**

```bash
cd vscode && npm run typecheck && npm run lint && npm test
git add vscode/src/rbx/varsPayload.ts vscode/src/rbx/varsPayload.test.ts vscode/src/statementVarsIndex.ts vscode/src/extension.ts
git commit -m "feat(vscode): cache the expanded vars of each problem package"
```

---

## Task 5: The inlay hint provider

**Files:**
- Create: `vscode/src/statementVarHints.ts`
- Modify: `vscode/package.json` (one `contributes.configuration` entry)
- Modify: `vscode/src/extension.ts` (registration)

**Step 1: Read the registration template**

`vscode/src/solutionLens.ts:74-95` (`registerSolutionLens`) — register the provider, subscribe to the index's `onDidChange`, subscribe to `onDidChangeConfiguration` filtered by `affectsConfiguration(SETTING)`, and fire the provider's own event. Copy that structure exactly.

**Step 2: Add the setting**

In `vscode/package.json`, beside `rbx.solutionCodeLens` in `contributes.configuration.properties`:

```json
"rbx.statementVarHints": {
  "type": "boolean",
  "default": true,
  "description": "Show the expanded value of each var referenced in a statement file."
}
```

**Step 3: Write the provider**

Create `vscode/src/statementVarHints.ts`:

```typescript
/**
 * The value of a var, shown beside the `\VAR{...}` that references it.
 *
 * An `InlayHintsProvider` rather than a text decoration, so the hints obey the
 * editor's own inlay setting and toggle. What gets a hint is decided by the
 * pure `rbx/statementVars.ts`; this file only asks and draws.
 */
import * as vscode from 'vscode';

import { DeclaredIndex } from './declared';
import { scanStatementVars } from './rbx/statementVars';
import { StatementVarsIndex } from './statementVarsIndex';

const SETTING = 'rbx.statementVarHints';

function enabled(): boolean {
  return vscode.workspace.getConfiguration().get<boolean>(SETTING, true);
}

class StatementVarHintsProvider implements vscode.InlayHintsProvider {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeInlayHints = this.changed.event;

  constructor(
    private readonly declared: DeclaredIndex,
    private readonly vars: StatementVarsIndex,
  ) {}

  async provideInlayHints(
    document: vscode.TextDocument,
    range: vscode.Range,
  ): Promise<vscode.InlayHint[]> {
    if (!enabled()) {
      return [];
    }
    // The manifest is the authority on which files are statements; it also
    // covers tutorials, which globbing `*.rbx.tex` would miss.
    const asset = this.declared.assetFor(document.uri);
    if (asset?.role !== 'statement') {
      return [];
    }

    const root = this.declared.rootFor(document.uri);
    if (root === undefined) {
      return [];
    }
    const vars = await this.vars.varsFor(root);
    if (vars === undefined) {
      return [];
    }

    const text = document.getText();
    return scanStatementVars(text, vars)
      .map((hint) => ({ hint, position: document.positionAt(hint.end) }))
      .filter(({ position }) => range.contains(position))
      .map(({ hint, position }) => {
        const inlay = new vscode.InlayHint(position, ` ${hint.text}`);
        inlay.paddingLeft = true;
        return inlay;
      });
  }

  refresh(): void {
    this.changed.fire();
  }

  dispose(): void {
    this.changed.dispose();
  }
}

export function registerStatementVarHints(
  context: vscode.ExtensionContext,
  declared: DeclaredIndex,
  vars: StatementVarsIndex,
): StatementVarHintsProvider {
  const provider = new StatementVarHintsProvider(declared, vars);
  context.subscriptions.push(
    provider,
    // Every file on disk: which ones are statements is a fact about the
    // manifest, not about the language.
    vscode.languages.registerInlayHintsProvider({ scheme: 'file' }, provider),
    declared.onDidChange(() => provider.refresh()),
    vars.onDidChange(() => provider.refresh()),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(SETTING)) {
        provider.refresh();
      }
    }),
  );
  return provider;
}
```

**Step 4: Resolve the package root for a document**

The provider calls `this.declared.rootFor(document.uri)`. Check whether `DeclaredIndex` already exposes the package root of an asset:

```bash
cd vscode && grep -n "root" src/declared.ts
```

If `DeclaredAsset` already carries the root, use that field and drop `rootFor`. If not, add a `rootFor(uri)` method to `DeclaredIndex` returning the package root the asset was declared in — the index already knows it, since it is built per discovered `problem.rbx.yml`.

**Step 5: Register it**

In `vscode/src/extension.ts:activate()`, construct the `StatementVarsIndex` and call `registerStatementVarHints(context, declared, statementVars)` beside the existing `registerSolutionLens(...)` call.

**Step 6: Typecheck, lint, test**

```bash
cd vscode && npm run typecheck && npm run lint && npm test
```

Expected: PASS.

**Step 7: Verify in a real editor**

```bash
./run-extension.sh
```

In the Extension Development Host, open a problem package that has a `vars:` block, open its statement `.rbx.tex`, and confirm:
- values appear after `\VAR{N.max}` and `\VAR{vars.N.max}`;
- nothing appears after `\VAR{g.N.max}`;
- editing `vars:` in `problem.rbx.yml` and saving updates the hints within ~1 s;
- toggling `rbx.statementVarHints` off removes them;
- the editor's own "Toggle Inlay Hints" also removes them.

**Step 8: Commit**

```bash
git add vscode/src/statementVarHints.ts vscode/src/extension.ts vscode/src/declared.ts vscode/package.json
git commit -m "feat(vscode): show expanded var values inline in statements"
```

---

## Task 6: Documentation

**Files:**
- Modify: `vscode/README.md`
- Modify: `docs/` — find the page that documents the extension's features

**Step 1: Find where extension features are documented**

```bash
grep -rln "solutionCodeLens\|decorateExplorer" docs/ vscode/README.md
```

**Step 2: Write the entry**

Follow `docs/plans/docs-writing-style-guide.md`. Introduce the concept before using it: a reader meets "statement files reference vars" before they meet "the extension shows their values". State the limits plainly — problem-root references only, raw value regardless of filter, requires `rbx` on `PATH` or in the `rbx.executable` setting.

**Step 3: Verify the docs build**

```bash
uv run mkdocs build
```

Expected: builds. Ignore pre-existing unrelated warnings; do not use `--strict`.

**Step 4: Revert the regenerated CLI reference if it changed**

`mkdocs build` rewrites the checked-in CLI reference. Since Task 1 added a command, the regenerated file legitimately differs — check the diff and keep **only** the `rbx vars` addition:

```bash
git diff docs/
```

**Step 5: Commit**

```bash
git add docs/ vscode/README.md
git commit -m "docs: document the statement var hints in the vscode extension"
```

---

## Final verification

```bash
uv run pytest tests/rbx/box/vars_cmd_test.py tests/rbx/box/lazy_cli_test.py -v
cd vscode && npm run typecheck && npm run lint && npm test
```

Do **not** run the full Python suite — it is slow and produces spurious sandbox wall-timeout failures. Run only the files this change touches.

Then open a PR against `main`.
