/**
 * The stress launcher's webview client: folds each control into the form and
 * keeps the footer's command in step. Nothing else.
 *
 * What the form holds and how a control changes it is launcherState.ts; how it
 * is painted is launcherRender.ts. The host owns everything with a side
 * effect: Run and Copy post the launch, and the host re-checks it before doing
 * anything with it.
 *
 * The form survives the tab being hidden through `setState`, not
 * `retainContextWhenHidden`. Each open of the launcher carries a target id;
 * a state post with the id the form was made for is the same launcher coming
 * back (keep the form, refresh the declarations), and any other id is a new
 * open (start from the launch the host sent).
 */
import type { StressDeclarations } from '../rbx/stressDeclarations';
import type { StressLaunch } from '../rbx/stressSpec';
import { INSERT_CHIPS, footerState, renderForm, runBlocker } from './launcherRender';
import { LauncherAction, LauncherForm, formOf, launchOf, reduce } from './launcherState';
import { setHtml } from './tree';

interface Persisted {
  readonly target?: string;
  readonly form?: LauncherForm;
  readonly vars?: readonly string[];
}

interface VsCodeApi {
  postMessage(message: unknown): void;
  getState(): Persisted | undefined;
  setState(state: Persisted): void;
}

declare function acquireVsCodeApi(): VsCodeApi;

const vscode = acquireVsCodeApi();

/** What the host posts. See stressLauncher.ts for the other side. */
type HostMessage =
  | {
      readonly type: 'state';
      readonly target: { readonly id: string; readonly launch: StressLaunch };
      readonly title: string;
      readonly rootLabel: string;
      readonly declarations: StressDeclarations;
      readonly dispatch: boolean;
    }
  | { readonly type: 'vars'; readonly names: readonly string[] };

const NO_DECLARATIONS: StressDeclarations = { stresses: [], generators: [], solutions: [], groups: [] };

const persisted = vscode.getState() ?? {};
let target = persisted.target;
let form: LauncherForm | undefined = persisted.form;
let vars: readonly string[] = persisted.vars ?? [];
let declarations: StressDeclarations = NO_DECLARATIONS;
let dispatch = false;
/** Whether the host has posted the declarations yet; until then there is nothing true to draw. */
let received = false;

const formHost = document.getElementById('form') as HTMLElement;
const title = document.getElementById('title') as HTMLElement;
const rootLabel = document.getElementById('root') as HTMLElement;
const preview = document.getElementById('preview') as HTMLElement;
const problem = document.getElementById('problem') as HTMLElement;
const runButton = document.getElementById('run') as HTMLButtonElement;
const copyButton = document.getElementById('copy') as HTMLButtonElement;

function persist(): void {
  vscode.setState({ target, form, vars });
}

function updateFooter(): void {
  if (form === undefined) {
    preview.textContent = '';
    if (problem.textContent !== '') {
      problem.textContent = '';
    }
    runButton.disabled = true;
    copyButton.disabled = true;
    return;
  }
  const footer = footerState(form, declarations);
  const blocker = runBlocker(footer, dispatch);
  preview.textContent = footer.command ?? '';
  // Written only when it changes: the line is a live region, and rewriting it
  // with the same words would have a screen reader repeat them per keystroke.
  if (problem.textContent !== (blocker ?? '')) {
    problem.textContent = blocker ?? '';
  }
  runButton.disabled = blocker !== undefined;
  // Copy is the terminal's Run: no line rbx would refuse.
  copyButton.disabled = footer.command === undefined || footer.problem !== undefined;
}

/**
 * Redraw the form, putting focus -- and the caret, in a text field -- back on
 * the control that had it. Every control has a stable id for exactly this.
 */
function renderAll(focusId?: string): void {
  if (!received) {
    return;
  }
  if (form !== undefined) {
    const active = document.activeElement as HTMLElement | null;
    const activeId = focusId ?? (formHost.contains(active) ? active?.id : undefined);
    // Every text field, the numeric ones included (they are `type="text"` for this).
    const text = active instanceof HTMLInputElement && active.type === 'text' ? active : undefined;
    const selection = text === undefined ? undefined : [text.selectionStart, text.selectionEnd];
    if (setHtml(formHost, renderForm({ form, declarations, vars })) && activeId) {
      const next = document.getElementById(activeId);
      next?.focus();
      if (next instanceof HTMLInputElement && selection !== undefined && focusId === undefined) {
        next.setSelectionRange(selection[0], selection[1]);
      }
    }
  }
  updateFooter();
}

/** Fold one change in; `redraw` false for typing, which only moves the footer. */
function apply(action: LauncherAction, redraw = true, focusId?: string): void {
  if (form === undefined) {
    return;
  }
  form = reduce(form, action, declarations);
  persist();
  if (redraw) {
    renderAll(focusId);
  } else {
    updateFooter();
  }
}

