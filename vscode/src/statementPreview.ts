/**
 * The statement preview (#909): the built statement beside its source,
 * refreshed whenever rbx writes a new one.
 *
 * The panel never builds anything itself and never reads a LaTeX log. It
 * follows the statement build report (rbx/statementReport.ts): which outputs
 * exist, which one is built from the file being edited, whether its last build
 * failed and where. A build -- the panel's button, a save with
 * `rbx.statements.buildOnSave`, or one typed in a terminal -- rewrites the
 * report, and the panel reloads from it, keeping the reader's place.
 *
 * The host reads the PDF and posts its bytes to the webview, rather than
 * pointing the webview at the file: that is the same over Remote SSH, WSL and
 * Codespaces, where the file is on another machine than the webview, and it
 * means the panel needs no resource root but its own `dist`.
 */
import * as fs from 'fs/promises';
import * as path from 'path';
import * as vscode from 'vscode';

import { ActiveProblem } from './activeProblem';
import { findContestRoot } from './contestIndex';
import { DeclaredIndex } from './declared';
import { Dispatcher } from './dispatch';
import { log } from './log';
import { RbxCommand, STATEMENT_COMMANDS, TASK_TYPE, collides, statementCommand } from './rbx/dispatch';
import { Latest } from './rbx/latest';
import { SaveTarget, StatementOutput, defaultOutput, saveTargets } from './rbx/statementReport';
import { previewModel } from './rbx/statementPreviewModel';
import { StatementReports, scopeOf } from './statementReports';
import type { ClientMessage, HostMessage } from './webview/statementProtocol';

const BUILD_ON_SAVE_SETTING = 'rbx.statements.buildOnSave';
const BUILD_ON_SAVE_DELAY_MS = 300;


