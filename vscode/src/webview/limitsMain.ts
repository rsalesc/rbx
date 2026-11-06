/**
 * The time-profile editor's client. Draws whatever state the host posts and
 * turns clicks and Enter presses into edit requests; it never edits anything
 * itself, so the host (and through it, rbx) stays the only writer.
 */
import { ViewState, renderDocument } from './limitsRender';

declare function acquireVsCodeApi(): { postMessage(message: unknown): void };

const vscode = acquireVsCodeApi();
const root = document.getElementById('root') as HTMLElement;

let state: ViewState = { busy: false };

function draw(): void {
  // Keep the focused input and its caret across a redraw: an edit's answer
  // arrives while the setter may still be on the field they typed in.
  const active = document.activeElement as HTMLElement | null;
  const focusKey = active?.dataset?.action ? `${active.dataset.action}:${active.dataset.row ?? ''}` : undefined;
  const scroll = window.scrollY;
  root.innerHTML = renderDocument(state);
  window.scrollTo(0, scroll);
  if (focusKey !== undefined) {
    const [action, row] = focusKey.split(':');
    const selector = row ? `[data-action="${action}"][data-row="${row}"]` : `[data-action="${action}"]`;
    (root.querySelector(selector) as HTMLElement | null)?.focus();
  }
}

window.addEventListener('message', (event: MessageEvent) => {
  const message = event.data as { type: string; state?: ViewState };
  if (message.type === 'state' && message.state) {
    state = message.state;
    draw();
  }
});

function currentLimit(row: string): number | undefined {
  const input = root.querySelector(`input[data-action="set"][data-row="${row}"]`) as HTMLInputElement | null;
  const value = input ? Number(input.value) : NaN;
  return Number.isFinite(value) && value > 0 ? value : undefined;
}

root.addEventListener('click', (event) => {
  const target = (event.target as Element).closest('[data-action]') as HTMLElement | SVGElement | null;
  if (target === null) return;
  const data = (target as HTMLElement).dataset;
  switch (data.action) {
    case 'open':
      event.preventDefault();
      vscode.postMessage({ type: 'open', path: data.path });
      return;
    case 'step': {
      const row = data.row ?? 'base';
      const current = currentLimit(row);
      if (current === undefined) return;
      vscode.postMessage({ type: 'edit', edit: { kind: 'set', row, ms: Math.max(1, current + Number(data.delta)) } });
      return;
    }
    case 'revert':
      vscode.postMessage({ type: 'edit', edit: { kind: 'revert', row: data.row } });
      return;
    case 'reestimate':
    case 'openText':
    case 'refresh':
      vscode.postMessage({ type: data.action });
      return;
  }
});

root.addEventListener('change', (event) => {
  const target = event.target as HTMLInputElement;
  const action = target.dataset.action;
  if (action === 'inherit') {
    vscode.postMessage({ type: 'edit', edit: { kind: 'inherit', value: target.checked } });
  }
});

root.addEventListener('keydown', (event) => {
  const target = event.target as HTMLInputElement;
  if (event.key !== 'Enter' || target.tagName !== 'INPUT') return;
  commit(target);
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
    vscode.postMessage({ type: 'edit', edit: { kind: 'set', row: target.dataset.row ?? 'base', ms: value } });
  } else if (target.dataset.action === 'memory') {
    vscode.postMessage({ type: 'edit', edit: { kind: 'memory', mb: value } });
  }
}

draw();
vscode.postMessage({ type: 'ready' });
