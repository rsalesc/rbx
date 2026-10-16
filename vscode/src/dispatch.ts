/**
 * Dispatching `rbx build` / `rbx run` to a visible terminal (#906).
 *
 * Design D3, as amended: the extension may *dispatch* rbx commands, as VS Code
 * tasks, to a terminal the user can see and interrupt; it never runs them
 * headless and never parses their output. Everything the views show still comes
 * from the artifacts on disk, and the watchers in extension.ts follow a
 * dispatched run exactly as they follow one typed by hand.
 *
 * ## The busy policy
 *
 * The one rule this file exists to keep: **a dispatch never interleaves with an
 * rbx command already running where it would run** -- the same package, or a
 * contest command above it (`collides` in rbx/dispatch.ts says why that is the
 * line). It is kept in two layers, because tasks can start from places this
 * file does not see:
 *
 * 1. **Before.** Every entry point the extension contributes -- the lens, the
 *    editor button, the view buttons, the palette -- goes through `dispatch`,
 *    which runs one request at a time (`serial`), and asks before anything is
 *    stopped. Two quick clicks cannot both pass the check, because the second
 *    waits for the first to have started its task.
 * 2. **After.** VS Code can start one of these tasks on its own -- *Rerun
 *    Last Task* re-executes the last task as it was, without asking anyone.
 *    That never passes through here first, so `onDidStartTask` checks every rbx
 *    task that starts without this file's approval and, if it collides, stops
 *    it at once and says why. rbx spends its first moments importing before it
 *    writes anything, so in practice the task is gone before it touches the run
 *    it collided with -- a race this wins by a wide margin, not a guarantee.
 *
 * There is no task provider, so `tasks.json` cannot declare an rbx task: the
 * commands are the bindable surface, and every one of them passes layer 1.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { ActiveProblem } from './activeProblem';
import { findContestRoot, readContestFiles } from './contestIndex';
import { DeclaredIndex } from './declared';
import { log } from './log';
import {
  ContestCandidate,
  contestCandidates,
  rememberedCandidate,
} from './rbx/contest';
import {
  ContestSelection,
  Invocation,
  NO_CONTEST,
  RbxCommand,
  TASK_TYPE,
  asExtraArgs,
  carriesArgs,
  collisions,
  isOneShot,
  needsShellQuoting,
  rbxArgs,
  rbxEnv,
  runningAt,
  scopeOf,
  taskDefinition,
  taskName,
  takesOnInvalid,
} from './rbx/dispatch';
import { invalidTestsMessage } from './rbx/invalidTests';
import { packageLayout, skeletonPath } from './rbx/layout';
import { parseSkeleton } from './rbx/model';
import { SolutionNode } from './rbx/nodes';
import { readYamlFile } from './rbx/store';
import { resolveRbx, supportsOnInvalid } from './rbxProcess';
import type { RunViewProvider } from './runView';

const ENABLED_SETTING = 'rbx.dispatch.enabled';
const EXTRA_ARGS_SETTING = 'rbx.run.extraArgs';

/** The remembered contest for a contest root (`''` is the canonical). */
const CONTEST_KEY_PREFIX = 'rbx.dispatch.contest:';

/** How long a stopped task may take to go away before the dispatch gives up. */
const STOP_TIMEOUT_MS = 10_000;

/** What a caller asks for, before the contest and the executable are resolved. */
export interface DispatchRequest {
  readonly command: RbxCommand;
  /** The package root, for both scopes: a contest command finds its root from it. */
  readonly root: string;
  readonly solutions?: readonly string[];
  /**
   * The argv tail of a `stress` or `add-finding`, as stressSpec.ts (or the
   * Stress view) built it. Passed through untouched; ignored by every other
   * command, as `rbx.run.extraArgs` is by everything but a run.
   */
  readonly args?: readonly string[];
  /** Root options, before the subcommand: `-cp` for an interactive `irun`. */
  readonly rootArgs?: readonly string[];
  /**
   * Never ask or alert: skip, and say so in the log, wherever a dispatch would
   * otherwise prompt -- something already running there, a contest to choose,
   * no rbx found. For dispatches the user did not click: a build on save must
   * never put a modal in front of someone who is typing.
   */
  readonly quiet?: boolean;
}

