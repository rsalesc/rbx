/**
 * Promoting a test into the testset: everything about it decidable without
 * `vscode`. The host half is promoter.ts.
 *
 * What a promotion does is decided by `rbx testcases promote`, never here
 * (design: docs/plans/2026-10-15-promotion-sinks-design.md). This module only
 * builds its argv, reads what its `--json` modes print -- the sinks a test
 * can go into, and the plan of file changes a promotion makes -- and checks
 * what the user types before rbx does, so a typo is caught in the input box.
 */

import { shellQuote } from './shellQuote';

/** The subcommand, after the executable. */
export const PROMOTE = ['testcases', 'promote'] as const;

/** How a test lands in a generator script: its call, or a `@copy` of its input. */
export type Form = 'recipe' | 'copy';

/** A place a test can be promoted into, as `--list-sinks --json` says. */
export interface Sink {
  /** The group, or `group/subgroup`. */
  readonly name: string;
  /** `glob`: a folder of `.in` files; `plan`: a `.txt` generator script. */
  readonly kind: 'glob' | 'plan';
  /** The glob, or the script relative to the package. */
  readonly path: string;
  /** The `@testgroup` the line goes into, when the script is shared. */
  readonly scope: string | null;
  /** What the tests can be written as there, the default first. */
  readonly forms: readonly Form[];
  readonly form: Form;
  /** The `*` pattern a copy fills, when one can be made. */
  readonly suggested: string | null;
  /** Whether the tests already live there: promoting changes them in place. */
  readonly inPlace: boolean;
}

export type Change =
  | {
      readonly action: 'modify';
      readonly path: string;
      readonly before: string;
      readonly after: string;
    }
  | { readonly action: 'create'; readonly path: string; readonly from: string }
  | { readonly action: 'create'; readonly path: string; readonly content: string }
  | { readonly action: 'delete'; readonly path: string };

export interface Promoted {
  readonly source: string;
  readonly form: Form;
  /** The file written, or the script the line went into; package-relative. */
  readonly to: string;
  readonly inPlace: boolean;
  readonly moved: boolean;
}

/** What `promote ... --dry-run --json` prints: the promotion, before it is made. */
export interface Plan {
  readonly sink: { readonly name: string; readonly kind: 'glob' | 'plan'; readonly path: string };
  /** Absolute paths, in the order rbx would make them. */
  readonly changes: readonly Change[];
  readonly promoted: readonly Promoted[];
  readonly skipped: readonly { readonly source: string; readonly reason: string }[];
}

/**
 * The JSON document `stdout` ends with, or undefined.
 *
 * The last line that parses, not the whole of stdout: rbx sends everything
 * but the JSON to stderr under `--json`, but a notice printed before that
 * redirect is in place -- a first run's cache setup, say -- still lands on
 * stdout, and one stray line should not cost the whole answer.
 */
export function lastJson(stdout: string): unknown {
  const lines = stdout.split(/\r?\n/);
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim();
    if (line.length === 0) {
      continue;
    }
    try {
      return JSON.parse(line) as unknown;
    } catch {
      // Not the document; keep looking further up.
    }
  }
  return undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isForm(value: unknown): value is Form {
  return value === 'recipe' || value === 'copy';
}

function isKind(value: unknown): value is 'glob' | 'plan' {
  return value === 'glob' || value === 'plan';
}

/** The sinks listed on `stdout`, or undefined when it is not that list. */
export function parseSinks(stdout: string): Sink[] | undefined {
  const raw = lastJson(stdout);
  if (!Array.isArray(raw)) {
    return undefined;
  }
  const sinks: Sink[] = [];
  for (const row of raw) {
    if (
      !isRecord(row) ||
      typeof row.name !== 'string' ||
      !isKind(row.kind) ||
      typeof row.path !== 'string' ||
      !(row.scope === null || typeof row.scope === 'string') ||
      !Array.isArray(row.forms) ||
      !row.forms.every(isForm) ||
      !isForm(row.form) ||
      !(row.suggested === null || typeof row.suggested === 'string') ||
      typeof row.inPlace !== 'boolean'
    ) {
      // One malformed row means the CLI changed shape; a partial list would
      // quietly hide a group rather than say anything is wrong.
      return undefined;
    }
    sinks.push({
      name: row.name,
      kind: row.kind,
      path: row.path,
      scope: row.scope,
      forms: row.forms,
      form: row.form,
      suggested: row.suggested,
      inPlace: row.inPlace,
    });
  }
  return sinks;
}

