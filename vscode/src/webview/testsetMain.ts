/**
 * The Tests view's webview client: events, focus and persistence. Nothing else.
 *
 * The same division of labour main.ts states, and the same reason for it:
 * everything with an answer lives in testsetRender.ts and testsetViewModel.ts,
 * where `node --test` can check it, and what is left here is the part no test
 * can reach.
 *
 * The tree, the filter box and the problem dropdown are tree.ts's -- shared
 * with the Run view so the two surfaces in one container cannot start
 * navigating differently. What is this view's own is the panel request: the
 * sidebar is 300px and deliberately does not try to be wide, so anything that
 * wants width is a deliberate open, posted to the host as a message.
 */
import type { ProblemChoice } from '../rbx/problems';
import type { TestsetRow, TestsetViewModel } from '../rbx/testsetViewModel';
import { renderSelector } from './render';
import {
  TestsetUiState,
  renderTestsetCard,
  renderTestsetFilter,
  renderTestsetHeader,
  renderTestsetTree,
  visibleTestsetRows,
} from './testsetRender';
import { FilterBox, SelectorHost, TreeClick, TreeController, debounce } from './tree';

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
  readonly touched: string[];
}

declare function acquireVsCodeApi(): VsCodeApi;

const vscode = acquireVsCodeApi();
const persisted = vscode.getState();

/**
 * The starting state, spelled out rather than imported.
 *
 * `EMPTY_TESTSET_MODEL` says the same thing, but importing a *value* from
 * testsetViewModel.ts would pull the manifest parser -- and, through it, node's
 * `path` -- into a bundle that runs in a browser. The client never parses
 * anything; the host hands it a model or it draws nothing.
 */
const EMPTY: TestsetViewModel = { rows: [], empty: true };

let model: TestsetViewModel = EMPTY;
/**
 * The dropdown's contents, and the host's answer for what is showing.
 *
 * Not persisted, for the reason main.ts gives: the host owns the selection and
 * re-posts it with every model, so a second copy here could only ever drift.
 */
let problems: readonly ProblemChoice[] = [];
let selectedProblem: string | undefined;
let filter = persisted?.filter ?? '';
let pendingScrollTop: number | undefined = persisted?.scrollTop ?? 0;

const header = document.getElementById('header') as HTMLElement;
const selectorHost = document.getElementById('selector-host') as HTMLElement;
const filterHost = document.getElementById('filter-host') as HTMLElement;
const tree = document.getElementById('tree') as HTMLElement;
const card = document.getElementById('card') as HTMLElement;

function uiState(): TestsetUiState {
  return { expanded: controller.expanded, selected: controller.selected, filter };
}

function rowById(id: string | undefined): TestsetRow | undefined {
  return id === undefined ? undefined : model.rows.find((row) => row.id === id);
}

const save = debounce(() => {
  vscode.setState({ ...controller.snapshot(), filter });
});

/**
 * What a click does. The same rule `gesture.rowClick` states for the Run view.
 *
 * Spelled out again rather than shared because `rowClick` reads a run `Row`,
 * and the two facts it needs -- does this row expand, does it open anything --
 * are the only ones either view consults. A group expands on a click anywhere
 * along it; a testcase opens on a single click, as a `TreeItem.command` did.
 */
function testsetClick(row: TestsetRow | undefined, detail: number): TreeClick {
  if (row === undefined || detail > 1) {
    return { expansion: 'none', invoke: false };
  }
  return {
    expansion: row.expandable ? 'toggle' : 'none',
    invoke: !row.expandable && row.primaryCommand !== undefined,
  };
}

const controller = new TreeController<TestsetRow>({
  container: tree,
  visible: () => visibleTestsetRows(model, uiState()),
  rowById,
  render: () => render(),
  invoke: (row) => invoke(row),
  click: testsetClick,
  save,
  memory: persisted,
});

const selector = new SelectorHost(selectorHost);

