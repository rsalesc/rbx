# VS Code run webview Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the Run `TreeView` with a webview view that can render the expectation, the verdict and the match as three independent visual channels.

**Architecture:** The data layer (`layout/wire/model/store/report/summary/outcome`) does not move. A new pure `viewModel.ts` turns `PackageRun[]` into a flat, serializable `RunViewModel`; a pure `render.ts` turns that into an HTML string; `main.ts` in the webview owns interaction; `runView.ts` on the host owns the store subscription and command dispatch. Expansion is entirely client-side — the whole model is posted once per refresh.

**Tech Stack:** TypeScript, esbuild (two bundles: extension for node, webview for browser), `node --test`, `@vscode/codicons`, VS Code webview view API.

Design doc: `docs/plans/2026-08-19-vscode-run-webview-design.md`.

---

## Conventions for every task

- All paths are relative to `vscode/`.
- Run commands from `vscode/`.
- Style: single quotes, absolute imports, 2-space indent, `readonly` on interface fields, explicit return types on exported functions. Match the surrounding files — they are heavily commented with *why*, not *what*, and that is the house style. Do not add "what" comments.
- Tests use `node:test` + `node:assert/strict`, as `src/rbx/summary.test.ts` does. Read that file first for the idiom.
- Test loop: `npm run pretest && npm test`. Typecheck: `npm run typecheck`.
- Commit with conventional commits (`feat(vscode): ...`), one commit per task, `Co-Authored-By: Claude <noreply@anthropic.com>`.

---

## Pinned interfaces

These are the contracts three parallel workstreams agree on. Do not change a
field name without saying so loudly — another task is compiling against it.

### `src/rbx/hue.ts`

```ts
/**
 * The color vocabulary shared by the model and the renderer.
 *
 * A name rather than a `ThemeColor` id or a hex: the model is serialized across
 * the webview boundary, and the mapping onto `--vscode-*` variables is the
 * stylesheet's business.
 */
export type Hue =
  | 'green'
  | 'red'
  | 'yellow'
  | 'blue'
  | 'purple'
  | 'orange'
  | 'neutral'
  | 'dim';

/** Theme color ids as `outcome.ts` records them, onto the hue vocabulary. */
export function hueOfThemeColor(color: string): Hue;
```

`hueOfThemeColor` maps `charts.green|red|yellow|blue|purple|orange` to the bare
name, `descriptionForeground` to `dim`, and anything else to `neutral`.

### `src/rbx/nodes.ts`

Moved verbatim out of `runTree.ts` (the type declarations only — `PackageNode`,
`SolutionNode`, `GroupNode`, `TestcaseNode`, `RunNode`), plus:

```ts
/** The stable row id. Identical to the `TreeItem.id`s the tree used. */
export function nodeId(node: RunNode): string;
```

- package: `<root>`
- solution: `<root>::<solutionIndex>`
- group: `<root>::<solutionIndex>::<group>`
- testcase: `<root>::<solutionIndex>::<group>::<stem>`

```ts
export interface PackageRunView {
  readonly pkg: PackageLayout;
  readonly run: PackageRun | undefined;
}

/**
 * Every node in display order, parents before children.
 *
 * The package level is skipped when there is exactly one package, matching what
 * the tree did -- a single-problem workspace should not make the user expand one
 * node forever.
 */
export function flattenNodes(packages: readonly PackageRunView[]): RunNode[];
```

`flattenNodes` skips packages whose `run` is `undefined`.

### `src/rbx/expectation.ts`

```ts
export interface ExpectationDisplay {
  /** `AC`, `WA`, `INCORRECT`, `AC or TLE`, `ANY`. */
  readonly label: string;
  readonly hue: Hue;
  readonly bold: boolean;
  /** `✓` / `⧖` / `✗` / `?`, mirroring `ExpectedOutcome.icon()`. */
  readonly glyph: string;
}

/** `undefined` when nothing was declared. */
export function expectationDisplay(expected: string | undefined): ExpectationDisplay | undefined;
```

### `src/rbx/viewModel.ts`

