/**
 * Package discovery and the artifact cache behind the run view.
 *
 * Split out of the old tree provider so that nothing about *drawing* the view
 * lives next to what feeds it: this half talks to the workspace and the disk,
 * the webview half turns what it loads into rows. The two meet at `PackageRun`,
 * which carries no editor API.
 */
import * as os from 'os';
import * as vscode from 'vscode';

import { VisualizerDeclarations } from './rbx/declaredVisualizers';
import { discoverPackages } from './discovery';
import { log } from './log';
import { RefreshPlan } from './rbx/artifactEvents';
import { PackageFindings } from './rbx/diagnostics';
import { PackageLayout } from './rbx/layout';
import { ArtifactStore, ArtifactStores, PackageRun, StoreTrace } from './rbx/store';
import { StressManifest, stressLiveness } from './rbx/stress';
import { Testset } from './rbx/testset';

/**
 * What a change event is about, so a listener can skip what it does not read.
 *
 * `root` and `plan` are both absent after a rediscovery, which may have moved
 * anything in any package.
 */
export interface RunDataChange {
  readonly root?: string;
  readonly plan?: RefreshPlan;
}

function traceLine({ root, reason, stats, ms }: StoreTrace): string {
  const parts = [`${stats.reads} read`];
  if (stats.hits > 0) {
    parts.push(`${stats.hits} unchanged`);
  }
  if (stats.errors > 0) {
    parts.push(`${stats.errors} failed`);
  }
  return `Artifacts in ${root}: ${reason}, ${parts.join(', ')} in ${ms} ms.`;
}

export class RunDataProvider {
  private readonly changed = new vscode.EventEmitter<RunDataChange>();
  readonly onDidChange: vscode.Event<RunDataChange> = this.changed.event;

  private packages: PackageLayout[] = [];
  // Every load and patch is logged with what it read: the instrumentation the
  // incremental refresh (#902) is checked against -- one `.eval` landing
  // should read one file, not the run.
  private readonly stores = new ArtifactStores(
    (pkg) => new ArtifactStore(pkg, { trace: (trace) => log(traceLine(trace)) }),
  );
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
    this.changed.fire({});
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
    // Also drops the store of a package whose build directory moved: the
    // preset watcher rediscovers precisely so paths get repointed.
    this.stores.retain(this.packages);
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

  /** Bring one package's cache in step with a batch of filesystem events. */
  apply(root: string, plan: RefreshPlan): void {
    this.stores.apply(root, plan);
    this.changed.fire({ root, plan });
  }

  private storeFor(pkg: PackageLayout): ArtifactStore {
    return this.stores.for(pkg);
  }

  /**
   * Whatever run is on disk for one package, or undefined if none is readable.
   *
   * A package with no readable run is not an error: one that has never been run
   * still has to be selectable, and `flattenNodes` renders it as nothing.
   */
  report(pkg: PackageLayout): Promise<PackageRun | undefined> {
    return this.storeFor(pkg).load();
  }

  /**
   * Whatever testset the last `rbx build` published for one package.
   *
   * Through the same store as `report`, which is the whole point: the run and
   * the testset describe one package and are dropped by one watcher tick, so
   * the Run and Tests views cannot end up disagreeing about which package they
   * are showing. A missing manifest is not an error -- it is what a package
   * that has never been built looks like.
   */
  testset(pkg: PackageLayout): Promise<Testset | undefined> {
    return this.storeFor(pkg).testset();
  }

  /**
   * The latest stress session `rbx stress` published for one package.
   *
   * A listener re-reads it when `touchesStress(change.plan)` holds; a run
   * landing never does, and a stress session never moves the run. A missing
   * manifest is what a package that has never been stressed looks like.
   */
  stress(pkg: PackageLayout): Promise<StressManifest | undefined> {
    return this.storeFor(pkg).stress();
  }

  /** What `problem.rbx.yml` declares about visualizers, for the lazy buttons. */
  visualizers(pkg: PackageLayout): Promise<VisualizerDeclarations | undefined> {
    return this.storeFor(pkg).visualizers();
  }

  /**
   * Every discovered package's compile findings.
   *
   * For the Problems panel, which is workspace-wide on purpose: it reports a
   * compile error in problem B while you are reading problem A. It reads only
   * each package's skeleton -- never an `.eval` -- since that is all the
   * findings come from.
   */
  async findingsAll(): Promise<PackageFindings[]> {
    const packages = await this.discovered();
    return Promise.all(
      packages.map(async (pkg) => ({ pkg, findings: await this.storeFor(pkg).findings() })),
    );
  }
}

/**
 * Whether a process is alive on this host.
 *
 * Signal 0 delivers nothing and only checks: ESRCH means no such process,
 * EPERM means one exists that this user may not signal. That one is alive,
 * and reading it as dead would call a live session stale.
 */
function processAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === 'EPERM';
  }
}

/**
 * `stressLiveness` against this host's name and process table. `unknown` is
 * for the caller to settle with `Dispatcher.isRunning`.
 */
export function stressLivenessHere(manifest: StressManifest): 'live' | 'stale' | 'unknown' {
  return stressLiveness(manifest, { hostname: os.hostname(), isAlive: processAlive });
}
