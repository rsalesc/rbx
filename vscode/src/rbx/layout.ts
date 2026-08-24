/**
 * The on-disk artifact layout produced by `rbx`.
 *
 * This module is the *only* place in the extension that knows where rbx puts
 * things. The layout is a contract (see docs/plans/2026-08-11-vscode-extension-design.md,
 * D2): the extension is a pure reader and never invokes rbx, because every rbx
 * invocation has side effects on the cache directory.
 *
 * Verified against rbx as of 2026-08-14 by materializing a real package:
 *
 *   <pkg>/problem.rbx.yml
 *   <pkg>/<build>/tests/<group>/<stem>.in   generated input      (symlink)
 *   <pkg>/<build>/tests/<group>/<stem>.out  expected answer      (symlink)
 *   <pkg>/<build>/testset.yml               TestsetManifest
 *   <pkg>/.rbx/runs/skeleton.yml            SolutionReportSkeleton
 *   <pkg>/.rbx/runs/<i>/<group>/<stem>.eval Evaluation
 *   <pkg>/.rbx/runs/<i>/<group>/<stem>.out  solution stdout      (symlink)
 *   <pkg>/.rbx/runs/<i>/<group>/<stem>.err  solution stderr      (symlink)
 *   <pkg>/.rbx/runs/<i>/<group>/<stem>.pio  interaction capture  (communication tasks)
 *
 * Note the expected answer is `.out`, not `.ans`, and the cache directory is
 * `.rbx`, not `.box` -- the v1 design doc is wrong on both counts.
 *
 * `<build>` is not literally `build`: it is `Environment.buildDir`, which a
 * preset may rename (see `environment.ts`). Only `packageLayout` resolves it;
 * every path below is built from what the layout already carries.
 *
 * The `.in`/`.out`/`.err` artifacts are symlinks into `.rbx/.storage/<sha1>`,
 * which is content-addressed. That is load-bearing for the watcher: artifact
 * content is never rewritten in place, so a path we have already read can be
 * cached until the link itself is replaced.
 */
import * as path from 'path';

import { resolveBuildDir } from './environment';

export const PROBLEM_MANIFEST = 'problem.rbx.yml';
export const CACHE_DIR = '.rbx';
/**
 * The manifest `rbx build` writes last, describing the testset it just built.
 *
 * It sits under the build directory rather than `.rbx/` on purpose (design D2):
 * a fresh build rewrites `<build>/tests` and this file together, so the two
 * cannot drift, and `rbx clean` -- which wipes `.rbx` -- can never orphan it.
 */
export const TESTSET_MANIFEST = 'testset.yml';

/** Artifact suffixes, as they appear on disk. */
export const enum Ext {
  Input = '.in',
  /** Both the expected answer (under `<build>/tests`) and solution stdout (under runs). */
  Output = '.out',
  Stderr = '.err',
  Eval = '.eval',
  Log = '.log',
  Interaction = '.pio',
}

/** A discovered rbx problem package, identified by the directory holding its manifest. */
export interface PackageLayout {
  /** Absolute path to the directory containing problem.rbx.yml. */
  readonly root: string;
  /**
   * Build directory, relative to `root`.
   *
   * Carried on the layout rather than read at every join: it comes from the
   * active preset's environment (`environment.ts`), so it is a fact about the
   * package, and resolving it once per package is what keeps a single view
   * from mixing paths built before and after a preset edit.
   */
  readonly buildDir: string;
}

/**
 * Describe a package rooted at `root`.
 *
 * `buildDir` is resolved from the active preset unless a caller names one,
 * which only tests do -- everywhere else the answer is whatever rbx would use,
 * and asking for it here is what stops each call site inventing a default.
 */
export function packageLayout(root: string, buildDir?: string): PackageLayout {
  return { root, buildDir: buildDir ?? resolveBuildDir(root) };
}

export function manifestPath(pkg: PackageLayout): string {
  return path.join(pkg.root, PROBLEM_MANIFEST);
}

export function cacheDir(pkg: PackageLayout): string {
  return path.join(pkg.root, CACHE_DIR);
}

export function runsDir(pkg: PackageLayout): string {
  return path.join(cacheDir(pkg), 'runs');
}

export function skeletonPath(pkg: PackageLayout): string {
  return path.join(runsDir(pkg), 'skeleton.yml');
}

