/**
 * The stress launcher's markup, as pure functions of its form.
 *
 * Two parts kept apart: the form and the footer. The footer -- the live
 * command and why it cannot run -- follows every keystroke; the form is
 * redrawn only when a control changes its shape (a row added, a source
 * switched), so typing in a field never has the field replaced under it.
 *
 * Every value here can come from problem.rbx.yml -- stress, generator,
 * solution and group names, the declared finder -- and all of it goes through
 * `escapeHtml` / `escapeAttr`, as in the other renderers. Every control has an
 * id, which is how launcherMain.ts puts focus back after a redraw, and either
 * `data-bind` (an input, read on change) or `data-act` (a button, read on
 * click), which is everything it reads.
 */
import { FINDER_OUTCOMES, FinderRow } from '../rbx/finder';
import type { StressDeclarations } from '../rbx/stressDeclarations';
import { generatorCallString } from '../rbx/stressSpec';
import {
  LauncherForm,
  SourceMode,
  commandLine,
  declaredRecognized,
  findDeclared,
  launchOf,
  launchProblem,
} from './launcherState';
import { escapeAttr, escapeHtml } from './render';

export interface LauncherView {
  readonly form: LauncherForm;
  readonly declarations: StressDeclarations;
  /** Package variable names, for the generator call's `<var>`; may be empty. */
  readonly vars: readonly string[];
}

/** An insert chip: what it types, and which part of that it leaves selected. */
export interface InsertChip {
  readonly label: string;
  readonly text: string;
  /** Offsets into `text` of the selection left behind, so typing replaces it. */
  readonly select: readonly [number, number];
  readonly title: string;
}

export const INSERT_CHIPS: readonly InsertChip[] = [
  { label: '@', text: '@', select: [1, 1], title: 'Insert @: a fresh random seed each iteration' },
  {
    label: '[1..10]',
    text: '[1..10]',
    select: [1, 6],
    title: 'Insert a range: a random integer between the two bounds',
  },
  { label: '(a|b)', text: '(a|b)', select: [1, 4], title: 'Insert a choice: one of the options' },
  { label: '<var>', text: '<>', select: [1, 1], title: 'Insert a package variable reference' },
];

function codicon(name: string): string {
  return `<span class="codicon codicon-${name}" aria-hidden="true"></span>`;
}

function option(value: string, label: string, selected: boolean): string {
  return `<option value="${escapeAttr(value)}"${selected ? ' selected' : ''}>${escapeHtml(label)}</option>`;
}

function checked(on: boolean): string {
  return on ? ' checked' : '';
}

function radio(name: string, value: string, label: string, on: boolean, bind: string): string {
  const id = `${name}-${value}`;
  return (
    `<label class="segment" for="${id}"><input type="radio" id="${id}" name="${name}" ` +
    `value="${escapeAttr(value)}" data-bind="${bind}"${checked(on)}><span>${escapeHtml(label)}</span></label>`
  );
}

function checkbox(id: string, bind: string, label: string, on: boolean, extra = ''): string {
  return (
    `<label class="check" for="${id}"><input type="checkbox" id="${id}" data-bind="${bind}"${extra}` +
    `${checked(on)}><span>${escapeHtml(label)}</span></label>`
  );
}

/**
 * The solutions a row may pick: the declared ones, plus the one it already
 * names if that is not among them (a remembered launch, a declared finder
 * naming an undeclared file), so a redraw never silently changes a row.
 */
function solutionOptions(
  declarations: StressDeclarations,
  current: string,
  placeholder: string,
): string {
  const paths = declarations.solutions.map((solution) => solution.path);
  if (current !== '' && !paths.includes(current)) {
    paths.push(current);
  }
  return (
    option('', placeholder, current === '') +
    paths.map((path) => option(path, path, path === current)).join('')
  );
}

function solutionSelect(
  id: string,
  index: number,
  field: 'solution' | 'a' | 'b',
  label: string,
  current: string,
  declarations: StressDeclarations,
): string {
  return (
    `<select id="${id}" class="row-solution" data-bind="row" data-index="${index}" data-field="${field}" ` +
    `aria-label="${escapeAttr(label)}">${solutionOptions(declarations, current, 'Choose a solution…')}</select>`
  );
}

