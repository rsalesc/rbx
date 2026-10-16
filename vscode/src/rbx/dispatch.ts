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
 * it (stressSpec.ts), and this module only puts the subcommand in front. So do
 * `irun` and `promote` (`rbx testcases promote`), which the testplan lens
 * builds (testplan.ts).
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
  | 'add-finding'
  | 'irun'
  | 'promote';

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
  'irun',
  'promote',
];

/**
 * The commands whose whole argv tail arrives in `Invocation.args`: only these
 * are handed it, and only these have it shell-quoted, since a finder, a
 * generator call or a glob is full of what a shell reads as syntax.
 */
export const ARGV_COMMANDS: readonly RbxCommand[] = ['stress', 'add-finding', 'irun', 'promote'];

export function carriesArgs(command: RbxCommand): boolean {
  return ARGV_COMMANDS.includes(command);
}

/**
 * The commands *Rerun* must not repeat: each acts once on something that is
 * gone afterwards. An `add-finding` names findings of one stress session; a
 * `promote` names a testplan line it deletes, so a rerun would promote
 * whichever statement moved up into its place.
 */
export function isOneShot(command: RbxCommand): boolean {
  return command === 'add-finding' || command === 'promote';
}

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
   * Run past testcases that fail validation (`--on-invalid=warn`), for the
   * commands `takesOnInvalid` names.
   *
   * At a terminal an invalid testcase aborting the run is the right call: the
   * setter is right there to fix it. A run started from the editor has no such
   * loop, so it goes on and the Run view flags the invalid testcases instead.
   * Set only when the resolved rbx takes the flag, decided at dispatch time.
   */
  readonly warnOnInvalid?: boolean;
  /**
   * For `stress` and `add-finding`: everything after the subcommand, built by
   * whoever asked. Ignored by every other command.
   */
  readonly args?: readonly string[];
  /**
   * Root options, typed before the subcommand: `-cp`, which keeps an
   * interactive run's transcript, is one (rbx/box/cli/__init__.py), and is
   * spelled nowhere else.
   */
  readonly rootArgs?: readonly string[];
  readonly contest: ContestSelection;
}

/**
 * The argv after the executable.
 *
 * `-C` goes first because it is a root option (rbx/box/cli/__init__.py), so it
 * is the one spelling every subcommand accepts. Extra args come before the
 * solutions, which is where a user typing the command would put them -- the
 * terminal shows this exact line, so it should read like one they would type.
 *
 * Statement builds pass `--no-validate`: they only refresh the preview, so the
 * samples are built without running the validators over them. A sample that
 * breaks its constraints is still caught by `rbx build`. They also pass
 * `--incremental`, which keeps the last build's LaTeX auxiliary files, so a
 * rebuild of an unchanged document needs one pdflatex pass, not two; `rbx st b`
 * in a terminal still starts clean.
 */
export function rbxArgs(invocation: Invocation): string[] {
  const args: string[] = [];
  if (invocation.contest.kind === 'variant') {
    args.push('-C', invocation.contest.id);
  }
  args.push(...(invocation.rootArgs ?? []));
  switch (invocation.command) {
    case 'build':
      args.push('build');
      break;
    case 'run':
      args.push(
        'run',
        ...onInvalidArgs(invocation),
        ...invocation.extraArgs,
        ...invocation.solutions,
      );
      break;
    case 'contest-run':
      args.push(
        'contest',
        'each',
        '--inline',
        'run',
        ...onInvalidArgs(invocation),
        ...invocation.extraArgs,
      );
      break;
    case 'statements':
      args.push('statements', 'build', '--no-validate', '--incremental');
      break;
    case 'contest-statements':
      args.push('contest', 'statements', 'build', '--no-validate', '--incremental');
      break;
    case 'tutorials':
      args.push('tutorials', 'build', '--no-validate', '--incremental');
      break;
    case 'contest-tutorials':
      args.push('contest', 'tutorials', 'build', '--no-validate', '--incremental');
      break;
    case 'stress':
      args.push('stress', ...(invocation.args ?? []));
      break;
    case 'add-finding':
      args.push('testcases', 'add-finding', ...(invocation.args ?? []));
      break;
    case 'irun':
      args.push('irun', ...onInvalidArgs(invocation), ...(invocation.args ?? []));
      break;
    case 'promote':
      args.push('testcases', 'promote', ...(invocation.args ?? []));
      break;
  }
  return args;
}

/** The flag that lets a run go on past testcases that fail validation. */
export const ON_INVALID_FLAG = '--on-invalid';

/** The commands that validate testcases before running solutions on them. */
export function takesOnInvalid(command: RbxCommand): boolean {
  return command === 'run' || command === 'contest-run' || command === 'irun';
}

/**
 * Ahead of `rbx.run.extraArgs`, so a user who wants the terminal's behaviour
 * back can put `--on-invalid=fail` there: the last occurrence of an option wins.
 */
function onInvalidArgs(invocation: Invocation): string[] {
  return invocation.warnOnInvalid === true && takesOnInvalid(invocation.command)
    ? [`${ON_INVALID_FLAG}=warn`]
    : [];
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
              : invocation.command === 'irun'
                ? `run on ${testSubject(invocation.args ?? [])}`
                : invocation.command === 'promote'
                  ? `promote ${testSubject(invocation.args ?? [])}`
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
 * Which test an `irun` or `promote` is about, for its name: the `-t` value of
 * an irun, the first positional argument of a promote.
 */
function testSubject(args: readonly string[]): string {
  const flag = args.indexOf('-t');
  if (flag >= 0 && flag + 1 < args.length) {
    return args[flag + 1];
  }
  // An irun on a generator call or on typed input (irun.ts), whose positional
  // arguments are solutions rather than a test.
  const generator = args.indexOf('-g');
  if (generator >= 0 && generator + 1 < args.length) {
    return args[generator + 1];
  }
  if (args.includes('--input')) {
    return 'typed input';
  }
  return args.find((arg) => !arg.startsWith('-')) ?? 'tests';
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
  /** Root options before the subcommand; part of the identity for the same reason. */
  readonly rootArgs?: readonly string[];
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
    ...(invocation.rootArgs === undefined || invocation.rootArgs.length === 0
      ? {}
      : { rootArgs: [...invocation.rootArgs] }),
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

/**
 * The running tasks that are `command` in exactly `root`.
 *
 * Exactly, unlike `collides`: this answers "is *that* stress still going", not
 * "would something be in the way", so a contest command above the package or
 * a run in it is not an answer. `command` is whatever the task's definition
 * holds, which for a task VS Code restored on its own is not checked by anyone.
 */
export function runningAt<T extends { readonly cwd: string; readonly command: unknown }>(
  running: readonly T[],
  root: string,
  command: RbxCommand,
): T[] {
  const target = path.resolve(root);
  return running.filter((task) => task.command === command && path.resolve(task.cwd) === target);
}

// Kept apart, in a module with no Node imports, so the stress launcher's
// webview can quote its command preview exactly as the terminal is sent it.
export { needsShellQuoting } from './shellQuote';

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
