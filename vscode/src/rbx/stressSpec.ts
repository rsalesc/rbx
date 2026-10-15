/**
 * What the stress launcher asks for, and the `rbx stress` line that says it.
 *
 * The launcher's three sections -- inputs, finder, budget -- compile to one
 * command, which the launcher shows live in its footer and the dispatcher
 * types into a visible terminal (design S4, D3 as amended by #906). That line
 * is the user's record of what ran, so it is built to read like one they would
 * type: flags only where they differ from rbx's defaults, and the same
 * spellings `rbx stress --help` documents (rbx/box/cli/commands/stress.py).
 *
 * Pure: no `vscode`, no disk. Mirroring the CLI's *flag names* here is fine for
 * the same reason report.ts mirrors field names -- a rename fails loudly and in
 * one place.
 */
import {
  FinderRow,
  Join,
  compileFinder,
  finderPathProblem,
  singleQuoteProblem,
} from './finder';
import { GeneratorCall } from './stress';
import { StressDeclaration } from './stressDeclarations';

/** rbx stress's own defaults, which the argv leaves out rather than repeats. */
export const STRESS_DEFAULTS = { timeout: 10, findings: 1 } as const;

/**
 * Where the last launch for a package is kept, in `workspaceState`.
 *
 * Per package root, so a contest's problems each remember their own; written
 * by the launcher, read by the Stress view's Run on a declared stress.
 */
export function lastLaunchKey(root: string): string {
  return `rbx.stress.lastLaunch:${root}`;
}

/** Where the inputs come from. */
export type StressSource =
  /** A stress declared in problem.rbx.yml, by name. */
  | { readonly kind: 'declared'; readonly name: string }
  /** A generator expression: `gens/gen.cpp [1..1000]`, `gens/gen.cpp @`, ... */
  | { readonly kind: 'generator'; readonly expression: string }
  /** Generator calls fuzzed from these testgroups; `[]` is every group. */
  | { readonly kind: 'fuzz'; readonly groups: readonly string[] };

export type StressTimeLimit =
  | { readonly kind: 'normal' }
  /** `--double-tl`: run under twice the time limit. */
  | { readonly kind: 'double' }
  /** `--timelimit MS`. */
  | { readonly kind: 'custom'; readonly ms: number };

export interface StressLaunch {
  readonly source: StressSource;
  /**
   * The finder rows, or undefined to keep what the source brings: a declared
   * stress's own finder, or -- when fuzzing -- rbx's default of checking the
   * main solution. A generator source has no finder of its own and needs rows.
   */
  readonly finder?: { readonly rows: readonly FinderRow[]; readonly join: Join };
  readonly slowest: boolean;
  /** Seconds. */
  readonly timeout: number;
  readonly findings: number;
  readonly tl: StressTimeLimit;
  readonly sanitized: boolean;
  readonly skipInvalid: boolean;
  readonly validate: boolean;
  /** A solution path, relative to the package root. */
  readonly reference?: string;
}

/**
 * A launch that changes nothing rbx would assume: `rbx stress <source>` plus
 * `--no-promote`. Also what the launcher opens blank on.
 */
export function defaultLaunch(source: StressSource): StressLaunch {
  return {
    source,
    slowest: false,
    timeout: STRESS_DEFAULTS.timeout,
    findings: STRESS_DEFAULTS.findings,
    tl: { kind: 'normal' },
    sanitized: false,
    skipInvalid: false,
    validate: true,
  };
}

/** What the argv needs of a declared stress: its generator call and finder. */
export type DeclaredStress = Pick<StressDeclaration, 'generator' | 'finder'>;

/** A generator call as `-g` takes it: `GeneratorCall.__str__`, name then args. */
export function generatorCallString(generator: GeneratorCall): string {
  const args = generator.args?.trim();
  return args === undefined || args === '' ? generator.name : `${generator.name} ${args}`;
}

function isPositiveInteger(value: number): boolean {
  return Number.isInteger(value) && value > 0;
}

function rowsProblem(rows: readonly FinderRow[]): string | undefined {
  for (const row of rows) {
    const paths = row.kind === 'break' ? [row.solution] : [row.a, row.b];
    for (const path of paths) {
      const problem = finderPathProblem(path);
      if (problem !== undefined) {
        return problem;
      }
    }
    if (row.kind === 'disagree' && row.a === row.b) {
      return `A disagreement needs two different solutions, not ${row.a} twice.`;
    }
    if (row.kind === 'break' && row.outcome === '') {
      return `Choose an outcome for ${row.solution}.`;
    }
  }
  return undefined;
}

/**
 * Why `launch` cannot run, in words for the launcher to show; undefined when it
 * can.
 *
 * Checked here rather than left to rbx so the launcher can say so before
 * anything is dispatched -- a terminal that opens just to print an error and
 * close is the worst place to learn it. Where rbx would refuse the same thing,
 * the message says what rbx says, in the launcher's terms.
 *
 * `declared` is the declared stress the source names, when it names one: its
 * generator call is what the argv spells out once its finder is replaced.
 *
 * Every value that becomes an argument is also refused if it holds a single
 * quote, which the terminal cannot pass on (see `singleQuoteProblem`).
 */