```ts
export type Gutter = 'none' | 'met' | 'missed';

export interface Span {
  readonly text: string;
  readonly hue?: Hue;
}

export interface VerdictChip {
  readonly icon: string;
  readonly hue: Hue;
  readonly short: string;
}

export interface HistogramSlice {
  readonly short: string;
  readonly hue: Hue;
  readonly count: number;
}

export interface MismatchDetail {
  readonly declared: string;
  readonly observed: string;
  readonly failedGroups: readonly string[];
}

export interface SolutionDetail {
  readonly mismatch?: MismatchDetail;
  readonly histogram: readonly HistogramSlice[];
  readonly maxTime?: string;
  readonly maxMemory?: string;
  readonly score?: string;
}

export interface Row {
  readonly id: string;
  readonly parentId?: string;
  readonly depth: number;
  readonly kind: 'package' | 'solution' | 'group' | 'testcase';
  readonly gutter: Gutter;
  readonly label: string;
  readonly labelHue?: Hue;
  readonly labelBold: boolean;
  readonly meta: readonly Span[];
  readonly verdict?: VerdictChip;
  readonly mismatch: boolean;
  readonly expandable: boolean;
  readonly defaultExpanded: boolean;
  readonly detail?: SolutionDetail;
  /** Lowercased haystack for the filter box. */
  readonly search: string;
  /** `webviewSection` for the context menu: `rbx.solution`, `rbx.testcase`, ... */
  readonly section: string;
  /** Command run on Enter / double click. */
  readonly primaryCommand?: string;
}

export interface RunViewModel {
  readonly rows: readonly Row[];
  /** Solutions that missed their declaration. */
  readonly mismatches: number;
  /** No package has a readable run: the webview shows the welcome copy. */
  readonly empty: boolean;
}

export function buildViewModel(packages: readonly PackageRunView[]): RunViewModel;
```

### `src/webview/render.ts`

```ts
export interface UiState {
  readonly expanded: ReadonlySet<string>;
  readonly selected?: string;
  readonly filter: string;
}

/** Rows the current filter and expansion state make visible, in order. */
export function visibleRows(model: RunViewModel, state: UiState): Row[];
export function matchesFilter(row: RunViewModel['rows'][number], filter: string): boolean;
/** innerHTML for `#tree`. */
export function renderTree(model: RunViewModel, state: UiState): string;
/** innerHTML for `#header`; empty string when there is nothing to say. */
export function renderHeader(model: RunViewModel, state: UiState): string;
export function escapeHtml(text: string): string;
export function escapeAttr(text: string): string;
```

### Message protocol

```ts
// host -> webview
{ type: 'state'; model: RunViewModel }
// webview -> host
{ type: 'ready' }
{ type: 'invoke'; commandId: string; nodeId: string }
```

---

## Task 1: `hue.ts`, `nodes.ts`, `expectation.ts`

**Files:**
- Create: `src/rbx/hue.ts`, `src/rbx/expectation.ts`
- Create: `src/rbx/nodes.ts` (move type declarations out of `src/runTree.ts`)
- Test: `src/rbx/expectation.test.ts`, `src/rbx/nodes.test.ts`

**Step 1: Write the failing tests**

`src/rbx/expectation.test.ts` must assert, at minimum:

```ts
import { strict as assert } from 'node:assert';
import { test } from 'node:test';

import { expectationDisplay } from './expectation';

test('an undeclared expectation has no display', () => {
  assert.equal(expectationDisplay(undefined), undefined);
});

test('ACCEPTED is bold green with a tick', () => {
  assert.deepEqual(expectationDisplay('ACCEPTED'), {
    label: 'AC',
    hue: 'green',
    bold: true,
    glyph: '✓',
  });
});

