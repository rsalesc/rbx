/**
 * Shows what each `\VAR{...}` in a statement expands to, beside the reference.
 *
 * ## Why an inlay hint
 *
 * The value belongs *between* two characters of the line rather than on a line
 * of its own, which is exactly what an inlay hint is: the editor reserves
 * horizontal space for it, so nothing is drawn over the LaTeX. A decoration's
 * `after` attachment could paint the same text, but only at the end of a line
 * -- there is no way to attach one mid-line -- and a constraints block routinely
 * names two bounds on one line. Inlay hints also come with a user-facing
 * toggle, a hover, and the editor's own re-request on every document change,
 * none of which a decoration gets for free.
 */
import * as vscode from 'vscode';

import { DeclaredIndex } from './declared';
import { scanStatementVars } from './rbx/statementVars';
import { StatementVarsIndex } from './statementVarsIndex';

const SETTING = 'rbx.statementVarHints';

export class StatementVarHintsProvider implements vscode.InlayHintsProvider {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeInlayHints: vscode.Event<void> = this.changed.event;

  constructor(
    private readonly declared: DeclaredIndex,
    private readonly vars: StatementVarsIndex,
  ) {}

  async provideInlayHints(
    document: vscode.TextDocument,
    range: vscode.Range,
    token: vscode.CancellationToken,
  ): Promise<vscode.InlayHint[]> {
    if (!enabled()) {
      return [];
    }
    // The manifest is the authority on which files are statements; it also
    // covers tutorials, which globbing `*.rbx.tex` would miss.
    if (this.declared.assetFor(document.uri)?.role !== 'statement') {
      return [];
    }
    const root = this.declared.rootFor(document.uri);
    if (root === undefined) {
      return [];
    }

    // Never rejects -- `StatementVarsIndex.varsFor` catches its own failures
    // and answers `undefined` -- so there is nothing here to guard against.
    const vars = await this.vars.varsFor(root);
    // The await is the only suspension point, and the first request for a cold
    // package waits on a process spawn behind it. By the time it answers, the
    // editor may well have asked again for a range that has since scrolled or
    // been edited; returning hints for the old one is what the token is for.
    if (vars === undefined || token.isCancellationRequested) {
      return [];
    }

    const hints: vscode.InlayHint[] = [];
    // The whole document is scanned and the result filtered, rather than the
    // requested range being sliced out: a reference may straddle the range's
    // edge, and offsets from a slice would all need shifting back. A statement
    // is a few kilobytes of prose, so the scan is not worth optimizing -- but a
    // pathologically large one would pay for it on every keystroke.
    for (const hint of scanStatementVars(document.getText(), vars)) {
      // `hint.end` is the offset just past the closing brace, so the hint sits
      // immediately after `}` and never inside the reference.
      const position = document.positionAt(hint.end);
      // Inclusive at both ends, which is the forgiving side to err on: a hint
      // exactly on the boundary is drawn rather than dropped, and the editor
      // accepts hints outside the range it asked for anyway.
      if (!range.contains(position)) {
        continue;
      }
      const inlay = new vscode.InlayHint(position, hint.text);
      // The editor's own leading gap, rather than a space in the label: a
      // space would be padding *inside* the hint's own background, and would
      // stack with this if both were used.
      inlay.paddingLeft = true;
      hints.push(inlay);
    }
    return hints;
  }

  /** Re-ask VS Code for the hints, after the vars changed or a setting did. */
  refresh(): void {
    this.changed.fire();
  }

  dispose(): void {
    this.changed.dispose();
  }
}

function enabled(): boolean {
  return vscode.workspace.getConfiguration().get<boolean>(SETTING, true);
}

export function registerStatementVarHints(
  context: vscode.ExtensionContext,
  declared: DeclaredIndex,
  vars: StatementVarsIndex,
): StatementVarHintsProvider {
  const provider = new StatementVarHintsProvider(declared, vars);
  context.subscriptions.push(
    provider,
    // Every file on disk, because which ones are statements is a fact about
    // the manifest rather than about the language: rbxTeX, plain LaTeX and
    // Markdown are all spelled by different language ids.
    vscode.languages.registerInlayHintsProvider({ scheme: 'file' }, provider),
    // Both indexes, because either can be the one that changed. The vars index
    // answers what a reference expands to; the declared index answers whether
    // this file is a statement at all, and it is empty until the first
    // discovery finishes -- without this, a statement open at startup would
    // show nothing until it was next edited.
    vars.onDidChange(() => provider.refresh()),
    declared.onDidChange(() => provider.refresh()),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(SETTING)) {
        provider.refresh();
      }
    }),
  );
  return provider;
}
