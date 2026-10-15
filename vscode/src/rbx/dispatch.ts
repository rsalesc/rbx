/**
 * What the extension types when it dispatches an rbx command, and when it may.
 *
 * Design D3 (amended by #906): the extension may *dispatch* `rbx build` /
 * `rbx run` as a VS Code task -- a visible terminal the user watches and can
 * interrupt -- but never runs them headless and never parses their output.
 * Results still come only from the artifacts on disk.
 *
 * Pure, like its neighbours: building a `vscode.Task` out of this and asking
 * VS Code which tasks are running is dispatch.ts's job (the host half).
 */
import * as path from 'path';

/** The task type every dispatched command is registered under. */
export const TASK_TYPE = 'rbx';

/**
 * The commands the extension can dispatch.
 *
 * `contest-run` is `rbx contest each --inline run`: `--inline` because the
 * default opens the contest TUI, which has no business inside a task terminal
 * whose whole point is that its output is the plain record of the run.
 *
 * `stress` and `add-finding` (`rbx testcases add-finding`) carry their whole
 * argv tail in `Invocation.args`: the stress launcher and the Stress view build
 * it (stressSpec.ts), and this module only puts the subcommand in front.
 */
export type RbxCommand =
  | 'build'
  | 'run'
  | 'contest-run'
  | 'statements'
  | 'contest-statements'
  | 'tutorials'
  | 'contest-tutorials'
  | 'stress'
  | 'add-finding';

export const RBX_COMMANDS: readonly RbxCommand[] = [
  'build',
  'run',
  'contest-run',
  'statements',
  'contest-statements',
  'tutorials',
  'contest-tutorials',
  'stress',
  'add-finding',
];

/** The commands that build statements, which the statement preview watches for. */
export const STATEMENT_COMMANDS: readonly RbxCommand[] = [
  'statements',
  'contest-statements',
  'tutorials',
  'contest-tutorials',
];

/**
 * What rebuilds one statement output: `rbx tutorials build` for a tutorial,
 * `rbx statements build` for anything else (a document is a contest statement
 * build's), each in its contest form for a contest output.
 */
export function statementCommand(scope: DispatchScope, kind: string): RbxCommand {
  const tutorial = kind === 'tutorial';
  if (scope === 'contest') {
    return tutorial ? 'contest-tutorials' : 'contest-statements';
  }
  return tutorial ? 'tutorials' : 'statements';
}

export function isRbxCommand(value: unknown): value is RbxCommand {
  return typeof value === 'string' && (RBX_COMMANDS as readonly string[]).includes(value);
}

/**
 * The commands a webview's empty state may ask the host to run.
 *
 * An allowlist, because the id arrives in a message from the webview: the
 * client is ours, but nothing it sends is taken as more than a request.
 */
export const WELCOME_COMMANDS: readonly string[] = ['rbx.runAll', 'rbx.build'];

/** Whether a command acts on one package or on the contest above it. */
export type DispatchScope = 'problem' | 'contest';

export function scopeOf(command: RbxCommand): DispatchScope {
  return command.startsWith('contest-') ? 'contest' : 'problem';
}

/**
 * Which contest a dispatched command runs under.
 *
 * - `none`: no contest was resolved -- the package is in none, or no contest
 *   file names it. Nothing is passed, so rbx resolves exactly as it would for a
 *   command typed by hand.
 * - `canonical`: `contest.rbx.yml` itself. It has no id to pass to `-C`, so the
 *   task clears `RBX_CONTEST` instead: an inherited one would otherwise select a
 *   variant the user just chose against.
 * - `variant`: `contest.<id>.rbx.yml`, passed as `-C <id>`.
 */
export type ContestSelection =
  | { readonly kind: 'none' }
  | { readonly kind: 'canonical' }
  | { readonly kind: 'variant'; readonly id: string };

export const NO_CONTEST: ContestSelection = Object.freeze({ kind: 'none' });

