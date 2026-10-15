/**
 * The statement preview's webview client: pdf.js, bundled, rendering the PDF
 * the host posts.
 *
 * The host decides what to show; this keeps the reader's place. A rebuild of
 * the output on screen arrives as the same `id` with a new `revision`, and the
 * new document opens at the zoom and scroll position the old one was left at --
 * which is the whole difference between a preview you can edit beside and one
 * you have to find your place in again after every save.
 *
 * pdf.js runs its parser in a worker. A webview cannot start a worker from its
 * resource origin, so the worker script is fetched and started from a blob
 * (`worker-src blob:` in the host's CSP). Nothing is loaded from the network:
 * the preview works offline and over a remote connection alike.
 */
import './pdfjsGlobal.js';

import * as pdfjs from 'pdfjs-dist';
import { EventBus, PDFLinkService, PDFViewer } from 'pdfjs-dist/web/pdf_viewer.mjs';

import type { ClientMessage, HostMessage, PreviewModel } from './statementProtocol.js';

interface VsCodeApi {
  postMessage(message: ClientMessage): void;
  getState(): unknown;
  setState(state: unknown): void;
}
declare function acquireVsCodeApi(): VsCodeApi;

const vscode = acquireVsCodeApi();
const post = (message: ClientMessage) => vscode.postMessage(message);

/** What survives the panel being reloaded: the zoom the reader chose. */
interface SavedState {
  readonly scale?: string;
}

function savedScale(): string | undefined {
  const state = vscode.getState() as SavedState | undefined;
  return typeof state?.scale === 'string' ? state.scale : undefined;
}

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (found === null) {
    throw new Error(`statement preview: missing #${id}`);
  }
  return found as T;
}

const outputs = element<HTMLSelectElement>('outputs');
const status = element<HTMLSpanElement>('status');
const buildButton = element<HTMLButtonElement>('build');
const sourceButton = element<HTMLButtonElement>('source');
const logButton = element<HTMLButtonElement>('log');
const page = element<HTMLSpanElement>('page');
const banner = element<HTMLDivElement>('banner');
const empty = element<HTMLDivElement>('empty');
const emptyMessage = element<HTMLParagraphElement>('emptyMessage');
const emptyAction = element<HTMLButtonElement>('emptyAction');
const container = element<HTMLDivElement>('viewerContainer');

let model: PreviewModel | undefined;

// --- The document --------------------------------------------------------

let workerStarted: Promise<void> | undefined;

function startWorker(): Promise<void> {
  workerStarted ??= (async () => {
    const response = await fetch(document.body.dataset.worker ?? '');
    const blob = new Blob([await response.text()], { type: 'text/javascript' });
    pdfjs.GlobalWorkerOptions.workerPort = new Worker(URL.createObjectURL(blob), {
      type: 'module',
    });
  })();
  return workerStarted;
}

const eventBus = new EventBus();
const linkService = new PDFLinkService({ eventBus });
const viewer = new PDFViewer({ container, eventBus, linkService });
linkService.setViewer(viewer);

interface Shown {
  readonly id: string;
  readonly revision: string;
  readonly doc: pdfjs.PDFDocumentProxy;
}

let shown: Shown | undefined;
/** Bumped per load, so a slow parse cannot land over a newer one. */
let loads = 0;
/** Where to put the reader once the next document's pages exist. */
let place: { top: number; left: number; scale: string } | undefined;

async function showDocument(id: string, revision: string, data: Uint8Array): Promise<void> {
  if (shown?.id === id && shown.revision === revision) {
    return;
  }
  const load = ++loads;
  await startWorker();
  const doc = await pdfjs.getDocument({ data, isEvalSupported: false }).promise;
  if (load !== loads) {
    void doc.destroy();
    return;
  }
  // The same output rebuilt keeps its place; another output starts at the top.
  place =
    shown?.id === id
      ? { top: container.scrollTop, left: container.scrollLeft, scale: viewer.currentScaleValue }
      : undefined;
  const previous = shown?.doc;
  shown = { id, revision, doc };
  viewer.setDocument(doc);
  linkService.setDocument(doc, null);
  void previous?.destroy();
  layout();
}

eventBus.on('pagesinit', () => {
  viewer.currentScaleValue = place?.scale ?? savedScale() ?? 'page-width';
  if (place !== undefined) {
    container.scrollTop = place.top;
    container.scrollLeft = place.left;
  }
  place = undefined;
  showPage();
});

