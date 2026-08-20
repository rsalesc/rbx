/**
 * The webview client: events, focus and persistence. Nothing else.
 *
 * Every question with an answer -- what a row shows, which rows are on screen,
 * whether a filter matches -- is answered by render.ts, which `node --test` can
 * check. This file is the part no test can reach, so it is kept to the part no
 * test needs to: read a DOM event, change `state`, re-render. When a decision
 * starts creeping in here, it belongs in render.ts or in the view model.
 *
 * It talks to the extension host only through `acquireVsCodeApi`; importing the
 * `vscode` module is impossible in a webview and would not work if it were.
 */
import type { Row, RunViewModel } from '../rbx/viewModel';
import {
  UiState,
  renderFilter,
  renderFindings,
  renderHeader,
  renderTree,
  visibleRows,
} from './render';

interface VsCodeApi {
  postMessage(message: unknown): void;
  getState(): PersistedState | undefined;
  setState(state: PersistedState): void;
}

interface PersistedState {
  readonly expanded: string[];
  readonly selected?: string;
  readonly filter: string;
  readonly scrollTop: number;
  /**
   * Ids the user has opened or closed by hand.
   *
   * Without this, a re-render cannot tell "never seen" from "deliberately
   * closed", and the `defaultExpanded` seed would reopen every node the user
   * shut. The TreeView got that distinction free from `TreeItem.id`
   * persistence; losing it would be a regression.
   */
  readonly touched: string[];
  readonly findingsOpen: boolean;
  /**
   * The findings the panel's open/closed state was last decided against.
   *
   * The host re-posts the whole model on every file-watcher tick, so "a new
   * model arrived" cannot mean "a new run started". Without this, a panel the
   * user closed would spring open again on the next tick of the same run.
   */
  readonly findingsSignature?: string;
}

declare function acquireVsCodeApi(): VsCodeApi;

const vscode = acquireVsCodeApi();

const EMPTY_MODEL: RunViewModel = { rows: [], mismatches: 0, warned: 0, empty: true };

const persisted = vscode.getState();

let model: RunViewModel = EMPTY_MODEL;
let expanded = new Set<string>(persisted?.expanded ?? []);
const touched = new Set<string>(persisted?.touched ?? []);
let selected: string | undefined = persisted?.selected;
let filter = persisted?.filter ?? '';
let pendingScrollTop: number | undefined = persisted?.scrollTop ?? 0;
let findingsOpen = persisted?.findingsOpen ?? false;
let findingsSignature: string | undefined = persisted?.findingsSignature;

const header = document.getElementById('header') as HTMLElement;
const filterHost = document.getElementById('filter-host') as HTMLElement;
const tree = document.getElementById('tree') as HTMLElement;
const findings = document.getElementById('findings') as HTMLElement;

function uiState(): UiState {
  return { expanded, selected, filter, findingsOpen };
}

function rowById(id: string | undefined): Row | undefined {
  return id === undefined ? undefined : model.rows.find((row) => row.id === id);
}

let saveTimer: ReturnType<typeof setTimeout> | undefined;

function save(): void {
  if (saveTimer !== undefined) {
    clearTimeout(saveTimer);
  }
  saveTimer = setTimeout(() => {
    vscode.setState({
      expanded: [...expanded],
      selected,
      filter,
      scrollTop: tree.scrollTop,
      touched: [...touched],
      findingsOpen,
      findingsSignature,
    });
  }, 100);
}

function filterInput(): HTMLInputElement | null {
  return document.getElementById('filter') as HTMLInputElement | null;
}

/** Re-render the tree and the findings panel, keeping scroll where it was. */
function render(): void {
  const scrollTop = tree.scrollTop;
  header.innerHTML = renderHeader(model, uiState());
  tree.innerHTML = renderTree(model, uiState());
  tree.scrollTop = scrollTop;
  findings.innerHTML = renderFindings(model, uiState());
  // The panel is `display: none` until it has something in it, so a clean run
  // does not leave an empty flex item taking the bottom border with it.
  findings.classList.toggle('has-findings', model.findings !== undefined);
  findings.classList.toggle('open', model.findings !== undefined && findingsOpen);
}

/** Re-render everything, including the filter box, and restore its caret. */
function renderAll(): void {
  const input = filterInput();
  const inFilter = input !== null && document.activeElement === input;
  // The caret, not just the focus: the host re-posts the model on every
  // file-watcher tick during a run, and putting the caret back at the end would
  // move it out from under someone editing the middle of a filter.
  const start = inFilter ? input.selectionStart : null;
  const end = inFilter ? input.selectionEnd : null;
  // A row can hold the focus too, and `render` is about to replace the element
  // holding it -- which would drop a keyboard or screen-reader user out to
  // `<body>` on every tick of a run.
  const inTree = tree.contains(document.activeElement);
  filterHost.innerHTML = renderFilter(uiState());
  render();
  if (inFilter) {
    const next = filterInput();
    next?.focus();
    if (start !== null && end !== null) {
      next?.setSelectionRange(start, end);
    }
  } else if (inTree) {
    if (elementFor(selected) === null) {
      // The focused row went away with the refresh; the container keeps the
      // focus inside the view so the next arrow key still reaches the tree.
      tree.focus({ preventScroll: true });
    } else {
      focusSelected();
    }
  }
}

