/**
 * The stress launcher's form: what it holds, how each control changes it, and
 * the `StressLaunch` it stands for.
 *
 * Pure, and shared by both halves: the client keeps a `LauncherForm` and folds
 * every input into it through `reduce`; the host builds the form's starting
 * launch (`initialLaunch`) and checks whatever launch the client sends back
 * (`launchProblem`, after stressSpec.ts's `parseLaunch`), because a message
 * from a webview is a request, never a fact.
 *
 * The form is not the launch. It keeps what the launch has no room for -- the
 * rows of the two sources not currently selected, so flipping the segmented
 * control back and forth loses nothing, and the text of a number field while
 * it is being typed -- and `launchOf` reads the launch out of it.
 */
import { FINDER_OUTCOMES, FinderRow, Join, defaultOutcomeFor, recognizeFinder } from '../rbx/finder';
import { shellQuote } from '../rbx/shellQuote';
import type { StressDeclaration, StressDeclarations } from '../rbx/stressDeclarations';
import {
  StressLaunch,
  defaultLaunch,
  stressArgv,
  validateLaunch,
} from '../rbx/stressSpec';

export type SourceMode = 'declared' | 'generator' | 'fuzz';

export type TlMode = 'normal' | 'double' | 'custom';

/** Rows and their join: one finder, as the Find section edits it. */
export interface FinderDraft {
  readonly rows: readonly FinderRow[];
  readonly join: Join;
}

/**
 * Whether a declared stress runs with its own finder or with the rows.
 *
 * `keep` runs it by name (`rbx stress NAME`), whatever the rows show -- they
 * are the declared finder read back, or nothing at all when rows cannot say
 * it. `replace` spells it out as `-g CALL -f ROWS`. Only an edit to the rows,
 * or "Replace with rows", moves a form to `replace`; only "Use the declared
 * finder" moves it back.
 */
export type DeclaredFinder = 'keep' | 'replace';

export interface LauncherForm {
  readonly mode: SourceMode;
  readonly declaredName: string;
  readonly declaredFinder: DeclaredFinder;
  readonly expression: string;
  /** Testgroups to fuzz; none checked is every group. */
  readonly fuzzGroups: readonly string[];
  /** One finder per source, so switching sources keeps each one's rows. */
  readonly finders: { readonly [mode in SourceMode]: FinderDraft };
  readonly slowest: boolean;
  /** Numbers as typed, so a half-typed field is not rewritten under the caret. */
  readonly timeout: string;
  readonly findings: string;
  readonly tl: TlMode;
  readonly tlMs: string;
  readonly sanitized: boolean;
  readonly skipInvalid: boolean;
  readonly validate: boolean;
  /** A solution path; `''` leaves the choice to rbx. */
  readonly reference: string;
  readonly advancedOpen: boolean;
}

const NO_ROWS: FinderDraft = { rows: [], join: 'all' };

/** What a bare solution in a finder means: `~ ANY` under `--slowest`, else `~ INCORRECT`. */
export function bareOutcome(slowest: boolean): string {
  return slowest ? 'ANY' : 'INCORRECT';
}

export function findDeclared(
  declarations: StressDeclarations,
  name: string,
): StressDeclaration | undefined {
  return declarations.stresses.find((stress) => stress.name === name);
}

/**
 * The declared stress's own finder, as rows -- or no rows when rows cannot say
 * it, which is what the Find section shows as a read-only chip instead.
 */
export function declaredDraft(declared: StressDeclaration | undefined, slowest: boolean): FinderDraft {
  if (declared === undefined) {
    return NO_ROWS;
  }
  return recognizeFinder(declared.finder, bareOutcome(slowest)) ?? NO_ROWS;
}

/** Whether rows can say the declared stress's finder. */
export function declaredRecognized(declared: StressDeclaration | undefined, slowest: boolean): boolean {
  return declared !== undefined && recognizeFinder(declared.finder, bareOutcome(slowest)) !== undefined;
}

/** The form a launch is shown as. */
export function formOf(launch: StressLaunch, declarations: StressDeclarations): LauncherForm {
  const source = launch.source;
  const declaredName =
    source.kind === 'declared' ? source.name : (declarations.stresses[0]?.name ?? '');
  const declared = findDeclared(declarations, declaredName);
  const ownRows: FinderDraft | undefined =
    launch.finder === undefined ? undefined : { rows: launch.finder.rows, join: launch.finder.join };
  const replaced = source.kind === 'declared' && ownRows !== undefined;
  return {
    mode: source.kind,
    declaredName,
    declaredFinder: replaced ? 'replace' : 'keep',
    expression:
      source.kind === 'generator' ? source.expression : defaultExpression(declarations),
    fuzzGroups: source.kind === 'fuzz' ? [...source.groups] : [],
    finders: {
      declared: replaced ? ownRows : declaredDraft(declared, launch.slowest),
      generator: source.kind === 'generator' ? (ownRows ?? NO_ROWS) : NO_ROWS,
      fuzz: source.kind === 'fuzz' ? (ownRows ?? NO_ROWS) : NO_ROWS,
    },
    slowest: launch.slowest,
    timeout: String(launch.timeout),
    findings: String(launch.findings),
    tl: launch.tl.kind,
    tlMs: launch.tl.kind === 'custom' ? String(launch.tl.ms) : '',
    sanitized: launch.sanitized,
    skipInvalid: launch.skipInvalid,
    validate: launch.validate,
    reference: launch.reference ?? '',
    advancedOpen: launch.sanitized || launch.skipInvalid || !launch.validate || launch.reference !== undefined,
  };
}

