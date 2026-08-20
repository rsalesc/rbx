/**
 * Puts a solution's declaration on a line of its own, above line one.
 *
 * ## Why a CodeLens and not a decoration
 *
 * VS Code has no banner API, and the obvious substitute -- a whole-line
 * decoration whose `before` attachment is forced onto its own line with
 * `display: block` -- cannot work, however the CSS is written. The extension
 * host passes only a fixed set of properties through to the editor
 * (`contentText`, `margin`, `width`, `height`, colours, `textDecoration`), and
 * none of them asks the editor to make the line taller. The line box stays one
 * line high, so the block lands *on top of* the code rather than above it.
 *
 * A CodeLens is the only stable API that gets a line: the editor renders one by
 * adding a **view zone** above the lens's range, which is real reserved space
 * and so cannot overlap anything. What it costs is colour -- a lens is drawn in
 * `editorCodeLens.foreground`, with no per-lens override -- which is why the
 * expectation's hue stays with the Explorer badge and the tab, and the lens
 * carries the badge as a codicon and the declaration in words instead.
 *
 * The alternative that is neither -- `createWebviewTextEditorInset` -- is still
 * proposed API and cannot ship in a published extension.
 */
import * as vscode from 'vscode';

import { DeclaredIndex } from './declared';
import { declarationFor, lensTitle } from './rbx/declaration';

const SETTING = 'rbx.solutionCodeLens';

/** Opens the Run view; VS Code registers `<viewId>.focus` for every view. */
const REVEAL = 'rbx.run.focus';

export class SolutionLensProvider implements vscode.CodeLensProvider {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses: vscode.Event<void> = this.changed.event;

  constructor(private readonly declared: DeclaredIndex) {}

  provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
    if (!enabled()) {
      return [];
    }
    const asset = this.declared.assetFor(document.uri);
    if (asset === undefined) {
      return [];
    }
    const declaration = declarationFor(asset);
    if (declaration === undefined) {
      return [];
    }
    return [
      new vscode.CodeLens(new vscode.Range(0, 0, 0, 0), {
        title: lensTitle(declaration),
        tooltip: declaration.tooltip,
        command: REVEAL,
      }),
    ];
  }

  /** Re-ask VS Code for the lens, after the manifest changed or a setting did. */
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

export function registerSolutionLens(
  context: vscode.ExtensionContext,
  declared: DeclaredIndex,
): SolutionLensProvider {
  const provider = new SolutionLensProvider(declared);
  context.subscriptions.push(
    provider,
    // Every file on disk, because which ones are solutions is a fact about the
    // manifest rather than about the language: a solution can be written in
    // anything rbx can compile.
    vscode.languages.registerCodeLensProvider({ scheme: 'file' }, provider),
    declared.onDidChange(() => provider.refresh()),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(SETTING)) {
        provider.refresh();
      }
    }),
  );
  return provider;
}
