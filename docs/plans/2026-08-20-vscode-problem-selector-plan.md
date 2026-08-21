# VS Code problem selector — implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Scope the Run view to one problem, chosen from a dropdown in its header, auto-switching to whichever problem is currently running.

**Architecture:** An `ActiveProblem` service in the extension host owns the ordered problem list, the selected package root and the auto-switch rule. `RunViewProvider` posts `{problems, selected, run}` — a light list plus **one** package's run — instead of every package's artifacts. Contest identity (the A/B/C `short_name`, declared order, colour) comes from walking up to the nearest `contest.rbx.yml`, resolved by a pure module under `src/rbx/`. The package row disappears from the tree entirely.

**Tech Stack:** TypeScript, VS Code extension API, `node --test` (no framework), esbuild, `yaml`.

Design doc: [`2026-08-20-vscode-problem-selector-design.md`](2026-08-20-vscode-problem-selector-design.md).

---

## Orientation for the implementer

Read these before Task 1. The extension is small but its conventions are strict.

**The extension never runs `rbx`.** It is a pure reader of files rbx leaves on disk (design D2/D3, `vscode/src/extension.ts:1-7`). Do not add `child_process`, a terminal, or a `cwd` anywhere. If a task seems to need one, you have misread it.

**Two halves, and the seam matters.** Anything under `vscode/src/rbx/` is pure: **no `import * as vscode`**, ever. That is what lets `node --test` cover it without an editor. Host-facing glue (watchers, `workspaceState`, quick picks, configuration) lives in `vscode/src/*.ts` one level up. Every task below says which half a file belongs to; respect it, because the test strategy depends on it.

**Commands:**

```bash
cd vscode
npm run test        # runs pretest (esbuild) then node --test
npm run typecheck   # tsc --noEmit
npm run lint        # eslint src
```

Run all three before each commit. `npm run test` alone will not catch a type error, because esbuild strips types without checking them.

**Test style.** No framework — `node:test` and `node:assert/strict`. Look at `vscode/src/rbx/nodes.test.ts` for the house style before writing the first test.

**Commits.** This project enforces conventional commits via commitizen; the pre-commit hook rejects non-compliant messages. Use the `/commit` skill. Never amend — if the hook rejects, make a new commit.

**A warning about scope.** Tasks 1–3 are pure additions that ship no behaviour change. Task 4 is the switch-over and is the only one that can break the view. Do not start Task 4 until 1–3 are committed and green.

---

## Task 1: Contest identity — parsing

**Files:**
- Create: `vscode/src/rbx/contest.ts` (pure — no `vscode` import)
- Create: `vscode/src/rbx/contest.test.ts`

Parse a `contest.rbx.yml` into the problems it declares. This task is parsing only; finding the file is Task 2.

The schema fields that matter (`rbx/box/contest/schema.py:121-165`):

| Field | Meaning |
|---|---|
| `short_name` | The A/B/C letter. Required. |
| `path` | Directory relative to the contest root. **Optional — defaults to `./{short_name}/`.** |
| `color` | Hex (`#abcdef`/`#abc`) or an X11 colour name. Optional. |

Plus `use_variants: bool` at the top level (`schema.py:213`): when true the file is a dispatcher sentinel declaring no problems of its own.

**Step 1: Write the failing tests**

```ts
import { strict as assert } from 'node:assert';
import { test } from 'node:test';

import { parseContest } from './contest';

test('parses declared problems in file order', () => {
  const contest = parseContest({
    problems: [
      { short_name: 'A', color: '#ff0000' },
      { short_name: 'B', path: 'problems/beta' },
    ],
  });
  assert.deepEqual(contest, {
    useVariants: false,
    problems: [
      { shortName: 'A', path: 'A', color: '#ff0000', order: 0 },
      { shortName: 'B', path: 'problems/beta', color: undefined, order: 1 },
    ],
  });
});

test('defaults a problem path to its short name', () => {
  const contest = parseContest({ problems: [{ short_name: 'C' }] });
  assert.equal(contest.problems[0].path, 'C');
});

test('reports a dispatcher as declaring no problems', () => {
  assert.deepEqual(parseContest({ use_variants: true }), { useVariants: true, problems: [] });
});

test('tolerates a file that is not a contest at all', () => {
  // Never throws: the walk in Task 2 reads whatever it finds, and a malformed
  // file must degrade to "no identity", not take the view down.
  for (const raw of [undefined, null, 'a string', 42, {}, { problems: 'not a list' }]) {
    assert.deepEqual(parseContest(raw), { useVariants: false, problems: [] });
  }
});

test('skips entries with no usable short name', () => {
  const contest = parseContest({ problems: [{ color: '#fff' }, { short_name: 'B' }] });
  assert.deepEqual(contest.problems.map((p) => p.shortName), ['B']);
});

test('numbers order by surviving position, not by input index', () => {
  // `order` drives display order downstream, so a skipped entry must not leave
  // a hole that sorts a later problem into the wrong slot.
  const contest = parseContest({ problems: [{}, { short_name: 'A' }, { short_name: 'B' }] });
  assert.deepEqual(contest.problems.map((p) => p.order), [0, 1]);
});
```

