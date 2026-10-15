/**
 * The Stress view's webview client: events and the ticking clock. Nothing else.
 *
 * What a row says is stressViewModel.ts and how it is painted is
 * stressRender.ts, as with the other two views. There is no tree here and so
 * no tree controller: the view is a short list of buttons, and every click is
 * one message to the host naming an action and what it acts on.
 */
import type { ProblemChoice } from '../rbx/problems';
import type { StressViewModel } from '../rbx/stressViewModel';
import { renderSelector } from './render';
import { renderDeclared, renderFindings, renderStatus, statusText } from './stressRender';
import { SelectorHost, setHtml } from './tree';

interface VsCodeApi {
  postMessage(message: unknown): void;
}

declare function acquireVsCodeApi(): VsCodeApi;

const vscode = acquireVsCodeApi();

/** Spelled out rather than imported; see the note on `EMPTY` in testsetMain.ts. */
const EMPTY: StressViewModel = { noPackage: true, dispatch: false, declared: [], findings: [] };

let model: StressViewModel = EMPTY;
let problems: readonly ProblemChoice[] = [];
let selectedProblem: string | undefined;

const selector = new SelectorHost(document.getElementById('selector-host') as HTMLElement);
const declared = document.getElementById('declared') as HTMLElement;
const status = document.getElementById('status') as HTMLElement;
// Not `findings`: style.css hides `#findings` until the Run view's compilation
// panel has something in it, and the views share that stylesheet.
const findings = document.getElementById('stress-findings') as HTMLElement;

function render(): void {
  selector.render(renderSelector(problems, selectedProblem));
  setHtml(declared, renderDeclared(model));
  // The frame only when it changed (`setHtml`), the numbers always: see
  // `renderStatus` for why the two are apart.
  setHtml(status, renderStatus(model));
  tick();
  setHtml(findings, renderFindings(model));
}

/** Write the clock and the counters into the status frame, as text. */
function tick(): void {
  if (model.status === undefined) {
    return;
  }
  const text = statusText(model.status, Date.now());
  const clock = status.querySelector('.stress-elapsed');
  const counts = status.querySelector('.stress-counts');
  if (clock !== null && clock.textContent !== text.elapsed) {
    clock.textContent = text.elapsed;
  }
  if (counts !== null && counts.textContent !== text.counts) {
    counts.textContent = text.counts;
  }
}

/**
 * The clock, client-side: a running session's manifest is rewritten at most
 * once a second and not at all while nothing changes, so a clock driven by
 * the host's posts would stall exactly when a stress is quietly searching.
 * Only text is touched, so a tick never moves focus.
 */
setInterval(() => {
  if (model.status?.startedAtMs !== undefined) {
    tick();
  }
}, 1000);

/**
 * The element a click acts through: the nearest `[data-action]`, or -- for a
 * click on the bare rest of a finding row -- that row's own gesture. Actions
 * are checked first, so Copy, Compare, Promote and the chips never also open
 * the row's input.
 */
function actionTarget(target: HTMLElement): HTMLElement | null {
  const button = target.closest('[data-action]') as HTMLElement | null;
  if (button !== null) {
    return button;
  }
  return target.closest('.stress-finding')?.querySelector('.stress-finding-main') ?? null;
}

document.addEventListener('click', (event) => {
  const button = actionTarget(event.target as HTMLElement);
  const action = button?.dataset.action;
  // A button shown disabled says why in its tooltip; the click is a no-op.
  if (action === undefined || button?.getAttribute('aria-disabled') === 'true') {
    return;
  }
  const k = button?.dataset.k;
  const solution = button?.dataset.solution;
  vscode.postMessage({
    type: action,
    name: button?.dataset.name,
    k: k === undefined ? undefined : Number(k),
    solution: solution === undefined ? undefined : Number(solution),
    // Which session the row belonged to; see `StressViewModel.session`.
    session: model.session,
  });
});

// Enter and Space on the row's `role="button"`, which a real button gets for
// free. Space is kept from scrolling the view, as a button's would be.
document.addEventListener('keydown', (event) => {
  const target = event.target as HTMLElement;
  if (
    target.getAttribute('role') === 'button' &&
    target.tagName !== 'BUTTON' &&
    (event.key === 'Enter' || event.key === ' ')
  ) {
    event.preventDefault();
    target.click();
  }
});

document.addEventListener('change', (event) => {
  const target = event.target as HTMLSelectElement;
  if (target.id === 'problem') {
    vscode.postMessage({ type: 'select', root: target.value });
  }
});

window.addEventListener('message', (event: MessageEvent) => {
  const message = event.data as {
    type?: string;
    model?: StressViewModel;
    problems?: readonly ProblemChoice[];
    selected?: string;
  };
  if (message.type === 'state' && message.model !== undefined) {
    model = message.model;
    problems = message.problems ?? [];
    selectedProblem = message.selected;
    render();
  }
});

render();
vscode.postMessage({ type: 'ready' });
