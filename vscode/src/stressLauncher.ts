/**
 * The stress launcher (#908, design S4): an editor tab whose form compiles to
 * one `rbx stress` command.
 *
 * The host half: the panel, the HTML shell, the messages, and the side
 * effects -- reading problem.rbx.yml, remembering the last launch, dispatching
 * the run. What the form holds is webview/launcherState.ts and how it is
 * painted is webview/launcherRender.ts; both are pure, and the host uses the
 * first to re-check every launch the client sends before acting on it.
 *
 * One launcher per window, not one per package or per stress: it is a form
 * being filled in, and two of them would be two drafts of the same thing.
 * Opening it again re-targets the one already open.
 */
import * as crypto from 'crypto';
import * as path from 'path';
import * as vscode from 'vscode';

import { Dispatcher, dispatchEnabled } from './dispatch';
import { log } from './log';
import { Latest } from './rbx/latest';
import { manifestPath, packageLayout } from './rbx/layout';
import { readYamlFile } from './rbx/store';
import { StressDeclarations, parseStressDeclarations } from './rbx/stressDeclarations';
import { StressLaunch, lastLaunchKey, parseLaunch, stressDispatchArgs } from './rbx/stressSpec';
import { declaredRunLaunch } from './rbx/stressViewModel';
import type { RunDataChange } from './runData';
import type { StatementVarsIndex } from './statementVarsIndex';
import type { OpenLauncherArgs } from './stressView';
import {
  commandLine,
  findDeclared,
  initialLaunch,
  launchProblem,
} from './webview/launcherState';

/** What the launcher needs from the rest of the extension. */
export interface LauncherDeps {
  readonly extensionUri: vscode.Uri;
  /** Where the last launch per package is kept (`lastLaunchKey`). */
  readonly memento: vscode.Memento;
  readonly dispatcher: Dispatcher;
  /** The watcher's signal; a `manifest` plan is an edit to problem.rbx.yml. */
  readonly onDidChange: vscode.Event<RunDataChange>;
  /** Package variables, for the generator call's `<var>`. */
  readonly vars: Pick<StatementVarsIndex, 'varsFor'>;
}

/** What launcherMain.ts posts. */
interface ClientMessage {
  readonly type?: string;
  readonly launch?: unknown;
  /** The target the form was made for; a Run from an earlier one is dropped. */
  readonly target?: unknown;
}

/** One open of the launcher: the id the client keys its form on, and the launch it starts from. */
interface Target {
  readonly id: string;
  /** Resolved on the first post, once the declarations are read. */
  launch?: StressLaunch;
}

function makeNonce(): string {
  return crypto.randomBytes(16).toString('base64');
}

function titleOf(args: OpenLauncherArgs): string {
  return args.stress === undefined ? 'New stress' : `Stress: ${args.stress}`;
}

/**
 * `rbx.stress.openLauncher`'s argument, checked: commands can be run with
 * anything, from anywhere.
 */
function asOpenArgs(raw: unknown): OpenLauncherArgs | undefined {
  if (typeof raw !== 'object' || raw === null) {
    return undefined;
  }
  const { root, stress } = raw as { root?: unknown; stress?: unknown };
  if (typeof root !== 'string' || root === '') {
    return undefined;
  }
  return typeof stress === 'string' && stress !== '' ? { root, stress } : { root };
}

async function readDeclarations(root: string): Promise<StressDeclarations> {
  return parseStressDeclarations(await readYamlFile(manifestPath(packageLayout(root))));
}

export class StressLauncher {
  static readonly viewType = 'rbx.stressLauncher';

  private static current?: StressLauncher;

