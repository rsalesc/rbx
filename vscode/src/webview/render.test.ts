import * as assert from 'assert';
import { test } from 'node:test';

import type { Row, RunViewModel } from '../rbx/viewModel';
import {
  UiState,
  escapeAttr,
  escapeHtml,
  matchesFilter,
  renderHeader,
  renderTree,
  visibleRows,
} from './render';

// The fixtures are written as `Row`s rather than run through `buildViewModel`:
// the renderer's contract is the row, and building one from a fake package run
// would make these tests fail for reasons that belong to viewModel.test.ts.

function row(over: Partial<Row> & Pick<Row, 'id'>): Row {
  return {
    depth: 0,
    kind: 'solution',
    gutter: 'none',
    label: over.id,
    labelBold: false,
    meta: [],
    mismatch: false,
    expandable: false,
    defaultExpanded: false,
    search: (over.label ?? over.id).toLowerCase(),
    section: 'rbx.solution',
    ...over,
  };
}

function model(rows: readonly Row[]): RunViewModel {
  return {
    rows,
    mismatches: rows.filter((r) => r.kind === 'solution' && r.mismatch).length,
    empty: !rows.some((r) => r.kind === 'solution'),
  };
}

function state(over: Partial<UiState> = {}): UiState {
  return { expanded: new Set<string>(), filter: '', ...over };
}

const MAIN = row({
  id: 'sol0',
  kind: 'solution',
  label: 'sols/main.cpp',
  labelHue: 'green',
  labelBold: true,
  gutter: 'met',
  expandable: true,
  verdict: { icon: 'pass', hue: 'green', short: 'AC' },
  search: 'sols/main.cpp ac',
  detail: { histogram: [{ short: 'AC', hue: 'green', count: 3 }], maxTime: '120 ms' },
});

const MAIN_GROUP = row({
  id: 'sol0::main',
  parentId: 'sol0',
  depth: 1,
  kind: 'group',
  label: 'main',
  expandable: true,
  section: 'rbx.group',
  search: 'main ac',
});

const MAIN_CASE = row({
  id: 'sol0::main::000',
  parentId: 'sol0::main',
  depth: 2,
  kind: 'testcase',
  label: '000',
  section: 'rbx.testcase',
  search: 'main/000 ac',
  primaryCommand: 'rbx.openInput',
  verdict: { icon: 'pass', hue: 'green', short: 'AC' },
  meta: [{ text: '12 ms', hue: 'dim' }],
});

const MISLABELED = row({
  id: 'sol1',
  kind: 'solution',
  label: 'sols/mislabeled.cpp',
  labelHue: 'red',
  gutter: 'missed',
  mismatch: true,
  expandable: true,
  verdict: { icon: 'close', hue: 'red', short: 'WA' },
  search: 'sols/mislabeled.cpp wa mismatch',
  detail: {
    mismatch: { declared: 'INCORRECT', observed: 'WA', failedGroups: ['small', 'big'] },
    histogram: [],
  },
});

const TREE = model([MAIN, MAIN_GROUP, MAIN_CASE, MISLABELED]);

test('escapeHtml neutralizes markup in text', () => {
  assert.strictEqual(escapeHtml('<b>&</b>'), '&lt;b&gt;&amp;&lt;/b&gt;');
});

test('escapeAttr escapes single quotes, which delimit data-vscode-context', () => {
  assert.strictEqual(escapeAttr("it's"), 'it&#39;s');
  assert.strictEqual(escapeAttr('"x"'), '&quot;x&quot;');
});

test('a group named like an injection produces no raw markup', () => {
  const evil = '<img src=x onerror=alert(1)>';
  const html = renderTree(
    model([
      MAIN,
      row({
        id: `sol0::${evil}`,
        parentId: 'sol0',
        depth: 1,
        kind: 'group',
        label: evil,
        expandable: true,
        section: 'rbx.group',
        search: evil.toLowerCase(),
      }),
    ]),
    state({ expanded: new Set(['sol0']) }),
  );
  // The angle brackets are the whole attack; `onerror=alert(1)` surviving as
  // inert text is fine and is what escaping is supposed to leave behind.
  assert.ok(!html.includes(evil), html);
  assert.ok(!html.includes('<img'), html);
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'), html);
});

