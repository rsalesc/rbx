/**
 * What a filesystem event under a package means for the artifacts read from it.
 *
 * The watchers used to answer one question -- "which package moved?" -- and the
 * store answered it by throwing the whole package away and re-reading every
 * `.eval` of the run. On a run of 20 solutions over 2,000 tests that is 40,000
 * reads per tick to take in one new file (#902). This module answers the finer
 * question instead: *which* artifact moved, so the store can do the smallest
 * correct thing about it.
 *
 * Pure path arithmetic, with no `vscode` import, so the rules are tested rather
 * than trusted. See layout.ts for the layout itself.
 */
import * as path from 'path';

import { CACHE_DIR, Ext, TESTSET_MANIFEST } from './layout';

/** One `.eval`, by the coordinates `runArtifactPath` builds its path from. */
export interface EvalKey {
  readonly solution: number;
  readonly group: string;
  readonly stem: string;
}

export type ArtifactEvent =
  /**
   * The cache directory itself, or `.rbx/runs` itself, appeared or vanished.
   * `rbx clean` removes `.rbx` in one call and the watcher reports only the top
   * directory, so nothing more specific will follow.
   */
  | { readonly kind: 'cache' }
  /** A new skeleton: a new run, whose `runs/` was just wiped. */
  | { readonly kind: 'skeleton' }
  /** The run's aggregates, rewritten as each solution finishes, or the end marker. */
  | { readonly kind: 'report' }
  /** One testcase of one solution was evaluated. */
  | ({ readonly kind: 'eval' } & EvalKey)
  /** `rbx build` published a testset. */
  | { readonly kind: 'testset' }
  /** `problem.rbx.yml` was edited: the visualizer declarations may have moved. */
  | { readonly kind: 'manifest' };

export interface PackageEvent {
  readonly root: string;
  readonly event: ArtifactEvent;
}

const SOLUTION_DIR = /^[0-9]+$/;

/**
 * Classify a path under some package's `.rbx`, or undefined to ignore it.
 *
 * Everything not named below is ignored on purpose: `.storage`, the dependency
 * caches, `.remote`, judge state, `runs/.irun` and `runs/.stress` all churn
 * during a build or a stress test, and none of them is read by anything here.
 * So are a run's `.out`/`.err`/`.log`/`.pio`, which the model holds only as
 * paths and which are opened on demand; and `runs/compilation/*`, whose findings
 * come from the skeleton rather than from the logs.
 */
export function classifyCachePath(fsPath: string): PackageEvent | undefined {
  const suffix = `${path.sep}${CACHE_DIR}`;
  if (fsPath.endsWith(suffix)) {
    return { root: fsPath.slice(0, -suffix.length), event: { kind: 'cache' } };
  }
  const marker = `${suffix}${path.sep}`;
  const index = fsPath.indexOf(marker);
  if (index === -1) {
    return undefined;
  }
  const root = fsPath.slice(0, index);
  const segments = fsPath.slice(index + marker.length).split(path.sep);
  if (segments[0] !== 'runs') {
    return undefined;
  }
  if (segments.length === 1) {
    return { root, event: { kind: 'cache' } };
  }
  if (segments.length === 2) {
    switch (segments[1]) {
      case 'skeleton.yml':
        return { root, event: { kind: 'skeleton' } };
      case 'report.yml':
        return { root, event: { kind: 'report' } };
      default:
        return undefined;
    }
  }
  // `runs/<i>/<group>/<stem>.eval`, and nothing deeper: a hand-typed `rbx
  // visualize output` lands in `runs/<i>/<group>/output_visualization/`, and
  // that carries no verdict.
  const [, solution, group, file] = segments;
  if (
    segments.length === 4 &&
    SOLUTION_DIR.test(solution) &&
    file.endsWith(Ext.Eval) &&
    file.length > Ext.Eval.length
  ) {
    return {
      root,
      event: {
        kind: 'eval',
        solution: Number(solution),
        group,
        stem: file.slice(0, -Ext.Eval.length),
      },
    };
  }
  return undefined;
}

/**
 * Classify any watched path: a run artifact, or a testset manifest.
 *
 * `testsetRootOf` decides whether a `testset.yml` is one of ours -- its build
 * directory is named by the preset, so only the caller can resolve it.
 */
export function classifyPath(
  fsPath: string,
  testsetRootOf: (fsPath: string) => string | undefined,
): PackageEvent | undefined {
  const cached = classifyCachePath(fsPath);
  if (cached !== undefined) {
    return cached;
  }
  if (path.basename(fsPath) !== TESTSET_MANIFEST) {
    return undefined;
  }
  const root = testsetRootOf(fsPath);
  return root === undefined ? undefined : { root, event: { kind: 'testset' } };
}

/**
 * What one package's store has to do about a batch of events.
 *
 * `run` is the expensive decision: `reload` drops the run outright, `patch`
 * re-reads only `report` and the `evals` named, `keep` leaves it alone.
 */
export interface RefreshPlan {
  readonly run: 'keep' | 'patch' | 'reload';
  readonly report: boolean;
  readonly evals: readonly EvalKey[];
  readonly testset: boolean;
  readonly manifest: boolean;
}

export const NOTHING: RefreshPlan = {
  run: 'keep',
  report: false,
  evals: [],
  testset: false,
  manifest: false,
};

export function evalKeyId(key: EvalKey): string {
  return `${key.solution}\0${key.group}\0${key.stem}`;
}

/**
 * Fold one package's events into the least work that accounts for all of them.
 *
 * A skeleton or a vanished cache wins over everything about the run: the run is
 * re-read from scratch, and since `runs/` was wiped with it, there are no
 * `.eval`s worth patching in. The testset and the manifest are independent of
 * the run and of each other, so an event about one never costs the others.
 */
export function planRefresh(events: readonly ArtifactEvent[]): RefreshPlan {
  let reload = false;
  let report = false;
  let testset = false;
  let manifest = false;
  const evals = new Map<string, EvalKey>();
  for (const event of events) {
    switch (event.kind) {
      case 'cache':
      case 'skeleton':
        reload = true;
        break;
      case 'report':
        report = true;
        break;
      case 'eval':
        evals.set(evalKeyId(event), {
          solution: event.solution,
          group: event.group,
          stem: event.stem,
        });
        break;
      case 'testset':
        testset = true;
        break;
      case 'manifest':
        manifest = true;
        break;
    }
  }
  if (reload) {
    return { run: 'reload', report: false, evals: [], testset, manifest };
  }
  const patch = report || evals.size > 0;
  return {
    run: patch ? 'patch' : 'keep',
    report,
    evals: [...evals.values()],
    testset,
    manifest,
  };
}

/**
 * Whether a change can move what a testset surface shows: the testset itself,
 * or the visualizer declarations its buttons come from. Undefined is a
 * rediscovery, which may have moved anything.
 */
export function touchesTestset(plan: RefreshPlan | undefined): boolean {
  return plan === undefined || plan.testset || plan.manifest;
}
