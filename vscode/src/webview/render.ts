/**
 * The run view's HTML, as a pure function of the view model.
 *
 * Everything here is a *painting* decision: which codicon a gutter draws, how
 * far a row is indented, which `hue-*` class a span carries. What a row means
 * -- whether an expectation was met, which verdict a chip spells, what its
 * search haystack contains -- was decided in viewModel.ts and is not reopened
 * here. When this file starts asking a question about outcomes, the answer
 * belongs upstream.
 *
 * No `vscode` import and no DOM: a string in, a string out, so `node --test`
 * can hold the markup to account. main.ts owns everything this file cannot --
 * events, focus, persistence -- precisely because that part cannot be tested,
 * which is why nothing that decides anything is allowed to live there.
 */
import type {
  HistogramSlice,
  MismatchDetail,
  Row,
  RunViewModel,
  SolutionDetail,
  Span,
} from '../rbx/viewModel';

export interface UiState {
  /** Ids the user (or the default-expansion seed) has opened. */
  readonly expanded: ReadonlySet<string>;
  readonly selected?: string;
  readonly filter: string;
}

/**
 * Indentation of a row at `depth`, in px -- also the detail card's.
 *
 * The base inset is what separates the gutter mark from the row's left edge,
 * where a mismatch draws its red rule. It applies at every depth and on every
 * row, mark or no mark, because the point of the gutter is that it lines up
 * down a column.
 */
function indent(depth: number): number {
  return 12 + depth * 12;
}

export function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/**
 * `escapeHtml` plus both quote characters.
 *
 * The single quote matters as much as the double one here: `data-vscode-context`
 * is delimited with `'` so its JSON can keep its own `"`, and a solution path
 * containing an apostrophe would otherwise close the attribute early and let
 * the rest of the path be read as markup.
 */
