/**
 * The Tests view's HTML, as a pure function of the view model.
 *
 * The sibling of render.ts, and it holds itself to the same rule: everything
 * here is a *painting* decision -- which codicon a flag draws, how far a row is
 * indented, which `hue-*` class a span carries. What a row means was decided in
 * testsetViewModel.ts and is not reopened here.
 *
 * The two renderers share a stylesheet and, where the markup is genuinely the
 * same control, share the function too: `renderSelector` draws the same problem
 * dropdown for both views, and drawing a second one would be two places for one
 * control to diverge. What is *not* shared is the row, because the two rows say
 * different things: a run row has a gutter, a declaration and a verdict; a
 * testset row has a size and two marks.
 *
 * No `vscode` import and no DOM: a string in, a string out.
 */
import type {
  TestsetCard,
  TestsetFlag,
  TestsetOrigin,
  TestsetRow,
  TestsetSpan,
  TestsetValidationCard,
  TestsetViewModel,
} from '../rbx/testsetViewModel';
import { escapeAttr, escapeHtml, renderFilter as renderRunFilter } from './render';

export interface TestsetUiState {
  /** Ids the user (or the default-expansion seed) has opened. */
  readonly expanded: ReadonlySet<string>;
  readonly selected?: string;
  readonly filter: string;
}

/**
 * Indentation of a row at `depth`, in px.
 *
 * The same two numbers render.ts uses, so the two views in one container line
 * their labels up at the same x rather than reading as two unrelated lists.
 * There is no gutter column here, so the base inset is what keeps the twisty
 * off the panel edge.
 */
function indent(depth: number): number {
  return 10 + depth * 12;
}

function codicon(name: string): string {
  return `<span class="codicon codicon-${name}"></span>`;
}

function twistyCell(row: TestsetRow, expanded: boolean): string {
  if (!row.expandable) {
    return '<span class="twisty"></span>';
  }
  return `<span class="twisty codicon codicon-${expanded ? 'chevron-down' : 'chevron-right'}"></span>`;
}

function spanCell(span: TestsetSpan): string {
  const hue = span.hue === undefined ? '' : ` hue-${span.hue}`;
  const role = span.role === undefined ? '' : ` span-${span.role}`;
  return `<span class="span${role}${hue}">${escapeHtml(span.text)}</span>`;
}

/**
 * The meta line, with no separators between its spans.
 *
 * The same arrangement -- and the same reason -- as `metaCell` in render.ts:
 * the stylesheet draws the `·` as a `::before` on every span but the first, so
 * a separator leaves with the span it precedes instead of trailing off a
 * narrowed row. It holds only while the responsive ladder hides a *suffix* of
 * the line, which is why the spans are built in priority order upstream and a
 * test pins the breakpoints in descending order.
 */
function metaCell(meta: readonly TestsetSpan[]): string {
  if (meta.length === 0) {
    return '';
  }
  return `<span class="meta">${meta.map(spanCell).join('')}</span>`;
}

/** The glyph each mark draws. A painting decision, hence here and not upstream. */
const FLAG_ICONS: Record<TestsetFlag['kind'], string> = {
  visualization: 'file-media',
  invalid: 'warning',
};

/**
 * The marks at the end of a row.
 *
 * Emitted as a cell even when empty, so the column exists on every row and a
 * warning can be found by scanning down it rather than by reading the rows --
 * the same argument the run view's gutter makes on the other side.
 */
function flagsCell(flags: readonly TestsetFlag[]): string {
  const marks = flags
    .map(
      (flag) =>
        `<span class="flag flag-${flag.kind} hue-${flag.hue}" title="${escapeAttr(flag.title)}">` +
        `${codicon(FLAG_ICONS[flag.kind])}</span>`,
    )
    .join('');
  return `<span class="flags">${marks}</span>`;
}