function parseChange(raw: unknown): Change | undefined {
  if (!isRecord(raw) || typeof raw.path !== 'string') {
    return undefined;
  }
  const { path } = raw;
  switch (raw.action) {
    case 'modify':
      return typeof raw.before === 'string' && typeof raw.after === 'string'
        ? { action: 'modify', path, before: raw.before, after: raw.after }
        : undefined;
    case 'create':
      if (typeof raw.from === 'string') {
        return { action: 'create', path, from: raw.from };
      }
      return typeof raw.content === 'string' ? { action: 'create', path, content: raw.content } : undefined;
    case 'delete':
      return { action: 'delete', path };
    default:
      return undefined;
  }
}

/** The plan printed on `stdout`, or undefined when it is not one. */
export function parsePlan(stdout: string): Plan | undefined {
  const raw = lastJson(stdout);
  if (
    !isRecord(raw) ||
    !isRecord(raw.sink) ||
    typeof raw.sink.name !== 'string' ||
    !isKind(raw.sink.kind) ||
    typeof raw.sink.path !== 'string' ||
    !Array.isArray(raw.changes) ||
    !Array.isArray(raw.promoted) ||
    !Array.isArray(raw.skipped)
  ) {
    return undefined;
  }
  const changes: Change[] = [];
  for (const each of raw.changes) {
    const change = parseChange(each);
    if (change === undefined) {
      return undefined;
    }
    changes.push(change);
  }
  const promoted: Promoted[] = [];
  for (const each of raw.promoted) {
    if (
      !isRecord(each) ||
      typeof each.source !== 'string' ||
      !isForm(each.form) ||
      typeof each.to !== 'string' ||
      typeof each.inPlace !== 'boolean' ||
      typeof each.moved !== 'boolean'
    ) {
      return undefined;
    }
    promoted.push({
      source: each.source,
      form: each.form,
      to: each.to,
      inPlace: each.inPlace,
      moved: each.moved,
    });
  }
  const skipped: { source: string; reason: string }[] = [];
  for (const each of raw.skipped) {
    if (!isRecord(each) || typeof each.source !== 'string' || typeof each.reason !== 'string') {
      return undefined;
    }
    skipped.push({ source: each.source, reason: each.reason });
  }
  return {
    sink: { name: raw.sink.name, kind: raw.sink.kind, path: raw.sink.path },
    changes,
    promoted,
    skipped,
  };
}

/**
 * Whether two versions of a file are the same text.
 *
 * Line endings and a leading BOM aside: rbx reads files with universal
 * newlines, so its `before` never holds a `\r`, while the file on disk -- or
 * the editor's copy of it -- may; and Node's `utf8` keeps a BOM that Python
 * reading the same file may or may not have.
 */
export function sameText(a: string, b: string): boolean {
  return normalize(a) === normalize(b);
}

function normalize(text: string): string {
  return text.replace(/^﻿/, '').replace(/\r\n?/g, '\n');
}

// --- argv -------------------------------------------------------------------

/** Where the tests go. */
export type Destination =
  | { readonly kind: 'sink'; readonly name: string }
  | { readonly kind: 'new-manual'; readonly name: string; readonly glob: string }
  | { readonly kind: 'new-script'; readonly path: string };

export interface PromoteOptions {
  readonly form?: Form;
  /** Where a `@copy` file goes: a file, or a `*` pattern. */
  readonly path?: string;
  /** The stem of the one file promoted into a glob. */
  readonly name?: string;
  readonly keepSource?: boolean;
  /** The stress session a `finding:K` source was picked from. */
  readonly session?: string;
}