function renderRow(row: FinderRow, index: number, declarations: StressDeclarations): string {
  const n = index + 1;
  let body: string;
  if (row.kind === 'break') {
    const outcomes = FINDER_OUTCOMES.map((outcome) => option(outcome, outcome, outcome === row.outcome)).join('');
    body =
      `<span class="row-kind">Break</span>` +
      solutionSelect(`row-${index}-solution`, index, 'solution', `Row ${n}: solution`, row.solution, declarations) +
      `<span class="row-op" aria-hidden="true">~</span>` +
      `<select id="row-${index}-outcome" data-bind="row" data-index="${index}" data-field="outcome" ` +
      `aria-label="Row ${n}: outcome">${outcomes}</select>`;
  } else {
    body =
      `<span class="row-kind">Disagree</span>` +
      solutionSelect(`row-${index}-a`, index, 'a', `Row ${n}: first solution`, row.a, declarations) +
      `<span class="row-op" aria-hidden="true">≠</span>` +
      solutionSelect(`row-${index}-b`, index, 'b', `Row ${n}: second solution`, row.b, declarations);
  }
  return (
    `<li class="finder-row">${body}` +
    `<button type="button" id="row-${index}-remove" class="icon-button" data-act="remove-row" data-index="${index}" ` +
    `title="Remove row ${n}" aria-label="Remove row ${n}">${codicon('close')}</button></li>`
  );
}

function renderDeclaredSource(view: LauncherView): string {
  const { form, declarations } = view;
  if (declarations.stresses.length === 0) {
    return '<p class="hint">problem.rbx.yml declares no stresses.</p>';
  }
  const names = declarations.stresses.map((stress) => stress.name);
  if (form.declaredName !== '' && !names.includes(form.declaredName)) {
    names.push(form.declaredName);
  }
  const declared = findDeclared(declarations, form.declaredName);
  const summary =
    declared === undefined
      ? '<p class="hint warn">Not declared in problem.rbx.yml.</p>'
      : `<p class="hint declared-summary"><code>${escapeHtml(generatorCallString(declared.generator))}</code>` +
        ` <span aria-hidden="true">·</span> <span class="sr-only">finding</span> ` +
        `<code>${escapeHtml(declared.finder)}</code></p>`;
  return (
    '<div class="field"><label for="declared-name">Stress</label>' +
    `<select id="declared-name" data-bind="declared">` +
    (form.declaredName === '' ? option('', 'Choose a stress…', true) : '') +
    names.map((name) => option(name, name, name === form.declaredName)).join('') +
    `</select></div>${summary}`
  );
}

function renderGeneratorSource(view: LauncherView): string {
  const { form, declarations, vars } = view;
  const datalist = declarations.generators.map((name) => option(name, name, false)).join('');
  const chips = INSERT_CHIPS.map(
    (chip, index) =>
      `<button type="button" id="chip-${index}" class="chip" data-act="insert" data-chip="${index}" ` +
      `title="${escapeAttr(chip.title)}" aria-label="${escapeAttr(chip.title)}">${escapeHtml(chip.label)}</button>`,
  ).join('');
  const varSelect =
    vars.length === 0
      ? ''
      : `<select id="insert-var" class="chip-select" data-bind="insert-var" aria-label="Insert a package variable">` +
        option('', 'Variable…', true) +
        vars.map((name) => option(name, name, false)).join('') +
        '</select>';
  return (
    '<div class="field"><label for="expression">Generator call</label>' +
    `<input type="text" id="expression" class="mono" data-bind="expression" list="generator-names" ` +
    `spellcheck="false" autocomplete="off" placeholder="gens/gen.cpp [1..1000]" ` +
    `aria-describedby="expression-hint" value="${escapeAttr(form.expression)}">` +
    `<datalist id="generator-names">${datalist}</datalist></div>` +
    `<div class="chips" role="group" aria-label="Insert into the generator call">${chips}${varSelect}</div>` +
    '<p class="hint" id="expression-hint"><code>@</code> a fresh seed · <code>[a..b]</code> a random ' +
    'integer in the range · <code>(a|b)</code> one of the options · <code>&lt;var&gt;</code> a package variable</p>'
  );
}