/**
 * The aggregates rbx publishes for the last run (`rbx.box.run_report`).
 *
 * Written once per solution as it finishes, and removed when a new skeleton is
 * written -- so its absence means "no solution has finished yet", never "stale".
 */
export function reportPath(pkg: PackageLayout): string {
  return path.join(runsDir(pkg), 'report.yml');
}

/**
 * One solution's compile output, from the path the skeleton records.
 *
 * The skeleton stores it relative to the runs dir (`compilation/0.log`) for the
 * same reason `solutionRunsDir` is derived rather than read: an absolute path
 * recorded by the machine that ran rbx is not one this host can necessarily
 * open.
 */
export function compilationLogPath(pkg: PackageLayout, relative: string): string {
  return path.join(runsDir(pkg), relative);
}

/**
 * A path rbx recorded relative to the package root, resolved on this host.
 *
 * Absolute inputs are passed through: a compiler is free to print an absolute
 * path in a warning, and joining one onto the root would produce a path that
 * exists nowhere.
 */
export function testsDir(pkg: PackageLayout): string {
  return path.join(buildPath(pkg), 'tests');
}

/** Absolute path to the package's build directory. */
export function buildPath(pkg: PackageLayout): string {
  return path.join(pkg.root, pkg.buildDir);
}

/**
 * The testset manifest, written last by `rbx build`.
 *
 * Written last is what the reader leans on: a manifest on disk means every test
 * and visualization it names has already landed, so the watcher can be a single
 * glob rather than a heuristic about when a build has settled.
 */
export function testsetPath(pkg: PackageLayout): string {
  return path.join(buildPath(pkg), TESTSET_MANIFEST);
}

/**
 * Directory holding one solution's artifacts.
 *
 * `SolutionSkeleton.runs_dir` records an absolute path to the same place, but we
 * derive it from the package root instead so the tree keeps working when the
 * package moved since the run (and so a remote-executed run does not send us
 * chasing paths that do not exist on this host).
 */
export function solutionRunsDir(pkg: PackageLayout, solutionIndex: number): string {
  return path.join(runsDir(pkg), String(solutionIndex));
}

/** Path to one artifact of one (solution, testcase) pair. */
export function runArtifactPath(
  pkg: PackageLayout,
  solutionIndex: number,
  group: string,
  stem: string,
  ext: Ext,
): string {
  return path.join(solutionRunsDir(pkg, solutionIndex), group, `${stem}${ext}`);
}

/** Path to a generated testcase artifact (input or expected answer). */
export function testArtifactPath(
  pkg: PackageLayout,
  group: string,
  stem: string,
  ext: Ext.Input | Ext.Output,
): string {
  return path.join(testsDir(pkg), group, `${stem}${ext}`);
}

/**
 * Absolute path to a solution's source file.
 *
 * `SolutionEntry.path` is relative to the package root and written with the
 * separator of the host that ran rbx, so a package generated on Windows and
 * read on macOS arrives with backslashes -- `path.join` would keep them and
 * produce one long, nonexistent basename. Splitting on both separators first
 * is what makes the join mean the same thing on either host.
 */
export function solutionSourcePath(pkg: PackageLayout, solutionPath: string): string {
  return packageFilePath(pkg, solutionPath);
}

/**
 * Absolute path to any file rbx named relative to the package root.
 *
 * The general form of `solutionSourcePath`, which it now delegates to: a
 * compiler warning names a file too, and it is not always the solution being
 * compiled. The separator rule above applies to both, and an absolute path is
 * passed through untouched -- a compiler is free to print one, and joining it
 * onto the root would produce a path that exists nowhere.
 */
export function packageFilePath(pkg: PackageLayout, relative: string): string {
  if (path.isAbsolute(relative)) {
    return relative;
  }
  const segments = relative.split(/[\\/]+/).filter((segment) => segment !== '');
  return path.join(pkg.root, ...segments);
}

/**
 * Absolute path to a file the testset manifest named, e.g. a visualization.
 *
 * A named seam onto `packageFilePath` rather than a call to it: the manifest's
 * paths being package-relative is a fact about the manifest, and this is the
 * one module allowed to know it. Consumers of `testset.ts` ask for a path and
 * never learn what the recorded string was relative to.
 */
export function testsetFilePath(pkg: PackageLayout, relative: string): string {
  return packageFilePath(pkg, relative);
}
