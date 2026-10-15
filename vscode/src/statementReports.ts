/**
 * The statement build reports in the workspace, kept current.
 *
 * One watcher and one cache for everything that reads them -- the preview and
 * the Problems panel -- so a build that finishes is read once, not once per
 * reader. The report is rewritten atomically by rbx after every output, so a
 * change event always lands on a whole file.
 */
import * as fs from 'fs/promises';
import * as path from 'path';
import * as vscode from 'vscode';

import { YamlFileCache } from './rbx/fileReader';
import { CACHE_DIR } from './rbx/layout';
import {
  ReportScope,
  StatementOutput,
  parseStatementReport,
  statementReportPath,
} from './rbx/statementReport';

const REPORT_GLOB = `**/${CACHE_DIR}/statements/report.yml`;

/** The root a report belongs to: three levels up from the file. */
function rootOf(reportFile: string): string {
  return path.dirname(path.dirname(path.dirname(reportFile)));
}

async function exists(file: string): Promise<boolean> {
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
  }
}

/**
 * A problem's report sits beside its `problem.rbx.yml`; anything else with a
 * report is a contest. Only labels, the default pick and the build command
 * depend on which, so a wrong guess costs a label, never data.
 */
export async function scopeOf(root: string): Promise<ReportScope> {
  return (await exists(path.join(root, 'problem.rbx.yml'))) ? 'problem' : 'contest';
}

export class StatementReports implements vscode.Disposable {
  private readonly cache = new YamlFileCache();
  private readonly scopes = new Map<string, ReportScope>();
  /** Every root with a report: scanned once, then kept by the watcher. */
  private known?: Promise<Set<string>>;
  private readonly emitter = new vscode.EventEmitter<string>();
  private readonly disposables: vscode.Disposable[] = [this.emitter];

  /** Fires with the root whose report changed. */
  readonly onDidChange = this.emitter.event;

  constructor() {
    const watcher = vscode.workspace.createFileSystemWatcher(REPORT_GLOB);
    const touched = (uri: vscode.Uri, exists: boolean) => {
      const root = rootOf(uri.fsPath);
      this.cache.forget(uri.fsPath);
      void this.known?.then((roots) => (exists ? roots.add(root) : roots.delete(root)));
      this.emitter.fire(root);
    };
    this.disposables.push(
      watcher,
      watcher.onDidCreate((uri) => touched(uri, true)),
      watcher.onDidChange((uri) => touched(uri, true)),
      watcher.onDidDelete((uri) => touched(uri, false)),
    );
  }

  /** Every root in the workspace with a report, for the Problems panel. */
  async roots(): Promise<string[]> {
    this.known ??= Promise.resolve(
      vscode.workspace.findFiles(REPORT_GLOB, '**/node_modules/**'),
    ).then((files) => new Set(files.map((uri) => rootOf(uri.fsPath))));
    return [...(await this.known)];
  }

  /** The outputs in `root`'s report; none when it has no report rbx can read. */
  async outputs(root: string): Promise<StatementOutput[]> {
    const read = await this.cache.read(statementReportPath(root));
    if (read.kind !== 'ok') {
      return [];
    }
    let scope = this.scopes.get(root);
    if (scope === undefined) {
      scope = await scopeOf(root);
      this.scopes.set(root, scope);
    }
    return parseStatementReport(read.value, root, scope);
  }

  dispose(): void {
    this.disposables.forEach((disposable) => disposable.dispose());
  }
}