function labelCell(row: TestsetRow): string {
  const title = row.labelTitle === undefined ? '' : ` title="${escapeAttr(row.labelTitle)}"`;
  return `<span class="label"${title}>${escapeHtml(row.label)}</span>`;
}

/** The payload VS Code hands to a `webview/context` menu contribution. */
function contextAttr(row: TestsetRow): string {
  const context = {
    webviewSection: row.section,
    rbxNodeId: row.id,
    preventDefaultContextMenuItems: true,
  };
  return `data-vscode-context='${escapeAttr(JSON.stringify(context))}'`;
}

interface Position {
  readonly level: number;
  readonly setsize: number;
  readonly posinset: number;
}

function renderRow(
  row: TestsetRow,
  state: TestsetUiState,
  position: Position,
  tabStop: string | undefined,
): string {
  const expanded = state.expanded.has(row.id);
  const selected = state.selected === row.id;
  const attrs = [
    `class="row testset-row kind-${row.kind}"`,
    'role="treeitem"',
    `data-id="${escapeAttr(row.id)}"`,
    `style="padding-left: ${indent(row.depth)}px"`,
    `aria-level="${position.level}"`,
    `aria-setsize="${position.setsize}"`,
    `aria-posinset="${position.posinset}"`,
    // Absent, not false, on a leaf: `aria-expanded="false"` on a childless node
    // tells a screen reader there is something to open.
    ...(row.expandable ? [`aria-expanded="${expanded}"`] : []),
    `aria-selected="${selected}"`,
    `tabindex="${tabStop === row.id ? 0 : -1}"`,
    contextAttr(row),
  ];
  return (
    `<div ${attrs.join(' ')}>` +
    twistyCell(row, expanded) +
    labelCell(row) +
    metaCell(row.meta) +
    flagsCell(row.flags) +
    '</div>'
  );
}

export function matchesTestsetFilter(row: TestsetRow, filter: string): boolean {
  const needle = filter.trim().toLowerCase();
  // `row.search` is already lowercased and already carries the tokens the flags
  // stand for; rebuilding the haystack here would let the two drift.
  return needle === '' || row.search.includes(needle);
}

/**
 * The rows on screen, in model order.
 *
 * The same three rules the run view's `visibleRows` applies, on a tree one
 * level shallower: a row survives when it matches, when its group matches, or
 * when one of its tests does. Collapse is applied afterwards, so filtering
 * narrows what is visible rather than opening what the user shut.
 */
export function visibleTestsetRows(
  model: TestsetViewModel,
  state: TestsetUiState,
): TestsetRow[] {
  const rows = model.rows;
  const self = new Map<string, boolean>();
  for (const row of rows) {
    self.set(row.id, matchesTestsetFilter(row, state.filter));
  }

  // A child always follows its parent, so one forward pass answers "did my
  // group match" and one backward pass answers "did any of my tests".
  const fromAncestor = new Map<string, boolean>();
  for (const row of rows) {
    const parent = row.parentId;
    fromAncestor.set(row.id, parent === undefined ? false : (self.get(parent) ?? false));
  }
  const fromDescendant = new Map<string, boolean>();
  for (let i = rows.length - 1; i >= 0; i--) {
    const row = rows[i];
    const parent = row.parentId;
    const carries = (self.get(row.id) ?? false) || (fromDescendant.get(row.id) ?? false);
    if (parent !== undefined && carries) {
      fromDescendant.set(parent, true);
    }
  }

  const shown = new Set<string>();
  const result: TestsetRow[] = [];
  for (const row of rows) {
    const matches =
      (self.get(row.id) ?? false) ||
      (fromAncestor.get(row.id) ?? false) ||
      (fromDescendant.get(row.id) ?? false);
    const reachable =
      row.parentId === undefined ||
      (shown.has(row.parentId) && state.expanded.has(row.parentId));
    if (matches && reachable) {
      shown.add(row.id);
      result.push(row);
    }
  }
  return result;
}

