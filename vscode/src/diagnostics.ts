/**
 * The compile phase in the Problems panel.
 *
 * The seam, and nothing else: what each entry says and which file it lands on
 * is decided in `rbx/diagnostics.ts`, which has no `vscode` import and is
 * tested. This half owns the one thing that cannot be tested -- the
 * `DiagnosticCollection` -- and the rule for keeping it in step with the run.
 *
 * Diagnostics rather than a second view, because Problems is already where a
 * setter looks for "what is wrong with this file", and an entry there works
 * whether or not the file is open, shows in the editor gutter when it is, and
 * is reachable with F8 without the sidebar being visible at all.
 */
import * as vscode from 'vscode';

import { artifactUri } from './artifactFs';
import { Finding, buildDiagnostics, byFile } from './rbx/diagnostics';
import { RunDataProvider } from './runData';

const SETTING = 'rbx.compilationDiagnostics';

/** `rbx`, the source shown in the Problems row. */
const SOURCE = 'rbx';

function enabled(): boolean {
  return vscode.workspace.getConfiguration().get<boolean>(SETTING, true);
}

function severityOf(finding: Finding): vscode.DiagnosticSeverity {
  return finding.severity === 'error'
    ? vscode.DiagnosticSeverity.Error
    : vscode.DiagnosticSeverity.Warning;
}

/**
 * The `code` cell, which does double duty.
 *
 * A warning spends it on the flag, the way every linter in the product does --
 * `rbx(-Wshadow)` is a thing a reader can search for. An error has no flag and
 * a message that is deliberately a summary, so it spends the cell on a link to
 * the compiler output instead: `code.target` is the one place in a diagnostic
 * that can carry a URI the reader can click.
 */
function codeOf(finding: Finding): vscode.Diagnostic['code'] {
  if (finding.severity === 'warning') {
    return finding.flag;
  }
  return {
    value: 'compiler output',
    target: artifactUri(finding.logPath, 'compile.log'),
  };
}

function toDiagnostic(finding: Finding): vscode.Diagnostic {
  // The whole line, not a column: rbx publishes the line a warning is on and
  // not the column within it, and inventing a column would underline the wrong
  // characters. `MAX_SAFE_INTEGER` is clamped to the real end of the line by
  // VS Code.
  const range = new vscode.Range(finding.line, 0, finding.line, Number.MAX_SAFE_INTEGER);
  const diagnostic = new vscode.Diagnostic(range, finding.message, severityOf(finding));
  diagnostic.source = SOURCE;
  diagnostic.code = codeOf(finding);
  return diagnostic;
}

export function registerDiagnostics(
  context: vscode.ExtensionContext,
  data: RunDataProvider,
): void {
  const collection = vscode.languages.createDiagnosticCollection('rbx');
  context.subscriptions.push(collection);

  const refresh = async (): Promise<void> => {
    // Cleared and rebuilt whole rather than diffed. The findings are a handful
    // of entries and they all come from one file that is rewritten at once, so
    // a diff would be machinery in exchange for nothing -- and a stale entry
    // here is a setter chasing a warning they already fixed.
    collection.clear();
    if (!enabled()) {
      return;
    }
    const packages = await data.loadAll();
    for (const [file, findings] of byFile(buildDiagnostics(packages))) {
      collection.set(vscode.Uri.file(file), findings.map(toDiagnostic));
    }
  };

  context.subscriptions.push(
    data.onDidChange(() => void refresh()),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(SETTING)) {
        void refresh();
      }
    }),
  );

  void refresh();
}