/** An rbx task VS Code reports as running, and where it runs. */
interface Running {
  readonly execution: vscode.TaskExecution;
  readonly cwd: string;
  /** The definition's `command`, unchecked: a restored task may hold anything. */
  readonly command: unknown;
}

export function dispatchEnabled(): boolean {
  return vscode.workspace.getConfiguration().get<boolean>(ENABLED_SETTING, true);
}

/**
 * Where a task runs.
 *
 * Read off the execution first, which is what actually decides the directory;
 * the definition's own `cwd` is the fallback for an execution that has none.
 */
function cwdOf(task: vscode.Task): string | undefined {
  const execution = task.execution;
  if (execution instanceof vscode.ShellExecution || execution instanceof vscode.ProcessExecution) {
    const cwd = execution.options?.cwd;
    if (cwd !== undefined) {
      return cwd;
    }
  }
  const defined = (task.definition as { cwd?: unknown }).cwd;
  return typeof defined === 'string' ? defined : undefined;
}

/** Every running rbx task, with where it runs. */
function runningRbxTasks(): Running[] {
  const running: Running[] = [];
  for (const execution of vscode.tasks.taskExecutions) {
    if (execution.task.definition.type !== TASK_TYPE) {
      continue;
    }
    const cwd = cwdOf(execution.task);
    if (cwd !== undefined) {
      running.push({ execution, cwd, command: execution.task.definition.command });
    }
  }
  return running;
}

/** A stable key for a task, for matching an approval to the start it caused. */
function approvalKey(task: vscode.Task): string {
  return JSON.stringify([task.definition, task.name]);
}

export class Dispatcher implements vscode.Disposable {
  private readonly disposables: vscode.Disposable[] = [];
  private readonly status: vscode.StatusBarItem;
  /** Requests run one at a time; see the busy policy above. */
  private serial: Promise<unknown> = Promise.resolve();
  /** Starts this file approved and has not yet seen `onDidStartTask` for. */
  private readonly approved = new Map<string, number>();
  private last?: Invocation;
  private readonly contestChanged = new vscode.EventEmitter<string>();
  /** Fired with the contest root whose remembered variant just changed. */
  readonly onDidChangeContest: vscode.Event<string> = this.contestChanged.event;

