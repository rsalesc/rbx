import * as assert from 'assert';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

import type { FindingRow, Findings, Row, RunViewModel } from '../rbx/viewModel';
import {
  UiState,
  escapeAttr,
  escapeHtml,
  matchesFilter,
  renderCard,
  renderFilter,
  renderFindings,
  renderHeader,
  renderSelector,
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
    warnings: [],
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
    warned: rows.filter((r) => r.kind === 'solution' && !r.mismatch && r.warnings.length > 0)
      .length,
    empty: !rows.some((r) => r.kind === 'solution'),
  };
}

function state(over: Partial<UiState> = {}): UiState {
  return { expanded: new Set<string>(), filter: '', findingsOpen: false, ...over };
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
  expectation: {
    label: 'INCORRECT',
    hue: 'red',
    bold: false,
    glyph: '\u2717',
    badge: '\u2717?',
  },
  search: 'sols/mislabeled.cpp wa incorrect mismatch',
  detail: {
    // The trap this card exists for: the pooled INCORRECT *held*, so there is
    // no `pooled` clause -- only the per-group layer failed.
    mismatch: {
      pooledHeld: 'INCORRECT',
      groups: [
        {
          name: 'small',
          declared: 'TLE',
          declaredHue: 'yellow',
          observed: 'AC',
          observedHue: 'green',
        },
        {
          name: 'big',
          declared: 'TLE',
          declaredHue: 'yellow',
          observed: 'WA',
          observedHue: 'red',
        },
      ],
    },
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
  assert.ok(html.includes('padding-left: 10px'), html);
  assert.ok(html.includes('padding-left: 34px'), html);
  assert.ok(html.includes('<span class="twisty"></span>'), html);
  assert.ok(html.includes('<span class="gutter"></span>'), html);
  assert.ok(html.includes('<span class="gutter gutter-met">'), html);
});

test('the meta line carries its roles and no separator elements of its own', () => {
  // The separators are drawn by the stylesheet, as a `::before` on every span
  // but the first. Emitting them here instead would leave one behind whenever
  // the ladder hides the span it divides, trailing a `·` off a narrowed row.
  const solution = row({
    id: 'sol0',
    kind: 'solution',
    label: 'sols/main.cpp',
    meta: [
      { text: '[70/100]', hue: 'yellow', role: 'score' },
      { text: '120 ms', hue: 'dim', role: 'time' },
      { text: '2 KiB', hue: 'dim', role: 'memory' },
    ],
  });
  const html = renderTree(model([solution]), state({}));
  assert.ok(html.includes('<span class="span span-score hue-yellow">[70/100]</span>'), html);
  assert.ok(html.includes('<span class="span span-time hue-dim">120 ms</span>'), html);
  assert.ok(html.includes('<span class="span span-memory hue-dim">2 KiB</span>'), html);
  // No `.sep` inside the meta line -- the stylesheet owns those now.
  const meta = html.slice(html.indexOf('<span class="meta">'), html.indexOf('</span></span>'));
  assert.ok(!meta.includes('class="sep"'), meta);
});