/**
 * The welcome text, in the words the Run view uses for the same absence.
 *
 * `viewsWelcome` does not apply to a webview view, so the copy lives here. Not
 * "in this workspace": the view is one problem's, and in a contest where nine
 * problems have been built and the selected one has not, a sentence about the
 * workspace is simply false.
 */
const WELCOME =
  '<div class="welcome">' +
  '<p>No testset built for this problem.</p>' +
  '<p>Run <code>rbx build</code> in its directory and the tests will show up here.</p>' +
  '</div>';

/** A manifest that named no tests at all -- built, and empty. */
const NO_TESTS =
  '<div class="welcome">' +
  '<p>This package was built with no testcases.</p>' +
  '<p>Declare a group in <code>problem.rbx.yml</code> and build again.</p>' +
  '</div>';

/**
 * The inner HTML of the `role="tree"` container.
 *
 * The container is part of the static shell so focus and scroll survive a
 * re-render; this returns only what goes inside it.
 */
export function renderTestsetTree(
  model: TestsetViewModel,
  state: TestsetUiState,
): string {
  if (model.empty) {
    return WELCOME;
  }
  if (model.rows.length === 0) {
    return NO_TESTS;
  }

  const rows = visibleTestsetRows(model, state);
  // Siblings are counted among the rows actually on screen: announcing "3 of 9"
  // while six of them are filtered out describes a tree the user cannot see.
  const siblings = new Map<string, TestsetRow[]>();
  const ranks = new Map<string, number>();
  for (const row of rows) {
    const key = row.parentId ?? '';
    let bucket = siblings.get(key);
    if (bucket === undefined) {
      bucket = [];
      siblings.set(key, bucket);
    }
    bucket.push(row);
    ranks.set(row.id, bucket.length);
  }

  // A tree needs exactly one tab stop. The selection holds it; with nothing
  // selected -- or with the selection filtered off screen -- the first row does.
  const tabStop = rows.some((row) => row.id === state.selected) ? state.selected : rows[0]?.id;

  return rows
    .map((row) =>
      renderRow(
        row,
        state,
        {
          level: row.depth + 1,
          setsize: (siblings.get(row.parentId ?? '') ?? [row]).length,
          posinset: ranks.get(row.id) ?? 1,
        },
        tabStop,
      ),
    )
    .join('');
}

/**
 * The strip above the tree: what is in the testset, and when it was built.
 *
 * Always present once there is a manifest, unlike the Run view's strip, which
 * appears only when something is wrong. There is no "wrong" for a testset to
 * report at this level -- the strip is a statement of size, and the time it
 * carries is a cue about which build is on screen and nothing more. It makes no
 * staleness claim, because nothing in the manifest can support one.
 */
export function renderTestsetHeader(model: TestsetViewModel): string {
  const header = model.header;
  if (header === undefined) {
    return '';
  }
  const built =
    header.built === undefined
      ? ''
      : `<span class="header-built">${escapeHtml(header.built)}</span>`;
  return (
    '<div class="header testset-header">' +
    `<span class="header-summary">${escapeHtml(header.summary)}</span>` +
    built +
    // The one deliberate open. Everything that wants width -- the gallery, the
    // coverage matrix, the stats -- lives in the panel, and the sidebar's job
    // is to be the thing that is always there.
    `<button id="open-panel" title="Open the Testset panel">${codicon('window')}</button>` +
    '</div>'
  );
}

/**
 * The filter box, drawn by the Run view's own renderer.
 *
 * One box, one set of styles, one set of behaviours. The shim is because
 * `renderFilter` takes the run view's `UiState`, of which it reads exactly one
 * field -- and widening that signature would mean editing a file this view has
 * no business editing.
 */
export function renderTestsetFilter(state: TestsetUiState): string {
  return renderRunFilter({ expanded: state.expanded, filter: state.filter, findingsOpen: false });
}