  constructor(
    private readonly memento: vscode.Memento,
    private readonly active: ActiveProblem,
  ) {
    this.status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
    this.status.command = 'rbx.changeContest';
    this.disposables.push(
      this.status,
      vscode.tasks.onDidStartTask((event) => void this.guard(event.execution)),
      vscode.tasks.onDidEndTaskProcess((event) => void this.reportInvalidTests(event.execution)),
      active.onDidChange(() => void this.refreshStatus()),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration(ENABLED_SETTING)) {
          void this.refreshStatus();
        }
      }),
    );
    void vscode.commands.executeCommand('setContext', 'rbx.canRerun', false);
  }

  /**
   * Say so when a dispatched run went ahead past invalid testcases.
   *
   * On the task's end rather than off the Run view's watcher, so it is said
   * once per run, and only for runs the extension itself started with
   * `--on-invalid=warn` -- the skeleton of one typed at a terminal is none of
   * this notification's business. Problem runs only: a contest run walks many
   * packages, and each one's Run view carries its own notice.
   */
  private async reportInvalidTests(execution: vscode.TaskExecution): Promise<void> {
    const definition = execution.task.definition;
    if (definition.type !== TASK_TYPE || typeof definition.cwd !== 'string') {
      return;
    }
    if (definition.command !== 'run' && definition.command !== 'irun') {
      return;
    }
    const raw = await readYamlFile(
      skeletonPath(packageLayout(definition.cwd), definition.command === 'irun' ? 'irun' : 'run'),
    );
    const message = invalidTestsMessage(parseSkeleton(raw)?.validation);
    if (message === undefined) {
      return;
    }
    const showRun = 'Show Run View';
    const showTests = 'Show Tests View';
    const choice = await vscode.window.showWarningMessage(message, showRun, showTests);
    if (choice === showRun) {
      void vscode.commands.executeCommand('rbx.run.focus');
    } else if (choice === showTests) {
      void vscode.commands.executeCommand('rbx.testset.focus');
    }
  }

  /** Dispatch one command, after every request ahead of it has settled. */
  dispatch(request: DispatchRequest): Promise<void> {
    return this.enqueue(() => this.dispatchNow(request));
  }

  /** Dispatch the last command again, under the same contest. */
  rerun(): Promise<void> {
    return this.enqueue(async () => {
      if (this.last === undefined) {
        void vscode.window.showInformationMessage('rbx: nothing has been dispatched yet.');
        return;
      }
      await this.execute(this.last);
    });
  }

  /** Forget and re-ask the contest for the selected problem's contest root. */
  async changeContest(): Promise<void> {
    const root = this.active.selected();
    const contestRoot = root === undefined ? undefined : await findContestRoot(root);
    if (root === undefined || contestRoot === undefined) {
      void vscode.window.showInformationMessage('rbx: the selected problem is in no contest.');
      return;
    }
    // Problem scope first: those are the candidates a run of this problem would
    // offer. A problem no contest names falls back to the whole contest's list.
    const files = await readContestFiles(contestRoot);
    let candidates = contestCandidates('problem', contestRoot, files, root);
    if (candidates.length === 0) {
      candidates = contestCandidates('contest', contestRoot, files);
    }
    if (candidates.length < 2) {
      void vscode.window.showInformationMessage(
        'rbx: this problem belongs to one contest only, so there is nothing to choose.',
      );
      return;
    }
    const picked = await this.pick(candidates, contestRoot);
    if (picked !== undefined) {
      await this.remember(contestRoot, picked);
    }
    await this.refreshStatus();
  }

  /**
   * The variant remembered for `contestRoot` -- `undefined` when none was
   * chosen, `''` for the canonical contest.rbx.yml, else the variant id.
   */
  rememberedVariant(contestRoot: string): string | undefined {
    return this.memento.get<string>(CONTEST_KEY_PREFIX + contestRoot);
  }

  /** The contest-wide candidates of `contestRoot`, canonical first. */
  async contestChoices(contestRoot: string): Promise<ContestCandidate[]> {
    return contestCandidates('contest', contestRoot, await readContestFiles(contestRoot));
  }

  /** Ask which contest of `contestRoot` to use, and remember it. */
  async chooseContest(contestRoot: string): Promise<void> {
    const candidates = await this.contestChoices(contestRoot);
    if (candidates.length < 2) {
      void vscode.window.showInformationMessage('rbx: this directory holds one contest only.');
      return;
    }
    const picked = await this.pick(candidates, contestRoot);
    if (picked !== undefined) {
      await this.remember(contestRoot, picked);
    }
    await this.refreshStatus();
  }

  private enqueue(work: () => Promise<void>): Promise<void> {
    const next = this.serial.then(work, work);
    // A failed request must not wedge the ones behind it.
    this.serial = next.catch((error) => log(`rbx dispatch failed: ${String(error)}`));
    return next;
  }

  private async dispatchNow(request: DispatchRequest): Promise<void> {
    if (!dispatchEnabled()) {
      return;
    }
    const scope = scopeOf(request.command);
    const contestRoot = await findContestRoot(request.root);
    if (scope === 'contest' && contestRoot === undefined) {
      void vscode.window.showInformationMessage(
        'rbx: this problem is in no contest, so there are no problems to run alongside it.',
      );
      return;
    }
    const contest = await this.resolveContest(request, contestRoot);
    if (contest === undefined) {
      return; // The user dismissed the picker, or a quiet request would have needed it.
    }
    const invocation: Invocation = {
      command: request.command,
      cwd: scope === 'contest' && contestRoot !== undefined ? contestRoot : request.root,
      solutions: request.solutions ?? [],
      extraArgs:
        request.command !== 'run' && request.command !== 'contest-run'
          ? []
          : asExtraArgs(
              vscode.workspace
                .getConfiguration(undefined, vscode.Uri.file(request.root))
                .get(EXTRA_ARGS_SETTING),
            ),
      // Only where it means something, so no other command's task identity
      // (its definition) changes because a caller passed args it ignores.
      ...(request.args !== undefined && carriesArgs(request.command)
        ? { args: request.args }
        : {}),
      ...(request.rootArgs === undefined || request.rootArgs.length === 0
        ? {}
        : { rootArgs: request.rootArgs }),
      contest,
    };
    if ((await this.execute(invocation, request.quiet)) && scope === 'problem') {
      // The user acted on this problem, so the views should be showing it; the
      // skeleton watcher would get there for a run, but a build writes none.
      this.active.select(request.root);
    }
  }

  /**
   * The contest a request runs under, or undefined if the user backed out.
   *
   * Zero candidates passes nothing; one is used without asking; more uses the
   * choice remembered for this contest root, and asks only when there is none
   * or it no longer applies.
   */
  private async resolveContest(
    request: DispatchRequest,
    contestRoot: string | undefined,
  ): Promise<ContestSelection | undefined> {
    if (contestRoot === undefined) {
      return NO_CONTEST;
    }
    const files = await readContestFiles(contestRoot);
    const candidates = contestCandidates(
      scopeOf(request.command),
      contestRoot,
      files,
      request.root,
    );
    if (candidates.length === 0) {
      return NO_CONTEST;
    }
    if (candidates.length === 1) {
      return selectionOf(candidates[0]);
    }
    const remembered = rememberedCandidate(
      candidates,
      this.memento.get<string>(CONTEST_KEY_PREFIX + contestRoot),
    );
    if (remembered !== undefined) {
      return selectionOf(remembered);
    }
    if (request.quiet) {
      log(`Skipped a ${request.command} in ${request.root}: no contest chosen yet to run it under.`);
      return undefined;
    }
    const picked = await this.pick(candidates, contestRoot);
    if (picked === undefined) {
      return undefined;
    }
    await this.remember(contestRoot, picked);
    void this.refreshStatus();
    return selectionOf(picked);
  }

  private async pick(
    candidates: readonly ContestCandidate[],
    contestRoot: string,
  ): Promise<ContestCandidate | undefined> {
    const remembered = this.memento.get<string>(CONTEST_KEY_PREFIX + contestRoot);
    const items = candidates.map((candidate) => ({
      label: candidate.variantId ?? 'default contest',
      description: [
        candidate.variantId === undefined ? 'contest.rbx.yml' : `contest.${candidate.variantId}.rbx.yml`,
        candidate.shortName === undefined ? undefined : `problem ${candidate.shortName}`,
        (candidate.variantId ?? '') === remembered ? 'current' : undefined,
      ]
        .filter((part) => part !== undefined)
        .join(' · '),
      candidate,
    }));
    const picked = await vscode.window.showQuickPick(items, {
      placeHolder: `Run under which contest of ${path.basename(contestRoot)}? (remembered for this contest)`,
    });
    return picked?.candidate;
  }

  private async remember(contestRoot: string, candidate: ContestCandidate): Promise<void> {
    await this.memento.update(CONTEST_KEY_PREFIX + contestRoot, candidate.variantId ?? '');
    this.contestChanged.fire(contestRoot);
  }

  /** Start the task; false when nothing was started. */
  private async execute(invocation: Invocation, quiet = false): Promise<boolean> {
    const executable = await resolveRbx(invocation.cwd);
    if (executable === undefined && quiet) {
      log(`Skipped "${taskName(invocation)}": no rbx executable found.`);
      return false;
    }
    if (executable === undefined) {
      const open = 'Open Settings';
      const choice = await vscode.window.showErrorMessage(
        'rbx: could not find the rbx executable. Set `rbx.executable` to its full path.',
        open,
      );
      if (choice === open) {
        void vscode.commands.executeCommand('workbench.action.openSettings', 'rbx.executable');
      }
      return false;
    }
    if (takesOnInvalid(invocation.command)) {
      invocation = {
        ...invocation,
        warnOnInvalid: await supportsOnInvalid(executable, invocation.cwd),
      };
    }
    if (!(await this.clearTheWay(invocation, quiet))) {
      return false;
    }
    const task = this.task(invocation, executable);
    const key = approvalKey(task);
    this.approved.set(key, (this.approved.get(key) ?? 0) + 1);
    log(`Dispatching \`${[executable, ...rbxArgs(invocation)].join(' ')}\` in ${invocation.cwd}.`);
    try {
      await vscode.tasks.executeTask(task);
    } catch (error) {
      this.release(key);
      throw error;
    }
    // Not a one-shot (`add-finding`, `promote`): Rerun is a button pressed
    // without looking at what it reruns, and by then what the first run acted
    // on is gone -- another stress session's finding 1, or the testplan line
    // the promote deleted.
    if (!isOneShot(invocation.command)) {
      this.last = invocation;
      void vscode.commands.executeCommand('setContext', 'rbx.canRerun', true);
    }
    return true;
  }

  /**
   * Whether an rbx task running `command` in exactly `root` is alive.
   *
   * The fallback for a stress manifest that reads `running` but cannot be
   * checked directly -- `stressLiveness` says `unknown` when it names no pid,
   * or another host's. Any such task counts, including one VS Code started on
   * its own (*Rerun Last Task*), since the definition is what it reads; a
   * stress typed into a terminal by hand is not a task, and so is not seen.
   */
  isRunning(root: string, command: RbxCommand): boolean {
    return matching(root, command).length > 0;
  }

  /**
   * Stop every rbx task running `command` in `root`, and wait for it to go.
   *
   * `terminate()` closes the task's terminal, whose process gets a SIGHUP. On
   * SIGHUP or SIGTERM rbx stamps the stress manifest `interrupted` and exits at
   * once -- unlike Ctrl-C, it does not let the current iteration finish -- so
   * nothing here touches the artifacts. Resolves once the tasks have ended, or after the same timeout a
   * dispatch waits for; the views follow the manifest either way.
   *
   * Queued behind any dispatch in flight, like every request here, so a Stop
   * pressed right after a Run cannot look for the task before it has started.
   */
  stop(root: string, command: RbxCommand): Promise<void> {
    return this.enqueue(async () => {
      const running = matching(root, command);
      if (running.length === 0) {
        return;
      }
      for (const task of running) {
        task.execution.terminate();
      }
      const stopped = await waitFor(() => matching(root, command).length === 0, STOP_TIMEOUT_MS);
      if (!stopped) {
        log(`${command} in ${root} did not stop within ${STOP_TIMEOUT_MS / 1000}s.`);
      }
    });
  }

  private task(invocation: Invocation, executable: string): vscode.Task {
    const env = rbxEnv(invocation.contest);
    const task = new vscode.Task(
      taskDefinition(invocation),
      vscode.TaskScope.Workspace,
      taskName(invocation),
      'rbx',
      // An argv, not a command line: VS Code quotes each argument for whatever
      // shell the terminal runs, so a path with a space stays one argument.
      new vscode.ShellExecution(executable, shellArgs(invocation), {
        cwd: invocation.cwd,
        ...(env === undefined ? {} : { env }),
      }),
      // No problem matchers: the extension never reads the terminal.
      [],
    );
    task.presentationOptions = {
      reveal: vscode.TaskRevealKind.Always,
      // A terminal per task, so a contest run and a package run each keep their
      // own scrollback and their own Ctrl-C.
      panel: vscode.TaskPanelKind.Dedicated,
      clear: true,
      focus: false,
      showReuseMessage: false,
    };
    return task;
  }

  /**
   * The before half of the busy policy: true when nothing is in the way, or
   * when the user chose to stop what was and it has gone.
   */
  private async clearTheWay(invocation: Invocation, quiet: boolean): Promise<boolean> {
    const blocking = collisions(runningRbxTasks(), invocation.cwd);
    if (blocking.length === 0) {
      return true;
    }
    const names = blocking.map((running) => `"${running.execution.task.name}"`).join(', ');
    if (quiet) {
      log(`Skipped "${taskName(invocation)}" in ${invocation.cwd}: ${names} is running there.`);
      return false;
    }
    const stop = 'Stop and Run';
    const choice = await vscode.window.showWarningMessage(
      `rbx is already running ${names} here.`,
      {
        modal: true,
        detail:
          `Starting "${taskName(invocation)}" alongside it would overwrite the results it is ` +
          'still writing. Stop it and run, or cancel and let it finish.',
      },
      stop,
    );
    if (choice !== stop) {
      return false;
    }
    for (const running of blocking) {
      running.execution.terminate();
    }
    const cleared = await waitFor(
      () => collisions(runningRbxTasks(), invocation.cwd).length === 0,
      STOP_TIMEOUT_MS,
    );
    if (!cleared) {
      void vscode.window.showErrorMessage(
        `rbx: ${names} did not stop within ${STOP_TIMEOUT_MS / 1000}s, so nothing was started.`,
      );
    }
    return cleared;
  }

  /** The after half of the busy policy; see the file header. */
  private guard(execution: vscode.TaskExecution): void {
    const task = execution.task;
    if (task.definition.type !== TASK_TYPE) {
      return;
    }
    if (this.release(approvalKey(task))) {
      return;
    }
    const cwd = cwdOf(task);
    if (cwd === undefined) {
      return;
    }
    const blocking = collisions(othersThan(execution, runningRbxTasks()), cwd);
    if (blocking.length === 0) {
      return;
    }
    execution.terminate();
    const names = blocking.map((running) => `"${running.execution.task.name}"`).join(', ');
    log(`Stopped "${task.name}" in ${cwd}: ${names} was already running there.`);
    void vscode.window.showWarningMessage(
      `rbx: stopped "${task.name}", because ${names} is still running where it would run. ` +
        'Run it again once that finishes, or stop it first.',
    );
  }

  /** Consume one approval for `key`; false when there was none. */
  private release(key: string): boolean {
    const count = this.approved.get(key) ?? 0;
    if (count === 0) {
      return false;
    }
    if (count === 1) {
      this.approved.delete(key);
    } else {
      this.approved.set(key, count - 1);
    }
    return true;
  }

  /**
   * The status-bar item: shown only while the selected problem has more than
   * one contest to run under, naming the one dispatches will use.
   */
  async refreshStatus(): Promise<void> {
    const root = this.active.selected();
    const contestRoot =
      root === undefined || !dispatchEnabled() ? undefined : await findContestRoot(root);
    void vscode.commands.executeCommand(
      'setContext',
      'rbx.activeInContest',
      contestRoot !== undefined,
    );
    if (root === undefined || contestRoot === undefined) {
      this.status.hide();
      return;
    }
    const candidates = contestCandidates(
      'problem',
      contestRoot,
      await readContestFiles(contestRoot),
      root,
    );
    if (candidates.length < 2) {
      this.status.hide();
      return;
    }
    const remembered = rememberedCandidate(
      candidates,
      this.memento.get<string>(CONTEST_KEY_PREFIX + contestRoot),
    );
    this.status.text =
      remembered === undefined
        ? '$(trophy) choose contest'
        : `$(trophy) ${remembered.variantId ?? 'default contest'}`;
    this.status.tooltip = 'The contest rbx commands dispatched from VS Code run under. Click to change.';
    this.status.show();
  }

  dispose(): void {
    this.disposables.forEach((disposable) => disposable.dispose());
    this.contestChanged.dispose();
  }
}