test('every ExpectedOutcome member rbx declares has a display', () => {
  const members = [
    'ANY',
    'ACCEPTED',
    'ACCEPTED_OR_TLE',
    'WRONG_ANSWER',
    'INCORRECT',
    'RUNTIME_ERROR',
    'TIME_LIMIT_EXCEEDED',
    'MEMORY_LIMIT_EXCEEDED',
    'OUTPUT_LIMIT_EXCEEDED',
    'TLE_OR_RTE',
    'COMPILATION_ERROR',
  ];
  for (const member of members) {
    assert.notEqual(expectationDisplay(member), undefined, member);
  }
});
```

**Before writing the table, read `rbx/box/schema.py`** (in the repo root, class
`ExpectedOutcome`) and take the member list and the hues from `style()` /
`full_style()` / `icon()` at lines 185-240. The list above is a starting point,
not the authority — if `schema.py` declares a member it omits, add it, and add
it to the test. An unknown string must return a `neutral`, non-bold display with
the raw string as its label rather than `undefined`: `undefined` means
*undeclared*, and the two must not be confused.

`nodes.test.ts` asserts the four id spellings and that `flattenNodes` emits
parents before children, skips the package level for a single package, and emits
it for two.

**Step 2: Run and watch them fail**

`npm run pretest && npm test` — expect failures naming the missing modules.

**Step 3: Implement**

`hue.ts` and `expectation.ts` from scratch. `nodes.ts` by **moving** the
interface declarations out of `runTree.ts` — cut, do not copy; `runTree.ts` will
be deleted in Task 3 but must still compile until then, so leave it importing
the types from `nodes.ts`.

Head each file with a comment in the house style saying why it exists. For
`expectation.ts`: this is the *declared* vocabulary (`ExpectedOutcome`, upper
snake case, from `problem.rbx.yml`) and must never be confused with the
*observed* one in `outcome.ts` — the header of `outcome.ts` explains the trap at
length and this file is the other half of it.

**Step 4: Run tests, expect pass. Then `npm run typecheck`.**

**Step 5: Commit** — `feat(vscode): add the hue, node and expectation vocabularies`

---

## Task 2: `viewModel.ts`

**Files:**
- Create: `src/rbx/viewModel.ts`
- Test: `src/rbx/viewModel.test.ts`

Depends on Task 1.

**The rules the tests must pin:**

*Gutter and mismatch* — the match axis, and nothing else touches it.
- solution: `none` if `solution.expectedOutcome` is undefined or `ANY`, or if the report has not landed yet; otherwise `met` / `missed` from `report.matchesExpectation`.
- group: `none` unless `report.expectedOutcome` is set (only an `outcomePerGroup` declaration sets it); then `met` / `missed`.
- package and testcase: always `none`.
- `mismatch === (gutter === 'missed')`.

*Label* — solution rows use `solution.path`, hued and bolded by
`expectationDisplay(solution.expectedOutcome)` (no hue and not bold when
undeclared). Group rows use the group name, testcase rows the stem, package rows
`packageLabel(pkg)`. Only solution labels are hued.

*Meta* — **the verdict name never appears in meta**, and neither does any
"expected X, got Y" phrasing. That folding is the bug this whole change exists
to remove; the chip and the gutter carry those facts now. So:
- solution and group: progress (`3/10`, only while incomplete), score
  (`formatScore`, only when `maxScore > 0`, hue `neutral`), max time, max memory
  — all others hue `dim`. Nothing at all when the report has not landed and the
  run has not started (`pending`).
- testcase: time, memory, checker message, all `dim`.
- Reuse `formatTime`, `formatMemory`, `formatScore`, `progressOf` from
  `summary.ts`. Do not reimplement them.

*Verdict chip* — `outcomeIcon()` + `shortName()` from `outcome.ts`, with
`hueOfThemeColor`. Present on solution, group and testcase rows; absent on
package rows.

*Detail* — solution rows only. `histogram` counts testcase outcomes most-frequent
first, ties broken by name (same ordering rule as `formatCounts`, which explains
why: the badness ranking is `Outcome.worst_outcome`'s business). `maxTime`,
`maxMemory`, `score` are the formatted report values, absent when the report is.
`mismatch` is set only when the solution missed, with `declared` from
`expectationDisplay(...).label`, `observed` from `shortName(report.outcome)`, and
`failedGroups` straight from `report.failedGroups`.

*Expansion* — solutions are `expandable`, `defaultExpanded` only when their
package's run has exactly one solution (the tree's solo rule, which mirrors
rbx's own `len(skeleton.solutions) == 1`). Groups are expandable and default
expanded. Testcases are leaves. Packages are expandable and default expanded.

*primaryCommand* — testcase rows get `rbx.diffOutput` when the evaluation exists
and is not accepted, `rbx.openInput` otherwise (exactly what the tree's
`item.command` did). Other rows get none.

*`search`* — lowercased. Solution rows: the path. Group rows: the group name.
Testcase rows: `<group>/<stem>`. Plus the verdict short name and, when
mismatched, the literal `mismatch`, so the filter box can take `wa` or
`mismatch` as a token.

*`mismatches`* — the count of *solution* rows with `gutter === 'missed'`. Not
failures: a solution that fails on purpose is the package working.

*`empty`* — true when no row of kind `solution` was produced.

**Test with a hand-built fixture**, not a real package: build `PackageRunView`
objects literally in the test file. Cover at least the three cases the
`outcome-per-group` e2e fixture covers, because they are the ones that break
naive encodings:

1. `main.cpp`, declares `ACCEPTED`, gets AC → gutter `met`, bold green label, green chip, no mismatch card.
2. `partial.cpp`, declares `INCORRECT`, gets WA → gutter `met`, red label, **red chip**, and **no** mismatch: it failed on purpose. Assert `mismatch === false` explicitly; this is the whole point.
3. `mislabeled.cpp`, declares `INCORRECT`, gets WA, `matchesExpectation: false`, `failedGroups: ['small', 'big']` → gutter `missed`, mismatch card naming both groups.

Also assert a pending solution (no report) produces `gutter: 'none'` and no
verdict-name text in meta.

**Steps:** write tests → `npm run pretest && npm test` (fail) → implement →
tests pass → `npm run typecheck` → commit
`feat(vscode): build a pure view model for the run view`.

---

## Task 3: the webview client

**Files:**
- Create: `src/webview/render.ts`, `src/webview/main.ts`, `src/webview/style.css`
- Test: `src/webview/render.test.ts`

Depends on Tasks 1-2 for types only. **`render.ts` and `render.test.ts` must not
import `vscode`**; `main.ts` may use the `acquireVsCodeApi()` global but never the
`vscode` module.

### `render.ts`

Pure `model + state -> HTML string`. Row markup, exactly:

```html
<div class="row kind-solution mismatch" role="treeitem" data-id="ESCAPED_ID"
     aria-level="1" aria-setsize="4" aria-posinset="3"
     aria-expanded="true" aria-selected="false" tabindex="-1"
     data-vscode-context='{"webviewSection":"rbx.solution","rbxNodeId":"...","preventDefaultContextMenuItems":true}'>
  <span class="gutter"><span class="codicon codicon-warning"></span></span>
  <span class="twisty codicon codicon-chevron-down"></span>
  <span class="label hue-red bold">sols/mislabeled.cpp</span>
  <span class="meta"><span class="span hue-dim">940 ms</span></span>
  <span class="verdict hue-red"><span class="codicon codicon-close"></span>WA</span>
