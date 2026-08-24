/**
 * The `rbx: Testset` panel's client: events and persistence. Nothing else.
 *
 * Same discipline as main.ts, and for the same reason: every question with an
 * answer -- which cells belong to the picked group, what a coverage cell is
 * hued, how a size is spelled -- is answered upstream where `node --test` can
 * reach it. What is left here is the part no test can reach, so it is kept to
 * reading a DOM event, changing `state`, and re-rendering.
 *
 * The tab and the picked group are client state on purpose. Both are pure
 * presentation over a model the host has already posted whole, so switching a
 * tab is a re-render rather than a round trip -- and a watcher tick that
 * re-posts the model does not throw the reader back to the first tab.
 *
 * panelViewModel.ts is imported for its types only, and must stay that way: its
 * values reach `model.ts`, which imports Node's `path` and cannot be bundled
 * for a browser. The same rule holds in panelRender.ts.
 */
import type {
  PanelTab,
  PanelUiState,
  PanelViewModel,
  VisualizationChannel,
} from '../rbx/panelViewModel';
import { type PanelAssets, renderPanel } from './panelRender';

interface VsCodeApi {
  postMessage(message: unknown): void;
  getState(): PersistedState | undefined;
  setState(state: PersistedState): void;
}

interface PersistedState {
  readonly tab: PanelTab;
  readonly group?: string;
  readonly channel?: VisualizationChannel;
  readonly scrollTop: number;
}

declare function acquireVsCodeApi(): VsCodeApi;

const vscode = acquireVsCodeApi();
const persisted = vscode.getState();

/** Undefined until the host answers `ready`, which it does immediately. */
let model: PanelViewModel | undefined;
let assets: PanelAssets = {};
let tab: PanelTab = persisted?.tab ?? 'gallery';
let group: string | undefined = persisted?.group;
let channel: VisualizationChannel | undefined = persisted?.channel;
let pendingScrollTop: number | undefined = persisted?.scrollTop;

const panel = document.getElementById('panel') as HTMLElement;

function state(): PanelUiState {
  return { tab, group, channel };
}

function save(): void {
  vscode.setState({ tab, group, channel, scrollTop: panel.scrollTop });
}

function draw(): void {
  if (model === undefined) {
    return;
  }
  panel.innerHTML = renderPanel(model, state(), assets);
  if (pendingScrollTop !== undefined) {
    panel.scrollTop = pendingScrollTop;
    pendingScrollTop = undefined;
  }
}

/**
 * A click anywhere in the body, resolved by walking up to the thing it hit.
 *
 * Delegated rather than bound per cell: the body is replaced wholesale on every
 * draw, and re-binding hundreds of gallery cells each time is how a panel over
 * a large testset starts to feel slow.
 */
panel.addEventListener('click', (event) => {
  const target = event.target as HTMLElement | null;
  const tabButton = target?.closest('[data-tab]') as HTMLElement | null;
  if (tabButton !== null && tabButton !== undefined) {
    tab = (tabButton.dataset.tab ?? 'gallery') as PanelTab;
    save();
    draw();
    return;
  }
  // Checked before `[data-open]`, because the button lives inside the cell and
  // the cell now carries `data-open` too -- the inner, more specific intent has
  // to win the `closest` race.
  const testcase = target?.closest('[data-testcase]') as HTMLElement | null;
  if (testcase !== null && testcase !== undefined) {
    vscode.postMessage({ type: 'openTestcase', id: testcase.dataset.testcase });
    return;
  }
  const open = target?.closest('[data-open]') as HTMLElement | null;
  if (open !== null && open !== undefined) {
    // Activating a picture opens that picture. It used to open the *testcase*,
    // which is a different file and a surprising answer to clicking an image;
    // the testcase now has its own button in the caption.
    vscode.postMessage({ type: 'openFile', id: open.dataset.open });
  }
});

// Enter and Space on a focused cell, so the gallery is reachable by keyboard.
// The cells carry `tabindex="0"` rather than a roving tab stop: a grid has no
// single axis to rove along, and Tab through a screenful is the behaviour the
// platform already gives for free.
panel.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' && event.key !== ' ') {
    return;
  }
  const cell = (event.target as HTMLElement | null)?.closest('.cell') as HTMLElement | null;
  if (cell !== null && cell !== undefined) {
    event.preventDefault();
    // Matches the click: the keyboard must not reach a different file than the
    // pointer does on the same cell.
    vscode.postMessage({ type: 'openFile', id: cell.dataset.open });
  }
});

panel.addEventListener('change', (event) => {
  const picker = event.target as HTMLSelectElement | null;
  if (picker?.id === 'channel') {
    channel = picker.value === '' ? undefined : (picker.value as VisualizationChannel);
    save();
    draw();
    return;
  }
  if (picker?.id !== 'group') {
    return;
  }
  group = picker.value === '' ? undefined : picker.value;
  save();
  draw();
});

panel.addEventListener('scroll', () => save(), { passive: true });

window.addEventListener('message', (event: MessageEvent) => {
  const message = event.data as {
    type?: string;
    model?: PanelViewModel;
    assets?: PanelAssets;
    tab?: PanelTab;
    group?: string;
    cellId?: string;
  };
  if (message.type === 'state') {
    model = message.model;
    assets = message.assets ?? {};
    if (message.tab !== undefined) {
      // The host only names a tab when the open asked for one, so a plain
      // refresh never moves the reader off the tab they are on.
      tab = message.tab;
    }
    if (message.group !== undefined) {
      group = message.group;
    }
    save();
    draw();
    return;
  }
  if (message.type === 'reveal' && message.cellId !== undefined) {
    // Live-follow from the sidebar. The gallery is the only tab with something
    // to reveal, so following implies switching to it -- otherwise the panel
    // would silently scroll a tab nobody is looking at.
    tab = 'gallery';
    const cell = model?.gallery.cells.find((candidate) => candidate.id === message.cellId);
    if (cell !== undefined && cell.group !== group && group !== undefined) {
      group = cell.group;
    }
    // A channel filter that hides what was just asked for turns a reveal into
    // nothing happening, which reads as the panel ignoring the sidebar. The
    // ask wins over the filter.
    if (cell !== undefined && channel !== undefined && cell.channel !== channel) {
      channel = undefined;
    }
    draw();
    const element = document.querySelector(`.cell[data-id="${CSS.escape(message.cellId)}"]`);
    element?.scrollIntoView({ block: 'nearest' });
    element?.classList.add('cell-revealed');
    save();
  }
});

draw();
vscode.postMessage({ type: 'ready' });
