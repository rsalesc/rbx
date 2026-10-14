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
 */
export type RbxCommand = 'build' | 'run' | 'contest-run';

export const RBX_COMMANDS: readonly RbxCommand[] = ['build', 'run', 'contest-run'];

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
  return command === 'contest-run' ? 'contest' : 'problem';
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
        : invocation.solutions.length === 0
          ? 'run'
          : `run ${invocation.solutions.join(' ')}`;
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
}

export function taskDefinition(invocation: Invocation): RbxTaskDefinition {
  const contest = invocation.contest;
  return {
    type: TASK_TYPE,
    command: invocation.command,
    cwd: invocation.cwd,
    ...(invocation.solutions.length === 0 ? {} : { solutions: [...invocation.solutions] }),
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
