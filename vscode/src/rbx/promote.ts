/**
 * Promoting a stress finding into the testset (#908, design S6): everything
 * about it decidable without `vscode`.
 *
 * The host half is stressPromote.ts. What goes into the testset is decided by
 * `rbx testcases add-finding`, never here: this module only builds its argv,
 * reads what its `--json` modes print, and checks a new group's name before
 * rbx does, so a typo is caught in the input box rather than in a terminal
 * the user has to go read.
 */

import { singleQuoteProblem } from './finder';
import { shellQuote } from './shellQuote';

/** The subcommand, for the headless runs; a dispatch puts it in front itself. */
export const ADD_FINDING = ['testcases', 'add-finding'] as const;

/** Where a new script group goes unless the user says otherwise. */
export const DEFAULT_SCRIPT_DIR = 'tests';

/** A group `add-finding --list-groups --json` says can take findings. */
export interface PromoteGroup {
  readonly name: string;
  readonly kind: 'script' | 'manual';
  /** The generator script, relative to the package; the glob for a manual group. */
  readonly path: string;
}

/** What `add-finding K --group G --dry-run --json` proposes. */
export interface DryRun {
  /** The generator script, absolute. */
  readonly file: string;
  readonly before: string;
  /** Equal to `before` when the group already has the finding. */
  readonly after: string;
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

/** The groups listed on `stdout`, or undefined when it is not that list. */
export function parseGroupList(stdout: string): PromoteGroup[] | undefined {
  const raw = lastJson(stdout);
  if (!Array.isArray(raw)) {
    return undefined;
  }
  const groups: PromoteGroup[] = [];
  for (const row of raw) {
    if (
      !isRecord(row) ||
      typeof row.name !== 'string' ||
      typeof row.path !== 'string' ||
      (row.kind !== 'script' && row.kind !== 'manual')
    ) {
      // One malformed row means the CLI changed shape; a partial list would
      // quietly hide a group rather than say anything is wrong.
      return undefined;
    }
    groups.push({ name: row.name, kind: row.kind, path: row.path });
  }
  return groups;
}

/** The proposal on `stdout`, or undefined when it is not one. */
export function parseDryRun(stdout: string): DryRun | undefined {
  const raw = lastJson(stdout);
  if (
    !isRecord(raw) ||
    typeof raw.file !== 'string' ||
    typeof raw.before !== 'string' ||
    typeof raw.after !== 'string'
  ) {
    return undefined;
  }
  return { file: raw.file, before: raw.before, after: raw.after };
}

/**
 * Whether two versions of a script are the same text.
 *
 * Line endings and a leading BOM aside: rbx reads the script with universal
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

/**
 * The tab label of a proposal for the script at `scriptPath`, which
 * `--list-groups` gives relative to the package.
 *
 * The URI path is what the tab shows, so it is the package-relative path
 * with forward slashes; a path that leaves the package (or is absolute)
 * would say less than its basename does, so it gets that instead.
 */
export function proposalLabel(scriptPath: string): string {
  const slashed = scriptPath.replace(/\\/g, '/').replace(/^(\.\/)+/, '');
  if (!insidePackage(slashed) || slashed.length === 0) {
    return basename(slashed);
  }
  return slashed;
}

// --- argv -------------------------------------------------------------------

/** `--list-groups --json`, after the subcommand. */
export function listGroupsArgs(): string[] {
  return ['--list-groups', '--json'];
}

/**
 * `--session S`, when the session's start is known: add-finding reads the
 * latest session, and a stress started from a terminal between the click and
 * the command would make finding `k` another input altogether. rbx refuses
 * a session that is no longer the latest instead of promoting the wrong one.
 */
function sessionArgs(session: string | undefined): string[] {
  return session === undefined ? [] : ['--session', session];
}

/** The script group's proposal, after the subcommand. */
export function dryRunArgs(k: number, group: string, session?: string): string[] {
  return [String(k), ...sessionArgs(session), '--group', group, '--dry-run', '--json'];
}

/** Add finding `k` to an existing group, after the subcommand. */
export function addToGroupArgs(k: number, group: string, session?: string): string[] {
  return [String(k), ...sessionArgs(session), '--group', group];
}

/** Create a script group at `path` and add finding `k`, after the subcommand. */
export function newScriptArgs(k: number, path: string, session?: string): string[] {
  return [String(k), ...sessionArgs(session), '--new-script', path];
}

/** Create a manual group and copy finding `k` in, after the subcommand. */
export function newManualArgs(k: number, name: string, glob: string, session?: string): string[] {
  return [String(k), ...sessionArgs(session), '--new-manual', name, '--glob', glob];
}

// --- the picker -------------------------------------------------------------

/** One row of the group picker, before it is a `QuickPickItem`. */
export type PickRow =
  | { readonly kind: 'separator'; readonly label: string }
  | {
      readonly kind: 'group';
      readonly label: string;
      readonly description: string;
      readonly group: PromoteGroup;
    }
  | {
      readonly kind: 'new-script' | 'new-manual';
      readonly label: string;
      readonly description: string;
    };

export const SCRIPT_SEPARATOR = 'Script groups — adds the generator call (reviewable)';
export const MANUAL_SEPARATOR = 'Manual groups — copies the input';

/**
 * The picker: script groups, then manual groups, each under a separator that
 * says what promoting into it does -- the one difference that matters when
 * choosing -- then the two ways to make a new one. A kind with no groups gets
 * no separator, so no heading sits over nothing.
 */
export function pickRows(groups: readonly PromoteGroup[]): PickRow[] {
  const rows: PickRow[] = [];
  for (const [kind, heading] of [
    ['script', SCRIPT_SEPARATOR],
    ['manual', MANUAL_SEPARATOR],
  ] as const) {
    const ofKind = groups.filter((group) => group.kind === kind);
    if (ofKind.length === 0) {
      continue;
    }
    rows.push({ kind: 'separator', label: heading });
    for (const group of ofKind) {
      rows.push({ kind: 'group', label: group.name, description: group.path, group });
    }
  }
  rows.push({ kind: 'separator', label: 'New group' });
  rows.push({
    kind: 'new-script',
    label: 'New script group…',
    description: 'a .txt generator script holding the call',
  });
  rows.push({
    kind: 'new-manual',
    label: 'New manual group…',
    description: 'a folder of .in files holding a copy',
  });
  return rows;
}

/** The title of the proposal's diff. */
export function proposalTitle(k: number, group: string): string {
  return `Promote finding #${k} → ${group} (edit the right side, then Accept)`;
}

// --- new groups -------------------------------------------------------------

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
 * nobody holds; and rbx only appends to `.txt` scripts, so the file must be
 * one -- a path with no suffix gets `.txt`, as rbx gives it.
 */
export function newScriptPathError(
  path: string,
  existing: readonly string[] = [],
): string | undefined {
  if (path.length === 0) {
    return 'Name the script, e.g. tests/stress.txt.';
  }
  // Every dispatched argument is single-quoted, which cannot hold one.
  if (path.includes("'")) {
    return singleQuoteProblem(path);
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

/** The name rbx gives the group a new script at `path` creates: its stem. */
export function scriptGroupName(path: string): string {
  const base = basename(path);
  return base.endsWith('.txt') && base.length > '.txt'.length ? base.slice(0, -'.txt'.length) : base;
}

/** Why `glob` cannot be a new manual group's glob, or undefined if it can. */
export function manualGlobError(glob: string): string | undefined {
  if (glob.includes("'")) {
    return singleQuoteProblem(glob);
  }
  if (!glob.includes('*') || !glob.endsWith('.in')) {
    return 'The glob of a manual group must contain a `*` and end in `.in`, e.g. tests/corner/*.in.';
  }
  if (!insidePackage(glob)) {
    return 'The glob must be inside the package: a relative path, without `..`.';
  }
  return undefined;
}

/**
 * A free name for a new script group: `stress`, else `stress-2`, `stress-3`…
 * Only a suggestion, filled into the box for the user to change.
 */
export function defaultScriptPath(existing: readonly string[]): string {
  let stem = 'stress';
  for (let n = 2; existing.includes(stem); n++) {
    stem = `stress-${n}`;
  }
  return `${DEFAULT_SCRIPT_DIR}/${stem}.txt`;
}

/** Where a new manual group's files go unless the user says otherwise. */
export function defaultManualGlob(name: string): string {
  return `tests/${name}/*.in`;
}

/**
 * What to show when a headless `add-finding` fails: rbx's own message, which
 * it prints on stderr, or the exit code when it printed nothing.
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
 * `rbx testcases add-finding …` as a line to paste, for when dispatching is
 * off and the user runs it themselves.
 */
export function commandLine(args: readonly string[]): string {
  return ['rbx', ...ADD_FINDING, ...args]
    .map(shellQuote)
    .join(' ');
}
