/**
 * The Stress view (#908, design S3), served as a webview beside Run and Tests.
 *
 * The host half: the HTML shell, the messages, and the reads that need a disk
 * or a process table. What a row says is stressViewModel.ts; how it is painted
 * is stressRender.ts. The arrangement is testsetView.ts's, for the reason that
 * file gives: three views in one container wired three ways would be three
 * things to keep in step.
 *
 * Not owned here, on purpose:
 *
 *   - `ActiveProblem`, the same instance the other two views hold, so the
 *     container never shows two problems at once.
 *   - The launcher (`rbx.stress.openLauncher`) and promotion
 *     (`rbx.stress.promote`). The view names the intent and the command
 *     answers, so neither has to know the other is a sidebar.
 *   - The task itself: Run and Stop go through the `Dispatcher`, which owns the
 *     one-task-at-a-time policy and the terminal.
 */
import * as crypto from 'crypto';
import * as vscode from 'vscode';

import { ActiveProblem } from './activeProblem';
import { Dispatcher, dispatchEnabled } from './dispatch';
import { log } from './log';
import { touchesStress } from './rbx/artifactEvents';
import { TASK_TYPE } from './rbx/dispatch';
import { Latest } from './rbx/latest';
import { PackageLayout, manifestPath, packageLayout } from './rbx/layout';
import { StressManifest } from './rbx/stress';
import { StressDeclaration, parseStressDeclarations } from './rbx/stressDeclarations';
import { compareCandidates, findingFiles, sessionOf } from './rbx/stressFindings';
import { lastLaunchKey, stressArgv } from './rbx/stressSpec';
import {
  EMPTY_STRESS_MODEL,
  StressViewModel,
  buildStressViewModel,
  declaredRunLaunch,
} from './rbx/stressViewModel';
import { readYamlFile } from './rbx/store';
import { RunDataProvider, stressLivenessHere } from './runData';
import { compareFinding, copyFindingCall, findingEntries, openFinding } from './stressCommands';

/** What stressMain.ts posts back. */
interface ClientMessage {
  readonly type?: string;
  readonly root?: string;
  readonly name?: string;
  readonly k?: number;
  /** The session the clicked row belonged to: its `startedAt`. */
  readonly session?: string;
}

/** What `rbx.stress.openLauncher` is called with. */
export interface OpenLauncherArgs {
  readonly root: string;
  /** A declared stress to pre-fill from; absent for a blank launcher. */
  readonly stress?: string;
}

/** What `rbx.stress.promote` is called with. */
export interface PromoteArgs {
  readonly root: string;
  readonly finding: number;
  /**
   * The `startedAt` of the session the row was drawn from; resolve it with
   * `StressViewProvider.sessionFor`, which refuses a replaced session.
   */
  readonly session?: string;
}

/** The context key the view title's Stop button keys on. */
const RUNNING_CONTEXT = 'rbx.stressRunning';

/**
 * How often a running session's pid is re-probed. Slow on purpose: it only
 * catches a session killed outside VS Code (a dispatched one is caught by its
 * task ending), and that can wait a few seconds to be called stale.
 */
const PROBE_MS = 5000;

function makeNonce(): string {
  return crypto.randomBytes(16).toString('base64');
}

/** Whether a task is a dispatched `rbx stress`. */
function isStressTask(task: vscode.Task): boolean {
  return task.definition.type === TASK_TYPE && task.definition.command === 'stress';
}

export class StressViewProvider implements vscode.WebviewViewProvider {
  static readonly viewType = 'rbx.stress';

  private view?: vscode.WebviewView;
  /** Overlapping posts resolve out of order; only the newest may land. */
  private readonly posts = new Latest();
  /**
   * Findings promoted this window, `root \0 startedAt \0 k` -> group.
   *
   * Keyed by the session's start so a new session's finding 1 -- a different
   * input altogether -- never inherits the badge of the last one's.
   */
  private readonly promoted = new Map<string, string>();
  /** The declarations as of the last post, for Run on a declared stress. */
  private declared: readonly StressDeclaration[] = [];
  /**
   * Where `declared` was read from, or undefined when it must be re-read.
   * problem.rbx.yml is read on a manifest event or a change of problem, not
   * on every tick of a stress session.
   */
  private declaredRoot?: string;
  /**
   * Whether a finding has two outputs to compare, `root \0 startedAt \0 k`.
   * Only for sessions that have ended: a finding's files never change after
   * that, while a running `--slowest` session may still renumber them.
   */
  private readonly comparable = new Map<string, boolean>();
  private probe?: ReturnType<typeof setTimeout>;