/** The running rbx tasks for `command` whose directory is exactly `root`. */
function matching(root: string, command: RbxCommand): Running[] {
  return runningAt(runningRbxTasks(), root, command);
}

/**
 * The argv as the terminal gets it.
 *
 * A `stress` or `add-finding` carries finders and generator calls, full of
 * what a shell reads as syntax (`[`, `|`, `&`, `!`, `$`, `"`, `@`), which
 * VS Code's quoting of a plain string does not protect (`needsShellQuoting`).
 * Those arguments go strongly quoted -- never `Escape`, whose escaping differs
 * per shell -- and `validateLaunch` has refused the single quote that cannot
 * be. Every other command keeps plain strings: its arguments are solution
 * paths and flags, and its terminal line stays as it always read.
 */
function shellArgs(invocation: Invocation): (string | vscode.ShellQuotedString)[] {
  const args = rbxArgs(invocation);
  if (!carriesArgs(invocation.command)) {
    return args;
  }
  return args.map((arg) =>
    needsShellQuoting(arg) ? { value: arg, quoting: vscode.ShellQuoting.Strong } : arg,
  );
}

/**
 * The running tasks other than `execution` itself.
 *
 * By identity first. Should VS Code ever hand `onDidStartTask` a different
 * wrapper than `taskExecutions` holds, nothing would be filtered out and the
 * task would collide with itself -- so the fallback drops one entry with the
 * same key, which is the same task as far as the policy can tell.
 */