function renderFuzzSource(view: LauncherView): string {
  const { form, declarations } = view;
  const groups = [...declarations.groups];
  for (const group of form.fuzzGroups) {
    if (!groups.includes(group)) {
      groups.push(group);
    }
  }
  if (groups.length === 0) {
    return '<p class="hint">problem.rbx.yml declares no testgroups to fuzz.</p>';
  }
  const boxes = groups
    .map((group, index) =>
      checkbox(
        `group-${index}`,
        'group',
        group,
        form.fuzzGroups.includes(group),
        ` value="${escapeAttr(group)}"`,
      ),
    )
    .join('');
  return (
    '<fieldset class="groups"><legend>Testgroups to fuzz</legend>' +
    `${boxes}</fieldset><p class="hint">None checked fuzzes every group.</p>`
  );
}

const MODE_LABELS: Readonly<Record<SourceMode, string>> = {
  declared: 'Declared',
  generator: 'Generator',
  fuzz: 'Fuzz',
};

function renderInputs(view: LauncherView): string {
  const { form } = view;
  const modes = (Object.keys(MODE_LABELS) as SourceMode[])
    .map((mode) => radio('mode', mode, MODE_LABELS[mode], form.mode === mode, 'mode'))
    .join('');
  const body =
    form.mode === 'declared'
      ? renderDeclaredSource(view)
      : form.mode === 'generator'
        ? renderGeneratorSource(view)
        : renderFuzzSource(view);
  return (
    '<section class="section" aria-labelledby="inputs-heading">' +
    '<h2 id="inputs-heading"><span class="step" aria-hidden="true">1</span>Inputs</h2>' +
    `<div class="segmented" role="radiogroup" aria-label="Where the inputs come from">${modes}</div>` +
    `<div class="source">${body}</div></section>`
  );
}

/** A line under the rows saying what they are, for a declared stress or a fuzz. */
function findNote(view: LauncherView): string {
  const { form } = view;
  if (form.mode === 'declared' && form.declaredName !== '') {
    if (form.declaredFinder === 'keep') {
      return '<p class="hint">The stress\'s own finder. Editing a row replaces it for this run.</p>';
    }
    return (
      '<p class="hint">These rows replace the stress\'s finder for this run, so it runs as its ' +
      'generator call with them. <button type="button" id="keep-finder" class="link-button" ' +
      'data-act="keep-finder">Use the declared finder</button></p>'
    );
  }
  if (form.mode === 'fuzz' && form.finders.fuzz.rows.length === 0) {
    return '<p class="hint">No rows: rbx checks the main solution.</p>';
  }
  return '';
}

function renderFind(view: LauncherView): string {
  const { form, declarations } = view;
  const declared = findDeclared(declarations, form.declaredName);
  const opaque =
    form.mode === 'declared' &&
    form.declaredFinder === 'keep' &&
    declared !== undefined &&
    !declaredRecognized(declared, form.slowest);
  let body: string;
  if (opaque) {
    // Rows cannot say this finder, and rows that meant something else would be
    // worse than none: it is shown as written, and runs as written.
    body =
      '<div class="finder-chip"><span class="finder-chip-label">Custom finder from problem.rbx.yml</span>' +
      `<code>${escapeHtml(declared.finder)}</code>` +
      '<button type="button" id="replace-finder" data-act="replace-finder">Replace with rows</button></div>';
  } else {
    const draft = form.finders[form.mode];
    const join =
      '<div class="segmented small" role="radiogroup" aria-label="How the rows combine">' +
      radio('join', 'all', 'All of', draft.join === 'all', 'join') +
      radio('join', 'any', 'Any of', draft.join === 'any', 'join') +
      '</div>';
    const rows =
      draft.rows.length === 0
        ? ''
        : `<ol class="finder-rows" aria-label="Finder rows">${draft.rows
            .map((row, index) => renderRow(row, index, declarations))
            .join('')}</ol>`;
    body =
      `${join}${rows}<div class="row-buttons">` +
      `<button type="button" id="add-break" class="secondary" data-act="add-row" data-kind="break">${codicon('add')}Break</button>` +
      `<button type="button" id="add-disagree" class="secondary" data-act="add-row" data-kind="disagree">${codicon('add')}Disagree</button>` +
      `</div>${findNote(view)}`;
  }
  const slowestHint = form.slowest
    ? '<p class="hint">Keeps the slowest tests rather than failures: a Break row names a solution ' +
      'to time, and its outcome which of its runs count.</p>'
    : '';
  return (
    '<section class="section" aria-labelledby="find-heading">' +
    '<h2 id="find-heading"><span class="step" aria-hidden="true">2</span>Find</h2>' +
    body +
    checkbox('slowest', 'slowest', 'Slowest tests', form.slowest) +
    slowestHint +
    '</section>'
  );
}