/**
 * A blank launcher's generator call: the first declared generator, on a fresh
 * seed each iteration -- a call with no arguments would generate the same input
 * every time, which is no stress at all.
 */
function defaultExpression(declarations: StressDeclarations): string {
  const generator = declarations.generators[0];
  return generator === undefined ? '' : `${generator} @`;
}

/**
 * What the launcher opens on.
 *
 * For a declared stress, the launch the Stress view's Run would run for it
 * (`declaredRun`, which prefers the remembered launch when it last ran this
 * one), so Edit shows exactly what Run does. Blank, the last launch for this
 * package if one was remembered, else a generator call to fill in.
 */
export function initialLaunch(
  declarations: StressDeclarations,
  remembered: StressLaunch | undefined,
): StressLaunch {
  if (remembered !== undefined) {
    return remembered;
  }
  return defaultLaunch({ kind: 'generator', expression: defaultExpression(declarations) });
}

function finderOf(form: LauncherForm): StressLaunch['finder'] {
  const draft = form.finders[form.mode];
  switch (form.mode) {
    case 'declared':
      return form.declaredFinder === 'replace' ? { rows: draft.rows, join: draft.join } : undefined;
    case 'generator':
      return { rows: draft.rows, join: draft.join };
    case 'fuzz':
      // No rows leaves rbx its default of checking the main solution.
      return draft.rows.length === 0 ? undefined : { rows: draft.rows, join: draft.join };
  }
}

/** `Number`, except that an empty field is not 0 by accident of coercion. */
function numberOf(text: string): number {
  return text.trim() === '' ? NaN : Number(text);
}

/** The launch the form stands for. Not necessarily a valid one: see `launchProblem`. */
export function launchOf(form: LauncherForm): StressLaunch {
  const source: StressLaunch['source'] =
    form.mode === 'declared'
      ? { kind: 'declared', name: form.declaredName }
      : form.mode === 'generator'
        ? { kind: 'generator', expression: form.expression }
        : { kind: 'fuzz', groups: [...form.fuzzGroups] };
  const finder = finderOf(form);
  return {
    source,
    ...(finder === undefined ? {} : { finder }),
    slowest: form.slowest,
    timeout: numberOf(form.timeout),
    findings: numberOf(form.findings),
    tl:
      form.tl === 'custom'
        ? { kind: 'custom', ms: numberOf(form.tlMs) }
        : form.tl === 'double'
          ? { kind: 'double' }
          : { kind: 'normal' },
    sanitized: form.sanitized,
    skipInvalid: form.skipInvalid,
    validate: form.validate,
    ...(form.reference === '' ? {} : { reference: form.reference }),
  };
}

/**
 * Why `launch` cannot run against these declarations, or undefined when it can.
 *
 * `validateLaunch`, plus the one thing it leaves to rbx: a declared stress run
 * by name that problem.rbx.yml no longer declares. rbx would refuse it too,
 * but only after a terminal had opened to say so.
 */
export function launchProblem(
  launch: StressLaunch,
  declarations: StressDeclarations,
): string | undefined {
  const declared =
    launch.source.kind === 'declared' ? findDeclared(declarations, launch.source.name) : undefined;
  if (launch.source.kind === 'declared' && launch.source.name.trim() !== '' && declared === undefined) {
    return `The stress ${launch.source.name} is not declared in problem.rbx.yml.`;
  }
  return validateLaunch(launch, declared);
}

/**
 * The `rbx stress ...` line the launcher shows and Copy copies, or undefined
 * when there is no line to show (a replaced finder of a stress that is gone).
 *
 * Display only: the dispatch sends the argv itself, and VS Code quotes each
 * argument the same way (dispatch.ts), so the two read alike.
 */
export function commandLine(
  launch: StressLaunch,
  declarations: StressDeclarations,
): string | undefined {
  const declared =
    launch.source.kind === 'declared' ? findDeclared(declarations, launch.source.name) : undefined;
  try {
    return ['rbx', ...stressArgv(launch, declared).map(shellQuote)].join(' ');
  } catch {
    return undefined;
  }
}

export type LauncherAction =
  | { readonly type: 'mode'; readonly mode: SourceMode }
  | { readonly type: 'declared'; readonly name: string }
  | { readonly type: 'expression'; readonly text: string }
  | { readonly type: 'group'; readonly group: string; readonly on: boolean }
  | { readonly type: 'add-row'; readonly kind: FinderRow['kind'] }
  | { readonly type: 'remove-row'; readonly index: number }
  | {
      readonly type: 'row';
      readonly index: number;
      readonly field: 'solution' | 'outcome' | 'a' | 'b';
      readonly value: string;
    }
  | { readonly type: 'join'; readonly join: Join }
  | { readonly type: 'replace-finder' }
  | { readonly type: 'keep-finder' }
  | { readonly type: 'slowest'; readonly on: boolean }
  | { readonly type: 'declarations' }
  | {
      readonly type: 'field';
      readonly field: 'timeout' | 'findings' | 'tlMs' | 'reference';
      readonly value: string;
    }
  | { readonly type: 'tl'; readonly tl: TlMode }
  | {
      readonly type: 'flag';
      readonly field: 'sanitized' | 'skipInvalid' | 'validate' | 'advancedOpen';
      readonly on: boolean;
    };