const filterBox = new FilterBox({
  host: filterHost,
  html: () => renderTestsetFilter(uiState()),
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

/** Re-render the header, the tree and the card, keeping scroll where it was. */
function render(): void {
  const scrollTop = controller.scrollTop;
  header.innerHTML = renderTestsetHeader(model);
  tree.innerHTML = renderTestsetTree(model, uiState());
  controller.scrollTop = scrollTop;
  const cardHtml = renderTestsetCard(model, uiState());
  card.innerHTML = cardHtml;
  // Empty means "the selection is not a testcase", and an empty flex item would
  // still take its border and padding with it.
  card.classList.toggle('has-card', cardHtml !== '');
}

function renderAll(): void {
  const inTree = controller.holdsFocus();
  selector.render(renderSelector(problems, selectedProblem));
  const keptFilter = filterBox.render();
  render();
  if (!keptFilter && inTree) {
    controller.restoreFocus();
  }
}

function invoke(row: TestsetRow | undefined): void {
  if (row?.primaryCommand !== undefined) {
    vscode.postMessage({ type: 'invoke', commandId: row.primaryCommand, nodeId: row.id });
  }
}

/** Ask the host to run a command against a row, by id. */
function invokeOn(commandId: string, nodeId: string): void {
  vscode.postMessage({ type: 'invoke', commandId, nodeId });
}

/**
 * Ask the host to open the wide surface, on a tab and about a row.
 *
 * The row travels as an id like everything else crossing this boundary; the
 * host resolves it and the panel decides what to do with it.
 */
function openPanel(tab: 'gallery' | 'coverage' | 'stats', nodeId?: string): void {
  vscode.postMessage({ type: 'panel', tab, nodeId });
}

function setModel(next: TestsetViewModel): void {
  model = next;
  controller.seed(next.rows);
  renderAll();
  // Only the first model restores the persisted scroll: there are no rows to
  // scroll to before it arrives, and after it `render` keeps the position the
  // user is actually at.
  if (pendingScrollTop !== undefined) {
    controller.scrollTop = pendingScrollTop;
    pendingScrollTop = undefined;
  }
  save();
}

header.addEventListener('click', (event) => {
  if ((event.target as HTMLElement).closest('#open-panel') !== null) {
    openPanel('gallery', controller.selected);
  }
});

// Delegated to the host element rather than bound to the `<select>`: the
// selector replaces that element whenever the list changes.
selectorHost.addEventListener('change', (event) => {
  const target = event.target as HTMLSelectElement;
  if (target.id === 'problem') {
    vscode.postMessage({ type: 'select', root: target.value });
  }
});

/**
 * Everything the card responds to, on the container rather than its contents:
 * the card is replaced wholesale on every selection, so a listener bound inside
 * it would be thrown away with the first move of the highlight.
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
  if (action.startsWith('panel:')) {
    openPanel(action.slice('panel:'.length) as 'gallery' | 'coverage' | 'stats', selected);
    return;
  }
  // Every other action already carries the command it opens with, decided in
  // the view model where "is this a real file" is known.
  invokeOn(action, selected);
});

window.addEventListener('message', (event: MessageEvent) => {
  const message = event.data as {
    type?: string;
    model?: TestsetViewModel;
    problems?: readonly ProblemChoice[];
    selected?: string;
  };
  if (message.type === 'state' && message.model !== undefined) {
    problems = message.problems ?? [];
    selectedProblem = message.selected;
    setModel(message.model);
  }
});

/**
 * Tell the host where the highlight is, so the panel can follow it.
 *
 * Posted from a listener on the tree rather than from `select`, because the
 * selection also moves through the keyboard, the click handler and a model
 * refresh -- and the panel following only *some* of those would be worse than
 * it not following at all. `focusin` fires for every one of them: the roving
 * tab stop moves with the selection by construction.
 */
tree.addEventListener('focusin', (event) => {
  const id = (event.target as HTMLElement).closest('.row')?.getAttribute('data-id');
  if (id !== null && id !== undefined) {
    vscode.postMessage({ type: 'selection', nodeId: id });
  }
});

renderAll();
vscode.postMessage({ type: 'ready' });
