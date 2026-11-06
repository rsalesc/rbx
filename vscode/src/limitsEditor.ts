/**
 * The time-profile editor: a custom *text* editor over `.limits/<name>.yml`.
 *
 * Backed by the YAML document itself, so undo/redo, the dirty marker, save and
 * git diff are VS Code's own, and the view and the raw text can never disagree.
 * The editor decides nothing: it hands the buffer (saved or not) to
 * `rbx time-inspect --stdin`, draws what comes back, and turns an edit into the
 * same call with `--set`/`--revert`/... -- applying the YAML rbx returns as one
 * WorkspaceEdit. rbx stays the only thing that knows what a limit breaks.
 *
 * Registered with priority `option`: a profile still opens as text by default,
 * and this view is reached from the Run view's title bar, the command palette,
 * or the editor-title toggle.
 */
import * as crypto from 'crypto';
import * as fs from 'fs/promises';
import * as path from 'path';
import * as vscode from 'vscode';

import { ActiveProblem } from './activeProblem';
import { log } from './log';
import {
  InspectResult,
  ProfileEdit,
  inspectArgs,
  parseInspect,
  profileLocation,
} from './rbx/limitsInspect';
import { resolveRbx, run } from './rbxProcess';
import type { ViewState } from './webview/limitsRender';

export const LIMITS_EDITOR_VIEW_TYPE = 'rbx.limitsProfile';

const INSPECT_TIMEOUT_MS = 30_000;
const REFRESH_DEBOUNCE_MS = 300;

/** A CSP nonce. Fresh per resolve, from a real random source. */
function makeNonce(): string {
  return crypto.randomBytes(16).toString('base64');
}

type Inbound =
  | { type: 'ready' }
  | { type: 'refresh' }
  | { type: 'openText' }
  | { type: 'reestimate' }
  | { type: 'open'; path: string }
  | { type: 'edit'; edit: ProfileEdit };

class ProfileSession implements vscode.Disposable {
  private readonly disposables: vscode.Disposable[] = [];
  private result?: InspectResult;
  private error?: string;
  private busy = false;
  private timer?: NodeJS.Timeout;
  /** Bumped per request so a slow, superseded answer is dropped. */
  private generation = 0;
  /** The text an edit just wrote, whose change event must not re-ask rbx. */
  private expectText?: string;