export function escapeAttr(text: string): string {
  return escapeHtml(text).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function codicon(name: string): string {
  return `<span class="codicon codicon-${name}"></span>`;
}

/**
 * The match axis, and nothing else.
 *
 * `none` still emits the element: an empty span keeps the grid column, so every
 * label on screen starts at the same x and a gutter mark can be found by
 * scanning down that column instead of by reading the rows.
 */
function gutterCell(row: Row): string {
  switch (row.gutter) {
    case 'met':
      return `<span class="gutter gutter-met">${codicon('check')}</span>`;
    case 'missed':
      return `<span class="gutter gutter-missed">${codicon('warning')}</span>`;
    case 'none':
      return '<span class="gutter"></span>';
  }
}

function twistyCell(row: Row, expanded: boolean): string {
  if (!row.expandable) {
    return '<span class="twisty"></span>';
  }
  const name = expanded ? 'chevron-down' : 'chevron-right';
  return `<span class="twisty codicon codicon-${name}"></span>`;
}

function spanCell(span: Span): string {
  const hue = span.hue === undefined ? '' : ` hue-${span.hue}`;
  return `<span class="span${hue}">${escapeHtml(span.text)}</span>`;
}

const SEPARATOR = '<span class="sep">·</span>';

function metaCell(meta: readonly Span[]): string {
  if (meta.length === 0) {
    return '';
  }
  return `<span class="meta">${meta.map(spanCell).join(SEPARATOR)}</span>`;
}

function verdictCell(row: Row): string {
  const verdict = row.verdict;
  if (verdict === undefined) {
    return '';
  }
  // The short name is its own element so the stylesheet can give it a fixed
  // width: without one, `SKIP` pushes its icon left of every `AC` above it and
  // the column of verdicts reads as ragged.
  return `<span class="verdict hue-${verdict.hue}">${codicon(
    verdict.icon,
  )}<span class="verdict-name">${escapeHtml(verdict.short)}</span></span>`;
}

function labelCell(row: Row): string {
  const classes = ['label'];
  if (row.labelHue !== undefined) {
    classes.push(`hue-${row.labelHue}`);
  }
  if (row.labelBold) {
    classes.push('bold');
  }
  return `<span class="${classes.join(' ')}">${escapeHtml(row.label)}</span>`;
}

/**
 * The payload VS Code hands to a `webview/context` menu contribution.
 *
 * Escaped like any other attribute even though it is machine-written: the ids
 * inside it are built from paths and group names a package author chose.
 */
function contextAttr(row: Row): string {
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

/**
 * `tabStop` is passed apart from `state.selected` on purpose.
 *
 * When the selection is filtered off screen the tree still needs exactly one
 * tab stop, and the first visible row stands in -- but standing in for the tab
 * stop is not being selected, and announcing `aria-selected` on a row the user
 * never picked describes a selection that does not exist.
 */
function renderRow(
  row: Row,
  state: UiState,
  position: Position,
  tabStop: string | undefined,
  describedBy: string | undefined,
): string {
  const expanded = state.expanded.has(row.id);
  const selected = state.selected === row.id;
  const classes = ['row', `kind-${row.kind}`];
  if (row.mismatch) {
    classes.push('mismatch');
  }
  const attrs = [
    `class="${classes.join(' ')}"`,
    'role="treeitem"',
    `data-id="${escapeAttr(row.id)}"`,
    `style="padding-left: ${indent(row.depth)}px"`,
    `aria-level="${position.level}"`,
    `aria-setsize="${position.setsize}"`,
    `aria-posinset="${position.posinset}"`,
    // Absent, not false, on a leaf: `aria-expanded="false"` on a childless node
    // tells a screen reader there is something to open.
    ...(row.expandable ? [`aria-expanded="${expanded}"`] : []),
    // Only when the card is really on screen: pointing at an id that is not in
    // the document makes a screen reader announce no description at all.
    ...(describedBy === undefined ? [] : [`aria-describedby="${escapeAttr(describedBy)}"`]),
    `aria-selected="${selected}"`,
    `tabindex="${tabStop === row.id ? 0 : -1}"`,
    contextAttr(row),
  ];
  return (
    `<div ${attrs.join(' ')}>` +
    gutterCell(row) +
    twistyCell(row, expanded) +
    labelCell(row) +
    metaCell(row.meta) +
    verdictCell(row) +
    '</div>'
  );
}

/**
 * What a caught solution got wrong, in a sentence.
 *
 * The old view said this as `expected INCORRECT, got WA` in the same dim grey
 * as every row's timing, where it was invisible. `failedGroups` is what rbx
 * itself names as the culprit, so the groups are the sentence when there are
 * any; the observed outcome only stands in when rbx named none.
 */
function mismatchSentence(mismatch: MismatchDetail): string {
  // `did not match`, not `matched`: rbx reports the groups that *failed* their
  // declaration, so naming them as the ones that matched says the opposite of
  // what happened -- and the whole reason this card exists is that the old
  // phrasing could not be read at a glance.
  const tail =
    mismatch.failedGroups.length > 0
      ? `${mismatch.failedGroups.map(escapeHtml).join(', ')} did not match`
      : `got ${escapeHtml(mismatch.observed)}`;
  return `Declared ${escapeHtml(mismatch.declared)}, but ${tail}.`;
}

function mismatchCard(mismatch: MismatchDetail): string {
  return (
    '<div class="mismatch-card">' +
    codicon('warning') +
    `<span class="mismatch-text">${mismatchSentence(mismatch)}</span>` +
    '</div>'
  );
}

/** A percentage with no trailing zeroes, so 3 of 4 reads `75%` and not `75.00%`. */
function percent(count: number, total: number): string {
  return `${Number(((count / total) * 100).toFixed(2))}%`;
}

function histogramCard(histogram: readonly HistogramSlice[]): string {
  const total = histogram.reduce((sum, slice) => sum + slice.count, 0);
  if (total === 0) {
    return '';
  }
  const bars = histogram
    .map(
      (slice) =>
        `<span class="bar hue-${slice.hue}" style="width: ${percent(slice.count, total)}"></span>`,
    )
    .join('');
  const counts = histogram
    .map(
      (slice) =>
        `<span class="span hue-${slice.hue}">${slice.count} ${escapeHtml(slice.short)}</span>`,
    )
    .join(SEPARATOR);
  return `<div class="histogram"><div class="bars">${bars}</div><div class="counts">${counts}</div></div>`;
}

function value(label: string, text: string | undefined): string {
  if (text === undefined || text === '') {
    return '';
  }
  return (
    '<span class="value">' +
    `<span class="value-label">${escapeHtml(label)}</span>` +
    `<span class="value-text">${escapeHtml(text)}</span>` +
    '</span>'
  );
}

function valuesCard(detail: SolutionDetail): string {
  // No denominators: the extension reads only `.rbx` artifacts, never
  // problem.rbx.yml, so there is no limit here to divide by.
  const values = [
    value('Max time', detail.maxTime),
    value('Max memory', detail.maxMemory),
    value('Score', detail.score),
  ].join('');
  return values === '' ? '' : `<div class="values">${values}</div>`;
}

/**
 * The card under an expanded solution -- empty string when it would be a box
 * with nothing in it, which is what a solution still running would get.
 */
function renderDetail(row: Row, detail: SolutionDetail, id: string): string {
  const body =
    (detail.mismatch === undefined ? '' : mismatchCard(detail.mismatch)) +
    histogramCard(detail.histogram) +
    valuesCard(detail);
  if (body === '') {
    return '';
  }
  // No `role="group"`: inside a `role="tree"`, a group is expected to contain
  // treeitems, and this card contains prose -- so a screen reader either skips
  // it or announces it as an empty level of the tree. As a plain div it is out
  // of the tree structure entirely, and the row it belongs to reaches it
  // through `aria-describedby` instead.
  // Indented with a margin, not padding: the card's padding is its own inset,
  // and mixing the two here is what left the text sitting flat against its edge.
  return `<div class="detail" id="${escapeAttr(id)}" style="margin-left: ${indent(row.depth + 1)}px">${body}</div>`;
}

/**
 * The id of the card under `rowId` -- what its row's `aria-describedby` names.
 *
 * Percent-encoded rather than interpolated raw: `aria-describedby` is a
 * *space-separated* id list, and a row id is built from a solution path, so
 * `sols/my sol.cpp` would otherwise name two ids and describe neither.
 */
function detailId(rowId: string): string {
  return `detail:${encodeURIComponent(rowId)}`;
}

export function matchesFilter(row: Row, filter: string): boolean {
  const needle = filter.trim().toLowerCase();
  // `row.search` is already lowercased and already carries the verdict and the
  // literal `mismatch`; rebuilding the haystack here would let the two drift.
  return needle === '' || row.search.includes(needle);
}

/**
 * The rows on screen, in model order.
 *
 * A row survives the filter when it matches, when an ancestor matches (typing a
 * solution path keeps its testcases) or when a descendant matches (typing a
 * stem keeps the ancestors that lead to it). Collapse is applied after that, so
 * a filter never opens a node the user closed -- it narrows what is already
 * visible rather than rearranging the tree under them.
 */
export function visibleRows(model: RunViewModel, state: UiState): Row[] {
  const rows = model.rows;
  const self = new Map<string, boolean>();
  for (const row of rows) {
    self.set(row.id, matchesFilter(row, state.filter));
  }

  const fromAncestor = new Map<string, boolean>();
  for (const row of rows) {
    const parent = row.parentId;
    fromAncestor.set(
      row.id,
      parent === undefined
        ? false
        : (self.get(parent) ?? false) || (fromAncestor.get(parent) ?? false),
    );
  }

  // Backwards, so a match reaches every ancestor in one pass: a child always
  // follows its parent in `rows`.
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
  const result: Row[] = [];
  for (const row of rows) {
    const matches =
      (self.get(row.id) ?? false) ||
      (fromAncestor.get(row.id) ?? false) ||
      (fromDescendant.get(row.id) ?? false);
    // The parent being on screen already implies every ancestor above it was,
    // so one lookup answers "is every ancestor expanded".
    const reachable =
      row.parentId === undefined || (shown.has(row.parentId) && state.expanded.has(row.parentId));
    if (matches && reachable) {
      shown.add(row.id);
      result.push(row);
    }
  }
  return result;
}

/** The welcome text, verbatim from the `viewsWelcome` block it replaces. */
const WELCOME =
  '<div class="welcome">' +
  '<p>No rbx run found in this workspace.</p>' +
  '<p>Run <code>rbx run</code> in the terminal and the results will show up here.</p>' +
  '</div>';

/**
 * The inner HTML of the `role="tree"` container.
 *
 * The container itself is part of the static shell so that focus and scroll
 * survive a re-render; this returns only what goes inside it.
 */
export function renderTree(model: RunViewModel, state: UiState): string {
  if (model.empty) {
    // `viewsWelcome` does not apply to a webview view, so the copy that used to
    // live in package.json lives here now.
    return WELCOME;
  }

  const rows = visibleRows(model, state);
  // Siblings are counted among the rows actually on screen: announcing "3 of 9"
  // while six of them are filtered out describes a tree the user cannot see.
  const siblings = new Map<string, Row[]>();
  // Filled in the same pass as the buckets, so a row's rank among its siblings
  // costs a lookup instead of a scan of the bucket it was just appended to.
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
  // selected -- or with the selection filtered off screen -- the first row does,
  // so a Tab into the view lands somewhere useful.
  const tabStop = rows.some((row) => row.id === state.selected) ? state.selected : rows[0]?.id;

  return rows
    .map((row) => {
      const bucket = siblings.get(row.parentId ?? '') ?? [row];
      const id = detailId(row.id);
      const detail =
        row.detail !== undefined && state.expanded.has(row.id)
          ? renderDetail(row, row.detail, id)
          : '';
      const html = renderRow(
        row,
        state,
        {
          level: row.depth + 1,
          setsize: bucket.length,
          posinset: ranks.get(row.id) ?? 1,
        },
        tabStop,
        detail === '' ? undefined : id,
      );
      return html + detail;
    })
    .join('');
}

/**
 * The mismatch strip, or nothing at all.
 *
 * Nothing at all is the point: a package whose declarations all held should not
 * carry a bar telling it so, so the strip's presence is itself the signal. The
 * filter box therefore cannot live here -- see `renderFilter`.
 */
export function renderHeader(model: RunViewModel, _state: UiState): string {
  if (model.mismatches === 0) {
    return '';
  }
  const solutions = model.rows.filter((row) => row.kind === 'solution').length;
  return (
    '<div class="header">' +
    `<span class="header-count">${codicon('warning')}${model.mismatches} of ${solutions} did not match</span>` +
    '<button id="next-mismatch">next ›</button>' +
    '</div>'
  );
}

/**
 * The filter box, rendered separately from the header.
 *
 * It has to survive the strip disappearing: a user who filters down to the one
 * bad solution and then fixes it would otherwise watch the box -- and their
 * typing -- vanish at the moment the count reaches zero.
 */
export function renderFilter(state: UiState): string {
  return (
    '<div class="filter">' +
    `<input id="filter" type="search" placeholder="Filter" value="${escapeAttr(state.filter)}">` +
    '</div>'
  );
}