/** One dispatch, fully resolved: everything the command line is built from. */
export interface Invocation {
  readonly command: RbxCommand;
  /**
   * The directory the command runs in: the package root for a problem command,
   * the contest root for a contest one.
   */
  readonly cwd: string;
  /** Solution paths for `run`, relative to `cwd`. Empty means every solution. */
  readonly solutions: readonly string[];
  /** `rbx.run.extraArgs`, for `run` and `contest-run`. */
  readonly extraArgs: readonly string[];
  /**
   * For `stress` and `add-finding`: everything after the subcommand, built by
   * whoever asked. Ignored by every other command.
   */
  readonly args?: readonly string[];
  readonly contest: ContestSelection;
}

/**
 * The argv after the executable.
 *
 * `-C` goes first because it is a root option (rbx/box/cli/__init__.py), so it
 * is the one spelling every subcommand accepts. Extra args come before the
 * solutions, which is where a user typing the command would put them -- the
 * terminal shows this exact line, so it should read like one they would type.
 */
export function rbxArgs(invocation: Invocation): string[] {
  const args: string[] = [];
  if (invocation.contest.kind === 'variant') {
    args.push('-C', invocation.contest.id);
  }
  switch (invocation.command) {
    case 'build':
      args.push('build');
      break;
    case 'run':
      args.push('run', ...invocation.extraArgs, ...invocation.solutions);
      break;
    case 'contest-run':
      args.push('contest', 'each', '--inline', 'run', ...invocation.extraArgs);
      break;
    case 'statements':
      args.push('statements', 'build');
      break;
    case 'contest-statements':
      args.push('contest', 'statements', 'build');
      break;
    case 'tutorials':
      args.push('tutorials', 'build');
      break;
    case 'contest-tutorials':
      args.push('contest', 'tutorials', 'build');
      break;
    case 'stress':
      args.push('stress', ...(invocation.args ?? []));
      break;
    case 'add-finding':
      args.push('testcases', 'add-finding', ...(invocation.args ?? []));
      break;
  }
  return args;
}

/**
 * Environment overrides for the task.
 *
 * Only the canonical selection needs one: an empty `RBX_CONTEST` reads as unset
 * to both click's envvar lookup and `resolve_explicit_selection`, which is what
 * selects the canonical when the user's shell exported a variant.
 */
export function rbxEnv(contest: ContestSelection): Record<string, string> | undefined {
  return contest.kind === 'canonical' ? { RBX_CONTEST: '' } : undefined;
}

/**
 * What the task is called in the terminal tab and in *Run Task*.
 *
 * The contest rides along whenever one was resolved, because it is the one
 * input that is not visible anywhere else at the moment of clicking -- and a
 * remembered choice is exactly the one a user may have forgotten making.
 */
export function taskName(invocation: Invocation): string {
  const base =
    invocation.command === 'build'
      ? 'build'
      : invocation.command === 'contest-run'
        ? 'run all problems'
        : invocation.command === 'run'
          ? invocation.solutions.length === 0
            ? 'run'
            : `run ${invocation.solutions.join(' ')}`
          : invocation.command === 'stress'
            ? `stress ${stressSubject(invocation.args ?? [])}`
            : invocation.command === 'add-finding'
              ? 'add finding'
              : `build ${invocation.command.replace('-', ' ')}`;
  const contest = invocation.contest;
  if (contest.kind === 'variant') {
    return `${base} [${contest.id}]`;
  }
  if (contest.kind === 'canonical') {
    return `${base} [default contest]`;
  }
  return base;
}

/**
 * What a stress task is about, for its name: the declared stress, the generator
 * call, or `fuzz`.
 *
 * Read back off the argv because the argv is all an invocation carries, and it
 * is one this extension wrote (stressSpec.ts) -- never rbx's output.
 */
