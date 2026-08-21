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
import type { ProblemChoice } from '../rbx/problems';
import type {
  GroupMismatch,
  HistogramSlice,
  MismatchDetail,
  Mismatched,
  Row,
  RunViewModel,
  RunWarning,
  ScoreMismatch,
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
  return 10 + depth * 12;
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
 * How the row came out, in one column.
 *
 * `none` still emits the element: an empty span keeps the grid column, so every
 * label on screen starts at the same x and a mark can be found by scanning down
 * that column instead of by reading the rows.
 *
 * `warned` draws the same triangle as `missed` in yellow rather than red, and
 * carries the warning itself as a tooltip. It shares this column rather than
 * getting one of its own because the alternative -- a second mark at the far
 * end of the row -- put a yellow clock beside the TLE verdict's own yellow
 * clock, and a double-TL warning only ever lands on a TLE row.
 */
function gutterCell(row: Row): string {
  switch (row.gutter) {
    case 'met':
      return `<span class="gutter gutter-met">${codicon('check')}</span>`;
    case 'warned': {
      const title = row.warnings.map(warningText).join(' ');
      return (
        `<span class="gutter gutter-warned" title="${escapeAttr(title)}">` +
        `${codicon('warning')}</span>`
      );
    }
    case 'missed':
      return `<span class="gutter gutter-missed">${codicon('warning')}</span>`;
    case 'none':
      return '<span class="gutter"></span>';
  }
}

/**
 * A warning about a run that *passed*, in one line.
 *
 * The words are the console's own, shortened to a row that has to fit a path
 * and two measurements beside them. Which run gets one is rbx's decision -- see
 * `RunWarning` -- so nothing here inspects an outcome to reach it.
 */
function warningText(warning: RunWarning): string {
  const where = warning.groups.length === 0 ? '' : ` on ${warning.groups.join(', ')}`;
  switch (warning.kind) {
    case 'double-tl-passed':
      return `Still passed in double TL${where}.`;
    case 'double-tl-verdicts': {
      const verdicts = warning.verdicts.map((verdict) => verdict.text).join(' ');
      return `Still finished in double TL, but failed with ${verdicts}${where}.`;
    }
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
  const role = span.role === undefined ? '' : ` span-${span.role}`;
  return `<span class="span${role}${hue}">${escapeHtml(span.text)}</span>`;
}

const SEPARATOR = '<span class="sep">·</span>';

/**
 * The meta line, with no separators between its spans.
 *
 * They are drawn by the stylesheet as a `::before` on each span but the first,
 * which is the only arrangement that survives a span being hidden: a separator
 * written here as its own element would stay behind when the span it divides
 * goes, leaving `[30/100] ·` trailing off a narrowed row. Belonging to the span
 * it precedes, it leaves when that span does.
 *
 * This holds because the responsive ladder always hides a *suffix* of the line
 * -- memory before time, and neither before the score -- so the span that is
 * first is always the one that was first.
 */
function metaCell(meta: readonly Span[]): string {
  if (meta.length === 0) {
    return '';
  }
  return `<span class="meta">${meta.map(spanCell).join('')}</span>`;
}

/**
 * What the row declared, in words, immediately left of what it got.
 *
 * Emitted even when there is nothing to say, for the same reason the gutter is:
 * the pair reads as `TLE \u2192 WA` down a column, and a cell that disappears on
 * the undeclared rows takes the column's alignment with it.
 *
 * The arrow is inside this cell rather than between the two, so it arrives and
 * leaves with the declaration it points from.
 */
function expectationCell(row: Row): string {
  const expectation = row.expectation;
  if (expectation === undefined) {
    return '<span class="expectation"></span>';
  }
  return (
    `<span class="expectation hue-${expectation.hue}">` +
    `<span class="expectation-name">${escapeHtml(expectation.label)}</span>` +
    '<span class="arrow">\u2192</span>' +
    '</span>'
  );
}

function verdictCell(row: Row): string {
  const verdict = row.verdict;
  if (verdict === undefined) {
    return '';
  }
  // The verdict a soft TLE hid, in its own hue rather than the chip's: the
  // point of showing it is that `TLE` and the verdict underneath disagree, and
  // painting them alike would hide the disagreement. Parenthesised because it
  // is a gloss on the chip and not a second verdict of equal standing.
  const under =
    verdict.under === undefined
      ? ''
      : `<span class="verdict-under hue-${verdict.under.hue}" ` +
        `title="Would have been ${escapeAttr(verdict.under.text)} without the time limit">` +
        `(${escapeHtml(verdict.under.text)})</span>`;
  // The short name is its own element so the stylesheet can give it a fixed
  // width: without one, `SKIP` pushes its icon left of every `AC` above it and
  // the column of verdicts reads as ragged.
  //
  // `verdict-glossed` releases that fixed width, and only here. It buys the
  // alignment of a column of icons, and a row carrying a gloss is wider than
  // its neighbours regardless -- so on this row the reserved width aligns
  // nothing and only holds `(WA)` a character away from the verdict it belongs
  // to. Written as a class rather than `:has(+ .verdict-under)` so the rule
  // does not depend on selector support in whichever Electron is underneath.
  const glossed = verdict.under === undefined ? '' : ' verdict-glossed';
  return `<span class="verdict hue-${verdict.hue}${glossed}">${codicon(
    verdict.icon,
  )}<span class="verdict-name">${escapeHtml(verdict.short)}</span>${under}</span>`;
}

function labelCell(row: Row): string {
  const classes = ['label'];
  if (row.labelHue !== undefined) {
    classes.push(`hue-${row.labelHue}`);
  }
  if (row.labelBold) {
    classes.push('bold');
  }
  // The title is the only channel a shortened label has for the path it stands
  // for; rows whose label is already the whole path get no tooltip, so hovering
  // one never pops a box repeating what is on screen.
  const title = row.labelTitle === undefined ? '' : ` title="${escapeAttr(row.labelTitle)}"`;
  return `<span class="${classes.join(' ')}"${title}>${escapeHtml(row.label)}</span>`;
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
  // Mutually exclusive with `mismatch` by construction -- `warned` is a gutter
  // state and `missed` outranks it -- so the two washes can never stack.
  if (row.gutter === 'warned') {
    classes.push('warned');
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
    expectationCell(row) +
    verdictCell(row) +
    '</div>'
  );
}

function hued(text: string, hue: string): string {
  return `<span class="hue-${hue}">${escapeHtml(text)}</span>`;
}

/** `TLE \u2192 AC`, the same pairing the rows use, so the card reads as a zoom
 * into them rather than as a second notation. */
function declaredGot(pair: Mismatched | GroupMismatch): string {
  return (
    hued(pair.declared, pair.declaredHue) +
    '<span class="arrow">\u2192</span>' +
    hued(pair.observed, pair.observedHue)
  );
}

/**
 * The pooled layer's own miss.
 *
 * Printed only when `MismatchDetail.pooled` is set, which is only when that
 * layer is what failed. The old card printed this unconditionally and then
 * listed the failing groups after a `but`, which read as if those groups had
 * missed the pooled declaration -- for a solution whose pooled declaration
 * held, that named the one expectation nothing was wrong with.
 */
function pooledLine(pooled: Mismatched): string {
  return `<p class="mismatch-line">Declared ${declaredGot(pooled)}</p>`;
}

/** A group per row, each naming its own declaration. */
function groupLines(groups: readonly GroupMismatch[], held: string | undefined): string {
  const count = groups.length;
  const subject = count === 1 ? '1 group' : `${count} groups`;
  // Naming the pooled declaration as *held* is the correction: the reader is
  // looking at a row labelled INCORRECT and needs to be told that is not the
  // declaration these groups missed.
  const lead =
    held === undefined
      ? `${subject} missed their <code>outcomePerGroup</code> declaration:`
      : `${escapeHtml(held)} held for the solution as a whole; ` +
        `${subject} missed their <code>outcomePerGroup</code> declaration:`;
  const rows = groups
    .map(
      (group) =>
        '<li>' +
        `<span class="group-name">${escapeHtml(group.name)}</span>` +
        `<span class="group-pair">${declaredGot(group)}</span>` +
        '</li>',
    )
    .join('');
  return `<p class="mismatch-line">${lead}</p><ul class="group-misses">${rows}</ul>`;
}

function scoreLine(score: ScoreMismatch): string {
  return (
    '<p class="mismatch-line">Expected ' +
    // Only what it scored is hued: the expectation is a range the author wrote,
    // not an outcome, and colouring it would read as a verdict on the
    // declaration rather than on the run.
    `${escapeHtml(score.expected)} pts, scored ${hued(score.got, score.gotHue)}.</p>`
  );
}

/**
 * What a caught solution got wrong, layer by layer.
 *
 * Each clause speaks only for the layer it belongs to and appears only when
 * that layer failed, so no sentence here can accuse an expectation that held.
 */
function mismatchCard(mismatch: MismatchDetail): string {
  const body =
    (mismatch.pooled === undefined ? '' : pooledLine(mismatch.pooled)) +
    (mismatch.groups.length === 0 ? '' : groupLines(mismatch.groups, mismatch.pooledHeld)) +
    (mismatch.score === undefined ? '' : scoreLine(mismatch.score));
  if (body === '') {
    return '';
  }
  return (
    '<div class="mismatch-card">' +
    codicon('warning') +
    `<div class="mismatch-text">${body}</div>` +
    '</div>'
  );
}

/**
 * What a passing run still warned about.
 *
 * Its own card rather than a clause inside `mismatchCard`: that card only ever
 * appears on a solution that missed something, and these warnings appear on
 * solutions that missed nothing at all -- which is the whole reason they were
 * invisible here before.
 */
function warningCard(warnings: readonly RunWarning[]): string {
  if (warnings.length === 0) {
    return '';
  }
  const body = warnings
    .map((warning) => `<p class="mismatch-line">${escapeHtml(warningText(warning))}</p>`)
    .join('');
  return (
    '<div class="warning-card">' +
    codicon('warning') +
    `<div class="mismatch-text">${body}</div>` +
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

function value(label: string, text: string | undefined, hue?: string): string {
  if (text === undefined || text === '') {
    return '';
  }
  // Always hued, `neutral` when the value has nothing to say about itself, so
  // that the colour of a value comes from the one `.hue-*` table like every
  // other coloured thing in the view rather than from `.value-text` itself.
  const textClass = `value-text hue-${hue ?? 'neutral'}`;
  return (
    '<span class="value">' +
    `<span class="value-label">${escapeHtml(label)}</span>` +
    `<span class="${textClass}">${escapeHtml(text)}</span>` +
    '</span>'
  );
}

function valuesCard(detail: SolutionDetail): string {
  // No denominators: see `solutionDetail`, which decides what these are. The
  // limits exist on the skeleton now; rendering against them does not.
  const values = [
    value('Max time', detail.maxTime),
    value('Max memory', detail.maxMemory),
    value('Score', detail.score, detail.scoreHue),
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
    warningCard(detail.warnings ?? []) +
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
  // Not "in this workspace": the view is one problem's now, and in a contest
  // where nine problems have run and the selected one has not, a sentence about
  // the workspace is simply false.
  '<p>No rbx run found for this problem.</p>' +
  '<p>Run <code>rbx run</code> in its directory and the results will show up here.</p>' +
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
  if (model.mismatches === 0 && model.warned === 0) {
    return '';
  }
  const solutions = model.rows.filter((row) => row.kind === 'solution').length;
  // Two counts, never merged: a solution that missed its declaration and one
  // that met it on a run rbx warned about are different news, and a single
  // number covering both would let the second hide inside the first.
  const counts =
    (model.mismatches === 0
      ? ''
      : `<span class="header-count">${codicon('warning')}${model.mismatches} of ${solutions} did not match</span>`) +
    (model.warned === 0
      ? ''
      : `<span class="header-count header-warned">${codicon('warning')}${model.warned} warned</span>`);
  return (
    '<div class="header">' +
    counts +
    // Only when there is a mismatch to walk to: the button steps through the
    // `mismatch` rows, and offering it on a run that has none is a control that
    // does nothing.
    (model.mismatches === 0 ? '' : '<button id="next-mismatch">next ›</button>') +
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

/**
 * The problem dropdown.
 *
 * Hidden for a single problem: a select with one option is a control that
 * cannot do anything, and a one-problem workspace should look exactly as it did
 * before the selector existed.
 *
 * The colour dot is a `style` attribute, which the CSP permits on styles only
 * (see the note in runView.ts) -- and the value is a colour a contest author
 * wrote, so it goes through `escapeAttr` like everything else. Escaping alone
 * would not be enough: a declared colour needs no markup to be a whole extra
 * declaration, which is why `contest.ts` drops anything that is not a colour
 * before it ever gets here.
 */
export function renderSelector(problems: readonly ProblemChoice[], selected?: string): string {
  if (problems.length <= 1) {
    return '';
  }
  const option = (problem: ProblemChoice): string =>
    `<option value="${escapeAttr(problem.root)}"${problem.root === selected ? ' selected' : ''}>` +
    escapeHtml(problem.label) +
    '</option>';

  // One pass, opening a group when it changes and closing the one before it.
  // Safe only because `problemChoices` sorts by group: a grouped and an
  // ungrouped run cannot interleave, so a group is never reopened. The tail of
  // ungrouped options -- the packages no contest claimed, which `problemChoices`
  // puts last -- closes the final group on the way past and needs no close at
  // the end, which is why the trailing close is conditional on `openGroup`.
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
    (dot === undefined
      ? ''
      : `<span class="selector-dot" style="background:${escapeAttr(dot)}"></span>`) +
    // Named outright rather than by a visible `<label>`: the sidebar has no
    // room for one, and a screen reader announcing an unnamed combo box leaves
    // the user to guess what the option list is a list of.
    `<select id="problem" aria-label="Problem">${body}</select>` +
    '</div>'
  );
}