test('a collapsed row hides its children', () => {
  const ids = visibleRows(TREE, state()).map((r) => r.id);
  assert.deepStrictEqual(ids, ['sol0', 'sol1']);
});

test('an expanded row shows the children of that row only', () => {
  const ids = visibleRows(TREE, state({ expanded: new Set(['sol0']) })).map((r) => r.id);
  assert.deepStrictEqual(ids, ['sol0', 'sol0::main', 'sol1']);
});

test('matchesFilter is a case-insensitive substring of the search haystack', () => {
  assert.ok(matchesFilter(MISLABELED, ''));
  assert.ok(matchesFilter(MISLABELED, '  MISmatch '));
  assert.ok(!matchesFilter(MAIN, 'mismatch'));
});

test('filtering by mismatch keeps the missed solution and drops the met one', () => {
  const ids = visibleRows(TREE, state({ filter: 'mismatch' })).map((r) => r.id);
  assert.deepStrictEqual(ids, ['sol1']);
});

test('filtering by a testcase stem keeps that testcase and its ancestors', () => {
  const ids = visibleRows(
    TREE,
    state({ filter: '000', expanded: new Set(['sol0', 'sol0::main']) }),
  ).map((r) => r.id);
  assert.deepStrictEqual(ids, ['sol0', 'sol0::main', 'sol0::main::000']);
});

test('a matching solution keeps its collapsed children hidden', () => {
  const ids = visibleRows(TREE, state({ filter: 'main.cpp' })).map((r) => r.id);
  assert.deepStrictEqual(ids, ['sol0']);
});

test('renderHeader stays out of the way when nothing missed its declaration', () => {
  assert.strictEqual(renderHeader(model([MAIN]), state()), '');
});

test('renderHeader counts the misses against the solutions', () => {
  const html = renderHeader(TREE, state());
  assert.ok(html.includes('1 of 2 did not match'), html);
  assert.ok(html.includes('id="next-mismatch"'), html);
});

test('aria-expanded is absent on a leaf and present on an expandable row', () => {
  const html = renderTree(
    model([MAIN, MAIN_GROUP, MAIN_CASE]),
    state({ expanded: new Set(['sol0', 'sol0::main']) }),
  );
  const leaf = html.slice(html.indexOf('data-id="sol0::main::000"'));
  assert.ok(!leaf.includes('aria-expanded'), leaf);
  assert.ok(html.includes('aria-expanded="true"'), html);
});

test('a collapsed expandable row reports aria-expanded false', () => {
  const html = renderTree(model([MAIN, MAIN_GROUP]), state());
  assert.ok(html.includes('aria-expanded="false"'), html);
});

test('siblings are counted among the rows actually on screen', () => {
  const html = renderTree(TREE, state({ expanded: new Set(['sol0']) }));
  const child = html.slice(html.indexOf('data-id="sol0::main"'));
  assert.ok(child.includes('aria-setsize="1"'), child);
  assert.ok(child.includes('aria-posinset="1"'), child);
  assert.ok(html.includes('aria-level="1"'), html);
  assert.ok(child.includes('aria-level="2"'), child);
});

test('indentation grows with depth and the twisty column survives on a leaf', () => {
  const html = renderTree(
    model([MAIN, MAIN_GROUP, MAIN_CASE]),
    state({ expanded: new Set(['sol0', 'sol0::main']) }),
  );
  assert.ok(html.includes('padding-left: 8px'), html);
  assert.ok(html.includes('padding-left: 32px'), html);
  assert.ok(html.includes('<span class="twisty"></span>'), html);
  assert.ok(html.includes('<span class="gutter"></span>'), html);
  assert.ok(html.includes('<span class="gutter gutter-met">'), html);
});

