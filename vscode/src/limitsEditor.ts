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
import type { NavInfo, NavProblem, ViewState } from './webview/limitsRender';

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
  | { type: 'nav'; root?: string; profile?: string }
  | { type: 'edit'; edit: ProfileEdit; preview?: boolean; seq?: number };

interface WantedEdit {
  readonly edit: ProfileEdit;
  /** A drag in progress: answer, but leave the document alone. */
  readonly preview: boolean;
  readonly seq: number;
}

/**
 * One open profile editor.
 *
 * Every call to rbx goes through one queue, `pump`, with at most one call in
 * flight. An edit asked for while another is running does not wait in line: it
 * *replaces* whatever was waiting, since the client always sends an absolute
 * value (the limit it wants, not "+100"). So any number of clicks or drag steps
 * costs at most one call more than the one already running, and nothing in the
 * webview is ever disabled while it happens.
 */
class ProfileSession implements vscode.Disposable {
  private readonly disposables: vscode.Disposable[] = [];
  private result?: InspectResult;
  private error?: string;
  private timer?: NodeJS.Timeout;
  private inFlight = false;
  private editInFlight = false;
  private wanted?: WantedEdit;
  private refreshWanted = false;
  /** The newest edit rbx has answered for; the client keeps its optimistic values until then. */
  private answeredSeq = 0;
  /** The text an edit just wrote, whose change event must not re-ask rbx. */
  private expectText?: string;