function othersThan(execution: vscode.TaskExecution, running: readonly Running[]): Running[] {
  const others = running.filter((entry) => entry.execution !== execution);
  if (others.length < running.length) {
    return others;
  }
  const key = approvalKey(execution.task);
  const self = running.findIndex((entry) => approvalKey(entry.execution.task) === key);
  return self < 0 ? others : running.filter((_, index) => index !== self);
}

function selectionOf(candidate: ContestCandidate): ContestSelection {
  return candidate.variantId === undefined
    ? { kind: 'canonical' }
    : { kind: 'variant', id: candidate.variantId };
}

/** Resolves true once `done()` holds, rechecked whenever a task ends. */
function waitFor(done: () => boolean, timeoutMs: number): Promise<boolean> {
  if (done()) {
    return Promise.resolve(true);
  }
  return new Promise((resolve) => {
    const finish = (value: boolean) => {
      clearTimeout(timer);
      subscription.dispose();
      resolve(value);
    };
    const subscription = vscode.tasks.onDidEndTask(() => {
      if (done()) {
        finish(true);
      }
    });
    const timer = setTimeout(() => finish(done()), timeoutMs);
  });
}

/**
 * The solution a command was invoked on, from whichever place invoked it.
 *
 * - The lens and the editor button pass the file's `Uri`.
 * - A Run view row's context menu passes its `data-vscode-context`, which
 *   carries only the row id.
 * - The palette passes nothing, so the active editor is the answer.
 */
