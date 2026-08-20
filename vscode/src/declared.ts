/**
 * What every discovered `problem.rbx.yml` declares, keyed by absolute path.
 *
 * One index, read once per manifest change, because two channels now draw the
 * same fact: the Explorer badge (decorations.ts) and the banner above line one
 * of a solution (solutionBanner.ts). Reading the manifest twice would let them
 * disagree for as long as the two reads are apart -- which is exactly the
 * window in which the setter is editing the file.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { log } from './log';
import { PackageLayout, manifestPath } from './rbx/layout';
import { DeclaredAsset, parseManifest } from './rbx/manifest';
import { readYamlFile } from './rbx/store';
import { RunDataProvider } from './runData';

export class DeclaredIndex {
  private readonly changed = new vscode.EventEmitter<void>();
  /** Fired after every re-read, whether or not anything actually moved. */
  readonly onDidChange: vscode.Event<void> = this.changed.event;

  private index = new Map<string, DeclaredAsset>();

  constructor(private readonly data: RunDataProvider) {}

  /** Re-read every discovered package's manifest. */
  async refresh(): Promise<void> {
    const packages = await this.data.discovered();
    const next = new Map<string, DeclaredAsset>();
    for (const pkg of packages) {
      await this.indexPackage(pkg, next);
    }
    this.index = next;
    log(`Indexed ${this.index.size} declared file(s).`);
    this.changed.fire();
  }

  private async indexPackage(
    pkg: PackageLayout,
    into: Map<string, DeclaredAsset>,
  ): Promise<void> {
    const raw = await readYamlFile(manifestPath(pkg));
    if (raw === undefined) {
      return;
    }
    for (const asset of parseManifest(raw)) {
      // Declared paths are relative to the package root. `resolve` also leaves
      // an absolute one alone, which rbx permits and some packages use.
      into.set(path.resolve(pkg.root, asset.path), asset);
    }
  }

  /**
   * What `uri` is declared as, or `undefined` for a file no manifest names.
   *
   * Anything that is not a file on disk is undeclared by construction:
   * artifacts opened through the extension's own read-only scheme are not
   * workspace files and must never be drawn as if they were.
   */
  assetFor(uri: vscode.Uri): DeclaredAsset | undefined {
    return uri.scheme === 'file' ? this.index.get(uri.fsPath) : undefined;
  }

  /** How many files are declared across the workspace. */
  get size(): number {
    return this.index.size;
  }

  dispose(): void {
    this.changed.dispose();
  }
}
