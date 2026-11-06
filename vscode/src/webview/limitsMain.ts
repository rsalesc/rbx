/**
 * The time-profile editor's client.
 *
 * Draws whatever the host posts, and turns clicks, drags and Enter presses
 * into edit requests. It never decides a check: what it does locally is only
 * *optimistic* -- the limit being dragged or stepped moves at once, while the
 * statuses beside it dim until rbx has answered for the new value.
 *
 * Nothing here is ever disabled. Every click counts against the value already
 * on screen, so five quick clicks on + mean +5 steps; the host keeps only the
 * latest value and sends it when rbx is free.
 */
import type { InspectResult, Row } from '../rbx/limitsInspect';
import { Domain, STRIP_W, ViewState, domainFor, msAtX, renderDocument } from './limitsRender';

declare function acquireVsCodeApi(): { postMessage(message: unknown): void };

const vscode = acquireVsCodeApi();
const root = document.getElementById('root') as HTMLElement;

let state: ViewState = { updating: false };
/** Limits set here that rbx has not answered for yet, by row key. */
const optimistic = new Map<string, number>();
/** Held while a drag is on, so the scale does not move under the cursor. */
let frozenDomain: Domain | undefined;
let dragging: { row: string; svg: SVGSVGElement; moved: boolean } | undefined;
/** The sequence number of the latest edit sent. */
let sentSeq = 0;

function step(): number {
  return state.result?.multipliers?.timeResolution ?? 100;
}

/** rbx's last answer, with every optimistic limit laid over it. */
function displayed(): ViewState {
  const result = state.result;
  if (result === undefined || optimistic.size === 0) return state;
  const rows: Row[] | undefined = result.rows?.map((row) =>
    optimistic.has(row.key) ? { ...row, timeLimit: optimistic.get(row.key) ?? row.timeLimit } : row,
  );
  const patched: InspectResult = {
    ...result,
    rows,
    timeLimit: optimistic.has('base') ? optimistic.get('base') : result.timeLimit,
  };
  return { ...state, result: patched, updating: true };
}

function draw(): void {
  const active = document.activeElement as HTMLElement | null;
  const focusKey = active?.dataset?.action ? `${active.dataset.action}:${active.dataset.row ?? ''}` : undefined;
  const scroll = window.scrollY;
  root.innerHTML = renderDocument(displayed(), { domain: frozenDomain });
  window.scrollTo(0, scroll);
  if (focusKey !== undefined) {
    const [action, row] = focusKey.split(':');
    const selector = row ? `[data-action="${action}"][data-row="${row}"]` : `[data-action="${action}"]`;
    (root.querySelector(selector) as HTMLElement | null)?.focus();
  }
}

window.addEventListener('message', (event: MessageEvent) => {
  const message = event.data as { type: string; state?: ViewState };
  if (message.type !== 'state' || !message.state) return;
  state = message.state;
  // Once rbx has caught up with everything asked of it, its answer is the
  // truth; until then the optimistic values stay on top of it.
  if (!state.updating && (state.seq ?? 0) >= sentSeq && dragging === undefined) optimistic.clear();
  draw();
});

function currentLimit(row: string): number | undefined {
  if (optimistic.has(row)) return optimistic.get(row);
  const found = displayed().result?.rows?.find((r) => r.key === row);
  return found?.timeLimit ?? (row === 'base' ? state.result?.timeLimit ?? undefined : undefined);
}

function setLimit(row: string, ms: number, commit: boolean): void {
  const value = Math.max(step(), Math.round(ms));
  optimistic.set(row, value);
  draw();
  vscode.postMessage({ type: 'edit', edit: { kind: 'set', row, ms: value }, preview: !commit, seq: ++sentSeq });
}

// ------------------------------------------------------------------ clicks

root.addEventListener('click', (event) => {
  const target = (event.target as Element).closest('[data-action]') as HTMLElement | null;
  if (target === null) return;
  const data = target.dataset;
  switch (data.action) {
    case 'open':
      event.preventDefault();
      if (!dragging?.moved) vscode.postMessage({ type: 'open', path: data.path });
      return;
    case 'step': {
      const row = data.row ?? 'base';
      const current = currentLimit(row);
      if (current === undefined) return;
      setLimit(row, current + Number(data.delta), true);
      return;
    }
    case 'revert':
      vscode.postMessage({ type: 'edit', edit: { kind: 'revert', row: data.row } });
      return;
    case 'navProfile':
      vscode.postMessage({ type: 'nav', root: state.nav?.root, profile: data.profile });
      return;
    case 'navStep':
      navStep(Number(data.delta));
      return;
    case 'reestimate':
    case 'openText':
    case 'refresh':
      vscode.postMessage({ type: data.action });
      return;
  }
});

