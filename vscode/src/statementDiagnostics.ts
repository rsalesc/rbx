/**
 * Statement build errors in the Problems panel (#909).
 *
 * The seam only: which entries exist and where they land is decided by
 * `statementDiagnostics` in rbx/statementReport.ts, which is tested. rbx already
 * traced each error to the setter's own file and line -- the `.rbx.tex`, not
 * the `statement.tex` it was rendered into -- so this places them as given.
 *
 * A collection of its own, not the compile findings' `rbx` one: that one is
 * cleared and rebuilt whole on every run, and would wipe these with it.
 */
import * as vscode from 'vscode';

import { Latest } from './rbx/latest';
import { StatementDiagnostic, statementDiagnostics } from './rbx/statementReport';
import { StatementReports } from './statementReports';

const SETTING = 'rbx.statementDiagnostics';

function enabled(): boolean {
  return vscode.workspace.getConfiguration().get<boolean>(SETTING, true);
}

function toDiagnostic(entry: StatementDiagnostic): vscode.Diagnostic {
  // The whole line: rbx knows the line an error is on, never the column.
  const range = new vscode.Range(entry.line, 0, entry.line, Number.MAX_SAFE_INTEGER);
  const diagnostic = new vscode.Diagnostic(
    range,
    entry.message,
    entry.severity === 'error' ? vscode.DiagnosticSeverity.Error : vscode.DiagnosticSeverity.Warning,
  );
  // Which outputs failed on it: a template error breaks every language at once,
  // and that is worth knowing before fixing it.
  diagnostic.source = `rbx (${entry.outputs.join(', ')})`;
  diagnostic.code = entry.origin === 'latex' ? 'pdflatex' : entry.origin;
  return diagnostic;
}

export function registerStatementDiagnostics(
  context: vscode.ExtensionContext,
  reports: StatementReports,
): void {
  const collection = vscode.languages.createDiagnosticCollection('rbx-statements');
  context.subscriptions.push(collection);

  const refreshes = new Latest();
  const refresh = async (): Promise<void> => {
    const current = refreshes.begin();
    const outputs = enabled()
      ? (await Promise.all((await reports.roots()).map((root) => reports.outputs(root)))).flat()
      : [];
    if (!current()) {
      return;
    }
    const byFile = new Map<string, vscode.Diagnostic[]>();
    for (const entry of statementDiagnostics(outputs)) {
      const bucket = byFile.get(entry.path) ?? [];
      bucket.push(toDiagnostic(entry));
      byFile.set(entry.path, bucket);
    }
    collection.clear();
    for (const [file, diagnostics] of byFile) {
      collection.set(vscode.Uri.file(file), diagnostics);
    }
  };

  context.subscriptions.push(
    reports.onDidChange(() => void refresh()),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(SETTING)) {
        void refresh();
      }
    }),
  );
  void refresh();
}