  constructor(
    private readonly document: vscode.TextDocument,
    private readonly panel: vscode.WebviewPanel,
    private readonly root: string,
    private readonly profile: string,
  ) {
    this.disposables.push(
      vscode.workspace.onDidChangeTextDocument((e) => {
        if (e.document.uri.toString() !== document.uri.toString()) return;
        if (this.expectText !== undefined && document.getText() === this.expectText) {
          this.expectText = undefined;
          return;
        }
        this.schedule();
      }),
      // The staleness badge depends on solutions and tests, which change on
      // disk under the profile: re-ask when anything in the package is saved,
      // and when a run or build finishes.
      vscode.workspace.onDidSaveTextDocument((d) => {
        if (d.uri.fsPath.startsWith(root) && d.uri.toString() !== document.uri.toString()) this.schedule();
      }),
      panel.onDidChangeViewState(() => {
        if (panel.visible) this.schedule();
      }),
      panel.webview.onDidReceiveMessage((m: Inbound) => void this.receive(m)),
    );
    const watcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(root, '{.rbx/runs/report.yml,build/**/*.in,problem.rbx.yml}'),
    );
    watcher.onDidChange(() => this.schedule());
    watcher.onDidCreate(() => this.schedule());
    this.disposables.push(watcher);
  }

  dispose(): void {
    clearTimeout(this.timer);
    this.disposables.forEach((d) => d.dispose());
  }

  private post(): void {
    const state: ViewState = { result: this.result, busy: this.busy, error: this.error };
    void this.panel.webview.postMessage({ type: 'state', state });
  }

  private schedule(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.refresh(), REFRESH_DEBOUNCE_MS);
  }

  private async inspect(edit?: ProfileEdit): Promise<InspectResult | undefined> {
    const rbx = await resolveRbx(this.root);
    if (rbx === undefined) {
      this.error = 'No rbx found for this problem. Set `rbx.executable`, or put rbx on PATH.';
      return undefined;
    }
    const args = inspectArgs(this.profile, edit);
    const result = await run(rbx, args, this.root, INSPECT_TIMEOUT_MS, this.document.getText());
    if (result.spawnError !== undefined || result.code !== 0) {
      log(`rbx ${args.join(' ')} failed (${result.code}): ${result.stderr}`);
      this.error = `rbx time-inspect failed${result.code !== null ? ` (exit ${result.code})` : ''}. Is this rbx too old? ${result.stderr.trim().split('\n').slice(-1)[0] ?? ''}`;
      return undefined;
    }
    const parsed = parseInspect(result.stdout);
    if (!parsed.ok) {
      this.error = parsed.error;
      return undefined;
    }
    this.error = undefined;
    return parsed.result;
  }

  async refresh(): Promise<void> {
    const generation = ++this.generation;
    const result = await this.inspect();
    if (generation !== this.generation) return;
    if (result !== undefined) this.result = result;
    this.post();
  }

  private async applyEdit(edit: ProfileEdit): Promise<void> {
    const generation = ++this.generation;
    this.busy = true;
    this.post();
    try {
      const result = await this.inspect(edit);
      if (generation !== this.generation) return;
      if (result === undefined) return;
      if (result.errors.length > 0 || result.yaml === undefined) {
        void vscode.window.showWarningMessage(result.errors.join(' ') || 'rbx returned no edit.');
        return;
      }
      if (result.yaml !== this.document.getText()) {
        const whole = new vscode.Range(
          this.document.positionAt(0),
          this.document.positionAt(this.document.getText().length),
        );
        const workspaceEdit = new vscode.WorkspaceEdit();
        workspaceEdit.replace(this.document.uri, whole, result.yaml);
        this.expectText = result.yaml;
        await vscode.workspace.applyEdit(workspaceEdit);
      }
      this.result = result;
    } finally {
      if (generation === this.generation) {
        this.busy = false;
        this.post();
      }
    }
  }

  private async receive(message: Inbound): Promise<void> {
    switch (message.type) {
      case 'ready':
      case 'refresh':
        this.error = undefined;
        this.post();
        await this.refresh();
        return;
      case 'edit':
        await this.applyEdit(message.edit);
        return;
      case 'openText':
        await vscode.commands.executeCommand('vscode.openWith', this.document.uri, 'default');
        return;
      case 'reestimate':
        await reestimate(this.root, this.profile);
        return;
      case 'open': {
        const target = vscode.Uri.file(path.join(this.root, message.path));
        await vscode.commands.executeCommand('vscode.open', target, { viewColumn: vscode.ViewColumn.Beside });
        return;
      }
    }
  }
}

/**
 * Re-estimation is a real `rbx time` run, with its pickers and prompts, so it
 * goes to a terminal the setter can answer. (Prototype: a plain terminal rather
 * than a dispatched task, which would mean teaching dispatch.ts a `time` command.)
 */
async function reestimate(root: string, profile: string): Promise<void> {
  const rbx = (await resolveRbx(root)) ?? 'rbx';
  const terminal = vscode.window.createTerminal({ name: `rbx time -p ${profile}`, cwd: root });
  terminal.show();
  terminal.sendText(`${JSON.stringify(rbx)} time -p ${profile}`);
}

export class LimitsEditorProvider implements vscode.CustomTextEditorProvider {
  constructor(private readonly extensionUri: vscode.Uri) {}