test('a row with no meta emits no meta column, and one with meta does', () => {
  const html = renderTree(
    model([MAIN, MAIN_GROUP, MAIN_CASE]),
    state({ expanded: new Set(['sol0', 'sol0::main']) }),
  );
  assert.strictEqual(html.match(/class="meta"/g)?.length, 1);
  assert.ok(html.includes('<span class="span hue-dim">12 ms</span>'), html);
});

test('a pending solution grows no empty detail card', () => {
  const pending = row({
    id: 'sol0',
    kind: 'solution',
    label: 'sols/main.cpp',
    expandable: true,
    verdict: { icon: 'circle-outline', hue: 'dim', short: '?' },
    detail: { histogram: [] },
  });
  const html = renderTree(model([pending]), state({ expanded: new Set(['sol0']) }));
  assert.ok(!html.includes('class="detail"'), html);
});

test('a detail card only appears under an expanded solution', () => {
  assert.ok(!renderTree(TREE, state()).includes('class="detail"'));
  assert.ok(renderTree(TREE, state({ expanded: new Set(['sol1']) })).includes('class="detail"'));
});

test('the mismatch card names every failing group in a sentence', () => {
  const html = renderTree(TREE, state({ expanded: new Set(['sol1']) }));
  assert.ok(html.includes('Declared INCORRECT, but small, big did not match.'), html);
});

test('the mismatch card names the observed outcome when no group is named', () => {
  const caught = row({
    id: 'sol2',
    kind: 'solution',
    label: 'sols/x.cpp',
    gutter: 'missed',
    mismatch: true,
    expandable: true,
    detail: {
      mismatch: { declared: 'INCORRECT', observed: 'AC', failedGroups: [] },
      histogram: [],
    },
  });
  const html = renderTree(model([caught]), state({ expanded: new Set(['sol2']) }));
  assert.ok(html.includes('Declared INCORRECT, but got AC.'), html);
});

test('the histogram sizes each bar by its share of the testcases', () => {
  const solution = row({
    id: 'sol0',
    kind: 'solution',
    label: 'sols/main.cpp',
    expandable: true,
    detail: {
      histogram: [
        { short: 'AC', hue: 'green', count: 3 },
        { short: 'WA', hue: 'red', count: 1 },
      ],
      score: '10/20',
    },
  });
  const html = renderTree(model([solution]), state({ expanded: new Set(['sol0']) }));
  assert.ok(html.includes('width: 75%'), html);
  assert.ok(html.includes('width: 25%'), html);
  assert.ok(html.includes('3 AC'), html);
  assert.ok(html.includes('1 WA'), html);
  assert.ok(html.includes('10/20'), html);
});

test('the detail card omits maxima it does not have', () => {
  const html = renderTree(model([MAIN]), state({ expanded: new Set(['sol0']) }));
  assert.ok(html.includes('120 ms'), html);
  assert.ok(!html.includes('Max memory'), html);
  assert.ok(!html.includes('Score'), html);
});

test('the empty model renders the welcome copy that viewsWelcome used to hold', () => {
  const html = renderTree(model([]), state());
  assert.ok(html.includes('No rbx run found in this workspace.'), html);
  assert.ok(
    html.includes('Run <code>rbx run</code> in the terminal and the results will show up here.'),
    html,
  );
  assert.ok(!html.includes('class="row'), html);
});

test('every row carries the context menu section and its node id', () => {
  const html = renderTree(model([MAIN]), state());
  assert.ok(
    html.includes(
      'data-vscode-context=\'{&quot;webviewSection&quot;:&quot;rbx.solution&quot;,' +
        '&quot;rbxNodeId&quot;:&quot;sol0&quot;,&quot;preventDefaultContextMenuItems&quot;:true}\'',
    ),
    html,
  );
});

test('the selected row is the one that holds the tab stop', () => {
  const html = renderTree(TREE, state({ selected: 'sol1' }));
  const selected = html.slice(html.indexOf('data-id="sol1"'));
  assert.ok(selected.includes('aria-selected="true"'), selected);
  assert.ok(selected.includes('tabindex="0"'), selected);
  assert.strictEqual(html.match(/tabindex="0"/g)?.length, 1);
});