function numberField(id: string, bind: string, label: string, value: string, unit: string): string {
  return (
    `<div class="field inline"><label for="${id}">${escapeHtml(label)}</label>` +
    // Text with a numeric keyboard rather than `type="number"`, which has no
    // caret to put back after a redraw and turns a half-typed value into ''.
    `<input type="text" inputmode="numeric" id="${id}" class="num" data-bind="${bind}" value="${escapeAttr(value)}">` +
    `<span class="unit">${escapeHtml(unit)}</span></div>`
  );
}

function renderBudget(view: LauncherView): string {
  const { form, declarations } = view;
  const tl =
    '<div class="field inline"><span id="tl-label" class="label">Time limit</span>' +
    '<div class="segmented small" role="radiogroup" aria-labelledby="tl-label">' +
    radio('tl', 'normal', 'Normal', form.tl === 'normal', 'tl') +
    radio('tl', 'double', '2× TL', form.tl === 'double', 'tl') +
    radio('tl', 'custom', 'Custom', form.tl === 'custom', 'tl') +
    '</div>' +
    (form.tl === 'custom'
      ? `<input type="text" inputmode="numeric" id="tl-ms" class="num" data-bind="tlMs" aria-label="Time limit in milliseconds" value="${escapeAttr(form.tlMs)}"><span class="unit">ms</span>`
      : '') +
    '</div>';
  const reference =
    '<div class="field inline"><label for="reference">Reference solution</label>' +
    `<select id="reference" data-bind="reference">${solutionOptions(
      declarations,
      form.reference,
      "rbx's choice",
    )}</select></div>`;
  return (
    '<section class="section" aria-labelledby="budget-heading">' +
    '<h2 id="budget-heading"><span class="step" aria-hidden="true">3</span>Budget</h2>' +
    numberField('timeout', 'timeout', 'Time budget', form.timeout, 's') +
    numberField('findings', 'findings', 'Stop after', form.findings, 'findings') +
    tl +
    `<details id="advanced"${form.advancedOpen ? ' open' : ''}>` +
    '<summary id="advanced-summary">Advanced</summary>' +
    checkbox('sanitized', 'sanitized', 'Sanitized', form.sanitized) +
    checkbox('skip-invalid', 'skipInvalid', 'Skip invalid inputs', form.skipInvalid) +
    checkbox('validate', 'validate', 'Validate inputs', form.validate) +
    reference +
    '</details></section>'
  );
}

/** The form: the three sections. */
export function renderForm(view: LauncherView): string {
  return renderInputs(view) + renderFind(view) + renderBudget(view);
}

/** What the footer shows: the line, and why it cannot run. */
export interface FooterState {
  readonly command?: string;
  readonly problem?: string;
}

export function footerState(form: LauncherForm, declarations: StressDeclarations): FooterState {
  const launch = launchOf(form);
  return {
    command: commandLine(launch, declarations),
    problem: launchProblem(launch, declarations),
  };
}

/**
 * Why Run is off, or undefined when it is on. The footer is a static shell
 * that launcherMain.ts fills by `textContent`, so its status line stays one
 * live region a screen reader follows, rather than one replaced per keystroke.
 */
export function runBlocker(footer: FooterState, dispatch: boolean): string | undefined {
  if (footer.problem !== undefined) {
    return footer.problem;
  }
  return dispatch ? undefined : 'Dispatching rbx commands is turned off (rbx.dispatch.enabled).';
}