/** The outcome a Break row on `solution` starts with. */
export function rowOutcomeFor(
  solution: string,
  declarations: StressDeclarations,
  slowest: boolean,
): string {
  // Under --slowest a Break row means "time this solution", whatever it gets.
  if (slowest) {
    return 'ANY';
  }
  return defaultOutcomeFor(declarations.solutions.find((s) => s.path === solution)?.outcome);
}

/**
 * Edit the rows of the current source. In a declared stress, any edit to them
 * is a replacement of its finder: from then on the rows are what runs.
 */
function editRows(form: LauncherForm, edit: (draft: FinderDraft) => FinderDraft): LauncherForm {
  const draft = edit(form.finders[form.mode]);
  return {
    ...form,
    finders: { ...form.finders, [form.mode]: draft },
    ...(form.mode === 'declared' ? { declaredFinder: 'replace' as const } : {}),
  };
}

function editRow(
  row: FinderRow,
  field: 'solution' | 'outcome' | 'a' | 'b',
  value: string,
  declarations: StressDeclarations,
  slowest: boolean,
): FinderRow {
  if (row.kind === 'break') {
    if (field === 'solution') {
      return { ...row, solution: value, outcome: rowOutcomeFor(value, declarations, slowest) };
    }
    if (field === 'outcome') {
      return FINDER_OUTCOMES.includes(value) ? { ...row, outcome: value } : row;
    }
    return row;
  }
  if (field === 'a' || field === 'b') {
    return { ...row, [field]: value };
  }
  return row;
}

/** Re-read the declared finder, for a form that keeps it. */
function reloadDeclared(form: LauncherForm, declarations: StressDeclarations): LauncherForm {
  if (form.declaredFinder !== 'keep') {
    return form;
  }
  const declared = findDeclared(declarations, form.declaredName);
  return {
    ...form,
    finders: { ...form.finders, declared: declaredDraft(declared, form.slowest) },
  };
}

/** The form after one control changed. */
export function reduce(
  form: LauncherForm,
  action: LauncherAction,
  declarations: StressDeclarations,
): LauncherForm {
  switch (action.type) {
    case 'mode':
      return { ...form, mode: action.mode };
    case 'declared':
      // Another stress: its own finder, kept, whatever was done to the last one's.
      return reloadDeclared({ ...form, declaredName: action.name, declaredFinder: 'keep' }, declarations);
    case 'expression':
      return { ...form, expression: action.text };
    case 'group': {
      const checked = new Set(form.fuzzGroups);
      if (action.on) {
        checked.add(action.group);
      } else {
        checked.delete(action.group);
      }
      // In declaration order, which is the order the argv lists them in. A
      // checked group the manifest no longer declares stays checked until
      // unchecked, rather than leaving the command behind the user's back.
      const declared = declarations.groups.filter((group) => checked.has(group));
      const stale = [...checked].filter((group) => !declarations.groups.includes(group));
      return { ...form, fuzzGroups: [...declared, ...stale] };
    }
    case 'add-row':
      return editRows(form, (draft) => ({
        ...draft,
        rows: [
          ...draft.rows,
          action.kind === 'break'
            ? { kind: 'break', solution: '', outcome: bareOutcome(form.slowest) }
            : { kind: 'disagree', a: '', b: '' },
        ],
      }));
    case 'remove-row':
      return editRows(form, (draft) => ({
        ...draft,
        rows: draft.rows.filter((_, index) => index !== action.index),
      }));
    case 'row':
      return editRows(form, (draft) => ({
        ...draft,
        rows: draft.rows.map((row, index) =>
          index === action.index
            ? editRow(row, action.field, action.value, declarations, form.slowest)
            : row,
        ),
      }));
    case 'join':
      return editRows(form, (draft) => ({ ...draft, join: action.join }));
    case 'replace-finder':
      // From the rows on screen: the declared finder read back when rows could
      // say it, nothing when they could not.
      return { ...form, declaredFinder: 'replace' };
    case 'keep-finder':
      return reloadDeclared({ ...form, declaredFinder: 'keep' }, declarations);
    case 'slowest':
      // A kept finder means something else under --slowest (a bare solution is
      // `~ ANY` there), so the rows that show it are read again.
      return reloadDeclared({ ...form, slowest: action.on }, declarations);
    case 'declarations':
      return reloadDeclared(form, declarations);
    case 'field':
      return { ...form, [action.field]: action.value };
    case 'tl':
      return { ...form, tl: action.tl };
    case 'flag':
      return { ...form, [action.field]: action.on };
  }
}
