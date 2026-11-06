/**
 * Ways into the time-profile editor that do not go through the file itself:
 *
 * - a status-bar item for the active problem, showing its `local` limit;
 * - a CodeLens over `timeLimit:` in `problem.rbx.yml`, one per profile.
 *
 * Both only *display* the base `timeLimit` a profile stores -- the number a
 * setter wrote or rbx estimated -- and decide nothing about it. Everything
 * else is in the editor they open.
 */
import * as fs from 'fs/promises';
import * as path from 'path';
import * as vscode from 'vscode';
import { parse as parseYaml } from 'yaml';

import { ActiveProblem } from './activeProblem';
import { LIMITS_EDITOR_VIEW_TYPE, listProfiles } from './limitsEditor';

/** The profile a plain `rbx run` is judged against (rbx's DEFAULT_RUN_PROFILE). */
const RUN_PROFILE = 'local';

interface ProfileSummary {
  readonly name: string;
  readonly uri: vscode.Uri;
  readonly timeLimit?: number;
  readonly inherits: boolean;
}

async function summarize(root: string, name: string): Promise<ProfileSummary> {
  const file = path.join(root, '.limits', `${name}.yml`);
  const uri = vscode.Uri.file(file);
  try {
    const data = parseYaml(await fs.readFile(file, 'utf8')) as Record<string, unknown> | null;
    return {
      name,
      uri,
      timeLimit: typeof data?.timeLimit === 'number' ? data.timeLimit : undefined,
      inherits: data?.inheritFromPackage === true,
    };
  } catch {
    return { name, uri, inherits: false };
  }
}

function describe(p: ProfileSummary): string {
  if (p.inherits) return 'problem.rbx.yml limits';
  return p.timeLimit !== undefined ? `${p.timeLimit} ms` : '—';
}

function openCommand(uri: vscode.Uri, title: string): vscode.Command {
  return { command: 'vscode.openWith', title, arguments: [uri, LIMITS_EDITOR_VIEW_TYPE] };
}

class TimeLimitStatus implements vscode.Disposable {
  private readonly item = vscode.window.createStatusBarItem('rbx.timeProfile', vscode.StatusBarAlignment.Left, 49);

  constructor(private readonly active: ActiveProblem) {
    this.item.name = 'rbx Time Limit';
    this.item.command = 'rbx.openTimeProfile';
  }

  async update(): Promise<void> {
    const root = this.active.selected();
    if (root === undefined) {
      this.item.hide();
      return;
    }
    const profiles = await listProfiles(root);
    if (profiles.length === 0) {
      this.item.text = '$(watch) no time profile';
      this.item.tooltip = 'This problem has no limits profile yet. Click to estimate one.';
    } else {
      const shown = profiles.includes(RUN_PROFILE) ? RUN_PROFILE : profiles[0];
      const summary = await summarize(root, shown);
      this.item.text = `$(watch) ${describe(summary)} · ${shown}`;
      const others = profiles.filter((p) => p !== shown);
      this.item.tooltip = new vscode.MarkdownString(
        `**Time limit** of the \`${shown}\` profile.` +
          (others.length > 0 ? `\n\nAlso: ${others.map((o) => `\`${o}\``).join(', ')}` : '') +
          '\n\nClick to open the time profile.',
      );
    }
    this.item.show();
  }

  dispose(): void {
    this.item.dispose();
  }
}

class TimeProfileLens implements vscode.CodeLensProvider {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this.changed.event;

  refresh(): void {
    this.changed.fire();
  }

  async provideCodeLenses(document: vscode.TextDocument): Promise<vscode.CodeLens[]> {
    if (path.basename(document.uri.fsPath) !== 'problem.rbx.yml') return [];
    const root = path.dirname(document.uri.fsPath);
    const text = document.getText();
    const match = /^timeLimit\s*:/m.exec(text);
    const line = match ? document.positionAt(match.index).line : 0;
    const range = new vscode.Range(line, 0, line, 0);
    const profiles = await listProfiles(root);
    if (profiles.length === 0) {
      return [new vscode.CodeLens(range, { command: 'rbx.openTimeProfile', title: '$(watch) Estimate a time profile' })];
    }
    const summaries = await Promise.all(profiles.map((p) => summarize(root, p)));
    return summaries.map(
      (s, i) => new vscode.CodeLens(range, openCommand(s.uri, `${i === 0 ? '$(watch) ' : ''}${s.name}: ${describe(s)}`)),
    );
  }
}

export function registerLimitsEntryPoints(context: vscode.ExtensionContext, active: ActiveProblem): void {
  const status = new TimeLimitStatus(active);
  const lens = new TimeProfileLens();
  const refresh = (): void => {
    void status.update();
    lens.refresh();
  };
  const watcher = vscode.workspace.createFileSystemWatcher('**/.limits/*.yml');
  watcher.onDidChange(refresh);
  watcher.onDidCreate(refresh);
  watcher.onDidDelete(refresh);
  context.subscriptions.push(
    status,
    watcher,
    active.onDidChange(refresh),
    vscode.languages.registerCodeLensProvider({ scheme: 'file', pattern: '**/problem.rbx.yml' }, lens),
  );
  void status.update();
}