</div>
```

- gutter glyphs: `met` → `codicon-check` with class `gutter-met`; `missed` →
  `codicon-warning` with class `gutter-missed`; `none` → an empty `<span class="gutter"></span>` that still occupies the column, so labels stay aligned.
- twisty: `codicon-chevron-down` when expanded, `codicon-chevron-right` when
  collapsed, absent (but the column preserved) for leaves.
- indentation is `style="padding-left: Npx"` on the row, `N = 8 + depth * 12`.
- the detail card follows its solution row as a sibling `<div class="detail" role="group">` and is emitted only when the row is expanded and `detail` is set. Mismatch card first (`declared` / `observed` / failing group names, in words — "declared INCORRECT, but small, big matched"), then the histogram as a row of proportional bars with counts, then max time / max memory / score.
- `renderHeader` returns `''` when `mismatches === 0`, otherwise a strip with the
  count in words and a `<button id="next-mismatch">` — plus the filter input,
  which is always rendered (put the filter in its own always-present element so
  the strip can come and go without taking the box with it; adjust the two
  functions' division of labour if that reads cleaner, and say so in a comment).
- the empty state (`model.empty`) renders the exact words the old `viewsWelcome`
  used: "No rbx run found in this workspace." and "Run `rbx run` in the terminal
  and the results will show up here."
- **Escape everything.** `escapeHtml` for text nodes, `escapeAttr` (which also
  escapes `'` and `"`) for attribute values including the JSON blob. A group is
  named by the package author and can contain anything.