export function validateLaunch(launch: StressLaunch, declared?: DeclaredStress): string | undefined {
  const source = launch.source;
  const rows = launch.finder?.rows;
  if (source.kind === 'declared') {
    if (source.name.trim() === '') {
      return 'Choose a declared stress to run.';
    }
    if (source.name.includes("'")) {
      return singleQuoteProblem(source.name);
    }
    if (rows !== undefined && rows.length === 0) {
      return "Add at least one finder row, or keep the stress's own finder.";
    }
    if (rows !== undefined) {
      if (declared === undefined) {
        return `The stress ${source.name} is no longer declared in problem.rbx.yml.`;
      }
      const call = generatorCallString(declared.generator);
      if (call.includes("'")) {
        return singleQuoteProblem(call);
      }
    }
  }
  if (source.kind === 'generator') {
    if (source.expression.trim() === '') {
      return 'Write a generator call to run, such as `gens/gen.cpp [1..1000]`.';
    }
    if (source.expression.includes("'")) {
      return singleQuoteProblem(source.expression.trim());
    }
    // rbx: "Option --generator/-g requires --finder/-f." Even under --slowest,
    // whose finder still names the solutions being timed.
    if (rows === undefined || rows.length === 0) {
      return launch.slowest
        ? 'A generator call needs at least one finder row: under Slowest, it names the solutions to time.'
        : 'A generator call needs at least one finder row to say what counts as a finding.';
    }
  }
  if (source.kind === 'fuzz') {
    if (rows !== undefined && rows.length === 0) {
      return 'Add at least one finder row, or leave the finder out to check the main solution.';
    }
    for (const group of source.groups) {
      if (group.trim() === '') {
        return 'Every testgroup to fuzz needs a name.';
      }
      if (group.includes("'")) {
        return singleQuoteProblem(group);
      }
    }
  }
  const problem = rows === undefined ? undefined : rowsProblem(rows);
  if (problem !== undefined) {
    return problem;
  }
  if (!isPositiveInteger(launch.timeout)) {
    return 'The time budget must be a whole number of seconds, at least 1.';
  }
  if (!isPositiveInteger(launch.findings)) {
    return 'The number of findings must be a whole number, at least 1.';
  }
  if (launch.tl.kind === 'custom' && !isPositiveInteger(launch.tl.ms)) {
    return 'The time limit must be a whole number of milliseconds, at least 1.';
  }
  if (launch.reference !== undefined && launch.reference.trim() === '') {
    return 'Choose a reference solution, or leave it out.';
  }
  if (launch.reference !== undefined && launch.reference.includes("'")) {
    return singleQuoteProblem(launch.reference);
  }
  return undefined;
}

/**
 * The argv after `rbx`: `['stress', ...]`, always ending in `--no-promote`.
 *
 * `--no-promote` because the CLI's end-of-run prompt would leave the
 * dispatched task waiting on a terminal nobody is looking at; promoting is the
 * Stress view's job, through `rbx testcases add-finding`.
 *
 * A declared stress whose finder was replaced by rows is spelled out as `-g`
 * plus `-f`, which is why `declared` is needed: `rbx stress NAME` takes no
 * finder override, and `-f` without `-g` is refused. The session then carries
 * no stress name -- it is, as far as rbx can tell, an ad-hoc stress with the
 * same generator. Throws when `declared` is missing for exactly that case,
 * which `validateLaunch` refuses when given the same `declared`.
 */
export function stressArgv(launch: StressLaunch, declared?: DeclaredStress): string[] {
  const args = ['stress'];
  const source = launch.source;
  const finder =
    launch.finder === undefined ? undefined : compileFinder(launch.finder.rows, launch.finder.join);
  switch (source.kind) {
    case 'declared':
      if (finder === undefined) {
        args.push(source.name);
      } else {
        if (declared === undefined) {
          throw new Error(
            `The declared stress ${source.name} is needed to replace its finder, and was not given.`,
          );
        }
        args.push('-g', generatorCallString(declared.generator), '-f', finder);
      }
      break;
    case 'generator':
      args.push('-g', source.expression.trim());
      if (finder !== undefined) {
        args.push('-f', finder);
      }
      break;
    case 'fuzz':
      if (source.groups.length === 0) {
        args.push('--fuzz');
      } else {
        for (const group of source.groups) {
          args.push('--fuzz-on', group);
        }
      }
      if (finder !== undefined) {
        args.push('-f', finder);
      }
      break;
  }
  if (launch.slowest) {
    args.push('--slowest');
  }
  if (launch.timeout !== STRESS_DEFAULTS.timeout) {
    args.push('--timeout', String(launch.timeout));
  }
  if (launch.findings !== STRESS_DEFAULTS.findings) {
    args.push('--findings', String(launch.findings));
  }
  if (launch.tl.kind === 'double') {
    args.push('--double-tl');
  } else if (launch.tl.kind === 'custom') {
    args.push('--timelimit', String(launch.tl.ms));
  }
  if (launch.sanitized) {
    args.push('--sanitized');
  }
  if (launch.skipInvalid) {
    args.push('--skip-invalid');
  }
  if (!launch.validate) {
    args.push('--no-validate');
  }
  if (launch.reference !== undefined) {
    args.push('--reference', launch.reference);
  }
  args.push('--no-promote');
  return args;
}