/** `--list-sinks --json` for `sources`, after the subcommand. */
export function listSinksArgs(sources: readonly string[]): string[] {
  return [...sources, '--list-sinks', '--json'];
}

function destinationArgs(destination: Destination): string[] {
  switch (destination.kind) {
    case 'sink':
      return ['--to', destination.name];
    case 'new-manual':
      return ['--new-manual', destination.name, '--glob', destination.glob];
    case 'new-script':
      return ['--new-script', destination.path];
  }
}

/** The promotion, after the subcommand, without `--dry-run`. */
export function promoteArgs(
  sources: readonly string[],
  destination: Destination,
  options: PromoteOptions = {},
): string[] {
  return [
    ...sources,
    ...(options.session === undefined ? [] : ['--session', options.session]),
    ...destinationArgs(destination),
    ...(options.form === undefined ? [] : ['--as', options.form]),
    ...(options.path === undefined || options.path === '' ? [] : ['--path', options.path]),
    ...(options.name === undefined || options.name === '' ? [] : ['--name', options.name]),
    ...(options.keepSource === true ? ['--keep-source'] : []),
  ];
}

/** The promotion as a plan, after the subcommand: changes nothing. */
export function planArgs(
  sources: readonly string[],
  destination: Destination,
  options: PromoteOptions = {},
): string[] {
  return [...promoteArgs(sources, destination, options), '--dry-run', '--json'];
}

/** `rbx testcases promote …` as a line to paste. */
export function commandLine(args: readonly string[]): string {
  return ['rbx', ...PROMOTE, ...args].map(shellQuote).join(' ');
}

// --- the pickers ------------------------------------------------------------

/** One row of the destination picker, before it is a `QuickPickItem`. */
export type PickRow =
  | { readonly kind: 'separator'; readonly label: string }
  | {
      readonly kind: 'sink';
      readonly label: string;
      readonly description: string;
      readonly detail?: string;
      readonly sink: Sink;
    }
  | {
      readonly kind: 'new-script' | 'new-manual';
      readonly label: string;
      readonly description: string;
    };

/** What a sink holds, said for the picker. */
export function sinkDescription(sink: Sink): string {
  const where = sink.scope === null ? sink.path : `${sink.path} · @testgroup ${sink.scope}`;
  return sink.kind === 'glob' ? `folder ${where}` : `testplan ${where}`;
}

function sinkDetail(sink: Sink): string | undefined {
  if (sink.inPlace) {
    return sink.forms.includes('copy') && sink.kind === 'plan'
      ? 'Already here: freeze it into a @copy on the same line'
      : 'Already here';
  }
  return undefined;
}

/**
 * The picker: the sinks in rbx's order -- where the tests already live, then
 * the samples, then the rest -- then the two ways to make a new group.
 */
export function pickRows(sinks: readonly Sink[]): PickRow[] {
  const rows: PickRow[] = [];
  const here = sinks.filter((sink) => sink.inPlace);
  const elsewhere = sinks.filter((sink) => !sink.inPlace);
  for (const [heading, group] of [
    ['Where it is now', here],
    ['Test groups', elsewhere],
  ] as const) {
    if (group.length === 0) {
      continue;
    }
    rows.push({ kind: 'separator', label: heading });
    for (const sink of group) {
      const detail = sinkDetail(sink);
      rows.push({
        kind: 'sink',
        label: sink.name,
        description: sinkDescription(sink),
        ...(detail === undefined ? {} : { detail }),
        sink,
      });
    }
  }
  rows.push({ kind: 'separator', label: 'New group' });
  rows.push({
    kind: 'new-script',
    label: 'New script group…',
    description: 'a .txt generator script holding the test',
  });
  rows.push({
    kind: 'new-manual',
    label: 'New manual group…',
    description: 'a folder of .in files holding a copy',
  });
  return rows;
}

/** One row of the form picker. */
export interface FormRow {
  readonly form: Form;
  readonly label: string;
  readonly description: string;
}