`matchesFilter`: case-insensitive substring against `row.search`; a row also
matches if any ancestor matches (so filtering to a solution keeps its testcases)
or if any descendant matches (so a matching testcase keeps its ancestors
visible). `visibleRows` applies the filter, then hides rows whose ancestor chain
is not fully expanded.

**Tests** (`render.test.ts`): assert the escaping (feed a group named
`<img src=x onerror=alert(1)>` and assert no raw `<img` survives), that a
collapsed row's children do not appear in `visibleRows`, that a filter of
`mismatch` keeps a missed solution and drops a met one, that `renderHeader` is
`''` at zero mismatches, and that `aria-expanded` is absent on leaves.

### `main.ts`

Owns interaction and nothing else — it must contain no display decisions that
belong in `render.ts` or `viewModel.ts`.

- `acquireVsCodeApi()`; on load post `{type:'ready'}`; on `message` with
  `type:'state'` store the model and re-render.
- State in `vscode.setState()`: `{expanded: string[], selected?: string, filter: string, scrollTop: number}`, restored on load. Debounce writes by 100ms.
- Default expansion: on the first render of a model, seed `expanded` from every
  row with `defaultExpanded`, but never override a decision already in the saved
  state — a user who collapsed a solution must find it collapsed after a refresh,
  which is what the tree did via `TreeItem.id` persistence. Track ids the user has
  explicitly toggled so seeding can tell "never seen" from "deliberately closed".
- Click on the twisty toggles; click on the row selects; double-click or Enter
  posts `{type:'invoke', commandId: row.primaryCommand, nodeId: row.id}` when the
  row has one.
- Keyboard on the `role="tree"` container, roving `tabindex`: Up/Down move
  selection through `visibleRows`, Right expands (or moves to the first child if
  already expanded), Left collapses (or moves to the parent), Home/End jump,
  Enter invokes the primary command, `/` focuses the filter box, Escape clears it.
  Keep the selected row scrolled into view.
- `#next-mismatch` cycles selection through rows with `mismatch === true`,
  expanding ancestors as needed.
- Re-render on every `state` message, preserving scroll and selection.

### `style.css`

- Hues map to VS Code variables: `--vscode-charts-green|red|yellow|blue|purple|orange`, `dim` → `--vscode-descriptionForeground`, `neutral` → `--vscode-foreground`.
- The row is a CSS grid: `grid-template-columns: 16px 16px 1fr auto auto`.
- `.mismatch` gets `border-left: 2px solid var(--vscode-charts-red)` and a wash
  built from `--vscode-inputValidation-errorBackground` at low alpha. **This must
  be the only background color in the stylesheet besides selection and hover**,
  which is what makes a miss findable without reading.
- Selection and hover use `--vscode-list-activeSelectionBackground`,
  `--vscode-list-hoverBackground`, and `--vscode-focusBorder` for the focus ring.
- Body font from `--vscode-font-family`/`--vscode-font-size`; the view must not
  scroll horizontally — the label truncates with an ellipsis and the meta column
  drops out under `@container (max-width: 260px)`.
- Import the codicon font via `@font-face` pointing at `codicon.ttf` next to the
  stylesheet (Task 4 puts it there).

**Commit** — `feat(vscode): render the run view as a webview client`.

---

## Task 4: host side

**Files:**
- Create: `src/runData.ts`, `src/runView.ts`
- Delete: `src/runTree.ts`
- Modify: `src/extension.ts`, `src/commands.ts`, `package.json`, `esbuild.mjs`

Depends on Tasks 1-3.

### `src/runData.ts`

Everything in `RunTreeProvider` that was *not* about drawing a `TreeItem`:
discovery, the `ArtifactStore` map, `refresh()`, `invalidate(root)`, `report(pkg)`.
Rename the class `RunDataProvider`. Replace the `vscode.EventEmitter<RunNode|undefined>`
`onDidChangeTreeData` with a plain `onDidChange: vscode.Event<void>`. Add:

```ts
/** Every package with a readable run, in discovery order. */
loadAll(): Promise<PackageRunView[]>;
```

