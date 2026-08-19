/**
 * Keeps the declaration visible after you have scrolled past line one.
 *
 * The CodeLens (solutionLens.ts) scrolls away with the top of the file, and the
 * Explorer badge is out of the corner of your eye. A language status item is
 * the one channel that stays put: it sits in the status bar for as long as the
 * document it is scoped to is the active one, it can be pinned so it is always
 * on screen, and it is the VS Code affordance that already means "something
 * about the file you are editing" -- which is exactly what a declaration is.
 *
 * Its `selector` is set to the active file itself rather than to a language or
 * a glob over the workspace. Two things follow: the item is shown for declared
 * solutions and nothing else, and its text can never be about a different file
 * from the one it is scoped to, because both are set in the same call.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { DeclaredIndex } from './declared';
import { declarationFor, statusDetail, statusText } from './rbx/declaration';

const SETTING = 'rbx.solutionStatus';

/** Opens the Run view; VS Code registers `<viewId>.focus` for every view. */
const REVEAL = 'rbx.run.focus';

export class SolutionStatus {
  private readonly item = vscode.languages.createLanguageStatusItem('rbx.solution', []);

  constructor(private readonly declared: DeclaredIndex) {
    this.item.name = 'rbx solution';
    this.item.command = { command: REVEAL, title: 'Open the rbx Run view' };
    // Always informational. Severity in this bar means "something is wrong",
    // and a declaration never is: `outcome: wrong-answer` on a solution that is
    // meant to answer wrongly is the package working. A *miss* is the thing
    // that deserves a severity, and it belongs to the run, not to this.
    this.item.severity = vscode.LanguageStatusSeverity.Information;
  }

  /** Re-scope and re-word the item for whatever is now the active editor. */
  refresh(): void {
    const document = vscode.window.activeTextEditor?.document;
    const asset = document === undefined ? undefined : this.declared.assetFor(document.uri);
    const declaration = asset === undefined ? undefined : declarationFor(asset);
    if (document === undefined || declaration === undefined || !enabled()) {
      // An empty selector matches no document, which is how a language status
      // item is hidden: there is no `visible` to set.
      this.item.selector = [];
      return;
    }
    this.item.text = statusText(declaration);
    this.item.detail = statusDetail(declaration);
    this.item.selector = scopeTo(document.uri);
  }

  dispose(): void {
    this.item.dispose();
  }
}

/**
 * A selector matching exactly one file.
 *
 * `RelativePattern` rather than the path as a glob string: a directory in the
 * path is then matched literally, so a package living under `a[1]/` -- which
 * is a perfectly ordinary contest layout -- does not read as a character class.
 * The file name itself is still a pattern, which is the residual case this
 * accepts.
 */
function scopeTo(uri: vscode.Uri): vscode.DocumentFilter {
  const base = vscode.Uri.file(path.dirname(uri.fsPath));
  return { scheme: 'file', pattern: new vscode.RelativePattern(base, path.basename(uri.fsPath)) };
}

function enabled(): boolean {
  return vscode.workspace.getConfiguration().get<boolean>(SETTING, true);
}

export function registerSolutionStatus(
  context: vscode.ExtensionContext,
  declared: DeclaredIndex,
): SolutionStatus {
  const status = new SolutionStatus(declared);
  context.subscriptions.push(
    status,
    vscode.window.onDidChangeActiveTextEditor(() => status.refresh()),
    declared.onDidChange(() => status.refresh()),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(SETTING)) {
        status.refresh();
      }
    }),
  );
  return status;
}