test('the responsive ladder hides a suffix of the meta line, score last', () => {
  // Pinned as a table because the *order* is the design, and it is expressed in
  // a stylesheet no unit test renders. The separator scheme in `metaCell` is
  // only correct while hiding removes a suffix: if a future breakpoint hid the
  // score while keeping the memory, the surviving line would start with a `·`.
  // The compiled test sits in out-test/webview; the stylesheet it is asserting
  // about is the source one, two levels up.
  const css = readFileSync(join(__dirname, '..', '..', 'src', 'webview', 'style.css'), 'utf8');
  const widthOf = (selector: string): number => {
    // The last query that names the selector is the width it disappears at.
    const queries = [...css.matchAll(/@container \(max-width: (\d+)px\)\s*\{([\s\S]*?)\n\}/g)];
    const hit = queries.find((q) => q[2].includes(selector));
    assert.ok(hit !== undefined, `no breakpoint hides ${selector}`);
    return Number(hit[1]);
  };
  const expectation = widthOf('.expectation {');
  const memory = widthOf('.span-memory');
  const time = widthOf('.span-time');
  const verdictName = widthOf('.verdict-name');
  const verdict = widthOf('.verdict {');
  // Strictly descending: each survives the one before it.
  assert.ok(
    expectation > memory && memory > time && time > verdictName && verdictName > verdict,
    `ladder out of order: ${[expectation, memory, time, verdictName, verdict].join(' > ')}`,
  );
  // The score is never named by any of them.
  assert.ok(!css.includes('.span-score'), 'the score must outlive every breakpoint');
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

test('a group-only miss says which declaration held and what each group wanted', () => {
  const html = renderTree(TREE, state({ expanded: new Set(['sol1']) }));
  // The correction, in one assertion: the pooled INCORRECT is named as having
  // *held*, and the groups are paired with the TLE they actually missed. The
  // sentence this replaces read `Declared INCORRECT, but small, big did not
  // match.`, which attached the groups to the one declaration that was met.
  assert.ok(html.includes('INCORRECT held for the solution as a whole'), html);
  assert.ok(html.includes('2 groups missed their <code>outcomePerGroup</code>'), html);
  assert.ok(html.includes('<span class="group-name">small</span>'), html);
  assert.ok(html.includes('<span class="hue-yellow">TLE</span>'), html);
  assert.ok(html.includes('<span class="hue-green">AC</span>'), html);
  // ...and nothing anywhere claims the solution's own declaration was missed.
  assert.ok(!html.includes('Declared <span class="hue-red">INCORRECT</span>'), html);
});

test('a pooled miss is stated as a declared/got pair and nothing more', () => {
  const caught = row({
    id: 'sol2',
    kind: 'solution',
    label: 'sols/x.cpp',
    gutter: 'missed',
    mismatch: true,
    expandable: true,
    detail: {
      mismatch: {
        pooled: {
          declared: 'AC',
          declaredHue: 'green',
          observed: 'WA',
          observedHue: 'red',
        },
        groups: [],
      },
      histogram: [],
    },
  });
  const html = renderTree(model([caught]), state({ expanded: new Set(['sol2']) }));
  assert.ok(html.includes('Declared <span class="hue-green">AC</span>'), html);
  assert.ok(html.includes('<span class="hue-red">WA</span>'), html);
  assert.ok(!html.includes('outcomePerGroup'), html);
});

test('a score miss names the range that was declared', () => {
  const caught = row({
    id: 'sol3',
    kind: 'solution',
    label: 'sols/x.cpp',
    gutter: 'missed',
    mismatch: true,
    expandable: true,
    detail: {
      mismatch: { groups: [], score: { expected: '40..60', got: '30', gotHue: 'yellow' } },
      histogram: [],
    },
  });
  const html = renderTree(model([caught]), state({ expanded: new Set(['sol3']) }));
  assert.ok(
    html.includes('Expected 40..60 pts, scored <span class="hue-yellow">30</span>.'),
    html,
  );
});

test('a group name in the card cannot escape into markup', () => {
  const caught = row({
    id: 'sol4',
    kind: 'solution',
    label: 'sols/x.cpp',
    gutter: 'missed',
    mismatch: true,
    expandable: true,
    detail: {
      mismatch: {
        groups: [
          {
            name: '<img src=x onerror=alert(1)>',
            declared: 'TLE',
            declaredHue: 'yellow',
            observed: 'AC',
            observedHue: 'green',
          },
        ],
      },
      histogram: [],
    },
  });
  const html = renderTree(model([caught]), state({ expanded: new Set(['sol4']) }));
  assert.ok(!html.includes('<img'), html);
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'), html);
});

test('a row spells its declaration beside the verdict, and reserves the cell without one', () => {
  // The gap the group rows fell into: the expectation had no channel of its
  // own, so a group declaring TLE through `outcomePerGroup` could only be a
  // hueless name with a warning next to it.
  const html = renderTree(TREE, state({}));
  assert.ok(
    html.includes('<span class="expectation hue-red"><span class="expectation-name">INCORRECT'),
    html,
  );
  // Reserved, not omitted, on the rows with nothing to declare -- the column
  // has to line up for the pair to be readable straight down.
  assert.ok(html.includes('<span class="expectation"></span>'), html);
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
      scoreHue: 'yellow',
    },
  });
  const html = renderTree(model([solution]), state({ expanded: new Set(['sol0']) }));
  assert.ok(html.includes('width: 75%'), html);
  assert.ok(html.includes('width: 25%'), html);
  assert.ok(html.includes('3 AC'), html);
  assert.ok(html.includes('1 WA'), html);
  assert.ok(html.includes('<span class="value-text hue-yellow">10/20</span>'), html);
});