  resolveCustomTextEditor(document: vscode.TextDocument, panel: vscode.WebviewPanel): void {
    const location = profileLocation(document.uri.fsPath);
    panel.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'dist')],
    };
    panel.webview.html = this.html(panel.webview);
    if (location === undefined) {
      void panel.webview.postMessage({
        type: 'state',
        state: { busy: false, error: 'Not a limits profile: expected .limits/<name>.yml.' },
      });
      return;
    }
    const session = new ProfileSession(document, panel, location.root, location.profile);
    panel.onDidDispose(() => session.dispose());
  }

  private html(webview: vscode.Webview): string {
    const nonce = makeNonce();
    const asset = (...parts: string[]): vscode.Uri =>
      webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'dist', ...parts));
    const csp = [
      `default-src 'none'`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `font-src ${webview.cspSource}`,
      `script-src 'nonce-${nonce}'`,
    ].join('; ');
    return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="${csp};">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="${asset('webview', 'codicon.css')}">
    <link rel="stylesheet" href="${asset('webview', 'limitsStyle.css')}">
    <title>Time profile</title>
  </head>
  <body>
    <div id="root"></div>
    <script nonce="${nonce}" src="${asset('webview', 'limitsMain.js')}"></script>
  </body>
</html>`;
  }
}

async function listProfiles(root: string): Promise<string[]> {
  try {
    const names = await fs.readdir(path.join(root, '.limits'));
    return names.filter((n) => /\.ya?ml$/.test(n)).map((n) => n.replace(/\.ya?ml$/, '')).sort();
  } catch {
    return [];
  }
}

/** Open the active problem's profile in the time-profile view, asking which when several exist. */
async function openTimeProfile(active: ActiveProblem): Promise<void> {
  const root = active.selected();
  if (root === undefined) {
    void vscode.window.showInformationMessage('No rbx problem is selected.');
    return;
  }
  const profiles = await listProfiles(root);
  let chosen: string | undefined;
  if (profiles.length === 1) {
    chosen = profiles[0];
  } else {
    const estimate = '$(play) Estimate a new profile…';
    const items: vscode.QuickPickItem[] = profiles.map((p) => ({
      label: p,
      description: p === 'local' ? 'default for rbx run' : undefined,
      detail: `.limits/${p}.yml`,
    }));
    items.push({ label: '', kind: vscode.QuickPickItemKind.Separator }, { label: estimate });
    const pick = await vscode.window.showQuickPick(items, {
      title: 'Time profile',
      placeHolder: profiles.length === 0 ? 'This problem has no limits profile yet' : 'Which limits profile?',
    });
    if (pick === undefined) return;
    if (pick.label === estimate) {
      const name = await vscode.window.showInputBox({ title: 'Profile to estimate', value: 'local' });
      if (name) await reestimate(root, name);
      return;
    }
    chosen = pick.label;
  }
  const uri = vscode.Uri.file(path.join(root, '.limits', `${chosen}.yml`));
  await vscode.commands.executeCommand('vscode.openWith', uri, LIMITS_EDITOR_VIEW_TYPE);
}

export function registerLimitsEditor(context: vscode.ExtensionContext, active: ActiveProblem): void {
  context.subscriptions.push(
    vscode.window.registerCustomEditorProvider(
      LIMITS_EDITOR_VIEW_TYPE,
      new LimitsEditorProvider(context.extensionUri),
      { webviewOptions: { retainContextWhenHidden: true } },
    ),
    vscode.commands.registerCommand('rbx.openTimeProfile', () => openTimeProfile(active)),
    vscode.commands.registerCommand('rbx.reopenTimeProfileAsView', (uri?: vscode.Uri) => {
      const target = uri ?? vscode.window.activeTextEditor?.document.uri;
      if (target) void vscode.commands.executeCommand('vscode.openWith', target, LIMITS_EDITOR_VIEW_TYPE);
    }),
    vscode.commands.registerCommand('rbx.reopenTimeProfileAsText', (uri?: vscode.Uri) => {
      const target = uri ?? activeCustomEditorUri();
      if (target) void vscode.commands.executeCommand('vscode.openWith', target, 'default');
    }),
  );
}

function activeCustomEditorUri(): vscode.Uri | undefined {
  const input = vscode.window.tabGroups.activeTabGroup.activeTab?.input;
  return input instanceof vscode.TabInputCustom ? input.uri : undefined;
}