**Step 2: Run to verify it fails**

Run: `cd vscode && npm run test`
Expected: FAIL — cannot find module `./contest`.

**Step 3: Implement**

```ts
/**
 * What a `contest.rbx.yml` says about the problems under it.
 *
 * Pure, like its neighbours: finding the file is the host's job (contestIndex.ts),
 * and this half only turns parsed YAML into identities. Nothing here throws --
 * a malformed contest file must cost the packages their letters, never the view.
 */

/** One problem as its contest declares it. */
export interface ContestProblem {
  readonly shortName: string;
  /** Directory, relative to the contest root. Defaults to the short name. */
  readonly path: string;
  readonly color?: string;
  /** Position among the problems that survived parsing. */
  readonly order: number;
}

export interface ParsedContest {
  /** A dispatcher sentinel: the real contests are sibling `contest.<id>.rbx.yml`. */
  readonly useVariants: boolean;
  readonly problems: readonly ContestProblem[];
}

const EMPTY: ParsedContest = { useVariants: false, problems: [] };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value !== '' ? value : undefined;
}

export function parseContest(raw: unknown): ParsedContest {
  if (!isRecord(raw)) {
    return EMPTY;
  }
  if (raw.use_variants === true) {
    // A dispatcher declares nothing else; rbx rejects any other field alongside
    // it (rbx/box/contest/schema.py:242).
    return { useVariants: true, problems: [] };
  }
  if (!Array.isArray(raw.problems)) {
    return EMPTY;
  }
  const problems: ContestProblem[] = [];
  for (const entry of raw.problems) {
    if (!isRecord(entry)) {
      continue;
    }
    const shortName = optionalString(entry.short_name);
    if (shortName === undefined) {
      continue;
    }
    problems.push({
      shortName,
      // rbx defaults an unset path to `./{short_name}/`.
      path: optionalString(entry.path) ?? shortName,
      color: optionalString(entry.color),
      // Counted off the survivors so a skipped entry leaves no hole.
      order: problems.length,
    });
  }
  return { useVariants: false, problems };
}
```

**Step 4: Run to verify it passes**

Run: `cd vscode && npm run test && npm run typecheck && npm run lint`
Expected: all PASS.

**Step 5: Commit**

```bash
git add vscode/src/rbx/contest.ts vscode/src/rbx/contest.test.ts
# /commit  ->  feat(vscode): parse the problems a contest declares
```

---

## Task 2: Contest identity — resolving roots to problems

**Files:**
- Create: `vscode/src/contestIndex.ts` (host half — reads files)
- Modify: `vscode/src/rbx/contest.ts` (add the pure matching function)
- Modify: `vscode/src/rbx/contest.test.ts`

Given package roots, produce a display identity for each. Split deliberately: the **matching** is pure and tested; the **file walk** is host-side and thin.

`readYamlFile` already exists in `vscode/src/rbx/store.ts` (used by `declared.ts:45`) and returns `undefined` for a missing or unparseable file. Reuse it — do not add a second YAML reader.

**Step 1: Write the failing test** (append to `contest.test.ts`)

```ts
import { problemIdentities } from './contest';

test('matches package roots to declared problems', () => {
  const identities = problemIdentities('/c', parseContest({
    problems: [{ short_name: 'A' }, { short_name: 'B', path: 'problems/beta' }],
  }));
  assert.deepEqual(identities.get('/c/A'), { shortName: 'A', color: undefined, order: 0 });
  assert.deepEqual(identities.get('/c/problems/beta'), {
    shortName: 'B',
    color: undefined,
    order: 1,
  });
});

test('normalizes a declared path before matching', () => {
  // Contest files are hand-written: `./A/` and `A` name the same directory.
  const identities = problemIdentities('/c', parseContest({
    problems: [{ short_name: 'A', path: './A/' }],
  }));
  assert.equal(identities.get('/c/A')?.shortName, 'A');
});

test('declares nothing for a dispatcher', () => {
  assert.equal(problemIdentities('/c', parseContest({ use_variants: true })).size, 0);
});
```

**Step 2: Run to verify it fails**

Run: `cd vscode && npm run test`
Expected: FAIL — `problemIdentities` is not exported.

**Step 3: Implement the pure half** (append to `contest.ts`)

