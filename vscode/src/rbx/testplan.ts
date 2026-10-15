/**
 * Testplans -- rbx-format `.txt` generator scripts -- line by line (#910):
 * where each test's statement is, and the argv that acts on one of them.
 *
 * The lens over each statement addresses its test as `<script>:<line>`, the
 * line the statement starts on, which `rbx testcases generate`, `promote` and
 * `irun -t` all accept. That needs no built testset, and so no `rbx build`
 * between editing a plan and acting on it: rbx resolves the line itself, and
 * refuses one no statement starts on.
 *
 * Which lines start a statement is the one thing decided here, by a scanner
 * that mirrors the Lark grammar in rbx/box/stressing/generator_script_parser.py
 * rather than asking rbx on every keystroke. `testplan.cases.json` pins the two
 * to the same answers: this module's test and a Python test over
 * `statement_spans` both read it.
 */
import { lastJson } from './promote';
import { shellQuote } from './shellQuote';

/** What a statement is, which decides the lenses it gets. */
export type StatementKind = 'call' | 'copy' | 'input';

export interface TestplanStatement {
  /** 1-based, as rbx counts: the line the statement starts on. */
  readonly line: number;
  /** 1-based and inclusive; past `line` only for a multi-line `@input`. */
  readonly endLine: number;
  readonly kind: StatementKind;
}

const COMMENT = /^(\/\/|#)/;
const KEYWORD = /^@(copy|input|testgroup)\b/;

/**
 * Every test statement in `text`, in order.
 *
 * `@testgroup name {` and its closing `}` are not statements: a group is
 * descended into, and each statement inside it is one test, as
 * `statement_spans` reports them. Lenient where the grammar is strict -- a
 * plan being typed rarely parses -- and a line it gets wrong costs a lens rbx
 * then refuses by name, never a wrong test.
 */
export function testplanStatements(text: string): TestplanStatement[] {
  const lines = text.split(/\r?\n/);
  const statements: TestplanStatement[] = [];
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (trimmed === '' || COMMENT.test(trimmed) || trimmed.startsWith('}')) {
      continue;
    }
    const keyword = KEYWORD.exec(trimmed)?.[1];
    if (keyword === 'testgroup') {
      continue;
    }
    if (keyword === 'copy') {
      statements.push({ line: i + 1, endLine: i + 1, kind: 'copy' });
      continue;
    }
    if (keyword === 'input') {
      const end = inputEnd(lines, i, trimmed.slice('@input'.length).trimStart());
      statements.push({ line: i + 1, endLine: end + 1, kind: 'input' });
      i = end;
      continue;
    }
    // `REST_OF_LINE` cannot start with `/` or `#`; anything else is a call.
    if (!trimmed.startsWith('/')) {
      statements.push({ line: i + 1, endLine: i + 1, kind: 'call' });
    }
  }
  return statements;
}

/**
 * The statement 1-based `line` is part of, for an action invoked from the
 * cursor rather than from a lens. A line between statements belongs to none.
 */
export function statementAt(
  statements: readonly TestplanStatement[],
  line: number,
): TestplanStatement | undefined {
  return statements.find((statement) => statement.line <= line && line <= statement.endLine);
}

/**
 * The 0-based line an `@input` starting on line `start` ends on. `rest` is
 * what follows the keyword there: a `"""` string or a `{ ... }` block may run
 * over several lines, a quoted string may not.
 */
function inputEnd(lines: readonly string[], start: number, rest: string): number {
  let closer: string;
  let from: string;
  if (rest.startsWith('"""')) {
    closer = '"""';
    from = rest.slice(3);
  } else if (rest.startsWith('{')) {
    // `BLOCK_CONTENT` is `[^}]+`: the first `}` closes the block.
    closer = '}';
    from = rest.slice(1);
  } else {
    return start;
  }
  if (from.includes(closer)) {
    return start;
  }
  for (let j = start + 1; j < lines.length; j++) {
    if (lines[j].includes(closer)) {
      return j;
    }
  }
  return lines.length - 1;
}

/** `tests/plan.txt:12`, relative to the package root with forward slashes. */
export function selector(scriptRelative: string, line: number): string {
  return `${scriptRelative.replace(/\\/g, '/')}:${line}`;
}

// --- argv -------------------------------------------------------------------

export const GENERATE = ['testcases', 'generate'] as const;
export const PROMOTE = ['testcases', 'promote'] as const;

