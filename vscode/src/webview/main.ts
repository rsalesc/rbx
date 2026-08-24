/**
 * The run view's webview client: events, focus and persistence. Nothing else.
 *
 * Every question with an answer -- what a row shows, which rows are on screen,
 * whether a filter matches -- is answered by render.ts, which `node --test` can
 * check. This file is the part no test can reach, so it is kept to the part no
 * test needs to: read a DOM event, change `state`, re-render. When a decision
 * starts creeping in here, it belongs in render.ts or in the view model.
 *
 * The tree itself -- the roving tabindex, the expansion set, the persistence
 * and the filter box -- now lives in tree.ts, shared with the Tests view. What
 * is left here is what knows about a *run*: the mismatch cycle, the Compilation
 * Findings panel, and the channel keys. Those are the pieces that could not be
 * generalized without giving the shared module a run-shaped hole.
 *
 * It talks to the extension host only through `acquireVsCodeApi`; importing the
 * `vscode` module is impossible in a webview and would not work if it were.
 */
import type { ProblemChoice } from '../rbx/problems';
import { EMPTY_MODEL, type Row, type RunViewModel } from '../rbx/viewModel';
import { rowClick } from './gesture';
import {
  UiState,
  renderCard,
  renderFilter,
  renderFindings,
  renderHeader,
  renderSelector,
  renderTree,
  visibleRows,
} from './render';
import { FilterBox, SelectorHost, TreeController, debounce } from './tree';

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
  /** Ids the user has opened or closed by hand -- see `TreeController`. */
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
let filter = persisted?.filter ?? '';
let pendingScrollTop: number | undefined = persisted?.scrollTop ?? 0;
let findingsOpen = persisted?.findingsOpen ?? false;
let findingsSignature: string | undefined = persisted?.findingsSignature;

const header = document.getElementById('header') as HTMLElement;
const selectorHost = document.getElementById('selector-host') as HTMLElement;
const filterHost = document.getElementById('filter-host') as HTMLElement;
const tree = document.getElementById('tree') as HTMLElement;
const card = document.getElementById('card') as HTMLElement;
const findings = document.getElementById('findings') as HTMLElement;

function uiState(): UiState {
  return { expanded: controller.expanded, selected: controller.selected, filter, findingsOpen };
}

function rowById(id: string | undefined): Row | undefined {
  return id === undefined ? undefined : model.rows.find((row) => row.id === id);
}

const save = debounce(() => {
  vscode.setState({
    ...controller.snapshot(),
    filter,
    findingsOpen,
    findingsSignature,
  });
});

const controller = new TreeController<Row>({
  container: tree,
  visible: () => visibleRows(model, uiState()),
  rowById,
  render: () => render(),
  invoke: (row) => invoke(row),
  click: rowClick,
  save,
  memory: persisted,
});

const selector = new SelectorHost(selectorHost);

const filterBox = new FilterBox({
  host: filterHost,
  html: () => renderFilter(uiState()),
  onInput: (value) => {
    filter = value;
    render();
    save();
  },
  onClear: () => {
    filter = '';
    renderAll();
    save();
  },
  value: () => filter,
});

/** Re-render the tree, the card and the findings panel, keeping scroll where it was. */
function render(): void {
  const scrollTop = controller.scrollTop;
  header.innerHTML = renderHeader(model, uiState());
  tree.innerHTML = renderTree(model, uiState());
  controller.scrollTop = scrollTop;
  // Redrawn with the tree rather than on its own message: the card describes
  // the selection, and the selection changes in the same breath as the rows do.
  const cardHtml = renderCard(model, uiState());
  card.innerHTML = cardHtml;
  // Empty means "the selection is not a testcase", and an empty flex item would
  // still take its border and padding with it -- the same rule the findings
  // panel follows for a clean run.
  card.classList.toggle('has-card', cardHtml !== '');
  findings.innerHTML = renderFindings(model, uiState());
  // The panel is `display: none` until it has something in it, so a clean run
  // does not leave an empty flex item taking the bottom border with it.
  findings.classList.toggle('has-findings', model.findings !== undefined);
  findings.classList.toggle('open', model.findings !== undefined && findingsOpen);
}

/** Re-render everything, including the filter box, and restore its caret. */
function renderAll(): void {
  // Asked before anything is replaced: `render` is about to throw away the
  // element holding the focus, which would drop a keyboard or screen-reader
  // user out to `<body>` on every tick of a run.
  const inTree = controller.holdsFocus();
  selector.render(renderSelector(problems, selectedProblem));
  const keptFilter = filterBox.render();
  render();
  if (!keptFilter && inTree) {
    controller.restoreFocus();
  }
}

function invoke(row: Row | undefined): void {
  if (row?.primaryCommand !== undefined) {
    vscode.postMessage({ type: 'invoke', commandId: row.primaryCommand, nodeId: row.id });
  }
}

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