  constructor(
    private readonly data: RunDataProvider,
    private readonly active: ActiveProblem,
    private readonly dispatcher: Dispatcher,
    private readonly memento: vscode.Memento,
    private readonly extensionUri: vscode.Uri,
  ) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'dist')],
    };
    view.webview.html = this.html(view.webview);
    view.webview.onDidReceiveMessage((message: ClientMessage) => void this.receive(message));

    // No `retainContextWhenHidden`, as with the other two views: the host
    // re-posts the whole model, and the client keeps nothing worth paying for.
    const onTask = (task: vscode.Task) => {
      // A dispatched stress starting or ending flips the session between live
      // and stale before the manifest says anything -- and a killed rbx never
      // will.
      if (isStressTask(task)) {
        void this.post();
      }
    };
    const subscriptions = [
      this.data.onDidChange((change) => {
        // The session moved, or problem.rbx.yml did: the declared stresses are
        // read from it, and an edit reaches the store as a `manifest` event.
        // No plan at all is a rediscovery, which may have moved either.
        const manifestMoved = change.plan === undefined || change.plan.manifest;
        if (manifestMoved) {
          this.declaredRoot = undefined;
        }
        if (touchesStress(change.plan) || manifestMoved) {
          void this.post();
        }
      }),
      this.active.onDidChange(() => {
        this.declaredRoot = undefined;
        void this.post();
      }),
      vscode.tasks.onDidStartTask((event) => onTask(event.execution.task)),
      vscode.tasks.onDidEndTask((event) => onTask(event.execution.task)),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration('rbx.dispatch.enabled')) {
          void this.post();
        }
      }),
    ];
    view.onDidDispose(() => {
      subscriptions.forEach((subscription) => subscription.dispose());
      this.view = undefined;
      this.reprobe(false);
      // Nothing is showing a Stop to key on, and a stale `true` would leave
      // the palette's Stop Stress offered for a session long gone.
      void vscode.commands.executeCommand('setContext', RUNNING_CONTEXT, false);
    });
  }

  /**
   * Show `group` on finding `k` of the session that started at
   * `sessionStartedAt`. For promotion, which knows where a finding went; the
   * view has no other way to learn it, since `add-finding` writes nothing
   * back into the session.
   */
  markPromoted(
    root: string,
    sessionStartedAt: string | undefined,
    k: number,
    group: string,
  ): void {
    // A session with no start cannot be told from the next one, so a badge
    // on it could land on the wrong input; better none.
    if (sessionStartedAt === undefined) {
      return;
    }
    this.promoted.set(`${root}\0${sessionStartedAt}\0${k}`, group);
    void this.post();
  }

  /**
   * The session at `root`, if it is still the one a row was drawn from
   * (`session` is that row's `startedAt`); undefined when a newer session
   * replaced it or there is none. For every action on a finding row, so each
   * refuses a stale row the same way (`findingGone`).
   */
  async sessionFor(root: string, session: string | undefined): Promise<StressManifest | undefined> {
    return sessionOf(await this.data.stress(packageLayout(root)), session);
  }

  /** Open the launcher on the selected problem, blank. The title bar's `+`. */
  newStress(): void {
    const root = this.active.selected();
    if (root === undefined) {
      void vscode.window.showInformationMessage('No rbx problem found in this workspace.');
      return;
    }
    this.openLauncher({ root });
  }

  /** Stop the selected problem's stress, if one is running. */
  async stop(): Promise<void> {
    const root = this.active.selected();
    if (root !== undefined) {
      await this.dispatcher.stop(root, 'stress');
    }
  }

  private async receive(message: ClientMessage): Promise<void> {
    if (message.type === 'ready') {
      await this.post();
      return;
    }
    if (message.type === 'select' && message.root !== undefined) {
      // No `post`: `ActiveProblem` fires its change event, subscribed above.
      this.active.select(message.root);
      return;
    }
    const root = this.active.selected();
    if (root === undefined) {
      return;
    }
    switch (message.type) {
      case 'run-declared':
        if (message.name !== undefined) {
          await this.runDeclared(root, message.name);
        }
        return;
      case 'edit-declared':
        if (message.name !== undefined) {
          this.openLauncher({ root, stress: message.name });
        }
        return;
      case 'new':
        this.openLauncher({ root });
        return;
      case 'stop':
        await this.dispatcher.stop(root, 'stress');
        return;
      case 'promote':
        if (typeof message.k === 'number') {
          const args: PromoteArgs = { root, finding: message.k, session: message.session };
          this.execute('rbx.stress.promote', args);
        }
        return;
      case 'open':
      case 'compare':
      case 'copy':
        if (typeof message.k === 'number') {
          await this.onFinding(root, message.type, message.k, message.session);
        }
        return;
    }
  }

  private async onFinding(
    root: string,
    action: 'open' | 'compare' | 'copy',
    k: number,
    session: string | undefined,
  ): Promise<void> {
    const pkg = packageLayout(root);
    // Undefined for a replaced session, which stressCommands.ts then reports
    // as gone.
    const manifest = await this.sessionFor(root, session);
    switch (action) {
      case 'open':
        return openFinding(pkg, manifest, k);
      case 'compare':
        return compareFinding(pkg, manifest, k);
      case 'copy':
        return copyFindingCall(manifest, k);
    }
  }

  /**
   * Run a declared stress: as the launcher last ran it, if it last ran this
   * one, else as declared. Remembering the budget is the point of the launcher;
   * a Run button that silently forgot it would undo that one row over.
   */
  private async runDeclared(root: string, name: string): Promise<void> {
    const { launch, declared } = declaredRunLaunch(
      name,
      this.declared,
      this.memento.get(lastLaunchKey(root)),
    );
    // `stressArgv` starts with `stress`, which the dispatcher puts in front of
    // `args` itself.
    await this.dispatcher.dispatch({
      command: 'stress',
      root,
      args: stressArgv(launch, declared).slice(1),
    });
  }

  private openLauncher(args: OpenLauncherArgs): void {
    this.execute('rbx.stress.openLauncher', args);
  }

  private execute(command: string, args: unknown): void {
    vscode.commands.executeCommand(command, args).then(undefined, (error) => {
      log(`${command} failed: ${String(error)}`);
    });
  }

  /**
   * Whether a `running` manifest still has its rbx. The manifest's own pid is
   * the answer where it can be checked; elsewhere, whether VS Code is running
   * a stress task there (`Dispatcher.isRunning`).
   */
  private alive(root: string, manifest: StressManifest): { alive: boolean; probed: boolean } {
    switch (stressLivenessHere(manifest)) {
      case 'live':
        return { alive: true, probed: manifest.state === 'running' };
      case 'stale':
        return { alive: false, probed: true };
      case 'unknown':
        return { alive: this.dispatcher.isRunning(root, 'stress'), probed: false };
    }
  }

  /**
   * Re-post in a while, so a running session whose pid answered for it is
   * probed again; or, with `on` false, stop doing so. A dispatched session
   * needs none of this -- its task ending already re-posts -- but one started
   * from a plain terminal and killed there says nothing anywhere.
   */
  private reprobe(on: boolean): void {
    if (this.probe !== undefined) {
      clearTimeout(this.probe);
      this.probe = undefined;
    }
    if (on && this.view !== undefined) {
      this.probe = setTimeout(() => {
        this.probe = undefined;
        void this.post();
      }, PROBE_MS);
    }
  }

  /** The findings of `manifest` with two outputs to compare. */
  private async comparableIn(
    root: string,
    pkg: PackageLayout,
    manifest: StressManifest,
  ): Promise<Set<number>> {
    const cacheable = manifest.state !== 'running' && manifest.startedAt !== undefined;
    const comparable = new Set<number>();
    await Promise.all(
      manifest.findings.map(async (finding) => {
        const key = `${root}\0${manifest.startedAt}\0${finding.index}`;
        let can = cacheable ? this.comparable.get(key) : undefined;
        if (can === undefined) {
          const files = findingFiles(
            pkg,
            manifest.solutions,
            finding,
            await findingEntries(pkg, finding.index),
          );
          can = compareCandidates(files).length >= 2;
          if (cacheable) {
            this.comparable.set(key, can);
          }
        }
        if (can) {
          comparable.add(finding.index);
        }
      }),
    );
    return comparable;
  }

  private promotedIn(root: string, manifest: StressManifest | undefined): Map<number, string> {
    const promoted = new Map<number, string>();
    if (manifest?.startedAt === undefined) {
      return promoted;
    }
    for (const finding of manifest.findings) {
      const group = this.promoted.get(`${root}\0${manifest.startedAt}\0${finding.index}`);
      if (group !== undefined) {
        promoted.set(finding.index, group);
      }
    }
    return promoted;
  }

  private async post(): Promise<void> {
    const root = this.active.selected();
    const current = this.posts.begin();
    let model: StressViewModel = EMPTY_STRESS_MODEL;
    let declared: readonly StressDeclaration[] = [];
    let probed = false;
    if (root !== undefined) {
      const pkg = packageLayout(root);
      const reread = this.declaredRoot !== root;
      const [raw, manifest] = await Promise.all([
        reread ? readYamlFile(manifestPath(pkg)) : Promise.resolve(undefined),
        this.data.stress(pkg),
      ]);
      declared = reread ? parseStressDeclarations(raw).stresses : this.declared;
      const comparable =
        manifest === undefined ? undefined : await this.comparableIn(root, pkg, manifest);
      const liveness =
        manifest === undefined ? { alive: true, probed: false } : this.alive(root, manifest);
      probed = liveness.probed && liveness.alive;
      model = buildStressViewModel({
        declared,
        manifest,
        alive: liveness.alive,
        task: this.dispatcher.isRunning(root, 'stress'),
        promoted: this.promotedIn(root, manifest),
        comparable,
        dispatch: dispatchEnabled(),
      });
    }
    // Every await is above this line: a post a newer one overtook must not
    // land, nor leave its declarations behind for a Run to read.
    if (!current()) {
      return;
    }
    this.declared = declared;
    this.declaredRoot = root;
    this.reprobe(probed);
    // Stoppable, not merely running: the palette's Stop Stress can only end a
    // task VS Code started.
    void vscode.commands.executeCommand(
      'setContext',
      RUNNING_CONTEXT,
      model.status?.stoppable === true,
    );
    await this.view?.webview.postMessage({
      type: 'state',
      model,
      problems: this.active.problems(),
      selected: root,
    });
  }

  private html(webview: vscode.Webview): string {
    const nonce = makeNonce();
    const asset = (...parts: string[]): vscode.Uri =>
      webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'dist', ...parts));
    // The same policy as the other views; see runView.ts for `'unsafe-inline'`
    // on styles, which the problem selector's colour dot needs.
    const csp = [
      `default-src 'none'`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `font-src ${webview.cspSource}`,
      `script-src 'nonce-${nonce}'`,
    ].join('; ');
    // Three static sections, filled apart, so the status line's once-a-second
    // rewrite never replaces the buttons below it.
    return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="${csp};">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="${asset('webview', 'codicon.css')}">
    <link rel="stylesheet" href="${asset('webview', 'style.css')}">
    <title>rbx Stress</title>
  </head>
  <body>
    <div id="selector-host"></div>
    <div id="stress-root">
      <div id="declared"></div>
      <div id="status"></div>
      <div id="findings"></div>
    </div>
    <script nonce="${nonce}" src="${asset('webview', 'stressMain.js')}"></script>
  </body>
</html>`;
  }
}