function elementFor(id: string | undefined): HTMLElement | null {
  if (id === undefined) {
    return null;
  }
  return tree.querySelector(`[data-id="${CSS.escape(id)}"]`);
}

function focusSelected(): void {
  const element = elementFor(selected);
  if (element === null) {
    return;
  }
  element.focus({ preventScroll: true });
  element.scrollIntoView({ block: 'nearest' });
}

function select(id: string | undefined): void {
  selected = id;
  render();
  focusSelected();
  save();
}

function toggle(id: string, open?: boolean): void {
  const shouldOpen = open ?? !expanded.has(id);
  if (shouldOpen) {
    expanded.add(id);
  } else {
    expanded.delete(id);
  }
  // Remember that this one was the user's call, so the next model's
  // `defaultExpanded` seed leaves it alone.
  touched.add(id);
  render();
  focusSelected();
  save();
}

function invoke(row: Row | undefined): void {
  if (row?.primaryCommand !== undefined) {
    vscode.postMessage({ type: 'invoke', commandId: row.primaryCommand, nodeId: row.id });
  }
}

/**
 * Open what the model says opens by default, without undoing the user.
 *
 * Only ids the user has never touched are seeded, so a solution they collapsed
 * stays collapsed across every refresh of the run.
 */
/**
 * Open the panel on a run that failed to compile something, once.
 *
 * Only on a *new* run -- a changed signature -- and only ever to open: a
 * warnings-only run is left for the badge to advertise, and a panel the user
 * closed stays closed for the rest of that run however many times the host
 * re-posts the model.
 */
function seedFindings(next: RunViewModel): void {
  const signature = next.findings?.signature;
  if (signature === findingsSignature) {
    return;
  }
  findingsSignature = signature;
  if (next.findings?.errors === true) {
    findingsOpen = true;
  }
}

function seedExpansion(next: RunViewModel): void {
  const ids = new Set([
    ...next.rows.map((row) => row.id),
    // Finding rows expand through the same `expanded` set, so their ids have to
    // survive the prune below.
    ...(next.findings?.rows ?? []).map((row) => row.id),
  ]);
  for (const row of next.rows) {
    if (row.defaultExpanded && !touched.has(row.id)) {
      expanded.add(row.id);
    }
  }
  // Rows that no longer exist would otherwise accumulate forever across runs.
  // `touched` is pruned with `expanded` and for the same reason: it is only
  // ever read for rows of the current model, and the persisted blob is
  // rewritten on every scroll. Keeping it would remember the collapse of a
  // solution that disappears and comes back, but rows here come from the
  // package's solution list and are present for the whole run -- so that case
  // is a state file that grows without bound in exchange for nothing.
  expanded = new Set([...expanded].filter((id) => ids.has(id)));
  for (const id of [...touched]) {
    if (!ids.has(id)) {
      touched.delete(id);
    }
  }
  if (selected !== undefined && !ids.has(selected)) {
    selected = undefined;
  }
}

function setModel(next: RunViewModel): void {
  model = next;
  seedFindings(next);
  seedExpansion(next);
  renderAll();
  // Only the first model restores the persisted scroll: there are no rows to
  // scroll to before it arrives, and after it `render` already keeps the
  // position the user is actually at.
  if (pendingScrollTop !== undefined) {
    tree.scrollTop = pendingScrollTop;
    pendingScrollTop = undefined;
  }
  save();
}

/** Open every ancestor of `id`, so a jump can land on a buried row. */
function revealAncestors(id: string): void {
  let row = rowById(id);
  while (row?.parentId !== undefined) {
    expanded.add(row.parentId);
    row = rowById(row.parentId);
  }
}

function cycleMismatch(): void {
  // Solutions only, to agree with the header's count: a group that missed its
  // `outcomePerGroup` is also `mismatch`, so cycling over every mismatched row
  // would make "1 of 2 did not match" and the number of stops disagree.
  const misses = model.rows.filter((row) => row.kind === 'solution' && row.mismatch);
  if (misses.length === 0) {
    return;
  }
  const at = misses.findIndex((row) => row.id === selected);
  const next = misses[(at + 1) % misses.length];
  revealAncestors(next.id);
  select(next.id);
}