Keep the comment explaining why `discovery` is tracked explicitly rather than
inferred from `packages.length` — the endless-loop hazard it names is still real.

### `src/runView.ts`

`RunViewProvider implements vscode.WebviewViewProvider`, `viewType = 'rbx.run'`.

- `resolveWebviewView`: `webview.options = {enableScripts: true, localResourceRoots: [Uri.joinPath(extensionUri, 'dist')]}`; set the HTML; subscribe to `data.onDidChange` and re-post; dispose the subscription with the view.
- HTML: a nonce (16+ random chars) on the single `<script>`, CSP
  `default-src 'none'; style-src ${webview.cspSource}; font-src ${webview.cspSource}; script-src 'nonce-${nonce}';`, a `<link>` to `dist/webview/style.css`, and `<div id="header"></div><div id="tree" role="tree" tabindex="0"></div>`.
- On `{type:'ready'}` and on every change: `buildViewModel(await data.loadAll())`, posted as `{type:'state', model}`. Build the id index in the same pass with `flattenNodes` and keep it for command resolution.
- On `{type:'invoke'}`: resolve `nodeId` to a `RunNode` and `vscode.commands.executeCommand(commandId, node)`. Ignore unknown ids — a stale webview can post one after a refresh.
- Expose `nodeById(id: string): RunNode | undefined` for `commands.ts`.

### `src/commands.ts`

The context-menu path does **not** hand a command its `RunNode`. VS Code invokes
a `webview/context` command with the `data-vscode-context` object, so handlers
receive `{webviewSection, rbxNodeId, preventDefaultContextMenuItems}` instead.
Add one resolver at the top of `registerCommands` and put every handler behind it:

```ts
const resolve = (arg: unknown): RunNode | undefined => {
  if (typeof arg === 'object' && arg !== null && 'kind' in arg) {
    return arg as RunNode;
  }
  const id = (arg as { rbxNodeId?: unknown } | undefined)?.rbxNodeId;
  return typeof id === 'string' ? view.nodeById(id) : undefined;
};
```

Comment it: this is the seam where a context menu and a keyboard invocation
arrive in two different shapes. `registerCommands` now takes the
`RunViewProvider` (for `nodeById`) and the `RunDataProvider` (for `refresh`).

### `src/extension.ts`

`registerTreeDataProvider` → `vscode.window.registerWebviewViewProvider('rbx.run', view)`.
Everything else — the watchers, the 200ms debounce, the two globs and why there
are two, the manifest watcher — is unchanged.

### `package.json`

- `views.rbx[0]` gains `"type": "webview"`.
- Delete the `viewsWelcome` block (it does not apply to webview views; the empty
  state moved into `render.ts`). Leave a `//`-free note nowhere — just delete it.
- `menus`: keep `view/title`. Replace every `view/item/context` entry with a
  `webview/context` entry keyed on `webviewSection`, e.g.
  `"when": "webviewSection == 'rbx.testcase'"`. Drop the `inline` group entry —
  webview context menus have no inline slot.
- devDependency `"@vscode/codicons": "^0.0.36"`.

### `esbuild.mjs`

Add a second build: `entryPoints: ['src/webview/main.ts', 'src/webview/style.css']`,
`bundle: true`, `format: 'iife'`, `platform: 'browser'`, `target: 'es2020'`,
`outdir: 'dist/webview'`. Copy `node_modules/@vscode/codicons/dist/codicon.ttf`
to `dist/webview/codicon.ttf` (`fs.cpSync`), because `node_modules` is not in the
shipped vsix. Keep `--watch` working for both builds.

**Verify:** `npm install`, `npm run typecheck`, `npm run compile`,
`npm run pretest && npm test`. Then confirm `dist/webview/main.js`,
`dist/webview/style.css` and `dist/webview/codicon.ttf` all exist.

**Commit** — `feat(vscode): serve the run view from a webview provider`.

---

## Task 5: docs and final verification

- Update `vscode/README.md` if it describes the view as a tree.
- Full run: `npm run typecheck && npm run compile && npm run pretest && npm test`.
- Report the test count. `npm run lint` fails on `main` (eslint is not installed
  in this checkout) — do not treat that as a regression, but say so.

**Commit** — `docs(vscode): describe the run view as a webview`.