function navStep(delta: number): void {
  const nav = state.nav;
  if (nav === undefined) return;
  const withProfiles = nav.problems.filter((p) => p.profiles.length > 0);
  const index = withProfiles.findIndex((p) => p.root === nav.root);
  if (withProfiles.length < 2) return;
  const next = withProfiles[(index + delta + withProfiles.length) % withProfiles.length];
  vscode.postMessage({ type: 'nav', root: next.root, profile: nav.profile });
}

root.addEventListener('change', (event) => {
  const target = event.target as HTMLInputElement | HTMLSelectElement;
  const action = target.dataset.action;
  if (action === 'inherit') {
    vscode.postMessage({ type: 'edit', edit: { kind: 'inherit', value: (target as HTMLInputElement).checked } });
  } else if (action === 'navProblem') {
    vscode.postMessage({ type: 'nav', root: target.value, profile: state.nav?.profile });
  }
});

window.addEventListener('keydown', (event) => {
  if (event.altKey && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
    event.preventDefault();
    navStep(event.key === 'ArrowLeft' ? -1 : 1);
    return;
  }
  const target = event.target as HTMLInputElement;
  if (event.key === 'Enter' && target.tagName === 'INPUT') commit(target);
});

root.addEventListener(
  'blur',
  (event) => {
    const target = event.target as HTMLInputElement;
    if (target.tagName === 'INPUT' && target.type === 'number') commit(target);
  },
  true,
);

function commit(target: HTMLInputElement): void {
  const value = Number(target.value);
  if (target.value === '' || !Number.isFinite(value) || value <= 0) return;
  if (String(value) === target.defaultValue) return;
  target.defaultValue = String(value);
  if (target.dataset.action === 'set') {
    setLimit(target.dataset.row ?? 'base', value, true);
  } else if (target.dataset.action === 'memory') {
    vscode.postMessage({ type: 'edit', edit: { kind: 'memory', mb: value } });
  }
}

// ------------------------------------------------------------------ dragging

function limitAt(event: PointerEvent, svg: SVGSVGElement, domain: Domain): number {
  const rect = svg.getBoundingClientRect();
  const x = ((event.clientX - rect.left) / rect.width) * STRIP_W;
  const s = step();
  return Math.max(s, Math.round(msAtX(x, domain) / s) * s);
}

root.addEventListener('pointerdown', (event) => {
  const hit = (event.target as Element).closest('[data-action]') as HTMLElement | null;
  // A solution under the pointer is a link, not a drag handle.
  if (hit === null || hit.dataset.action !== 'drag' || event.button !== 0) return;
  const svg = hit as unknown as SVGSVGElement;
  const result = displayed().result;
  if (result?.rows === undefined) return;
  frozenDomain = domainFor(result.rows, result.multipliers?.timeLimitToTle);
  dragging = { row: hit.dataset.row ?? 'base', svg, moved: false };
  document.body.classList.add('dragging');
  event.preventDefault();
  const value = limitAt(event, svg, frozenDomain);
  dragging.moved = true;
  setLimit(dragging.row, value, false);
});

window.addEventListener('pointermove', (event) => {
  if (dragging === undefined || frozenDomain === undefined) return;
  // The svg was replaced by the last redraw: measure the one now on screen.
  const svg = (root.querySelector(`svg[data-action="drag"][data-row="${dragging.row}"]`) as SVGSVGElement | null) ?? dragging.svg;
  const value = limitAt(event, svg, frozenDomain);
  if (value === optimistic.get(dragging.row)) return;
  dragging.moved = true;
  setLimit(dragging.row, value, false);
});

window.addEventListener('pointerup', () => {
  if (dragging === undefined) return;
  const row = dragging.row;
  dragging = undefined;
  frozenDomain = undefined;
  document.body.classList.remove('dragging');
  const value = optimistic.get(row);
  if (value !== undefined) setLimit(row, value, true);
});

draw();
vscode.postMessage({ type: 'ready' });