tree.addEventListener('click', (event) => {
  const target = event.target as HTMLElement;
  const element = target.closest('.row') as HTMLElement | null;
  const id = element?.dataset.id;
  if (id === undefined) {
    return;
  }
  const row = rowById(id);
  // `detail` is the click count, so the second click of a double click selects
  // without acting twice -- which would otherwise expand a node and instantly
  // collapse it again, or open the same testcase twice.
  const acts = event.detail <= 1;
  // A click anywhere on a parent row expands it, not just one on the 16px
  // twisty. The twisty is a target you have to aim at, and every other row in
  // the view responds to being clicked anywhere along it.
  if (acts && row?.expandable === true) {
    // Assigned rather than passed through `select`, which renders: `toggle`
    // renders too, and doing both would draw the view twice per click.
    selected = id;
    toggle(id);
    return;
  }
  select(id);
  if (!acts) {
    return;
  }
  // A leaf opens on a single click, as it did when this view was a `TreeView`
  // and the row carried `TreeItem.command` -- VS Code fires that on the first
  // click, and every tree in the product opens a testcase the same way.
  invoke(row);
});

tree.addEventListener('keydown', (event) => {
  const rows = visibleRows(model, uiState());
  const at = rows.findIndex((row) => row.id === selected);
  const row = at < 0 ? undefined : rows[at];
  const move = (index: number): void => {
    const target = rows[Math.max(0, Math.min(rows.length - 1, index))];
    if (target !== undefined) {
      select(target.id);
    }
  };

  switch (event.key) {
    case 'ArrowDown':
      move(at + 1);
      break;
    case 'ArrowUp':
      move(at < 0 ? 0 : at - 1);
      break;
    case 'ArrowRight':
      if (row === undefined) {
        return;
      }
      if (row.expandable && !expanded.has(row.id)) {
        toggle(row.id, true);
      } else {
        move(at + 1);
      }
      break;
    case 'ArrowLeft':
      if (row === undefined) {
        return;
      }
      if (row.expandable && expanded.has(row.id)) {
        toggle(row.id, false);
      } else if (row.parentId !== undefined) {
        select(row.parentId);
      }
      break;
    case 'Home':
      move(0);
      break;
    case 'End':
      move(rows.length - 1);
      break;
    case 'Enter':
      invoke(row);
      break;
    default:
      return;
  }
  event.preventDefault();
});

document.addEventListener('keydown', (event) => {
  const input = filterInput();
  if (event.key === '/' && document.activeElement !== input) {
    input?.focus();
    input?.select();
    event.preventDefault();
    return;
  }
  if (event.key === 'Escape' && filter !== '') {
    filter = '';
    renderAll();
    save();
    event.preventDefault();
  }
});

filterHost.addEventListener('input', (event) => {
  filter = (event.target as HTMLInputElement).value;
  render();
  save();
});

header.addEventListener('click', (event) => {
  if ((event.target as HTMLElement).closest('#next-mismatch') !== null) {
    cycleMismatch();
  }
});

/** Ask the host to open one of a finding's two files. */
function openFinding(commandId: string, nodeId: string): void {
  vscode.postMessage({ type: 'invoke', commandId, nodeId });
}

function toggleFindings(open?: boolean): void {
  findingsOpen = open ?? !findingsOpen;
  render();
  save();
}

/**
 * Everything the panel responds to, in one listener on a container that
 * survives re-rendering -- the same arrangement the tree uses, and for the same
 * reason: the elements inside are replaced wholesale on every model.
 */
findings.addEventListener('click', (event) => {
  const target = event.target as HTMLElement;
  if (target.closest('#findings-header') !== null) {
    toggleFindings();
    return;
  }
  const warning = target.closest('.finding-warning') as HTMLElement | null;
  if (warning?.dataset.id !== undefined) {
    // The warning knows its own line; the host reads it off the node this id
    // resolves to, so nothing about a position has to survive postMessage.
    openFinding('rbx.openSolutionSource', warning.dataset.id);
    return;
  }
  const row = target.closest('.finding-row') as HTMLElement | null;
  const id = row?.dataset.id;
  if (id === undefined) {
    return;
  }
  const action = (target.closest('.finding-action') as HTMLElement | null)?.dataset.action;
  if (action === 'source') {
    openFinding('rbx.openSolutionSource', id);
    return;
  }
  if (action === 'log') {
    openFinding('rbx.openCompileLog', id);
    return;
  }
  // A row with warnings under it opens them; a row that failed to compile has
  // nothing to expand, so clicking it goes where the answer is -- the compiler's
  // own output.
  const expandable =
    row !== null && row.querySelector('.finding-twisty[aria-expanded]') !== null;
  if (expandable) {
    toggle(id);
    return;
  }
  openFinding('rbx.openCompileLog', id);
});

findings.addEventListener('keydown', (event) => {
  const target = event.target as HTMLElement;
  // The header is a `div` playing a button, so it has to honour both keys a
  // real button would.
  if (target.id === 'findings-header' && (event.key === 'Enter' || event.key === ' ')) {
    toggleFindings();
    event.preventDefault();
  }
});

window.addEventListener('message', (event: MessageEvent) => {
  const message = event.data as { type?: string; model?: RunViewModel };
  if (message.type === 'state' && message.model !== undefined) {
    setModel(message.model);
  }
});

tree.addEventListener('scroll', save);

renderAll();
vscode.postMessage({ type: 'ready' });