test('the detail card omits maxima it does not have', () => {
  const html = renderTree(model([MAIN]), state({ expanded: new Set(['sol0']) }));
  // Neutral rather than unhued: a value with nothing to say about itself still
  // takes its colour from the `.hue-*` table, which is what leaves the score
  // free to say something with the same mechanism.
  assert.ok(html.includes('<span class="value-text hue-neutral">120 ms</span>'), html);
  assert.ok(!html.includes('Max memory'), html);
  assert.ok(!html.includes('Score'), html);
});

test('the empty model renders the welcome copy that viewsWelcome used to hold', () => {
  const html = renderTree(model([]), state());
  // One problem's, not the workspace's: nine of ten problems having run says
  // nothing about the one on screen.
  assert.ok(html.includes('No rbx run found for this problem.'), html);
  assert.ok(
    html.includes('Run <code>rbx run</code> in its directory and the results will show up here.'),
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

test('a selection filtered off screen lends its tab stop without its selection', () => {
  // `main.cpp` filters `sol1` away; the tree still needs one tab stop, but the
  // row that stands in for it is not the one the user picked.
  const html = renderTree(TREE, state({ selected: 'sol1', filter: 'main.cpp' }));
  assert.strictEqual(html.match(/tabindex="0"/g)?.length, 1);
  assert.ok(!html.includes('aria-selected="true"'), html);
});

test('the filter box escapes a quote rather than closing its own attribute', () => {
  const html = renderFilter(state({ filter: 'say "hi" & <b>' }));
  assert.ok(html.includes('value="say &quot;hi&quot; &amp; &lt;b&gt;"'), html);
  assert.ok(!html.includes('<b>'), html);
});

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
  // A select with one option is a control that cannot do anything, and the
  // one-problem workspace has to look exactly as it did before the selector.
  assert.strictEqual(renderSelector([{ root: '/only', label: 'only' }], '/only'), '');
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
  assert.strictEqual(html.match(/<\/optgroup>/g)?.length, 2);
});

test('closes the last group before the problems no contest claimed', () => {
  // The order `problemChoices` yields: every contested problem first, the loose
  // ones last. The loose options must land outside the group, and the group
  // must still be closed -- which is the one sequence a single-pass
  // open-on-change loop can get wrong.
  const html = renderSelector(
    [
      { root: '/x/A', label: 'A', group: 'x' },
      { root: '/x/B', label: 'B', group: 'x' },
      { root: '/loose', label: 'loose' },
    ],
    '/x/A',
  );
  assert.strictEqual(html.match(/<optgroup label="x">/g)?.length, 1);
  assert.strictEqual(html.match(/<\/optgroup>/g)?.length, 1);
  assert.match(html, /<\/optgroup><option value="\/loose">loose<\/option>/);
});

test('escapes a label and a root', () => {
  const html = renderSelector(
    [
      { root: '/a"b', label: '<script>' },
      { root: '/c', label: 'c' },
    ],
    '/c',
  );
  assert.strictEqual(html.includes('<script>'), false);
  assert.strictEqual(html.includes('"/a"b"'), false);
});

test('the dot takes the colour of the selected problem, escaped', () => {
  const html = renderSelector(
    [
      { root: '/c/A', label: 'A', color: 'red' },
      { root: '/c/B', label: 'B', color: 'blue"' },
    ],
    '/c/B',
  );
  assert.match(html, /class="selector-dot" style="background:blue&quot;"/);
});

test('a selected problem with no colour renders no dot', () => {
  const html = renderSelector(
    [
      { root: '/c/A', label: 'A' },
      { root: '/c/B', label: 'B' },
    ],
    '/c/A',
  );
  assert.strictEqual(html.includes('selector-dot'), false);
});

// Every verdict short name in outcome.ts, plus the pending and unknown ones.
// The list is spelled out because `DISPLAY` is private to that module; a new
// verdict that slips past this test still cannot slip past the invariant, which
// is that meta never consults the outcome at all.
const SHORT_NAMES = ['AC', 'SKIP', 'WA', 'TLE', 'ILE', 'MLE', 'RTE', 'OLE', 'FL', 'IE', 'CE', 'XX'];

/** The inner HTML of every meta column on screen -- the chip that follows is not part of it. */
function metaRegions(html: string): string[] {
  return [...html.matchAll(/<span class="meta">([\s\S]*?)(?=<span class="verdict|<\/div>)/g)].map(
    (match) => match[1],
  );
}

test('no verdict short name reaches the meta column', () => {
  // The verdict has its own chip; spelling it in the meta as well is the
  // conflation the view model exists to undo, and the renderer must not
  // reintroduce it by painting a verdict into that column.
  const html = renderTree(TREE, state({ expanded: new Set(['sol0', 'sol0::main']) }));
  const regions = metaRegions(html);
  assert.ok(regions.length > 0, html);
  for (const region of regions) {
    for (const short of SHORT_NAMES) {
      assert.ok(!region.includes(short), `${short} in meta: ${region}`);
    }
  }
});

test('an expanded solution points at its detail card and the card is not a tree group', () => {
  const html = renderTree(TREE, state({ expanded: new Set(['sol1']) }));
  assert.ok(html.includes('aria-describedby="detail:sol1"'), html);
  assert.ok(html.includes('<div class="detail" id="detail:sol1"'), html);
  assert.ok(!html.includes('role="group"'), html);
});

test('a row id with a space still names exactly one detail card', () => {
  const spaced = row({
    id: '/w/a::sols/my sol.cpp',
    kind: 'solution',
    label: 'sols/my sol.cpp',
    expandable: true,
    detail: { histogram: [], maxTime: '1 ms' },
  });
  const html = renderTree(model([spaced]), state({ expanded: new Set([spaced.id]) }));
  const described = /aria-describedby="([^"]*)"/.exec(html)?.[1];
  assert.ok(described !== undefined, html);
  assert.ok(!described.includes(' '), described);
  assert.ok(html.includes(`id="${described}"`), html);
});

test('a solution whose card is empty carries no aria-describedby', () => {
  const pending = row({
    id: 'sol0',
    kind: 'solution',
    label: 'sols/main.cpp',
    expandable: true,
    detail: { histogram: [] },
  });
  const html = renderTree(model([pending]), state({ expanded: new Set(['sol0']) }));
  assert.ok(!html.includes('aria-describedby'), html);
});

test('sibling rank follows model order across two families of siblings', () => {
  const second = row({
    id: 'sol0::other',
    parentId: 'sol0',
    depth: 1,
    kind: 'group',
    label: 'other',
    section: 'rbx.group',
    search: 'other',
  });
  const html = renderTree(
    model([MAIN, MAIN_GROUP, MAIN_CASE, second, MISLABELED]),
    state({ expanded: new Set(['sol0']) }),
  );
  const first = html.slice(html.indexOf('data-id="sol0::main"'));
  assert.ok(first.includes('aria-posinset="1"'), first);
  assert.ok(first.includes('aria-setsize="2"'), first);
  const other = html.slice(html.indexOf('data-id="sol0::other"'));
  assert.ok(other.includes('aria-posinset="2"'), other);
  const roots = html.slice(html.indexOf('data-id="sol1"'));
  assert.ok(roots.includes('aria-posinset="2"'), roots);
});

test('a shortened label carries its full path as a tooltip, escaped', () => {
  const html = renderTree(
    model([row({ id: 'sol0', label: 'main.cpp', labelTitle: 'sols/"a b"/main.cpp' })]),
    state(),
  );
  assert.ok(html.includes('title="sols/&quot;a b&quot;/main.cpp"'), html);
});

test('a row whose label is already the whole path gets no tooltip', () => {
  const html = renderTree(model([MAIN]), state());
  assert.ok(!html.includes('title='), html);
});

const WARNED = row({
  id: 'sol3',
  kind: 'solution',
  label: 'sols/slow.cpp',
  gutter: 'warned',
  expandable: true,
  verdict: { icon: 'watch', hue: 'yellow', short: 'TLE' },
  warnings: [{ kind: 'double-tl-passed', verdicts: [], groups: ['big'] }],
  detail: {
    histogram: [],
    warnings: [{ kind: 'double-tl-passed', verdicts: [], groups: ['big'] }],
  },
});

test('a warned row draws its mark in the gutter, and not as a miss', () => {
  const html = renderTree(model([WARNED]), state());
  assert.ok(html.includes('gutter-warned'));
  assert.ok(!html.includes('gutter-missed'));
  assert.ok(!html.includes('gutter-met'));
});

test('a warned row is washed and ruled like a miss, in the other colour', () => {
  // The mark alone is 14px in a 22px row. The rule and the wash are what make a
  // warned row findable without reading the sidebar, which is the whole point.
  const html = renderTree(model([WARNED]), state());
  assert.ok(/class="row kind-solution warned"/.test(html));
  assert.ok(!html.includes('mismatch'));
});

test('a row never carries both washes', () => {
  // `warned` is a gutter state and `missed` outranks it, so a mismatched row is
  // never also warned -- the two tints can never stack into a third colour.
  const both = row({
    id: 'sol7',
    kind: 'solution',
    gutter: 'missed',
    mismatch: true,
    warnings: [{ kind: 'double-tl-passed', verdicts: [], groups: [] }],
  });
  const html = renderTree(model([both]), state());
  assert.ok(html.includes('mismatch'));
  assert.ok(!/class="[^"]*\bwarned\b/.test(html));
});