  constructor(
    private readonly document: vscode.TextDocument,
    private readonly panel: vscode.WebviewPanel,
    private readonly root: string,
    private readonly profile: string,
    private readonly active: ActiveProblem,
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
      // The staleness banner depends on solutions and tests, which change on
      // disk under the profile: re-ask when anything in the package is saved,
      // and when a run or build finishes.
      vscode.workspace.onDidSaveTextDocument((d) => {
        if (d.uri.fsPath.startsWith(root) && d.uri.toString() !== document.uri.toString()) this.schedule();
      }),
      panel.onDidChangeViewState(() => {
        if (panel.visible) this.schedule();
      }),
      panel.webview.onDidReceiveMessage((m: Inbound) => void this.receive(m)),
      active.onDidChange(() => void this.post()),
    );
    const watcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(root, '{.rbx/runs/report.yml,build/**/*.in,problem.rbx.yml}'),
    );
    watcher.onDidChange(() => this.schedule());
    watcher.onDidCreate(() => this.schedule());
    const profiles = vscode.workspace.createFileSystemWatcher('**/.limits/*.yml', false, true, false);
    profiles.onDidCreate(() => void this.post());
    profiles.onDidDelete(() => void this.post());
    this.disposables.push(watcher, profiles);
  }

  dispose(): void {
    clearTimeout(this.timer);
    this.disposables.forEach((d) => d.dispose());
  }

  private async post(): Promise<void> {
    const state: ViewState = {
      result: this.result,
      updating: this.editInFlight || this.wanted !== undefined,
      error: this.error,
      nav: await navInfo(this.active, this.root, this.profile),
      seq: this.answeredSeq,
    };
    void this.panel.webview.postMessage({ type: 'state', state });
  }

  private schedule(): void {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.refreshWanted = true;
      void this.pump();
    }, REFRESH_DEBOUNCE_MS);
  }

  private request(wanted: WantedEdit): void {
    this.wanted = wanted;
    void this.post();
    void this.pump();
  }

  private async pump(): Promise<void> {
    if (this.inFlight) return;
    const wanted = this.wanted;
    if (wanted === undefined && !this.refreshWanted) return;
    this.inFlight = true;
    try {
      if (wanted !== undefined) {
        this.wanted = undefined;
        this.editInFlight = true;
        await this.runEdit(wanted);
        this.answeredSeq = Math.max(this.answeredSeq, wanted.seq);
      } else {
        this.refreshWanted = false;
        const result = await this.inspect();
        if (result !== undefined) this.result = result;
      }
    } catch (e) {
      log(`time profile: ${String(e)}`);
    } finally {
      this.inFlight = false;
      this.editInFlight = false;
    }
    await this.post();
    void this.pump();
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

  private async runEdit(wanted: WantedEdit): Promise<void> {
    const result = await this.inspect(wanted.edit);
    if (result === undefined) return;
    if (result.errors.length > 0 || result.yaml === undefined) {
      void vscode.window.showWarningMessage(result.errors.join(' ') || 'rbx returned no edit.');
      return;
    }
    this.result = result;
    if (wanted.preview || result.yaml === this.document.getText()) return;
    const whole = new vscode.Range(this.document.positionAt(0), this.document.positionAt(this.document.getText().length));
    const workspaceEdit = new vscode.WorkspaceEdit();
    workspaceEdit.replace(this.document.uri, whole, result.yaml);
    this.expectText = result.yaml;
    await vscode.workspace.applyEdit(workspaceEdit);
  }

  private async receive(message: Inbound): Promise<void> {
    switch (message.type) {
      case 'ready':
      case 'refresh':
        this.error = undefined;
        this.refreshWanted = true;
        await this.post();
        await this.pump();
        return;
      case 'edit':
        this.request({ edit: message.edit, preview: message.preview === true, seq: message.seq ?? 0 });
        return;
      case 'openText':
        await vscode.commands.executeCommand('vscode.openWith', this.document.uri, 'default');
        return;
      case 'reestimate':
        await reestimate(this.root, this.profile);
        return;
      case 'nav':
        await this.navigate(message.root ?? this.root, message.profile ?? this.profile);
        return;
      case 'open': {
        const target = vscode.Uri.file(path.join(this.root, message.path));
        await vscode.commands.executeCommand('vscode.open', target, { viewColumn: vscode.ViewColumn.Beside });
        return;
      }
    }
  }

  /**
   * Show another profile in this editor's place: same column, and the old tab
   * closed unless it holds unsaved edits -- moving through a contest's
   * profiles should not leave a trail of tabs behind.
   */
  private async navigate(root: string, profile: string): Promise<void> {
    const profiles = await listProfiles(root);
    if (profiles.length === 0) return;
    const chosen = profiles.includes(profile) ? profile : profiles.includes(this.profile) ? this.profile : profiles[0];
    const uri = vscode.Uri.file(path.join(root, '.limits', `${chosen}.yml`));
    if (uri.fsPath === this.document.uri.fsPath) return;
    if (root !== this.root) this.active.select(root);
    const oldTab = findProfileTab(this.document.uri);
    await vscode.commands.executeCommand('vscode.openWith', uri, LIMITS_EDITOR_VIEW_TYPE, {
      viewColumn: this.panel.viewColumn,
      preview: false,
    });
    if (oldTab !== undefined && !this.document.isDirty) {
      await vscode.window.tabGroups.close(oldTab);
    }
  }
}

function findProfileTab(uri: vscode.Uri): vscode.Tab | undefined {
  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) {
      const input = tab.input;
      if (
        input instanceof vscode.TabInputCustom &&
        input.viewType === LIMITS_EDITOR_VIEW_TYPE &&
        input.uri.fsPath === uri.fsPath
      ) {
        return tab;
      }
    }
  }
  return undefined;
}

async function navInfo(active: ActiveProblem, root: string, profile: string): Promise<NavInfo> {
  const choices = active.problems();
  const known = choices.some((c) => c.root === root) ? choices : [...choices, { root, label: path.basename(root) }];
  const problems: NavProblem[] = await Promise.all(
    known.map(async (c) => ({ root: c.root, label: c.label, group: c.group, profiles: await listProfiles(c.root) })),
  );
  return { problems, root, profile };
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
  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly active: ActiveProblem,
  ) {}

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
        state: { updating: false, error: 'Not a limits profile: expected .limits/<name>.yml.' },
      });
      return;
    }
    const session = new ProfileSession(document, panel, location.root, location.profile, this.active);
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

export async function listProfiles(root: string): Promise<string[]> {
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
      new LimitsEditorProvider(context.extensionUri, active),
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
