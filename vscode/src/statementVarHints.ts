/**
 * Shows what each `\VAR{...}` in a statement expands to, beside the reference.
 *
 * ## Why an inlay hint
 *
 * The value belongs *between* two characters of the line rather than on a line
 * of its own, which is what an inlay hint is: the editor reserves horizontal
 * space for it and pushes the rest of the line along, so nothing is drawn over
 * the LaTeX. An `after` decoration on a zero-width range could paint the same
 * text in the same place, but it would be ours to place and to place again: a
 * decoration is set on one editor at a time, so every split, every newly
 * revealed statement and every re-scan is ours to drive. And it would carry no
 * `editor.inlayHints.enabled` for a setter who wants the numbers out of the
 * way. The hint API asks us only to answer a range.
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
    // The manifest is the authority on which files are statements, because the
    // extension does not decide it: a statement is whatever `problem.rbx.yml`
    // names as one, in any format rbx converts. `StatementType.extension`
    // (rbx/box/statements/schema.py) alone spells `.rbx.tex`, `.md`, `.rbx.md`
    // and `.jinja.md`, so no glob over extensions is the same question.
    const declared = this.declared.declarationFor(document.uri);
    if (declared?.asset.role !== 'statement') {
      return [];
    }

    // Neither check is needed for correctness -- VS Code drops a cancelled
    // request's result whatever we hand back. They are early-outs. The first
    // matters most: typing hands a provider an already-cancelled token quite
    // routinely, and answering it immediately skips the round-trip below.
    if (token.isCancellationRequested) {
      return [];
    }
    // Never rejects -- `StatementVarsIndex.varsFor` catches its own failures
    // and answers `undefined` -- so there is nothing here to guard against.
    // It is also the only suspension point, and a cold package waits on a
    // process spawn behind it, which is time enough to be cancelled twice.
    const vars = await this.vars.varsFor(declared.root);
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
      // `contains` is inclusive at both ends, which is the side to err on: a
      // reference ending exactly on the boundary keeps its hint rather than
      // falling between two adjacent requests.
      if (!range.contains(position)) {
        continue;
      }
      const inlay = new vscode.InlayHint(position, hint.text);
      // The editor's own gaps, rather than spaces in the label: a space would
      // be padding *inside* the hint's own background, and would stack with
      // these if both were used. Both sides, because a reference is as often
      // followed by a `$` or a `\)` as by a space, and a badge with a gap on
      // one side only reads as lopsided.
      inlay.paddingLeft = true;
      inlay.paddingRight = true;
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
    // the manifest rather than about the language: a statement can be written
    // in anything rbx can convert, and `.rbx.tex` has no language id of its
    // own to select on.
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