```ts
import * as path from 'path';

/** A problem's contest-given identity, keyed by absolute package root. */
export interface ProblemIdentity {
  readonly shortName: string;
  readonly color?: string;
  readonly order: number;
}

/**
 * Resolve each declared problem to the absolute root it names.
 *
 * `path.resolve` normalizes the hand-written spellings a contest file carries
 * -- `./A/`, `A`, `problems/../A` all land on the same key -- so a match is a
 * plain map lookup downstream rather than a path comparison at every use.
 */
export function problemIdentities(
  contestRoot: string,
  contest: ParsedContest,
): Map<string, ProblemIdentity> {
  const identities = new Map<string, ProblemIdentity>();
  for (const problem of contest.problems) {
    identities.set(path.resolve(contestRoot, problem.path), {
      shortName: problem.shortName,
      color: problem.color,
      order: problem.order,
    });
  }
  return identities;
}
```

**Step 4: Implement the host half**

Create `vscode/src/contestIndex.ts`:

```ts
/**
 * Contest identities for the discovered packages.
 *
 * Walks up from each package root to the nearest `contest.rbx.yml`, mirroring
 * `find_contest_root` (rbx/box/contest/contest_package.py:103). Nothing new is
 * asked of rbx: the file is already on disk, and reading it is what lets the
 * selector call a package `A` instead of naming its directory.
 */
import * as fs from 'fs/promises';
import * as path from 'path';

import { ProblemIdentity, parseContest, problemIdentities } from './rbx/contest';
import { readYamlFile } from './rbx/store';

const CONTEST_MANIFEST = 'contest.rbx.yml';
/** Sibling variant files: `contest.<id>.rbx.yml`. */
const VARIANT_PREFIX = 'contest.';
const VARIANT_SUFFIX = '.rbx.yml';

/** The nearest ancestor of `from` holding a contest.rbx.yml, or undefined. */
async function findContestRoot(from: string): Promise<string | undefined> {
  let walker = from;
  for (;;) {
    try {
      await fs.access(path.join(walker, CONTEST_MANIFEST));
      return walker;
    } catch {
      // Not here; keep walking.
    }
    const parent = path.dirname(walker);
    if (parent === walker) {
      return undefined;
    }
    walker = parent;
  }
}

/**
 * Every contest file in a root: the canonical one plus its variants.
 *
 * A `use_variants: true` canonical declares no problems of its own, so the
 * letters live only in the siblings. Reading all of them and letting the first
 * file to name a root win means the extension never has to resolve which
 * variant is *selected* -- a question only `RBX_CONTEST` can answer, and one
 * whose answer is almost always the same letters anyway.
 */
async function contestFiles(root: string): Promise<string[]> {
  const files = [path.join(root, CONTEST_MANIFEST)];
  let entries: string[];
  try {
    entries = await fs.readdir(root);
  } catch {
    return files;
  }
  for (const entry of entries.sort()) {
    if (
      entry.startsWith(VARIANT_PREFIX) &&
      entry.endsWith(VARIANT_SUFFIX) &&
      entry !== CONTEST_MANIFEST
    ) {
      files.push(path.join(root, entry));
    }
  }
  return files;
}

/** Identities for every root that a contest names, keyed by absolute root. */
export async function indexContests(
  roots: readonly string[],
): Promise<Map<string, ProblemIdentity>> {
  const index = new Map<string, ProblemIdentity>();
  const scanned = new Set<string>();
  for (const root of roots) {
    const contestRoot = await findContestRoot(root);
    if (contestRoot === undefined || scanned.has(contestRoot)) {
      continue;
    }
    scanned.add(contestRoot);
    for (const file of await contestFiles(contestRoot)) {
      const identities = problemIdentities(contestRoot, parseContest(await readYamlFile(file)));
      for (const [key, identity] of identities) {
        // First file to name a root wins; canonical is read first.
        if (!index.has(key)) {
          index.set(key, identity);
        }
      }
    }
  }
  return index;
}
```

**Step 5: Run everything**

Run: `cd vscode && npm run test && npm run typecheck && npm run lint`
Expected: all PASS.

**Step 6: Commit**

```bash
git add vscode/src/rbx/contest.ts vscode/src/rbx/contest.test.ts vscode/src/contestIndex.ts
# /commit  ->  feat(vscode): resolve packages to the letters their contest gives them
```

---

## Task 3: The problem list

**Files:**
- Create: `vscode/src/rbx/problems.ts` (pure)
- Create: `vscode/src/rbx/problems.test.ts`

Turn discovered roots plus contest identities into the ordered list the dropdown renders. Pure, so ordering is tested without a workspace.