function originLine(origin: TestsetOrigin): string {
  const text = escapeHtml(origin.text);
  const title = escapeAttr(origin.title);
  // A `button` only when there is somewhere to go: an origin that looked like a
  // link and did nothing would promise a destination the view cannot reach.
  return origin.open === undefined
    ? `<div class="card-origin" title="${title}">${text}</div>`
    : `<button class="card-origin card-link" data-action="${origin.open}" title="${title}">${text}</button>`;
}

/**
 * What the validator said, on the row that has room for it.
 *
 * Drawn for both answers, not only for a rejection: a group with a validator
 * and a group without one both leave the flag column empty, and this line is
 * the only place that difference is visible.
 */
function validationLine(validation: TestsetValidationCard): string {
  const validator =
    validation.validator === undefined
      ? ''
      : `<span class="card-validator">${escapeHtml(validation.validator)}</span>`;
  const message =
    validation.message === undefined
      ? ''
      : `<div class="card-message">${escapeHtml(validation.message)}</div>`;
  return (
    `<div class="card-validation hue-${validation.hue}">` +
    codicon(validation.ok ? 'pass' : 'warning') +
    `<span>${escapeHtml(validation.text)}</span>` +
    validator +
    '</div>' +
    message
  );
}

function valuesLine(card: TestsetCard): string {
  if (card.values.length === 0) {
    return '';
  }
  const values = card.values
    .map(
      (value) =>
        '<span class="value">' +
        `<span class="value-label">${escapeHtml(value.label)}</span>` +
        `<span class="value-text hue-neutral">${escapeHtml(value.text)}</span>` +
        '</span>',
    )
    .join('');
  return `<div class="values">${values}</div>`;
}

/**
 * The card under the tree: what the selected testcase's row cannot say.
 *
 * Absent whenever the selection is not a testcase, on the same rule the Run
 * view's follows -- the card being on screen is itself a statement about what is
 * selected. It does not repeat the row: the stem, the input size and the two
 * marks are a few pixels above.
 */
export function renderTestsetCard(
  model: TestsetViewModel,
  state: TestsetUiState,
): string {
  const card = model.rows.find((row) => row.id === state.selected)?.card;
  if (card === undefined) {
    return '';
  }
  // One button per picture that exists, named for the channel it opens. A
  // single unqualified `visualization` button was wrong twice over on a package
  // with both: it named neither, and it could reach only the input one.
  //
  // A channel is either built or lazy, never both: `lazyVisualizers` is already
  // false wherever a picture exists. So `--visualize` packages keep exactly the
  // buttons they had -- instant, opening a file -- and a lazy button appears
  // only where the build left nothing to open but a visualizer is declared.
  const buttons = [
    card.visualization !== undefined
      ? '<button class="card-channel" data-action="rbx.openTestVisualization" ' +
        `title="${escapeAttr(card.visualization)}">input</button>`
      : card.lazyVisualizers.input
        ? '<button class="card-channel lazy" data-action="rbx.visualizeTest" ' +
          'title="Run the input visualizer for this testcase">input</button>'
        : '',
    card.answerVisualization !== undefined
      ? '<button class="card-channel" data-action="rbx.openTestAnswerVisualization" ' +
        `title="${escapeAttr(card.answerVisualization)}">answer</button>`
      : card.lazyVisualizers.output
        ? '<button class="card-channel lazy" data-action="rbx.visualizeTestAnswer" ' +
          'title="Run the solution visualizer on this testcase\'s expected answer">answer</button>'
        : '',
  ].join('');
  const visualization =
    buttons === ''
      ? ''
      : '<div class="card-channels">' +
        '<span class="card-channels-label">visualization</span>' +
        buttons +
        '<button class="card-channel" data-action="panel:gallery" ' +
        'title="Show this group in the Testset panel">gallery</button>' +
        '</div>';
  return (
    `<div class="card-title">${escapeHtml(card.title)}</div>` +
    (card.validation === undefined ? '' : validationLine(card.validation)) +
    valuesLine(card) +
    card.origins.map(originLine).join('') +
    visualization
  );
}
