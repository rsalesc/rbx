/**
 * Badges every file `problem.rbx.yml` declares, in the Explorer and on tabs.
 *
 * This is the only channel that can say what a solution promises *while you are
 * editing it*: a webview cannot decorate an Explorer row, and the run view is
 * not open when you are in another editor group. It is also the only one that
 * works before `rbx run` has ever been invoked, which is why it reads the
 * manifest rather than `.rbx/runs` (see manifest.ts).
 *
 * What the colour means here is the *declaration*, not the last run. That is a
 * deliberate reversal of the rule this started from (#666), and it costs the
 * Explorer any way of showing a solution that missed: the badge budget is two
 * characters and both are already spent distinguishing expectations that share
 * a colour. A miss is surfaced in the run view instead, which has the room for
 * it.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { log } from './log';
import { BadgeDecoration, decorationFor } from './rbx/decoration';
import { PackageLayout, manifestPath } from './rbx/layout';
import { parseManifest } from './rbx/manifest';
import { readYamlFile } from './rbx/store';
import { RunDataProvider } from './runData';

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

  private index = new Map<string, BadgeDecoration>();

  constructor(private readonly data: RunDataProvider) {}

  /** Re-read every discovered package's manifest. */
  async refresh(): Promise<void> {
    const packages = await this.data.discovered();
    const next = new Map<string, BadgeDecoration>();
    for (const pkg of packages) {
      await this.indexPackage(pkg, next);
    }
    this.index = next;
    log(`Decorating ${this.index.size} declared file(s).`);
    this.changed.fire(undefined);
  }

  private async indexPackage(
    pkg: PackageLayout,
    into: Map<string, BadgeDecoration>,
  ): Promise<void> {
    const raw = await readYamlFile(manifestPath(pkg));
    if (raw === undefined) {
      return;
    }
    for (const asset of parseManifest(raw)) {
      const decoration = decorationFor(asset);
      if (decoration === undefined) {
        continue;
      }
      // Declared paths are relative to the package root. `resolve` also leaves
      // an absolute one alone, which rbx permits and some packages use.
      into.set(path.resolve(pkg.root, asset.path), decoration);
    }
  }

  provideFileDecoration(uri: vscode.Uri): vscode.FileDecoration | undefined {
    // Artifacts opened through the extension's own read-only scheme are not
    // files in the workspace and must never be badged as if they were.
    if (uri.scheme !== 'file') {
      return undefined;
    }
    if (!enabled()) {
      return undefined;
    }
    const decoration = this.index.get(uri.fsPath);
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

  /** Re-ask VS Code for every decoration, without re-reading any manifest. */
  restyle(): void {
    this.changed.fire(undefined);
  }
}

function enabled(): boolean {
  return vscode.workspace.getConfiguration().get<boolean>(SETTING, true);
}

export function registerDecorations(
  context: vscode.ExtensionContext,
  data: RunDataProvider,
): RbxDecorationProvider {
  const provider = new RbxDecorationProvider(data);
  context.subscriptions.push(
    provider,
    vscode.window.registerFileDecorationProvider(provider),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(SETTING)) {
        provider.restyle();
      }
    }),
  );
  return provider;
}
