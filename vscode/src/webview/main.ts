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
import type { ProblemChoice } from '../rbx/problems';
import { EMPTY_MODEL, type Row, type RunViewModel } from '../rbx/viewModel';
import { rowClick } from './gesture';
import {
  UiState,
  renderFilter,
  renderHeader,
  renderSelector,
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
}

declare function acquireVsCodeApi(): VsCodeApi;

const vscode = acquireVsCodeApi();

const persisted = vscode.getState();

let model: RunViewModel = EMPTY_MODEL;
/**
 * The dropdown's contents, and the host's answer for what is showing.
 *
 * Deliberately *not* in `PersistedState`: the host owns the selection and
 * re-posts it with every model, so a second copy here could only ever drift
 * from it -- and would win on reload, showing a problem the host is not
 * loading.
 */
let problems: readonly ProblemChoice[] = [];
let selectedProblem: string | undefined;
let expanded = new Set<string>(persisted?.expanded ?? []);
const touched = new Set<string>(persisted?.touched ?? []);
let selected: string | undefined = persisted?.selected;
let filter = persisted?.filter ?? '';
let pendingScrollTop: number | undefined = persisted?.scrollTop ?? 0;

const header = document.getElementById('header') as HTMLElement;
const selectorHost = document.getElementById('selector-host') as HTMLElement;
const filterHost = document.getElementById('filter-host') as HTMLElement;
const tree = document.getElementById('tree') as HTMLElement;

function uiState(): UiState {
  return { expanded, selected, filter };
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
    });
  }, 100);
}

function filterInput(): HTMLInputElement | null {
  return document.getElementById('filter') as HTMLInputElement | null;
}

function problemSelect(): HTMLSelectElement | null {
  return document.getElementById('problem') as HTMLSelectElement | null;
}

/** What `selectorHost` currently holds, so an unchanged dropdown is left alone. */
let selectorHtml = '';

/**
 * Redraw the dropdown, but only when it would actually differ.
 *
 * A `<select>` is the one control in the view that cannot survive being
 * rebuilt: replacing the element drops the focus and, on some platforms, snaps
 * the open list shut. The host re-posts the whole model on every file-watcher
 * tick of a run, so without this guard a run would fight anyone trying to use
 * the dropdown. During a run the problems and the selection are exactly what
 * does *not* change, so comparing the markup skips almost every tick.
 *
 * The rebuild that does happen -- a package appearing, or the selection moving
 * -- still puts the focus back, the way `renderAll` does for the filter box.
 */
function renderSelectorHost(): void {
  const next = renderSelector(problems, selectedProblem);
  if (next === selectorHtml) {
    return;
  }
  const focused = document.activeElement === problemSelect();
  selectorHtml = next;
  selectorHost.innerHTML = next;
  if (focused) {
    problemSelect()?.focus();
  }
}

/** Re-render the tree, keeping scroll where it was. */
function render(): void {
  const scrollTop = tree.scrollTop;
  header.innerHTML = renderHeader(model, uiState());
  tree.innerHTML = renderTree(model, uiState());
  tree.scrollTop = scrollTop;
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
  renderSelectorHost();
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
function seedExpansion(next: RunViewModel): void {
  const ids = new Set(next.rows.map((row) => row.id));
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
  const action = rowClick(row, event.detail);
  if (action.expansion === 'none') {
    select(id);
  } else {
    // Assigned rather than passed through `select`, which renders: `toggle`
    // renders too, and doing both would draw the view twice per click.
    selected = id;
    toggle(id, action.expansion === 'expand' ? true : undefined);
  }
  if (action.invoke) {
    invoke(row);
  }
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

// Delegated to the host element rather than bound to the `<select>`, because
// `renderSelectorHost` replaces that element whenever the list changes and a
// listener on it would go with it.
selectorHost.addEventListener('change', (event) => {
  const target = event.target as HTMLSelectElement;
  if (target.id === 'problem') {
    // Nothing is re-rendered here: the host is the one that decides what is
    // showing, and it answers with a fresh `state` message.
    vscode.postMessage({ type: 'select', root: target.value });
  }
});

window.addEventListener('message', (event: MessageEvent) => {
  const message = event.data as {
    type?: string;
    model?: RunViewModel;
    problems?: readonly ProblemChoice[];
    selected?: string;
  };
  if (message.type === 'state' && message.model !== undefined) {
    problems = message.problems ?? [];
    selectedProblem = message.selected;
    setModel(message.model);
  }
});

tree.addEventListener('scroll', save);

renderAll();
vscode.postMessage({ type: 'ready' });