eventBus.on('scalechanging', () => {
  vscode.setState({ scale: viewer.currentScaleValue } satisfies SavedState);
});

function showPage(): void {
  page.textContent =
    viewer.pagesCount > 0 ? `${viewer.currentPageNumber} / ${viewer.pagesCount}` : '';
}
eventBus.on('pagechanging', showPage);

// A "fit width" zoom has to be re-fitted when the panel is resized.
// Not while hidden: a hidden container has no size to fit, and pdf.js complains.
new ResizeObserver(() => {
  if (container.hidden || container.clientWidth === 0) {
    return;
  }
  const scale = viewer.currentScaleValue;
  if (shown !== undefined && (scale === 'page-width' || scale === 'page-fit' || scale === 'auto')) {
    viewer.currentScaleValue = scale;
  }
}).observe(container);

element('zoomOut').addEventListener('click', () => viewer.decreaseScale());
element('zoomIn').addEventListener('click', () => viewer.increaseScale());
element('fit').addEventListener('click', () => {
  viewer.currentScaleValue = 'page-width';
});
container.addEventListener(
  'wheel',
  (event) => {
    if (!event.ctrlKey && !event.metaKey) {
      return;
    }
    event.preventDefault();
    if (event.deltaY < 0) {
      viewer.increaseScale();
    } else {
      viewer.decreaseScale();
    }
  },
  { passive: false },
);

// --- The chrome around it ------------------------------------------------

function renderModel(next: PreviewModel): void {
  model = next;

  outputs.replaceChildren(
    ...next.outputs.map((item) => {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = item.ok ? item.label : `${item.label} (failed)`;
      return option;
    }),
  );
  outputs.value = next.selected ?? '';
  outputs.disabled = next.outputs.length < 2;
  outputs.hidden = next.outputs.length === 0;

  status.textContent = next.building ? 'building…' : (next.summary ?? '');
  status.className = next.building ? 'building' : next.ok ? 'ok' : 'failed';
  buildButton.disabled = next.building;
  sourceButton.hidden = !next.hasSource;
  logButton.hidden = !next.hasLog;

  renderBanner(next);

  empty.hidden = next.empty === undefined;
  if (next.empty !== undefined) {
    emptyMessage.textContent = next.empty.message;
    emptyAction.hidden = next.empty.action === undefined;
    emptyAction.textContent = next.empty.action === 'open' ? 'Open' : 'Build';
  }
  layout();
}

function renderBanner(next: PreviewModel): void {
  banner.replaceChildren();
  banner.hidden = next.ok;
  if (next.ok) {
    return;
  }
  const title = document.createElement('div');
  title.className = 'title';
  title.textContent =
    next.empty === undefined
      ? 'The last build failed; this is the last PDF it produced.'
      : 'The last build failed.';
  banner.append(title);
  for (const finding of next.findings) {
    const row = document.createElement('button');
    row.className = 'finding';
    if (finding.where !== undefined) {
      const where = document.createElement('span');
      where.className = 'where';
      where.textContent = finding.where;
      row.append(where);
    }
    const message = document.createElement('span');
    message.textContent = finding.message;
    row.append(message);
    row.addEventListener('click', () => post({ type: 'reveal', index: finding.index }));
    banner.append(row);
  }
}

/** The document is drawn only when there is one and nothing stands in for it. */
function layout(): void {
  container.hidden = shown === undefined || model?.empty !== undefined;
}

outputs.addEventListener('change', () => post({ type: 'select', id: outputs.value }));
buildButton.addEventListener('click', () => post({ type: 'build' }));
sourceButton.addEventListener('click', () => post({ type: 'openSource' }));
logButton.addEventListener('click', () => post({ type: 'openLog' }));
emptyAction.addEventListener('click', () =>
  post(model?.empty?.action === 'open' ? { type: 'openOutput' } : { type: 'build' }),
);

window.addEventListener('message', (event: MessageEvent<HostMessage>) => {
  const message = event.data;
  if (message.type === 'model') {
    renderModel(message.model);
  } else if (message.type === 'document') {
    // Only the output the model says is selected; a late one is stale.
    if (model === undefined || model.selected === message.id) {
      void showDocument(message.id, message.revision, message.data);
    }
  }
});

post({ type: 'ready' });