/** The forms a sink offers, the default first, said for the picker. */
export function formRows(sink: Sink): FormRow[] {
  return sink.forms.map((form) =>
    form === 'recipe'
      ? { form, label: 'Generator call', description: 'generated again on every build' }
      : { form, label: '@copy of the input', description: 'frozen into a file of its own' },
  );
}

// --- the plan, said ---------------------------------------------------------

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** What a plan does, in a line: `1 file created, 1 deleted, 1 edited`. */
export function planSummary(plan: Plan): string {
  const created = plan.changes.filter((change) => change.action === 'create').length;
  const edited = plan.changes.filter((change) => change.action === 'modify').length;
  const deleted = plan.changes.filter((change) => change.action === 'delete').length;
  const parts = [
    created > 0 ? plural(created, 'file created', 'files created') : undefined,
    edited > 0 ? plural(edited, 'file edited', 'files edited') : undefined,
    deleted > 0 ? plural(deleted, 'file deleted', 'files deleted') : undefined,
  ].filter((part): part is string => part !== undefined);
  return parts.length === 0 ? 'nothing to change' : parts.join(', ');
}

/** The changes a plan's text diffs show: edits, and new text files. */
export function textChanges(plan: Plan): Change[] {
  return plan.changes.filter(
    (change) => change.action === 'modify' || (change.action === 'create' && 'content' in change),
  );
}

/** The title of a plan's diffs. */
export function proposalTitle(label: string, plan: Plan, file: string): string {
  return `Promote ${label} → ${plan.sink.name}: ${file} (${planSummary(plan)}; edit, then Accept)`;
}

/** Why nothing was promoted, when the plan changes nothing. */
export function nothingToDo(plan: Plan): string {
  const reasons = plan.skipped.map((each) => `${each.source}: ${each.reason}`);
  return reasons.length === 0 ? 'there is nothing to change.' : `${reasons.join('; ')}.`;
}

/** What was done, once the plan is applied. */
export function doneMessage(label: string, plan: Plan): string {
  const first = plan.promoted[0];
  if (first === undefined) {
    return `promoted ${label} into ${plan.sink.name}.`;
  }
  const what = first.form === 'recipe' ? 'its generator call' : `a copy at ${first.to}`;
  if (first.inPlace) {
    return `turned ${label} into ${what === 'its generator call' ? 'a generator call' : what}, in place.`;
  }
  return `${first.moved ? 'moved' : 'copied'} ${label} into ${plan.sink.name}, as ${what}.`;
}

// --- what the user types ----------------------------------------------------

/** Mirrors `NameField` in rbx/box/fields.py, which names every test group. */
const GROUP_NAME = /^[a-zA-Z0-9][a-zA-Z0-9\-_]*$/;

/** Why `name` cannot name a new group, or undefined if it can. */
export function groupNameError(
  name: string,
  existing: readonly string[] = [],
): string | undefined {
  if (name.length < 3 || name.length > 32 || !GROUP_NAME.test(name)) {
    return (
      `"${name}" is not a valid test group name: it must be 3 to 32 letters, ` +
      'digits, `-` or `_`, starting with a letter or digit.'
    );
  }
  if (existing.includes(name)) {
    return `Test group "${name}" already exists.`;
  }
  return undefined;
}

/**
 * Whether `path` stays inside the package: relative, and never climbing out.
 * rbx checks this too; asking here is only so the box can say so.
 */
function insidePackage(path: string): boolean {
  if (path.startsWith('/') || path.startsWith('\\') || /^[A-Za-z]:/.test(path)) {
    return false;
  }
  return !path.split(/[\\/]/).includes('..');
}

function basename(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1];
}

/**
 * Why `path` cannot be a new script group's file, or undefined if it can.
 *
 * The group is named after the file's stem, so the stem must be a group name
 * nobody holds; and rbx only writes `.txt` scripts, so the file must be one --
 * a path with no suffix gets `.txt`, as rbx gives it.
 */
