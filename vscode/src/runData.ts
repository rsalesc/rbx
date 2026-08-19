/**
 * Package discovery and the artifact cache behind the run view.
 *
 * Split out of the old tree provider so that nothing about *drawing* the view
 * lives next to what feeds it: this half talks to the workspace and the disk,
 * the webview half turns what it loads into rows. The two meet at
 * `PackageRunView`, which carries no editor API.
 */
import * as vscode from 'vscode';

import { discoverPackages, packageLabel } from './discovery';
import { log } from './log';
import { PackageLayout } from './rbx/layout';
import { PackageRunView } from './rbx/nodes';
import { ArtifactStore, PackageRun } from './rbx/store';

export class RunDataProvider {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChange: vscode.Event<void> = this.changed.event;

  private packages: PackageLayout[] = [];
  private readonly stores = new Map<string, ArtifactStore>();
  /**
   * In-flight or completed discovery.
   *
   * Discovery must be tracked explicitly rather than inferred from
   * `packages.length`: a workspace with no rbx package is a legitimate steady
   * state, and re-running discovery whenever the list is empty would have a
   * load fire the change event, which makes the consumer load again -- an
   * endless loop behind a permanently empty view.
   */
  private discovery?: Promise<void>;

  /** Reload everything: rediscover packages and drop all cached artifacts. */
  async refresh(): Promise<void> {
    this.discovery = this.discover();
    await this.discovery;
    this.changed.fire();
  }

  private async ensureDiscovered(): Promise<void> {
    if (this.discovery === undefined) {
      this.discovery = this.discover();
    }
    await this.discovery;
  }

  private async discover(): Promise<void> {
    this.packages = await discoverPackages();
    log(
      this.packages.length === 0
        ? 'No problem.rbx.yml found in the workspace.'
        : `Found ${this.packages.length} package(s): ${this.packages.map((p) => p.root).join(', ')}`,
    );
    const roots = new Set(this.packages.map((pkg) => pkg.root));
    for (const root of this.stores.keys()) {
      if (!roots.has(root)) {
        this.stores.delete(root);
      }
    }
    for (const store of this.stores.values()) {
      store.invalidate();
    }
  }

  /**
   * The discovered packages, waiting for discovery if it has not run yet.
   *
   * Exposed so the Explorer decorations reuse this discovery rather than
   * globbing the workspace a second time, and so both surfaces always agree on
   * which directories are rbx packages.
   */
  async discovered(): Promise<readonly PackageLayout[]> {
    await this.ensureDiscovered();
    return this.packages;
  }

  /** Drop cached artifacts for one package, in response to a filesystem event. */
  invalidate(root: string): void {
    this.stores.get(root)?.invalidate();
    this.changed.fire();
  }

  private storeFor(pkg: PackageLayout): ArtifactStore {
    let store = this.stores.get(pkg.root);
    if (store === undefined) {
      store = new ArtifactStore(pkg);
      this.stores.set(pkg.root, store);
    }
    return store;
  }

  report(pkg: PackageLayout): Promise<PackageRun | undefined> {
    return this.storeFor(pkg).load();
  }

  /**
   * Every discovered package paired with whatever run is on disk for it.
   *
   * Packages with no readable run are kept rather than filtered: `flattenNodes`
   * already drops them, and the rule that hides the package level counts
   * *discovered* packages, so dropping them here would make the view gain and
   * lose a level as runs come and go.
   */
  async loadAll(): Promise<PackageRunView[]> {
    await this.ensureDiscovered();
    const views: PackageRunView[] = [];
    for (const pkg of this.packages) {
      const run = await this.report(pkg);
      if (run === undefined) {
        log(`No readable run for ${pkg.root} -- run \`rbx run\` in that directory.`);
      } else {
        log(`${pkg.root}: ${run.solutions.length} solution(s) in the last run.`);
      }
      views.push({ pkg, run, label: packageLabel(pkg) });
    }
    return views;
  }
}