/** Type `text` at the caret of the generator call, leaving `select` of it selected. */
function insertIntoExpression(text: string, select: readonly [number, number]): void {
  const input = document.getElementById('expression') as HTMLInputElement | null;
  if (input === null) {
    return;
  }
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? start;
  // A token glued to the end of the one before it (`gen@`) is another token
  // altogether; inside one (`[1..`, `(a|`) it is exactly what was meant.
  const pad = start > 0 && /[A-Za-z0-9_\])>@]/.test(input.value[start - 1]) ? ' ' : '';
  input.value = input.value.slice(0, start) + pad + text + input.value.slice(end);
  const at = start + pad.length;
  input.focus();
  input.setSelectionRange(at + select[0], at + select[1]);
  apply({ type: 'expression', text: input.value }, false);
}

function onChange(target: HTMLElement): void {
  const bind = target.dataset.bind;
  const input = target as HTMLInputElement;
  const value = input.value;
  switch (bind) {
    case 'mode':
      if (value === 'declared' || value === 'generator' || value === 'fuzz') {
        apply({ type: 'mode', mode: value });
      }
      return;
    case 'declared':
      apply({ type: 'declared', name: value });
      return;
    case 'group':
      apply({ type: 'group', group: value, on: input.checked });
      return;
    case 'join':
      if (value === 'all' || value === 'any') {
        apply({ type: 'join', join: value });
      }
      return;
    case 'tl':
      if (value === 'normal' || value === 'double' || value === 'custom') {
        apply({ type: 'tl', tl: value });
      }
      return;
    case 'row': {
      const field = target.dataset.field;
      if (field === 'solution' || field === 'outcome' || field === 'a' || field === 'b') {
        apply({ type: 'row', index: Number(target.dataset.index), field, value });
      }
      return;
    }
    case 'slowest':
      apply({ type: 'slowest', on: input.checked });
      return;
    case 'sanitized':
    case 'skipInvalid':
    case 'validate':
      apply({ type: 'flag', field: bind, on: input.checked });
      return;
    case 'reference':
      apply({ type: 'field', field: 'reference', value });
      return;
    case 'insert-var':
      if (value !== '') {
        const reference = `<${value}>`;
        insertIntoExpression(reference, [reference.length, reference.length]);
        // Back to its prompt: it is a menu of things to type, not a setting.
        input.value = '';
      }
      return;
  }
}

document.addEventListener('change', (event) => {
  const target = event.target as HTMLElement;
  if (target.dataset.bind !== undefined) {
    onChange(target);
  }
});

document.addEventListener('input', (event) => {
  const target = event.target as HTMLInputElement;
  switch (target.dataset.bind) {
    case 'expression':
      apply({ type: 'expression', text: target.value }, false);
      return;
    case 'timeout':
    case 'findings':
    case 'tlMs':
      apply({ type: 'field', field: target.dataset.bind, value: target.value }, false);
      return;
  }
});

// `toggle` does not bubble, so it is caught on the way down.
document.addEventListener(
  'toggle',
  (event) => {
    const target = event.target as HTMLDetailsElement;
    if (target.id === 'advanced' && form !== undefined && form.advancedOpen !== target.open) {
      form = { ...form, advancedOpen: target.open };
      persist();
    }
  },
  true,
);

document.addEventListener('click', (event) => {
  const button = (event.target as HTMLElement).closest('[data-act]') as HTMLElement | null;
  if (button === null || form === undefined) {
    return;
  }
  switch (button.dataset.act) {
    case 'insert': {
      const chip = INSERT_CHIPS[Number(button.dataset.chip)];
      if (chip !== undefined) {
        insertIntoExpression(chip.text, chip.select);
      }
      return;
    }
    case 'add-row': {
      const kind = button.dataset.kind === 'disagree' ? 'disagree' : 'break';
      const index = form.finders[form.mode].rows.length;
      apply({ type: 'add-row', kind }, true, `row-${index}-${kind === 'break' ? 'solution' : 'a'}`);
      return;
    }
    case 'remove-row': {
      const index = Number(button.dataset.index);
      const left = form.finders[form.mode].rows.length - 1;
      // Focus stays in the list: on the row that took this one's place, else
      // the one before, else the button that adds one back.
      const next = left === 0 ? 'add-break' : `row-${Math.min(index, left - 1)}-remove`;
      apply({ type: 'remove-row', index }, true, next);
      return;
    }
    case 'replace-finder':
      apply({ type: 'replace-finder' }, true, 'add-break');
      return;
    case 'keep-finder':
      apply({ type: 'keep-finder' }, true, 'add-break');
      return;
    case 'run':
      vscode.postMessage({ type: 'run', target, launch: launchOf(form) });
      return;
    case 'copy':
      vscode.postMessage({ type: 'copy', target, launch: launchOf(form) });
      return;
  }
});

window.addEventListener('message', (event: MessageEvent) => {
  const message = event.data as HostMessage;
  if (message.type === 'state') {
    received = true;
    declarations = message.declarations;
    dispatch = message.dispatch;
    title.textContent = message.title;
    rootLabel.textContent = message.rootLabel;
    if (form === undefined || target !== message.target.id) {
      target = message.target.id;
      form = formOf(message.target.launch, declarations);
    } else {
      // problem.rbx.yml changed under an open form: a kept declared finder is
      // read again, everything the user typed stays.
      form = reduce(form, { type: 'declarations' }, declarations);
    }
    persist();
    renderAll();
  } else if (message.type === 'vars') {
    vars = message.names;
    persist();
    renderAll();
  }
});

renderAll();
vscode.postMessage({ type: 'ready' });