export function newScriptPathError(
  path: string,
  existing: readonly string[] = [],
): string | undefined {
  if (path.length === 0) {
    return 'Name the script, e.g. tests/edge.txt.';
  }
  if (!insidePackage(path)) {
    return 'The script must be inside the package: a relative path, without `..`.';
  }
  const base = basename(path);
  const dot = base.lastIndexOf('.');
  // pathlib's suffix: a leading dot is part of the name, not a suffix.
  const suffix = dot > 0 ? base.slice(dot) : '';
  if (suffix !== '' && suffix !== '.txt') {
    return `The script must be a .txt file (got ${suffix}).`;
  }
  const stem = suffix === '' ? base : base.slice(0, dot);
  return groupNameError(stem, existing);
}

/** Why `glob` cannot be a new manual group's glob, or undefined if it can. */
export function manualGlobError(glob: string): string | undefined {
  if (!glob.includes('*') || !glob.endsWith('.in')) {
    return 'The glob of a manual group must contain a `*` and end in `.in`, e.g. tests/corner/*.in.';
  }
  if (!insidePackage(glob)) {
    return 'The glob must be inside the package: a relative path, without `..`.';
  }
  return undefined;
}

/**
 * Why `path` cannot say where a `@copy` file goes, or undefined if it can: a
 * file, or a pattern whose `*` rbx fills, ending in `.in`, in the package.
 */
export function copyPathError(path: string): string | undefined {
  if (path.length === 0) {
    return 'Say where the file goes, e.g. tests/edge/*.in.';
  }
  if (!path.endsWith('.in')) {
    return 'A promoted input must end in `.in`.';
  }
  if (!insidePackage(path)) {
    return 'The file must be inside the package: a relative path, without `..`.';
  }
  if (path.split('/').slice(0, -1).some((part) => part.includes('*'))) {
    return 'Only the file name may hold a `*`.';
  }
  return undefined;
}

/**
 * What a promoted file's stem may be: letters, digits, `.`, `_` or `-`, so the
 * file lands in the group's own folder. Empty means the next free one.
 */
const STEM = /^[A-Za-z0-9._-]+$/;

/** Why `stem` cannot name a promoted test's file, or undefined if it can. */
export function stemError(stem: string): string | undefined {
  if (stem === '') {
    return undefined;
  }
  if (!STEM.test(stem) || stem === '.' || stem === '..') {
    return 'A file name is letters, digits, `.`, `_` or `-`; leave it empty for the next free one.';
  }
  return undefined;
}

/** A free name for a new script group: `edge`, else `edge-2`, `edge-3`… */
export function defaultScriptPath(existing: readonly string[]): string {
  let stem = 'edge';
  for (let n = 2; existing.includes(stem); n++) {
    stem = `edge-${n}`;
  }
  return `tests/${stem}.txt`;
}

/** Where a new manual group's files go unless the user says otherwise. */
export function defaultManualGlob(name: string): string {
  return `tests/${name}/*.in`;
}

/**
 * What to show when a headless rbx fails: rbx's own message, which it prints
 * on stderr, or the exit code when it printed nothing.
 */
export function failureMessage(code: number | null, stderr: string): string {
  // The escape byte is named, as in visualizeRun.ts: rbx colours its errors.
  const text = stderr.replace(/\u001b\[[0-9;?]*[A-Za-z]/g, '').trim();
  if (text.length === 0) {
    return code === null ? 'rbx did not finish.' : `rbx exited with ${code}.`;
  }
  // The end of it: a traceback's last lines are the ones that say what broke.
  const lines = text.split(/\r?\n/);
  return lines.slice(-6).join('\n');
}

/**
 * The tab label of a proposed file, from its path relative to the package.
 *
 * The URI path is what the tab shows; a path that leaves the package (or is
 * absolute) would say less than its basename does, so it gets that instead.
 */
export function proposalLabel(relative: string): string {
  const slashed = relative.replace(/\\/g, '/').replace(/^(\.\/)+/, '');
  if (!insidePackage(slashed) || slashed.length === 0) {
    return basename(slashed);
  }
  return slashed;
}