test('the warning mark is not the TLE verdict icon it would sit beside', () => {
  // The mark used to be a clock at the far end of the row, which is where
  // `watch` -- time-limit-exceeded's own icon -- already sits, and a double-TL
  // warning only ever lands on a TLE row. It has to be findable next to one.
  const html = renderTree(model([WARNED]), state());
  const gutter = html.slice(html.indexOf('gutter-warned'));
  assert.ok(gutter.startsWith('gutter-warned"'));
  assert.ok(!gutter.slice(0, 200).includes('codicon-watch'));
});

test('an unwarned row draws the plain met tick', () => {
  const html = renderTree(model([MAIN]), state());
  assert.ok(html.includes('gutter-met'));
  assert.ok(!html.includes('gutter-warned'));
});

test('the gutter carries the warning as its tooltip', () => {
  const html = renderTree(model([WARNED]), state());
  assert.ok(html.includes('Still passed in double TL on big.'));
});

test('an expanded warned solution gets a card of its own', () => {
  const html = renderTree(model([WARNED]), state({ expanded: new Set(['sol3']) }));
  assert.ok(html.includes('class="warning-card"'));
  // Not folded into the mismatch card: this solution missed nothing.
  assert.ok(!html.includes('class="mismatch-card"'));
});

test('the double-TL verdicts warning names the verdicts it found', () => {
  const warned = row({
    id: 'sol4',
    kind: 'solution',
    expandable: true,
    detail: {
      histogram: [],
      warnings: [
        {
          kind: 'double-tl-verdicts',
          verdicts: [{ text: 'WA', hue: 'red' }],
          groups: ['big'],
        },
      ],
    },
  });
  const html = renderTree(model([warned]), state({ expanded: new Set(['sol4']) }));
  assert.ok(html.includes('Still finished in double TL, but failed with WA on big.'));
});