function solutionTarget(
  arg: unknown,
  declared: DeclaredIndex,
  view: RunViewProvider,
): { root: string; solution: string } | undefined {
  if (typeof arg === 'object' && arg !== null && 'rbxNodeId' in arg) {
    const id = (arg as { rbxNodeId?: unknown }).rbxNodeId;
    const node = typeof id === 'string' ? view.nodeById(id) : undefined;
    return node?.kind === 'solution' ? fromNode(node) : undefined;
  }
  if (typeof arg === 'object' && arg !== null && 'kind' in arg) {
    const node = arg as SolutionNode;
    return node.kind === 'solution' ? fromNode(node) : undefined;
  }
  const uri = arg instanceof vscode.Uri ? arg : vscode.window.activeTextEditor?.document.uri;
  const declaration = uri === undefined ? undefined : declared.declarationFor(uri);
  if (declaration === undefined || declaration.asset.role !== 'solution') {
    return undefined;
  }
  return { root: declaration.root, solution: declaration.asset.path };
}

function fromNode(node: SolutionNode): { root: string; solution: string } {
  return { root: node.pkg.root, solution: node.run.solution.path };
}

/**
 * Wire the dispatcher up: its commands, and the context keys the menus in
 * package.json key on.
 */
export function registerDispatch(
  context: vscode.ExtensionContext,
  active: ActiveProblem,
  declared: DeclaredIndex,
  view: RunViewProvider,
): Dispatcher {
  const dispatcher = new Dispatcher(context.workspaceState, active);
  context.subscriptions.push(dispatcher);

  const selectedRoot = (): string | undefined => {
    const root = active.selected();
    if (root === undefined) {
      void vscode.window.showInformationMessage('No rbx problem found in this workspace.');
    }
    return root;
  };

  const syncContext = () => {
    void vscode.commands.executeCommand('setContext', 'rbx.dispatchEnabled', dispatchEnabled());
    // The editor button keys on this list, since a menu `when` cannot ask the
    // index whether a file is a solution.
    void vscode.commands.executeCommand('setContext', 'rbx.solutionFiles', declared.solutionPaths());
  };
  syncContext();

  context.subscriptions.push(
    declared.onDidChange(syncContext),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(ENABLED_SETTING)) {
        syncContext();
      }
    }),
    // The Explorer's context menu passes the clicked file *and* the whole
    // selection, so several solutions picked there run as one `rbx run a b`.
    vscode.commands.registerCommand('rbx.runSolution', async (arg: unknown, selection?: unknown) => {
      const args =
        Array.isArray(selection) && selection.length > 1 ? (selection as unknown[]) : [arg];
      const targets = args.map((each) => solutionTarget(each, declared, view));
      if (targets.some((target) => target === undefined)) {
        void vscode.window.showInformationMessage(
          args.length === 1
            ? 'rbx: this file is not a solution declared in a problem.rbx.yml.'
            : 'rbx: not every selected file is a solution declared in a problem.rbx.yml.',
        );
        return;
      }
      const solutions = targets as { root: string; solution: string }[];
      const root = solutions[0].root;
      if (solutions.some((target) => target.root !== root)) {
        void vscode.window.showInformationMessage(
          'rbx: the selected solutions belong to different problems; run them one problem at a time.',
        );
        return;
      }
      // rbx reads the files from disk; running the last saved version of a
      // file the user is looking at would be a surprise.
      for (const target of solutions) {
        const absolute = path.resolve(target.root, target.solution);
        const open = vscode.workspace.textDocuments.find(
          (document) => document.uri.scheme === 'file' && document.uri.fsPath === absolute,
        );
        if (open?.isDirty) {
          await open.save();
        }
      }
      await dispatcher.dispatch({
        command: 'run',
        root,
        solutions: [...new Set(solutions.map((target) => target.solution))],
      });
    }),
    vscode.commands.registerCommand('rbx.runAll', async () => {
      const root = selectedRoot();
      if (root !== undefined) {
        await dispatcher.dispatch({ command: 'run', root });
      }
    }),
    vscode.commands.registerCommand('rbx.build', async () => {
      const root = selectedRoot();
      if (root !== undefined) {
        await dispatcher.dispatch({ command: 'build', root });
      }
    }),
    vscode.commands.registerCommand('rbx.runContest', async () => {
      const root = selectedRoot();
      if (root !== undefined) {
        await dispatcher.dispatch({ command: 'contest-run', root });
      }
    }),
    vscode.commands.registerCommand('rbx.rerun', () => dispatcher.rerun()),
    vscode.commands.registerCommand('rbx.changeContest', () => dispatcher.changeContest()),
  );
  void dispatcher.refreshStatus();
  return dispatcher;
}