function makeNonce(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let nonce = '';
  for (let i = 0; i < 32; i++) {
    nonce += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return nonce;
}

/** The services the preview reads from and acts through. */
export interface PreviewDeps {
  readonly context: vscode.ExtensionContext;
  readonly reports: StatementReports;
  readonly declared: DeclaredIndex;
  readonly active: ActiveProblem;
  readonly dispatcher: Dispatcher;
}

/** Where a preview is pointed: a package (or contest) root, and the file asked about. */
interface Target {
  readonly root: string;
  readonly file?: string;
}

/**
 * The root a file's statement lives under.
 *
 * A file a `problem.rbx.yml` declares belongs to that package. Anything else
 * may still be the source of an output some report knows -- a contest's
 * statement file, which no problem declares. Failing both, the problem the
 * sidebar has selected.
 */
async function targetFor(deps: PreviewDeps, uri: vscode.Uri | undefined): Promise<Target | undefined> {
  if (uri !== undefined && uri.scheme === 'file') {
    const declared = deps.declared.declarationFor(uri);
    if (declared !== undefined) {
      return { root: declared.root, file: uri.fsPath };
    }
    for (const root of await deps.reports.roots()) {
      const outputs = await deps.reports.outputs(root);
      if (outputs.some((output) => output.source === uri.fsPath)) {
        return { root, file: uri.fsPath };
      }
    }
  }
  const selected = deps.active.selected();
  return selected === undefined ? undefined : { root: selected, file: uri?.fsPath };
}

export class StatementPreviewPanel {
  static readonly viewType = 'rbx.statementPreview';
  private static current?: StatementPreviewPanel;

  /** The package root, then its contest's -- whose reports the picker lists. */
  private roots: string[] = [];
  private home: string;
  private activeFile?: string;
  private outputs: StatementOutput[] = [];
  private selected?: StatementOutput;
  /** `id` + file revision of the document the webview has, to skip resends. */
  private sent?: string;
  private ready = false;
  /** A file the panel itself is opening, which `follow` must not chase. */
  private navigatingTo?: string;
  private readonly refreshes = new Latest();
  private readonly disposables: vscode.Disposable[] = [];

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private readonly deps: PreviewDeps,
    target: Target,
    /** Where sources open: the column the preview was opened from. */
    private readonly sourceColumn: vscode.ViewColumn,
  ) {
    this.home = target.root;
    this.activeFile = target.file;
    panel.webview.html = this.html();
    this.disposables.push(
      panel.webview.onDidReceiveMessage((message: ClientMessage) => void this.handle(message)),
      deps.reports.onDidChange((root) => {
        if (this.roots.includes(root)) {
          void this.refresh();
        }
      }),
      vscode.tasks.onDidStartTask(() => void this.refresh()),
      vscode.tasks.onDidEndTask(() => void this.refresh()),
      vscode.window.onDidChangeActiveTextEditor((editor) => void this.follow(editor)),
    );
    panel.onDidDispose(() => {
      this.disposables.forEach((disposable) => disposable.dispose());
      if (StatementPreviewPanel.current === this) {
        StatementPreviewPanel.current = undefined;
      }
    });
    void this.retarget(target);
  }

  /** Open the preview for `uri` (the active editor when absent), or point the open one at it. */
  static async show(deps: PreviewDeps, uri?: vscode.Uri): Promise<void> {
    const target = await targetFor(deps, uri ?? vscode.window.activeTextEditor?.document.uri);
    if (target === undefined) {
      void vscode.window.showInformationMessage(
        'rbx: open a statement, or a file of an rbx problem, to preview its statement.',
      );
      return;
    }
    const existing = StatementPreviewPanel.current;
    if (existing !== undefined) {
      existing.panel.reveal(undefined, true);
      await existing.retarget(target);
      return;
    }
    const sourceColumn = vscode.window.activeTextEditor?.viewColumn ?? vscode.ViewColumn.One;
    const panel = vscode.window.createWebviewPanel(
      StatementPreviewPanel.viewType,
      'Statement Preview',
      { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
      {
        enableScripts: true,
        localResourceRoots: [vscode.Uri.joinPath(deps.context.extensionUri, 'dist')],
        // A rendered PDF is expensive to rebuild and the reader's place in it
        // lives in the webview; hiding the tab must keep both.
        retainContextWhenHidden: true,
      },
    );
    panel.iconPath = new vscode.ThemeIcon('open-preview');
    StatementPreviewPanel.current = new StatementPreviewPanel(panel, deps, target, sourceColumn);
    deps.context.subscriptions.push(panel);
  }

  /** The output on screen while the panel is the active tab, for its title-bar Build button. */
  static focusedBuild(): { command: RbxCommand; root: string } | undefined {
    const current = StatementPreviewPanel.current;
    return current?.panel.active ? current.buildRequest() : undefined;
  }

  private async retarget(target: Target): Promise<void> {
    this.home = target.root;
    this.activeFile = target.file ?? this.activeFile;
    const contest = (await scopeOf(target.root)) === 'problem' ? await findContestRoot(target.root) : undefined;
    this.roots = contest === undefined ? [target.root] : [target.root, contest];
    // A file asked about by name takes over from whatever was picked before.
    if (target.file !== undefined) {
      this.selected = undefined;
    }
    await this.refresh();
  }

  /** Follow the editor to another statement source, as the Markdown preview does. */
  private async follow(editor: vscode.TextEditor | undefined): Promise<void> {
    const file = editor?.document.uri;
    if (file === undefined || file.scheme !== 'file' || file.fsPath === this.activeFile) {
      return;
    }
    // The panel opened this file itself -- a finding, the source button -- so
    // the reader is working through *this* output's errors; stay on it.
    if (file.fsPath === this.navigatingTo) {
      this.navigatingTo = undefined;
      return;
    }
    if (this.outputs.some((output) => output.source === file.fsPath)) {
      this.activeFile = file.fsPath;
      if (this.selected?.source !== file.fsPath) {
        this.selected = undefined;
      }
      await this.refresh();
      return;
    }
    const declared = this.deps.declared.declarationFor(file);
    if (declared?.asset.role === 'statement' && declared.root !== this.home) {
      await this.retarget({ root: declared.root, file: file.fsPath });
    }
  }

  private building(): boolean {
    return vscode.tasks.taskExecutions.some((execution) => {
      const definition = execution.task.definition as { type?: unknown; command?: unknown; cwd?: unknown };
      return (
        definition.type === TASK_TYPE &&
        (STATEMENT_COMMANDS as readonly unknown[]).includes(definition.command) &&
        typeof definition.cwd === 'string' &&
        this.roots.includes(definition.cwd)
      );
    });
  }

  private async refresh(): Promise<void> {
    const current = this.refreshes.begin();
    const outputs = (await Promise.all(this.roots.map((root) => this.deps.reports.outputs(root)))).flat();
    if (!current()) {
      return;
    }
    this.outputs = outputs;
    this.selected = defaultOutput(outputs, this.activeFile, this.selected?.id);
    const revision = await this.revisionOf(this.selected);
    if (!current()) {
      return;
    }
    this.panel.title =
      this.selected === undefined ? 'Statement Preview' : `Preview ${path.basename(this.selected.path)}`;
    this.post({
      type: 'model',
      model: previewModel({
        outputs,
        selected: this.selected,
        exists: revision !== undefined,
        building: this.building(),
      }),
    });
    if (this.selected !== undefined && this.selected.format === 'pdf' && revision !== undefined) {
      await this.sendDocument(this.selected, revision, current);
    }
  }

  /** The file's revision, or undefined when it is not on disk. */
  private async revisionOf(output: StatementOutput | undefined): Promise<string | undefined> {
    if (output === undefined) {
      return undefined;
    }
    try {
      const stat = await fs.stat(output.path);
      return `${stat.mtimeMs}:${stat.size}`;
    } catch {
      return undefined;
    }
  }

  private async sendDocument(
    output: StatementOutput,
    revision: string,
    current: () => boolean,
  ): Promise<void> {
    const key = `${output.id}\u0000${revision}`;
    if (!this.ready || this.sent === key) {
      return;
    }
    let data: Uint8Array;
    try {
      // A plain `Uint8Array` of its own, not the `Buffer`: a Buffer may be a
      // view into a shared pool, and the webview message would carry all of it.
      data = new Uint8Array(await fs.readFile(output.path));
    } catch (error) {
      log(`Statement preview could not read ${output.path}: ${String(error)}`);
      return;
    }
    // A big PDF takes a while to read; a newer refresh may have picked
    // another output meanwhile, and its document must not be painted over.
    if (!current()) {
      return;
    }
    this.sent = key;
    this.post({ type: 'document', id: output.id, revision, data });
  }

  private post(message: HostMessage): void {
    void this.panel.webview.postMessage(message);
  }

  private buildRequest(): { command: RbxCommand; root: string } {
    const output = this.selected;
    if (output === undefined) {
      return { command: 'statements', root: this.home };
    }
    // A contest command finds its contest from the root it is handed, so the
    // package root works for both scopes; the contest's own root is the
    // fallback for a preview opened on a contest file.
    return {
      command: statementCommand(output.scope, output.kind),
      root: output.scope === 'problem' ? output.root : this.home,
    };
  }

  private async handle(message: ClientMessage): Promise<void> {
    switch (message.type) {
      case 'ready':
        this.ready = true;
        this.sent = undefined;
        await this.refresh();
        return;
      case 'select':
        this.selected = this.outputs.find((output) => output.id === message.id);
        await this.refresh();
        return;
      case 'build':
        await this.deps.dispatcher.dispatch(this.buildRequest());
        return;
      case 'openSource':
        if (this.selected?.source !== undefined) {
          await this.open(this.selected.source);
        }
        return;
      case 'openLog':
        if (this.selected?.log !== undefined) {
          await this.open(this.selected.log);
        }
        return;
      case 'openOutput':
        await this.openOutput();
        return;
      case 'reveal': {
        const output = this.selected;
        const finding = output?.findings[message.index];
        const file = finding?.file ?? output?.source;
        if (file !== undefined) {
          await this.open(file, finding?.file !== undefined ? finding.line : undefined);
        }
        return;
      }
    }
  }

  private async open(file: string, line?: number): Promise<void> {
    this.navigatingTo = file;
    const position = new vscode.Position(Math.max(0, (line ?? 1) - 1), 0);
    await vscode.window.showTextDocument(vscode.Uri.file(file), {
      viewColumn: this.sourceColumn,
      selection: new vscode.Range(position, position),
    });
  }

  private async openOutput(): Promise<void> {
    const output = this.selected;
    if (output === undefined) {
      return;
    }
    const uri = vscode.Uri.file(output.path);
    if (output.format === 'md') {
      await vscode.commands.executeCommand('markdown.showPreview', uri);
    } else {
      await vscode.window.showTextDocument(uri, { viewColumn: this.sourceColumn });
    }
  }

  private html(): string {
    const webview = this.panel.webview;
    const nonce = makeNonce();
    const asset = (name: string) =>
      webview.asWebviewUri(vscode.Uri.joinPath(this.deps.context.extensionUri, 'dist', 'webview', name));
    // `blob:` workers for pdf.js (see webview/statementMain.mts); `connect-src`
    // only so the worker script can be fetched to make one. No `unsafe-eval`:
    // pdf.js is told not to use it (`isEvalSupported: false`).
    const csp = [
      `default-src 'none'`,
      `img-src ${webview.cspSource} data: blob:`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `font-src ${webview.cspSource} data:`,
      `script-src 'nonce-${nonce}'`,
      `worker-src blob:`,
      `connect-src ${webview.cspSource}`,
    ].join('; ');
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="${csp}">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="${asset('statementStyle.css')}" rel="stylesheet">
  <title>Statement Preview</title>
</head>
<body data-worker="${asset('pdf.worker.mjs')}">
  <div id="toolbar">
    <select id="outputs" title="Which output to preview"></select>
    <span id="status"></span>
    <button id="build" title="Build the statements (rbx statements build)">Build</button>
    <span class="spacer"></span>
    <button id="zoomOut" title="Zoom out">−</button>
    <button id="fit" title="Fit to width">Fit</button>
    <button id="zoomIn" title="Zoom in">+</button>
    <span id="page"></span>
    <button id="source" title="Open the source this is built from" hidden>Source</button>
    <button id="log" title="Open the full pdflatex log of the last build" hidden>Log</button>
  </div>
  <div id="banner" hidden></div>
  <div id="main">
    <div id="viewerContainer" hidden><div id="viewer" class="pdfViewer"></div></div>
    <div id="empty" hidden>
      <p id="emptyMessage"></p>
      <button id="emptyAction"></button>
    </div>
  </div>
  <script nonce="${nonce}" src="${asset('statementMain.js')}"></script>
</body>
</html>`;
  }
}

/**
 * Build on save, when `rbx.statements.buildOnSave` is on.
 *
 * Which builds a save asks for is `saveTargets`' call. Each is debounced, and
 * dispatched quietly: a dispatch that would have to ask anything is skipped,
 * never a modal. A save that lands while an rbx command already runs there is
 * not lost, though -- it waits, and fires once that command ends, so the
 * preview never settles on a PDF missing the last edit.
 */
function registerBuildOnSave(deps: PreviewDeps): void {
  const timers = new Map<string, NodeJS.Timeout>();
  const waiting = new Map<string, SaveTarget>();
  const keyOf = (target: SaveTarget) => `${target.command}\u0000${target.root}`;
  const busy = (root: string) =>
    vscode.tasks.taskExecutions.some((execution) => {
      const definition = execution.task.definition as { type?: unknown; cwd?: unknown };
      return (
        definition.type === TASK_TYPE &&
        typeof definition.cwd === 'string' &&
        collides(definition.cwd, root)
      );
    });
  const fire = (target: SaveTarget) => {
    if (busy(target.root)) {
      waiting.set(keyOf(target), target);
      return;
    }
    void deps.dispatcher.dispatch({ ...target, quiet: true });
  };
  const schedule = (target: SaveTarget) => {
    const key = keyOf(target);
    clearTimeout(timers.get(key));
    timers.set(
      key,
      setTimeout(() => {
        timers.delete(key);
        fire(target);
      }, BUILD_ON_SAVE_DELAY_MS),
    );
  };
  deps.context.subscriptions.push(
    { dispose: () => timers.forEach((timer) => clearTimeout(timer)) },
    vscode.tasks.onDidEndTask(() => {
      for (const [key, target] of [...waiting]) {
        if (!busy(target.root)) {
          waiting.delete(key);
          fire(target);
        }
      }
    }),
    vscode.workspace.onDidSaveTextDocument(async (document) => {
      if (
        document.uri.scheme !== 'file' ||
        !vscode.workspace.getConfiguration(undefined, document.uri).get<boolean>(BUILD_ON_SAVE_SETTING, false)
      ) {
        return;
      }
      const file = document.uri.fsPath;
      const outputs = (
        await Promise.all((await deps.reports.roots()).map((root) => deps.reports.outputs(root)))
      ).flat();
      const targets = saveTargets(outputs, file);
      // A declared statement that has never been built is in no report yet.
      const declared = deps.declared.declarationFor(document.uri);
      if (targets.length === 0 && declared?.asset.role === 'statement') {
        targets.push({ command: 'statements', root: declared.root });
      }
      targets.forEach(schedule);
    }),
  );
}

export function registerStatementPreview(deps: PreviewDeps): void {
  const syncContext = async () => {
    // The editor button keys on this list, as the run button keys on
    // `rbx.solutionFiles`: declared statements, plus every source a report
    // names (a contest's statement file is declared by no problem).
    const files = new Set(deps.declared.statementPaths());
    for (const root of await deps.reports.roots()) {
      for (const output of await deps.reports.outputs(root)) {
        if (output.source !== undefined) {
          files.add(output.source);
        }
      }
    }
    void vscode.commands.executeCommand('setContext', 'rbx.statementFiles', [...files]);
  };
  void syncContext();

  deps.context.subscriptions.push(
    deps.declared.onDidChange(() => void syncContext()),
    deps.reports.onDidChange(() => void syncContext()),
    vscode.commands.registerCommand('rbx.openStatementPreview', (uri?: unknown) =>
      StatementPreviewPanel.show(deps, uri instanceof vscode.Uri ? uri : undefined),
    ),
    vscode.commands.registerCommand('rbx.buildStatements', async (uri?: unknown) => {
      const focused = StatementPreviewPanel.focusedBuild();
      if (focused !== undefined && !(uri instanceof vscode.Uri)) {
        await deps.dispatcher.dispatch(focused);
        return;
      }
      const target = await targetFor(
        deps,
        uri instanceof vscode.Uri ? uri : vscode.window.activeTextEditor?.document.uri,
      );
      if (target === undefined) {
        void vscode.window.showInformationMessage('No rbx problem found in this workspace.');
        return;
      }
      await deps.dispatcher.dispatch({
        command: statementCommand(await scopeOf(target.root), 'statement'),
        root: target.root,
      });
    }),
  );
  registerBuildOnSave(deps);
}