test('the sanitizer warning points at the stderr, the way the console does', () => {
  const warned = row({
    id: 'sol7',
    kind: 'solution',
    expandable: true,
    warnings: [{ kind: 'sanitizer', verdicts: [], groups: ['big'] }],
    detail: {
      histogram: [],
      warnings: [{ kind: 'sanitizer', verdicts: [], groups: ['big'] }],
    },
  });
  const html = renderTree(model([warned]), state({ expanded: new Set(['sol7']) }));
  assert.ok(html.includes("Sanitizer errors or warnings on big. See the testcase's stderr."));
});

test('a warning with no group attribution says nothing about groups', () => {
  const warned = row({
    id: 'sol5',
    kind: 'solution',
    expandable: true,
    detail: { histogram: [], warnings: [{ kind: 'double-tl-passed', verdicts: [], groups: [] }] },
  });
  const html = renderTree(model([warned]), state({ expanded: new Set(['sol5']) }));
  assert.ok(html.includes('Still passed in double TL.'));
});

test('a group name in a warning cannot escape into markup', () => {
  const warned = row({
    id: 'sol6',
    kind: 'solution',
    gutter: 'warned',
    warnings: [{ kind: 'double-tl-passed', verdicts: [], groups: ['<script>'] }],
  });
  const html = renderTree(model([warned]), state());
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
});