function setModel(next: RunViewModel): void {
  model = next;
  seedFindings(next);
  // Finding rows expand through the same set, so their ids are named here to
  // survive the prune that goes with the seeding.
  controller.seed(next.rows, (next.findings?.rows ?? []).map((row) => row.id));
  renderAll();
  // Only the first model restores the persisted scroll: there are no rows to
  // scroll to before it arrives, and after it `render` already keeps the
  // position the user is actually at.
  if (pendingScrollTop !== undefined) {
    controller.scrollTop = pendingScrollTop;
    pendingScrollTop = undefined;
  }
  save();
}

function cycleMismatch(): void {
  // Solutions only, to agree with the header's count: a group that missed its
  // `outcomePerGroup` is also `mismatch`, so cycling over every mismatched row
  // would make "1 of 2 did not match" and the number of stops disagree.
  const misses = model.rows.filter((row) => row.kind === 'solution' && row.mismatch);
  if (misses.length === 0) {
    return;
  }
  const at = misses.findIndex((row) => row.id === controller.selected);
  const next = misses[(at + 1) % misses.length];
  controller.reveal(next.id);
  controller.select(next.id);
}

document.addEventListener('keydown', (event) => {
  // The channel switch, mirroring `rbx ui`'s 1/2/3. Handled here rather than
  // contributed as a keybinding because a webview does not reliably forward
  // unhandled keys to the workbench, and a shortcut that works only sometimes
  // is worse than one that lives where the view can see it.
  //
  // `alt` and not the bare digits `rbx ui` uses: this view has a filter box,
  // and a bare `2` has to be able to reach it.
  if (event.altKey && ['1', '2', '3'].includes(event.key)) {
    const channel = (['out', 'err', 'log'] as const)[Number(event.key) - 1];
    const selected = controller.selected;
    if (selected !== undefined) {
      invokeOn(CHANNEL_COMMANDS[channel], selected);
      event.preventDefault();
    }
  }
});

header.addEventListener('click', (event) => {
  if ((event.target as HTMLElement).closest('#next-mismatch') !== null) {
    cycleMismatch();
  }
});

// Delegated to the host element rather than bound to the `<select>`, because
// the selector replaces that element whenever the list changes and a listener
// on it would go with it.
selectorHost.addEventListener('change', (event) => {
  const target = event.target as HTMLSelectElement;
  if (target.id === 'problem') {
    // Nothing is re-rendered here: the host is the one that decides what is
    // showing, and it answers with a fresh `state` message.
    vscode.postMessage({ type: 'select', root: target.value });
  }
});

/** Ask the host to run a command against a row, by id. */
function invokeOn(commandId: string, nodeId: string): void {
  vscode.postMessage({ type: 'invoke', commandId, nodeId });
}

/** The command each channel button and each `alt` key stands for. */
const CHANNEL_COMMANDS: Record<string, string> = {
  out: 'rbx.showOutput',
  err: 'rbx.showStderr',
  log: 'rbx.showLog',
};

/**
 * Everything the card responds to, on the container rather than its contents:
 * the card is replaced wholesale on every selection, so a listener bound inside
 * it would be thrown away with the first move of the highlight.
 *
 * The card always describes the selected row, so `selected` is the id every one
 * of these commands acts on -- the buttons carry an action and no id of their
 * own, which is what stops a stale card from naming a row that has moved on.
 */
card.addEventListener('click', (event) => {
  const button = (event.target as HTMLElement).closest(
    '.card-channel, .card-origin',
  ) as HTMLElement | null;
  const action = button?.dataset.action;
  const selected = controller.selected;
  if (action === undefined || selected === undefined) {
    return;
  }
  // A channel button names a channel; an origin already carries the command it
  // opens with, decided in the view model where "is this a real file" is known.
  invokeOn(CHANNEL_COMMANDS[action] ?? action, selected);
});

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
    invokeOn('rbx.openSolution', warning.dataset.id);
    return;
  }
  const row = target.closest('.finding-row') as HTMLElement | null;
  const id = row?.dataset.id;
  if (id === undefined) {
    return;
  }
  const action = (target.closest('.finding-action') as HTMLElement | null)?.dataset.action;
  if (action === 'source') {
    invokeOn('rbx.openSolution', id);
    return;
  }
  if (action === 'log') {
    invokeOn('rbx.openCompileLog', id);
    return;
  }
  // A row with warnings under it opens them; a row that failed to compile has
  // nothing to expand, so clicking it goes where the answer is -- the compiler's
  // own output.
  const expandable =
    row !== null && row.querySelector('.finding-twisty[aria-expanded]') !== null;
  if (expandable) {
    controller.toggle(id);
    return;
  }
  invokeOn('rbx.openCompileLog', id);
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

renderAll();
vscode.postMessage({ type: 'ready' });