  /** Overlapping posts resolve out of order; only the newest may land. */
  private readonly posts = new Latest();
  private readonly subscriptions: vscode.Disposable[] = [];
  private target: Target = { id: StressLauncher.newId() };
  /** Set once the panel is gone; every await below re-checks it. */
  private disposed = false;

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private readonly deps: LauncherDeps,
    private args: OpenLauncherArgs,
  ) {
    panel.webview.html = this.html(panel.webview);
    this.subscriptions.push(
      panel.webview.onDidReceiveMessage((message: ClientMessage) => {
        this.receive(message).catch((error) => {
          log(`The stress launcher failed to handle ${String(message.type)}: ${String(error)}`);
        });
      }),
      deps.onDidChange((change) => {
        // The same signal the Stress view redraws its declared stresses on.
        if (change.plan?.manifest === true && this.concerns(change.root)) {
          void this.post();
          void this.postVars();
        }
      }),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration('rbx.dispatch.enabled')) {
          void this.post();
        }
      }),
    );
    panel.onDidDispose(() => {
      this.disposed = true;
      this.subscriptions.forEach((subscription) => subscription.dispose());
      if (StressLauncher.current === this) {
        StressLauncher.current = undefined;
      }
    });
  }

  private static newId(): string {
    return crypto.randomBytes(8).toString('hex');
  }

  /** Open the launcher on `raw` (an `OpenLauncherArgs`), or re-target the one open. */
  static open(deps: LauncherDeps, raw: unknown): void {
    const args = asOpenArgs(raw);
    if (args === undefined) {
      log(`rbx.stress.openLauncher: ignored an argument with no package root.`);
      return;
    }
    const existing = StressLauncher.current;
    if (existing !== undefined) {
      existing.retarget(args);
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      StressLauncher.viewType,
      titleOf(args),
      vscode.ViewColumn.Active,
      {
        enableScripts: true,
        localResourceRoots: [vscode.Uri.joinPath(deps.extensionUri, 'dist')],
        // No `retainContextWhenHidden`: the client keeps its form through
        // `setState`, and the host re-posts everything else on `ready`.
      },
    );
    StressLauncher.current = new StressLauncher(panel, deps, args);
  }

  private retarget(args: OpenLauncherArgs): void {
    // The same open again -- a second click on New stress, or on Edit for the
    // stress already being edited -- is a reveal: re-targeting would throw
    // away the draft for the very launch it is a draft of.
    if (
      path.resolve(args.root) === path.resolve(this.args.root) &&
      args.stress === this.args.stress
    ) {
      this.panel.reveal(undefined, false);
      return;
    }
    this.args = args;
    this.target = { id: StressLauncher.newId() };
    this.panel.title = titleOf(args);
    this.panel.reveal(undefined, false);
    void this.post();
    void this.postVars();
  }

  private concerns(root: string | undefined): boolean {
    return root === undefined || path.resolve(root) === path.resolve(this.args.root);
  }

  /** The launch a new target starts from; see `initialLaunch` and `declaredRunLaunch`. */
  private startingLaunch(declarations: StressDeclarations): StressLaunch {
    const remembered = parseLaunch(this.deps.memento.get(lastLaunchKey(this.args.root)));
    if (this.args.stress !== undefined) {
      return declaredRunLaunch(this.args.stress, declarations.stresses, remembered).launch;
    }
    return initialLaunch(declarations, remembered);
  }

  private async post(): Promise<void> {
    const current = this.posts.begin();
    const root = this.args.root;
    const declarations = await readDeclarations(root);
    if (!current() || this.disposed) {
      return;
    }
    const target = this.target;
    target.launch ??= this.startingLaunch(declarations);
    await this.panel.webview.postMessage({
      type: 'state',
      target: { id: target.id, launch: target.launch },
      title: titleOf(this.args),
      rootLabel: vscode.workspace.asRelativePath(root),
      declarations,
      dispatch: dispatchEnabled(),
    });
  }

  /**
   * The package's variable names, posted apart from the state: they come from
   * a spawned `rbx vars --json`, cached per package, and the form should not
   * wait on a process to draw.
   */
  private async postVars(): Promise<void> {
    const root = this.args.root;
    let names: string[] = [];
    try {
      names = Object.keys((await this.deps.vars.varsFor(root))?.vars ?? {});
    } catch (error) {
      log(`rbx vars for the stress launcher failed: ${String(error)}`);
    }
    if (!this.disposed && root === this.args.root) {
      await this.panel.webview.postMessage({ type: 'vars', names });
    }
  }

  private async receive(message: ClientMessage): Promise<void> {
    switch (message.type) {
      case 'ready':
        await Promise.all([this.post(), this.postVars()]);
        return;
      case 'run':
      case 'copy':
        // A launch from a form made for an earlier open names that open's
        // package, which may not be the one this panel now runs in.
        if (message.target !== this.target.id) {
          log(`The stress launcher dropped a ${message.type} from a launcher since re-targeted.`);
          return;
        }
        await (message.type === 'run' ? this.run(message.launch) : this.copy(message.launch));
        return;
    }
  }

  /**
   * Run what the client asked for -- after reading it back into a launch and
   * checking it against problem.rbx.yml as it is now, not as the form last saw
   * it: the client is ours, but a message is still only a request.
   */
  private async run(raw: unknown): Promise<void> {
    const root = this.args.root;
    const launch = parseLaunch(raw);
    if (launch === undefined) {
      log('The stress launcher sent a launch it could not have built; ignored.');
      return;
    }
    if (!dispatchEnabled()) {
      void vscode.window.showInformationMessage('rbx: dispatching commands is turned off.');
      return;
    }
    const declarations = await readDeclarations(root);
    if (this.disposed || root !== this.args.root) {
      return;
    }
    const problem = launchProblem(launch, declarations);
    if (problem !== undefined) {
      void vscode.window.showErrorMessage(`rbx stress: ${problem}`);
      return;
    }
    const declared =
      launch.source.kind === 'declared' ? findDeclared(declarations, launch.source.name) : undefined;
    // Remembered before the dispatch, which may wait on a contest prompt: what
    // was asked for is worth keeping even if that prompt is dismissed.
    await this.deps.memento.update(lastLaunchKey(root), launch);
    await this.deps.dispatcher.dispatch({
      command: 'stress',
      root,
      args: stressDispatchArgs(launch, declared),
    });
    // The view is where the session shows up; the launcher stays open behind
    // it for the next run.
    void vscode.commands.executeCommand('rbx.stress.focus');
  }

  private async copy(raw: unknown): Promise<void> {
    const launch = parseLaunch(raw);
    if (launch === undefined) {
      return;
    }
    const declarations = await readDeclarations(this.args.root);
    // Only a line that would run: Copy is the terminal's Run, and a copied
    // command rbx refuses is the same surprise later.
    const line =
      launchProblem(launch, declarations) === undefined
        ? commandLine(launch, declarations)
        : undefined;
    if (line !== undefined && !this.disposed) {
      await vscode.env.clipboard.writeText(line);
      vscode.window.setStatusBarMessage('rbx: stress command copied.', 3000);
    }
  }

  private html(webview: vscode.Webview): string {
    const nonce = makeNonce();
    const asset = (...parts: string[]): vscode.Uri =>
      webview.asWebviewUri(vscode.Uri.joinPath(this.deps.extensionUri, 'dist', ...parts));
    // The same policy as the views, without `'unsafe-inline'`: nothing here
    // sets a `style` attribute.
    const csp = [
      `default-src 'none'`,
      `style-src ${webview.cspSource}`,
      `font-src ${webview.cspSource}`,
      `script-src 'nonce-${nonce}'`,
    ].join('; ');
    // The footer is static and filled by `textContent`, so its status line is
    // one live region that a screen reader follows across keystrokes.
    return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="${csp};">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="${asset('webview', 'codicon.css')}">
    <link rel="stylesheet" href="${asset('webview', 'launcherStyle.css')}">
    <title>rbx Stress Launcher</title>
  </head>
  <body>
    <main class="launcher">
      <header class="launcher-header">
        <h1 id="title"></h1>
        <span id="root" class="root"></span>
      </header>
      <div id="form" class="launcher-form"></div>
    </main>
    <footer class="launcher-footer">
      <div role="group" aria-labelledby="preview-label">
        <span id="preview-label" class="sr-only">Command to run</span>
        <code id="preview" class="preview"></code>
      </div>
      <p id="problem" class="problem" role="status"></p>
      <div class="footer-buttons">
        <button type="button" id="run" data-act="run" disabled><span class="codicon codicon-play" aria-hidden="true"></span>Run</button>
        <button type="button" id="copy" class="secondary" data-act="copy" disabled><span class="codicon codicon-copy" aria-hidden="true"></span>Copy</button>
      </div>
    </footer>
    <script nonce="${nonce}" src="${asset('webview', 'launcherMain.js')}"></script>
  </body>
</html>`;
  }
}