test('a testcase renders the hidden verdict as a gloss on its chip', () => {
  const leaf = row({
    id: 'tc0',
    kind: 'testcase',
    label: '1-gen-001',
    verdict: {
      icon: 'watch',
      hue: 'yellow',
      short: 'TLE',
      under: { text: 'WA', hue: 'red' },
    },
  });
  // With a solution above it: a model of testcases alone is `empty`, and an
  // empty model renders the welcome copy instead of any rows at all.
  const html = renderTree(model([MAIN, leaf]), state({ expanded: new Set(['sol0']) }));

  assert.ok(html.includes('class="verdict-under hue-red"'));
  assert.ok(html.includes('(WA)'));
  // Inside the verdict cell, after the name it glosses.
  assert.ok(html.indexOf('verdict-under') > html.indexOf('verdict-name'));
  assert.ok(html.includes('Would have been WA without the time limit'));
  // The gloss has to sit against the name, so the chip releases the width it
  // reserves for column alignment -- which this row was never going to keep.
  assert.ok(html.includes('verdict-glossed'));
});

test('a testcase with no hidden verdict renders no gloss', () => {
  const leaf = row({
    id: 'tc1',
    kind: 'testcase',
    verdict: { icon: 'pass', hue: 'green', short: 'AC' },
  });
  const html = renderTree(model([MAIN, leaf]), state({ expanded: new Set(['sol0']) }));
  assert.ok(html.includes('kind-testcase'));
  assert.ok(!html.includes('verdict-under'));
  // An unglossed chip keeps its reserved width: that is what lines the verdict
  // icons up down the column on every ordinary row.
  assert.ok(!html.includes('verdict-glossed'));
});

test('a run that warned but matched everywhere still gets a header strip', () => {
  // The whole point: before this, a package whose declarations all held showed
  // no strip at all, and rbx was printing a WARNING about it in the terminal.
  const html = renderHeader(model([WARNED]), state());
  assert.ok(html.includes('1 warned'));
  assert.ok(!html.includes('did not match'));
  // Nothing to walk to, so the button that walks mismatches is not offered.
  assert.ok(!html.includes('next-mismatch'));
});

test('a clean run with nothing warned still gets no header strip', () => {
  assert.strictEqual(renderHeader(model([MAIN]), state()), '');
});

// --- The Compilation Findings panel ------------------------------------------

function findingRow(over: Partial<FindingRow> & Pick<FindingRow, 'id'>): FindingRow {
  return {
    label: over.id,
    labelBold: false,
    severity: 'warning',
    summary: '1 warn',
    warnings: [],
    section: 'rbx.finding',
    ...over,
  };
}

function withFindings(rows: readonly FindingRow[]): RunViewModel {
  const errors = rows.some((row) => row.severity === 'error');
  const findings: Findings = {
    rows,
    badge: rows.length,
    hue: errors ? 'red' : 'yellow',
    errors,
    signature: rows.map((row) => row.id).join('|'),
  };
  return { ...model([MAIN]), findings };
}

const WARNED_FINDING = findingRow({
  id: 'f0',
  label: 'main.cpp',
  labelTitle: 'sols/main.cpp',
  labelHue: 'green',
  labelBold: true,
  summary: '2 warns',
  warnings: [
    { id: 'f0::0', line: 41, flag: '-Wsign-compare', title: 'comparison of integers' },
    { id: 'f0::1', line: 88, flag: '', title: 'something unflagged' },
  ],
});

const BROKEN_FINDING = findingRow({
  id: 'f1',
  label: 'broken.cpp',
  severity: 'error',
  summary: 'CE',
  labelHue: 'red',
  reason: "'g++' was not found",
});

test('a run with nothing to report draws no panel at all', () => {
  // Its presence is the signal, so a clean package must not carry a header
  // telling it there is nothing to see.
  assert.strictEqual(renderFindings(model([MAIN]), state()), '');
});