Ordering rules:
1. Problems in a contest come first, grouped by contest root, in declared `order`.
2. Packages in no contest follow, sorted by path (today's behaviour).
3. The **group label** is the contest root's directory name, used for `<optgroup>` when more than one group exists.

**Step 1: Write the failing tests**

```ts
import { strict as assert } from 'node:assert';
import { test } from 'node:test';

import { problemChoices } from './problems';

const identity = (shortName: string, order: number, color?: string) => ({
  shortName,
  order,
  color,
});

test('orders contest problems by their declared order, not by path', () => {
  // `/c/z` is `A` and sorts first despite sorting last lexicographically --
  // which is the whole point of reading the contest file.
  const choices = problemChoices(
    ['/c/a', '/c/z'],
    new Map([
      ['/c/z', identity('A', 0)],
      ['/c/a', identity('B', 1)],
    ]),
    () => 'fallback',
  );
  assert.deepEqual(choices.map((c) => c.label), ['A', 'B']);
  assert.deepEqual(choices.map((c) => c.root), ['/c/z', '/c/a']);
});

test('labels an uncontested package with the host fallback, after the contest', () => {
  const choices = problemChoices(
    ['/loose', '/c/A'],
    new Map([['/c/A', identity('A', 0)]]),
    (root) => `label:${root}`,
  );
  assert.deepEqual(choices.map((c) => c.label), ['A', 'label:/loose']);
});

test('carries the declared colour through', () => {
  const choices = problemChoices(['/c/A'], new Map([['/c/A', identity('A', 0, '#f00')]]), () => '');
  assert.equal(choices[0].color, '#f00');
});

test('groups by contest only when there is more than one group', () => {
  const one = problemChoices(['/c/A'], new Map([['/c/A', identity('A', 0)]]), () => '');
  assert.equal(one[0].group, undefined);

  const two = problemChoices(
    ['/x/A', '/y/A'],
    new Map([
      ['/x/A', identity('A', 0)],
      ['/y/A', identity('A', 0)],
    ]),
    () => '',
  );
  assert.deepEqual(two.map((c) => c.group), ['x', 'y']);
});

test('sorts uncontested packages by path', () => {
  const choices = problemChoices(['/b', '/a'], new Map(), (root) => root);
  assert.deepEqual(choices.map((c) => c.root), ['/a', '/b']);
});
```

**Step 2: Run to verify it fails**

Run: `cd vscode && npm run test`
Expected: FAIL — cannot find module `./problems`.

**Step 3: Implement**

```ts
/**
 * The problems the selector offers, in the order it offers them.
 *
 * Pure: the caller supplies the roots, the contest identities and a fallback
 * labeller, because naming a package with no contest needs `vscode.workspace`
 * to say which folder it sits in -- and this module's value is being testable
 * without the editor API. Same split as `PackageRunView.label`.
 */
import * as path from 'path';

import { ProblemIdentity } from './contest';

/** One entry in the dropdown. */
export interface ProblemChoice {
  readonly root: string;
  readonly label: string;
  /** The contest this belongs to, for `<optgroup>`. Absent when there is one group. */
  readonly group?: string;
  readonly color?: string;
}

/** How a package with no contest is named. Supplied by the host. */
export type FallbackLabel = (root: string) => string;

interface Entry {
  readonly root: string;
  readonly label: string;
  readonly color?: string;
  readonly group?: string;
  readonly order: number;
}

/**
 * The contest a root belongs to, as a grouping key.
 *
 * Derived from the root's own path rather than tracked through the index: a
 * problem's contest root is the only ancestor that named it, and for grouping
 * purposes its parent directory separates two contests exactly as well.
 */
function groupKeyOf(root: string): string {
  return path.dirname(root);
}

export function problemChoices(
  roots: readonly string[],
  identities: ReadonlyMap<string, ProblemIdentity>,
  fallback: FallbackLabel,
): ProblemChoice[] {
  const contested: Entry[] = [];
  const loose: Entry[] = [];
  for (const root of roots) {
    const identity = identities.get(root);
    if (identity === undefined) {
      loose.push({ root, label: fallback(root), order: 0 });
    } else {
      contested.push({
        root,
        label: identity.shortName,
        color: identity.color,
        group: groupKeyOf(root),
        order: identity.order,
      });
    }
  }

  contested.sort((a, b) => {
    const group = (a.group ?? '').localeCompare(b.group ?? '');
    return group !== 0 ? group : a.order - b.order;
  });
  loose.sort((a, b) => a.root.localeCompare(b.root));

  // One group is no grouping: an `<optgroup>` wrapping every option says
  // nothing and costs a row of chrome in a narrow sidebar.
  const groups = new Set(contested.map((entry) => entry.group));
  const grouped = groups.size > 1;

  return [...contested, ...loose].map((entry) => ({
    root: entry.root,
    label: entry.label,
    color: entry.color,
    group: grouped && entry.group !== undefined ? path.basename(entry.group) : undefined,
  }));
}
```

**Step 4: Run everything**

Run: `cd vscode && npm run test && npm run typecheck && npm run lint`
Expected: all PASS.

**Step 5: Commit**

```bash
git add vscode/src/rbx/problems.ts vscode/src/rbx/problems.test.ts
# /commit  ->  feat(vscode): order the problems a selector would offer
```

---

## Task 4: Scope the view model to one package

**Files:**
- Modify: `vscode/src/rbx/nodes.ts:85-107` (`flattenNodes`)
- Modify: `vscode/src/rbx/nodes.ts:14-19` (delete `PackageNode`)
- Modify: `vscode/src/rbx/viewModel.ts:655-673` (delete `packageRow`), `:819-868` (`buildViewModel`)
- Modify: `vscode/src/rbx/nodes.test.ts`, `vscode/src/rbx/viewModel.test.ts`

This is the breaking change. `flattenNodes` takes **one** `PackageRunView` and never emits a package row.

**Step 1: Update the existing tests first**

Read `nodes.test.ts` and `viewModel.test.ts` and rewrite every case that passes an array or asserts on a `package` row. Delete tests that only covered the multi-package flatten and the `showPackages` rule — they are asserting behaviour this task removes. Add:

```ts
test('emits no package row', () => {
  const nodes = flattenNodes({ pkg, run });
  assert.equal(nodes.some((node) => node.kind === 'package'), false);
});

test('yields nothing for a package with no run', () => {
  assert.deepEqual(flattenNodes({ pkg, run: undefined }), []);
});
```

**Step 2: Run to verify they fail**

Run: `cd vscode && npm run test`
Expected: FAIL — `flattenNodes` still expects an array.

**Step 3: Implement**

In `nodes.ts`: delete the `PackageNode` interface, drop `'package'` from the `RunNode` union and from `nodeId`, and replace `flattenNodes`:

```ts
/**
 * Every row of one package's run, in display order, parents before children.
 *
 * One package, because the view shows one: the selector upstream decides which,
 * so there is no package level left to draw and no rule about when to draw it.
 */
export function flattenNodes(view: PackageRunView): RunNode[] {
  const { pkg, run } = view;
  if (run === undefined) {
    return [];
  }
  const nodes: RunNode[] = [];
  const solo = run.solutions.length === 1;
  for (const solutionRun of run.solutions) {
    nodes.push({ kind: 'solution', pkg, run: solutionRun, solo });
    for (const group of solutionRun.groups) {
      nodes.push({ kind: 'group', pkg, run: solutionRun, group });
      for (const testcase of group.testcases) {
        nodes.push({ kind: 'testcase', pkg, run: solutionRun, group, testcase });
      }
    }
  }
  return nodes;
}
```

In `viewModel.ts`: delete `packageRow` and `packageName`, drop the `PackageNode` import and the `'package'` case from the switch, and simplify `buildViewModel`:

```ts
export function buildViewModel(
  view: PackageRunView,
  style: SolutionLabelStyle = DEFAULT_SOLUTION_LABEL_STYLE,
): RunViewModel {
  const nodes = flattenNodes(view);
  // One package, so labels are trimmed against its solutions alone -- which is
  // what `labelsByPackage` was always computing per package anyway.
  const labels = solutionLabels(
    view.run?.solutions.map((solution) => solution.solution.path) ?? [],
    style,
  );
  const parents = new Map<number, string>();

  const rows: Row[] = [];
  for (const node of nodes) {
    // No offset: with the package level gone, a solution is always depth 0.
    const depth = DEPTHS[node.kind] - 1;
    const parentId = parents.get(depth - 1);
    const row = ((): Row => {
      switch (node.kind) {
        case 'solution': {
          const path = node.run.solution.path;
          return solutionRow(node, depth, labels.get(path) ?? path, parentId);
        }
        case 'group':
          return groupRow(node, depth, parentId);
        case 'testcase':
          return testcaseRow(node, depth, parentId);
      }
    })();
    rows.push(row);
    parents.set(depth, row.id);
  }

  return {
    rows,
    mismatches: rows.filter((row) => row.kind === 'solution' && row.gutter === 'missed').length,
    warned: rows.filter(
      (row) => row.kind === 'solution' && row.gutter !== 'missed' && row.warnings.length > 0,
    ).length,
    empty: !rows.some((row) => row.kind === 'solution'),
  };
}
```

Check `solutionLabels`' real signature in `vscode/src/rbx/solutionLabel.ts` before writing this — adapt the call to what it actually takes. Delete `labelsByPackage` (`viewModel.ts:585`) once nothing calls it, and drop `'package'` from the `Row['kind']` union and from `DEPTHS`.

**Step 4: Run everything**

Run: `cd vscode && npm run test && npm run typecheck && npm run lint`
Expected: PASS. `typecheck` is what proves no `'package'` case survives anywhere; fix every error it reports rather than casting past it.

**Step 5: Commit**

```bash
git add vscode/src/rbx/
# /commit  ->  refactor(vscode): build the run model from one package
```

---

## Task 5: The ActiveProblem service

**Files:**
- Create: `vscode/src/activeProblem.ts` (host half)
- Modify: `vscode/src/runData.ts` (expose the roots; keep `discovered()` intact)

`DeclaredIndex` (`vscode/src/declared.ts:29`) calls `data.discovered()` to index **every** package's manifest, and Explorer badges, the solution lens and the status bar all draw from it. **Those stay workspace-wide.** Narrowing `discovered()` would silently strip badges off every unselected problem. Do not touch it.

**Step 1: Implement**

```ts
/**
 * Which problem the Run view is showing.
 *
 * The single source of truth for the selection: the dropdown, the quick pick
 * and the auto-switch all go through here, so they cannot disagree about what
 * is on screen.
 */
import * as vscode from 'vscode';

import { indexContests } from './contestIndex';
import { packageLabel } from './discovery';
import { log } from './log';
import { ProblemChoice, problemChoices } from './rbx/problems';
import { packageLayout } from './rbx/layout';
import { RunDataProvider } from './runData';

const SELECTED_KEY = 'rbx.selectedProblem';

export class ActiveProblem {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChange: vscode.Event<void> = this.changed.event;

  private choices: ProblemChoice[] = [];
  private selectedRoot?: string;

  constructor(
    private readonly data: RunDataProvider,
    private readonly memento: vscode.Memento,
  ) {
    this.selectedRoot = memento.get<string>(SELECTED_KEY);
  }

  /** Rebuild the list after discovery, keeping the selection if it survived. */
  async refresh(): Promise<void> {
    const roots = (await this.data.discovered()).map((pkg) => pkg.root);
    const identities = await indexContests(roots);
    this.choices = problemChoices(roots, identities, (root) => packageLabel(packageLayout(root)));
    if (!this.choices.some((choice) => choice.root === this.selectedRoot)) {
      // The selected package went away -- deleted, renamed, or moved out of the
      // glob. Falling back to the first keeps the view showing *something*.
      this.selectedRoot = this.choices[0]?.root;
    }
    this.changed.fire();
  }

  problems(): readonly ProblemChoice[] {
    return this.choices;
  }

  selected(): string | undefined {
    return this.selectedRoot;
  }

  /** Show a problem. No-op when it is already showing, or is not a problem. */
  select(root: string): void {
    if (root === this.selectedRoot || !this.choices.some((choice) => choice.root === root)) {
      return;
    }
    this.selectedRoot = root;
    void this.memento.update(SELECTED_KEY, root);
    log(`Showing ${root}.`);
    this.changed.fire();
  }

  /**
   * Follow a run that just started.
   *
   * rbx writes `skeleton.yml` when a run *begins* (rbx/box/solutions.py:746),
   * so this tracks the problem currently running rather than jumping to one
   * that already finished -- during `rbx contest each run` the view walks the
   * contest in step with it.
   *
   * Unlike `select`, an unknown root is not ignored: a package can be created
   * and run before discovery has seen it, and dropping the switch there would
   * leave the view on the wrong problem until the next rediscovery.
   */
  async follow(root: string): Promise<void> {
    if (!this.choices.some((choice) => choice.root === root)) {
      await this.refresh();
    }
    this.select(root);
  }
}
```

**Step 2: Run typecheck**

Run: `cd vscode && npm run typecheck && npm run lint`
Expected: PASS. Adjust the `packageLabel`/`packageLayout` imports to their real signatures.

**Step 3: Commit**

```bash
git add vscode/src/activeProblem.ts
# /commit  ->  feat(vscode): track which problem the run view is showing
```

---

## Task 6: Post one problem, and the dropdown

**Files:**
- Modify: `vscode/src/runView.ts` (`post`, message handling, `html`)
- Modify: `vscode/src/webview/render.ts` (add `renderSelector`)
- Modify: `vscode/src/webview/main.ts` (render it, post changes back)
- Modify: `vscode/src/webview/style.css`
- Modify: `vscode/src/webview/render.test.ts`

**Step 1: Host — post one package**

In `runView.ts`, take an `ActiveProblem` in the constructor and rewrite `post`:

```ts
private async post(): Promise<void> {
  const selected = this.active.selected();
  const view =
    selected === undefined
      ? undefined
      : { pkg: packageLayout(selected), run: await this.data.report(packageLayout(selected)) };
  this.nodes = new Map(
    (view === undefined ? [] : flattenNodes(view)).map((node) => [nodeId(node), node]),
  );
  const style = asSolutionLabelStyle(
    vscode.workspace.getConfiguration('rbx').get('solutionLabel'),
  );
  await this.view?.webview.postMessage({
    type: 'state',
    model: view === undefined ? EMPTY_MODEL : buildViewModel(view, style),
    problems: this.active.problems(),
    selected,
  });
}
```

`data.report(pkg)` already exists (`runData.ts:93`) and goes through the per-package `ArtifactStore` cache. **`loadAll` should now have no callers — delete it.** Subscribe to `active.onDidChange` alongside `data.onDidChange`, and handle the new client message:

```ts
if (message.type === 'select' && message.root !== undefined) {
  this.active.select(message.root);
  return;
}
```

Add a `<div id="selector-host"></div>` to the HTML shell, above `#header`.

**Step 2: Client — write the failing test** in `render.test.ts`

```ts
test('renders one option per problem, marking the selected one', () => {
  const html = renderSelector(
    [
      { root: '/c/A', label: 'A' },
      { root: '/c/B', label: 'B' },
    ],
    '/c/B',
  );
  assert.match(html, /<option value="\/c\/A"[^>]*>A<\/option>/);
  assert.match(html, /<option value="\/c\/B" selected[^>]*>B<\/option>/);
});

test('renders nothing for a single problem', () => {
  assert.equal(renderSelector([{ root: '/only', label: 'only' }], '/only'), '');
});

test('groups options when the problems carry groups', () => {
  const html = renderSelector(
    [
      { root: '/x/A', label: 'A', group: 'x' },
      { root: '/y/A', label: 'A', group: 'y' },
    ],
    '/x/A',
  );
  assert.match(html, /<optgroup label="x">/);
  assert.match(html, /<optgroup label="y">/);
});

test('escapes a label and a root', () => {
  const html = renderSelector([{ root: '/a"b', label: '<script>' }, { root: '/c', label: 'c' }], '/c');
  assert.equal(html.includes('<script>'), false);
  assert.equal(html.includes('"/a"b"'), false);
});
```

**Step 3: Run to verify it fails**

Run: `cd vscode && npm run test`
Expected: FAIL — `renderSelector` is not exported.

**Step 4: Implement `renderSelector`** in `render.ts`, reusing the existing `escapeHtml`/`escapeAttr`:

```ts
/**
 * The problem dropdown.
 *
 * Hidden for a single problem: a select with one option is a control that
 * cannot do anything, and a one-problem workspace should look exactly as it did
 * before the selector existed.
 *
 * The colour dot is a `style` attribute, which the CSP permits on styles only
 * (see the note in runView.ts) -- and the value is a colour a contest author
 * wrote, so it goes through `escapeAttr` like everything else.
 */
export function renderSelector(problems: readonly ProblemChoice[], selected?: string): string {
  if (problems.length <= 1) {
    return '';
  }
  const option = (problem: ProblemChoice): string =>
    `<option value="${escapeAttr(problem.root)}"${problem.root === selected ? ' selected' : ''}>` +
    escapeHtml(problem.label) +
    '</option>';

  let body = '';
  let openGroup: string | undefined;
  for (const problem of problems) {
    if (problem.group !== openGroup) {
      body += openGroup === undefined ? '' : '</optgroup>';
      openGroup = problem.group;
      body += openGroup === undefined ? '' : `<optgroup label="${escapeAttr(openGroup)}">`;
    }
    body += option(problem);
  }
  body += openGroup === undefined ? '' : '</optgroup>';

  const dot = problems.find((problem) => problem.root === selected)?.color;
  return (
    '<div class="selector">' +
    (dot === undefined ? '' : `<span class="selector-dot" style="background:${escapeAttr(dot)}"></span>`) +
    `<select id="problem">${body}</select>` +
    '</div>'
  );
}
```

Note the grouped/ungrouped mix cannot interleave, because `problemChoices` sorts by group — the single-pass open/close above is safe *because* of that ordering.

**Step 5: Wire the client** in `main.ts`

Hold `problems`/`selected` from the `state` message, render into `#selector-host` inside `renderAll`, and post back on change:

```ts
selectorHost.addEventListener('change', (event) => {
  const target = event.target as HTMLSelectElement;
  if (target.id === 'problem') {
    vscode.postMessage({ type: 'select', root: target.value });
  }
});
```

Do **not** persist the selection in webview state — the host owns it and re-posts it. Persisting it in both places is how they drift.

**Step 6: Style it.** Add `.selector` (flex row, full width, small bottom margin) and `.selector-dot` (a ~8px circle, `border-radius:50%`, `flex:none`) to `style.css`, matching the existing `.filter` rules.

**Step 7: Run everything**

Run: `cd vscode && npm run test && npm run typecheck && npm run lint`
Expected: all PASS.

**Step 8: Commit**

```bash
git add vscode/src/runView.ts vscode/src/webview/ vscode/src/runData.ts
# /commit  ->  feat(vscode): pick the problem the run view shows
```

---

## Task 7: Auto-switch, and the quick pick

**Files:**
- Modify: `vscode/src/extension.ts` (construct `ActiveProblem`, add the skeleton watcher, refresh)
- Modify: `vscode/src/commands.ts` (add `rbx.selectProblem`)
- Modify: `vscode/package.json` (contribute the command; **delete `rbx.packageSearchDepth`**)

**Step 1: Construct and refresh.** In `activate`, build `ActiveProblem` with `context.workspaceState`, pass it to `RunViewProvider`, and refresh it inside `rediscover` **after** `data.refresh()` so it sees the new roots:

```ts
const rediscover = () => {
  void data.refresh().then(() => Promise.all([declared.refresh(), active.refresh()]));
};
```

**Step 2: Watch the skeleton.**

```ts
// `skeleton.yml` is written when a run *starts* (rbx/box/solutions.py:746 --
// "A new skeleton is what marks a new run"), so following it makes the view
// track the problem currently running: `rbx contest each run` walks the view
// through the contest in step with the run itself.
const skeletons = vscode.workspace.createFileSystemWatcher(`**/${CACHE_DIR}/runs/skeleton.yml`);
const followRun = (uri: vscode.Uri) => {
  const root = packageRootOf(uri.fsPath);
  if (root !== undefined) {
    void active.follow(root);
  }
};
skeletons.onDidCreate(followRun);
skeletons.onDidChange(followRun);
context.subscriptions.push(skeletons);
```

Only create and change — **not delete**. `rbx clean` removes the skeleton, and switching to a package whose run was just deleted is the opposite of following work.

**Step 3: The quick pick,** in `commands.ts`:

```ts
vscode.commands.registerCommand('rbx.selectProblem', async () => {
  const problems = active.problems();
  if (problems.length === 0) {
    void vscode.window.showInformationMessage('No rbx problem found in this workspace.');
    return;
  }
  const picked = await vscode.window.showQuickPick(
    problems.map((problem) => ({
      label: problem.label,
      description: problem.group,
      detail: problem.root,
      root: problem.root,
    })),
    { placeHolder: 'Show which problem in the Run view?' },
  );
  if (picked !== undefined) {
    active.select(picked.root);
  }
});
```

**Step 4: Contribute it** in `package.json` — `{"command": "rbx.selectProblem", "title": "Select Problem", "category": "rbx"}` — and add a `view/title` menu entry with `"when": "view == rbx.run"`.

**Step 5: Delete the dead setting.** Remove the whole `rbx.packageSearchDepth` block from `contributes.configuration.properties`. It is contributed with a default of 3 and read nowhere in `src/`; discovery has always globbed unbounded. While here, delete `IGNORED_DIRS` (`vscode/src/rbx/layout.ts:119`) — exported, unused, and already drifted from the real exclusion glob in `discovery.ts:12`.

Verify both are gone:

```bash
cd vscode && grep -rn "packageSearchDepth\|IGNORED_DIRS" src package.json
```
Expected: no output.

**Step 6: Run everything**

Run: `cd vscode && npm run test && npm run typecheck && npm run lint`
Expected: all PASS.

**Step 7: Commit**

```bash
git add vscode/src/extension.ts vscode/src/commands.ts vscode/package.json vscode/src/rbx/layout.ts
# /commit  ->  feat(vscode): follow the problem that is running
```

---

## Task 8: Manual verification

Automated tests cover the pure half; the wiring needs eyes. Build a scratch contest and press on it.

**Step 1: Launch.** Open `vscode/` in VS Code, press F5 for an Extension Development Host, and open a real multi-problem contest in it.

**Step 2: Walk the checklist.**

| # | Check | Expected |
|---|---|---|
| 1 | Open the Run view | A dropdown listing problems as `A`, `B`, `C` — contest order, not path order |
| 2 | Pick `C` | Only C's solutions. No package row, no extra indent |
| 3 | Header strip | Counts describe C alone, not the workspace |
| 4 | `cd A && rbx run` | View switches to A and fills in live |
| 5 | `rbx contest each run` | View walks A → B → C in step with the run |
| 6 | Reload the window | Comes back on the last-selected problem |
| 7 | Open a single-problem package | No dropdown at all; view looks as it did before |
| 8 | Explorer badges on an **unselected** problem | Still present — `DeclaredIndex` stays workspace-wide |
| 9 | `rbx: Select Problem` from the palette | Quick pick, same list, same order |
| 10 | Delete the selected package's directory | Falls back to the first problem; no error |
| 11 | `rbx clean` in the selected package | View empties; does **not** switch away |

**Step 3: Update the README.** `vscode/README.md` describes the view; add the selector and the auto-switch rule.

**Step 4: Commit**

```bash
git add vscode/README.md
# /commit  ->  docs(vscode): describe the problem selector
```

---

## Done when

- `npm run test`, `npm run typecheck` and `npm run lint` all pass.
- No `'package'` row kind survives anywhere (`grep -rn "'package'" vscode/src` is empty).
- `packageSearchDepth` and `IGNORED_DIRS` are gone.
- The Task 8 checklist passes end to end.
