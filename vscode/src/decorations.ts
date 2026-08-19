/**
 * Badges every file `problem.rbx.yml` declares, in the Explorer and on tabs.
 *
 * This and the banner above line one (solutionBanner.ts) are the only channels
 * that can say what a solution promises *while you are editing it*: a webview
 * cannot decorate an Explorer row, and the run view is not open when you are in
 * another editor group. They are also the only ones that work before `rbx run`
 * has ever been invoked, which is why they read the manifest rather than
 * `.rbx/runs` (see manifest.ts).
 *
 * What the colour means here is the *declaration*, not the last run. That is a
 * deliberate reversal of the rule this started from (#666), and it costs the
 * Explorer any way of showing a solution that missed: the badge budget is two
 * characters and both are already spent distinguishing expectations that share
 * a colour. A miss is surfaced in the run view instead, which has the room for
 * it.
 */
import * as vscode from 'vscode';

import { DeclaredIndex } from './declared';
import { log } from './log';
import { decorationFor } from './rbx/decoration';

const SETTING = 'rbx.decorateExplorer';

export class RbxDecorationProvider implements vscode.FileDecorationProvider {
  private readonly changed = new vscode.EventEmitter<undefined>();
  /**
   * Fired with `undefined`, meaning "re-ask about everything".
   *
   * The alternative -- naming the URIs that changed -- would have to include
   * the ones that *stopped* being declared, which are exactly the ones no
   * longer in the index and so cannot be enumerated from it.
   */
  readonly onDidChangeFileDecorations: vscode.Event<undefined> = this.changed.event;

  constructor(private readonly declared: DeclaredIndex) {}

  provideFileDecoration(uri: vscode.Uri): vscode.FileDecoration | undefined {
    if (!enabled()) {
      return undefined;
    }
    const asset = this.declared.assetFor(uri);
    if (asset === undefined) {
      return undefined;
    }
    const decoration = decorationFor(asset);
    if (decoration === undefined) {
      return undefined;
    }
    return {
      badge: decoration.badge,
      color: new vscode.ThemeColor(decoration.colorId),
      tooltip: decoration.tooltip,
    };
  }

  dispose(): void {
    this.changed.dispose();
  }

  /** Re-ask VS Code for every decoration. */
  restyle(): void {
    this.changed.fire(undefined);
  }
}

function enabled(): boolean {
  return vscode.workspace.getConfiguration().get<boolean>(SETTING, true);
}

export function registerDecorations(
  context: vscode.ExtensionContext,
  declared: DeclaredIndex,
): RbxDecorationProvider {
  const provider = new RbxDecorationProvider(declared);
  context.subscriptions.push(
    provider,
    vscode.window.registerFileDecorationProvider(provider),
    declared.onDidChange(() => {
      log(`Decorating ${declared.size} declared file(s).`);
      provider.restyle();
    }),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(SETTING)) {
        provider.restyle();
      }
    }),
  );
  return provider;
}