test('the header survives collapsing, and the badge with it', () => {
  // A warnings-only run never opens the panel by itself, so the badge is the
  // only thing that can carry the news.
  const html = renderFindings(withFindings([WARNED_FINDING]), state());
  assert.ok(html.includes('Compilation Findings'));
  assert.ok(html.includes('findings-badge hue-yellow'));
  assert.ok(html.includes('aria-expanded="false"'));
  // Collapsed means collapsed: no rows are drawn behind the header.
  assert.ok(!html.includes('finding-row'));
});

test('the badge reddens when something failed to compile', () => {
  const html = renderFindings(
    withFindings([WARNED_FINDING, BROKEN_FINDING]),
    state({ findingsOpen: true }),
  );
  assert.ok(html.includes('findings-badge hue-red'));
  assert.ok(html.includes('>2<'));
});

test('severity is carried by the row, and the label keeps the declaration', () => {
  const html = renderFindings(withFindings([BROKEN_FINDING]), state({ findingsOpen: true }));
  assert.ok(html.includes('severity-error'));
  // The label hue is the declaration, exactly as it is in the tree above: the
  // panel says how badly it compiled in the gutter and the wash, not in the name.
  assert.ok(html.includes('class="label hue-red"'));
  assert.ok(html.includes('CE'));
});

test('a failure names its reason in the row title', () => {
  const html = renderFindings(withFindings([BROKEN_FINDING]), state({ findingsOpen: true }));
  assert.ok(html.includes(escapeAttr("'g++' was not found")));
});

test('a row with no warnings offers nothing to expand', () => {
  const html = renderFindings(withFindings([BROKEN_FINDING]), state({ findingsOpen: true }));
  assert.ok(!html.includes('finding-twisty codicon'));
});

test('an expanded row lists where each warning is and what kind it is', () => {
  const html = renderFindings(
    withFindings([WARNED_FINDING]),
    state({ findingsOpen: true, expanded: new Set(['f0']) }),
  );
  assert.ok(html.includes('-Wsign-compare'));
  assert.ok(html.includes('>41<'));
  // The message is a hover title and never a line of the panel: the panel is a
  // third of a narrow sidebar.
  assert.ok(html.includes('title="comparison of integers"'));
  assert.ok(!html.includes('>comparison of integers<'));
});

test('a collapsed row lists no warnings', () => {
  const html = renderFindings(withFindings([WARNED_FINDING]), state({ findingsOpen: true }));
  assert.ok(html.includes('finding-row'));
  assert.ok(!html.includes('finding-warning'));
});

test('every row offers both destinations', () => {
  // The source is where you fix it; the log is what the compiler actually said.
  const html = renderFindings(withFindings([WARNED_FINDING]), state({ findingsOpen: true }));
  assert.ok(html.includes('data-action="source"'));
  assert.ok(html.includes('data-action="log"'));
});

test('a finding row carries the context payload its menu keys on', () => {
  const html = renderFindings(withFindings([WARNED_FINDING]), state({ findingsOpen: true }));
  assert.ok(html.includes('rbx.finding'));
  assert.ok(html.includes('rbxNodeId'));
});

test('a path with a quote in it cannot break out of the row', () => {
  // `data-vscode-context` is delimited with a single quote so its JSON can keep
  // its own double ones, and a solution path is a name the package author
  // chose -- an apostrophe in one would otherwise close the attribute early.
  const nasty = findingRow({
    id: "f'2",
    label: `it's "bad".cpp`,
    labelTitle: `sols/it's "bad".cpp`,
    summary: 'CE',
    severity: 'error',
  });
  const html = renderFindings(withFindings([nasty]), state({ findingsOpen: true }));
  assert.ok(html.includes(`data-id="${escapeAttr("f'2")}"`));
  assert.ok(!html.includes(`data-id="f'2"`));
  assert.ok(html.includes(escapeAttr(`sols/it's "bad".cpp`)));
});

test('an empty run that failed to compile is not told there is no run', () => {
  // There *is* a run; the reason it looks like nothing happened is in the panel.
  const html = renderTree({ ...model([]), findings: withFindings([BROKEN_FINDING]).findings }, state());
  assert.ok(html.includes('No solution made it into this run'));
  assert.ok(!html.includes('No rbx run found'));
});

test('an empty workspace still gets the welcome text', () => {
  assert.ok(renderTree(model([]), state()).includes('No rbx run found'));
});