/** `rbx testcases generate <sel> ... --json`, after the executable. */
export function generateArgs(
  sel: string,
  options: { readonly output?: boolean; readonly validate?: boolean },
): string[] {
  return [
    ...GENERATE,
    sel,
    ...(options.output === true ? ['--output'] : []),
    ...(options.validate === true ? ['--validate'] : []),
    '--json',
  ];
}

/** `--list-groups --json`, after `testcases promote`. */
export function promoteListArgs(): string[] {
  return ['--list-groups', '--json'];
}

/** Promote `sel` into an existing manual group, after `testcases promote`. */
export function promoteToGroupArgs(sel: string, group: string, name?: string): string[] {
  return [sel, '--group', group, ...nameArgs(name)];
}

/** Promote `sel` into a new manual group, after `testcases promote`. */
export function promoteNewManualArgs(
  sel: string,
  group: string,
  glob: string,
  name?: string,
): string[] {
  return [sel, '--new-manual', group, '--glob', glob, ...nameArgs(name)];
}

/**
 * `rbx testcases promote …` as a line to paste, for when dispatching is off
 * and the user runs it themselves.
 */
export function promoteCommandLine(args: readonly string[]): string {
  return ['rbx', ...PROMOTE, ...args].map(shellQuote).join(' ');
}

function nameArgs(name: string | undefined): string[] {
  return name === undefined || name === '' ? [] : ['--name', name];
}

/**
 * What a promoted file's stem may be. Stricter than rbx's `validate_stems`
 * (no whitespace): no `/` either, so the file lands in the group's own folder,
 * and no `'`, which a dispatched, single-quoted argument cannot hold.
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

// --- what `generate --json` prints -----------------------------------------

export interface ValidatorVerdict {
  readonly validator: string;
  readonly ok: boolean;
  readonly message?: string;
}

export interface Generated {
  /** `group/index`. */
  readonly test: string;
  /** `script:line`, when a script wrote the test. */
  readonly source?: string;
  /** The generator call, when the test has one. */
  readonly call?: string;
  /** Absolute. */
  readonly input: string;
  /** Absolute; absent unless `--output` was asked for and an answer exists. */
  readonly answer?: string;
  /** Absent unless `--validate` was asked for; empty when no validator applies. */
  readonly validation?: readonly ValidatorVerdict[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function optionalString(value: unknown): string | undefined | null {
  if (value === null || value === undefined) {
    return undefined;
  }
  return typeof value === 'string' ? value : null;
}

/** The document `generate --json` ended `stdout` with, or undefined. */
export function parseGenerated(stdout: string): Generated | undefined {
  const raw = lastJson(stdout);
  if (!isRecord(raw) || typeof raw.test !== 'string' || typeof raw.input !== 'string') {
    return undefined;
  }
  const source = optionalString(raw.source);
  const call = optionalString(raw.call);
  const answer = optionalString(raw.answer);
  if (source === null || call === null || answer === null) {
    return undefined;
  }
  let validation: ValidatorVerdict[] | undefined;
  if (raw.validation !== null && raw.validation !== undefined) {
    if (!Array.isArray(raw.validation)) {
      return undefined;
    }
    validation = [];
    for (const row of raw.validation) {
      if (!isRecord(row) || typeof row.validator !== 'string' || typeof row.ok !== 'boolean') {
        return undefined;
      }
      const message = optionalString(row.message);
      if (message === null) {
        return undefined;
      }
      validation.push({ validator: row.validator, ok: row.ok, message });
    }
  }
  return { test: raw.test, source, call, input: raw.input, answer, validation };
}

/** What to tell the user about a validated test, in one notification. */
export function validationSummary(generated: Generated): { ok: boolean; text: string } {
  const verdicts = generated.validation ?? [];
  const where = generated.source ?? generated.test;
  if (verdicts.length === 0) {
    return { ok: true, text: `No validator applies to ${where} (${generated.test}).` };
  }
  const rejected = verdicts.filter((verdict) => !verdict.ok);
  if (rejected.length === 0) {
    const names = verdicts.map((verdict) => verdict.validator).join(', ');
    return { ok: true, text: `${where} (${generated.test}) is valid: ${names} accepted it.` };
  }
  const reasons = rejected
    .map((verdict) =>
      verdict.message === undefined || verdict.message.trim() === ''
        ? verdict.validator
        : `${verdict.validator}: ${verdict.message.trim()}`,
    )
    .join('; ');
  return { ok: false, text: `${where} (${generated.test}) is invalid. ${reasons}` };
}