function stressSubject(args: readonly string[]): string {
  if (args.length > 0 && !args[0].startsWith('-')) {
    return args[0];
  }
  const generator = args.indexOf('-g');
  if (generator >= 0 && generator + 1 < args.length) {
    return args[generator + 1];
  }
  return args.includes('--fuzz') || args.includes('--fuzz-on') ? 'fuzz' : 'session';
}

/**
 * The task definition VS Code identifies a task by, and the shape a
 * `tasks.json` entry of type `rbx` takes.
 *
 * `cwd` is carried in the definition rather than recovered from the execution,
 * because the busy policy below has to read it off *any* running rbx task --
 * including one the user started from `tasks.json` -- and the definition is the
 * one part of a task VS Code hands back unchanged.
 */
export interface RbxTaskDefinition {
  readonly type: typeof TASK_TYPE;
  readonly command: RbxCommand;
  readonly cwd: string;
  readonly solutions?: readonly string[];
  /** A variant id, `""` for the canonical, or absent to resolve it. */
  readonly contest?: string;
  /**
   * The argv tail of a `stress` or `add-finding`. Part of the identity: two
   * stresses with different finders are different tasks, and a definition
   * that dropped the finder would let VS Code mistake one for the other.
   */
  readonly args?: readonly string[];
}

export function taskDefinition(invocation: Invocation): RbxTaskDefinition {
  const contest = invocation.contest;
  return {
    type: TASK_TYPE,
    command: invocation.command,
    cwd: invocation.cwd,
    ...(invocation.solutions.length === 0 ? {} : { solutions: [...invocation.solutions] }),
    ...(invocation.args === undefined || invocation.args.length === 0
      ? {}
      : { args: [...invocation.args] }),
    ...(contest.kind === 'variant'
      ? { contest: contest.id }
      : contest.kind === 'canonical'
        ? { contest: '' }
        : {}),
  };
}

/** The selection a definition pins, or undefined when it leaves it open. */
export function definedContest(contest: unknown): ContestSelection | undefined {
  if (typeof contest !== 'string') {
    return undefined;
  }
  return contest === '' ? { kind: 'canonical' } : { kind: 'variant', id: contest };
}

/**
 * Whether `a` is `b` or an ancestor of it.
 *
 * By path segments, not by string prefix: `/c/A` must not contain `/c/AB`.
 */
function containsPath(a: string, b: string): boolean {
  const relative = path.relative(a, b);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

/**
 * Whether two rbx commands, running in these two directories, would step on
 * each other.
 *
 * **The busy policy's whole rule.** Two commands collide when either runs where
 * the other does or above it:
 *
 * - The same package, *whatever* the two commands are. VS Code's own "task is
 *   already active" guard only catches an *identical* task, so it would let
 *   `rbx build` start while `rbx run sols/a.cpp` is still going. A second run
 *   begins by writing a fresh skeleton (which clears `.rbx/runs/report.yml`),
 *   wiping the report the first is still writing; a build regenerates the very
 *   tests the run is reading. The cache would survive -- rbx takes a shared
 *   session lock (rbx/box/global_package.py) -- but the results would not.
 * - A contest command and any package under that contest: `contest each run`
 *   will reach the package sooner or later and collide there, just later.
 *
 * Two different packages never collide; they may run side by side.
 */
export function collides(cwdA: string, cwdB: string): boolean {
  const a = path.resolve(cwdA);
  const b = path.resolve(cwdB);
  return containsPath(a, b) || containsPath(b, a);
}

/** The running tasks a new dispatch in `cwd` would collide with. */
export function collisions<T extends { readonly cwd: string }>(
  running: readonly T[],
  cwd: string,
): T[] {
  return running.filter((task) => collides(task.cwd, cwd));
}

/**
 * Reads `rbx.run.extraArgs`, dropping anything that is not a non-empty string.
 *
 * An array rather than one string to split, so an argument with a space in it
 * means what it says and the extension never has to guess at shell quoting.
 */
export function asExtraArgs(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === 'string' && item !== '');
}