// The card: the two facts the extension has been parsing out of every run and
// rendering nowhere. It follows the *selection*, so it can be read while
// scanning a failing group without opening a single editor.

const CARD_CASE = row({
  id: 'sol0::main::1-gen-002',
  parentId: 'sol0::main',
  depth: 2,
  kind: 'testcase',
  label: '1-gen-002',
  section: 'rbx.testcase',
  verdict: { icon: 'error', hue: 'red', short: 'WA' },
  card: {
    title: 'main/1-gen-002',
    checker: 'wrong answer, expected 14, found 12',
    origins: [
      { text: 'gen_random 5 3 --seed=7', title: 'Generated by gen_random 5 3 --seed=7' },
      {
        text: 'gens/script.txt:12',
        open: 'rbx.openGeneratorScript',
        title: 'Generated from gens/script.txt:12',
      },
    ],
  },
});

test('the card shows the selected testcase, and nothing when the selection is not one', () => {
  const view = model([MAIN, MAIN_GROUP, CARD_CASE]);
  const html = renderCard(view, state({ selected: CARD_CASE.id }));
  assert.ok(html.includes('main/1-gen-002'));
  assert.ok(html.includes('wrong answer, expected 14, found 12'));
  // A solution row has no card, and the card must not linger over it describing
  // a testcase that is no longer selected.
  assert.strictEqual(renderCard(view, state({ selected: MAIN.id })), '');
  assert.strictEqual(renderCard(view, state()), '');
});

test('the card never repeats the verdict, the time or the memory', () => {
  // They are on the row a few pixels above. Repeating them would put the same
  // fact on screen twice within one glance and spend the card on the half of
  // the story that was never missing.
  const withMeta = {
    ...CARD_CASE,
    meta: [
      { text: '1306 ms', hue: 'dim' as const, role: 'time' as const },
      { text: '10 MiB', hue: 'dim' as const, role: 'memory' as const },
    ],
  };
  const html = renderCard(model([withMeta]), state({ selected: CARD_CASE.id }));
  assert.ok(!html.includes('1306 ms'));
  assert.ok(!html.includes('10 MiB'));
  assert.ok(!html.includes('WA'));
});

test('an origin is a button only when it names something openable', () => {
  const html = renderCard(model([CARD_CASE]), state({ selected: CARD_CASE.id }));
  // The generator script is a real `path:line` rbx recorded, so it opens.
  assert.ok(html.includes('data-action="rbx.openGeneratorScript"'));
  // The generator *call* names a generator declared in problem.rbx.yml, not a
  // file, so it is text: a button that did nothing would promise a destination.
  assert.ok(html.includes('<div class="card-origin"'));
  assert.ok(!html.includes('data-action="gen_random'));
});

test('a checker that said nothing leaves no empty line behind', () => {
  const card = CARD_CASE.card;
  assert.ok(card !== undefined);
  const quiet = { ...CARD_CASE, card: { ...card, checker: undefined } };
  const html = renderCard(model([quiet]), state({ selected: CARD_CASE.id }));
  // A hard TLE never reached the checker. The absence is informative and is
  // left to speak for itself rather than filled with a placeholder.
  assert.ok(!html.includes('card-checker'));
  assert.ok(html.includes('main/1-gen-002'));
});

test('the card offers three channels and never an input button', () => {
  const html = renderCard(model([CARD_CASE]), state({ selected: CARD_CASE.id }));
  for (const channel of ['out', 'err', 'log']) {
    assert.ok(html.includes(`data-action="${channel}"`), channel);
  }
  // The input lives permanently in the first pane; a button pointing it at the
  // second would put the same file on screen twice.
  assert.ok(!html.includes('data-action="in"'));
});

test('the card escapes what a checker wrote', () => {
  // A checker message is free-form output from the package's own binary, so it
  // reaches the view as untrusted text like every path does.
  const card = CARD_CASE.card;
  assert.ok(card !== undefined);
  const nasty = { ...CARD_CASE, card: { ...card, checker: 'expected <b>7</b> & got "9"' } };
  const html = renderCard(model([nasty]), state({ selected: CARD_CASE.id }));
  assert.ok(html.includes('&lt;b&gt;7&lt;/b&gt; &amp; got'));
  assert.ok(!html.includes('<b>7</b>'));
});
