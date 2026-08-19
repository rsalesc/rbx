/**
 * The rows of the run view, and the walk that produces them.
 *
 * These types moved out of runTree.ts so nothing here imports `vscode`: the
 * view model that renders the webview is a pure function of these nodes, and it
 * can only stay pure -- and testable under plain `node --test` -- if the shape
 * it consumes carries no editor API with it.
 */
import { PackageLayout } from './layout';
import { GroupRun, PackageRun, SolutionRun, TestcaseRun } from './store';

export type RunNode = PackageNode | SolutionNode | GroupNode | TestcaseNode;

export interface PackageNode {
  readonly kind: 'package';
  readonly pkg: PackageLayout;
  /** The host's disambiguated label, when it supplied one. */
  readonly label?: string;
}

export interface SolutionNode {
  readonly kind: 'solution';
  readonly pkg: PackageLayout;
  readonly run: SolutionRun;
  /**
   * This package's run covered only this solution, so the user is focused on
   * it and the tree opens it. Mirrors how `rbx run` itself picks
   * `SingleSolutionRunReporter` -- the only reporter that prints per-testcase
   * lines -- on `len(skeleton.solutions) == 1`.
   */
  readonly solo: boolean;
}

export interface GroupNode {
  readonly kind: 'group';
  readonly pkg: PackageLayout;
  readonly run: SolutionRun;
  readonly group: GroupRun;
}

export interface TestcaseNode {
  readonly kind: 'testcase';
  readonly pkg: PackageLayout;
  readonly run: SolutionRun;
  readonly group: GroupRun;
  readonly testcase: TestcaseRun;
}

/** The stable row id. Identical to the `TreeItem.id`s the tree used. */
export function nodeId(node: RunNode): string {
  switch (node.kind) {
    case 'package':
      return node.pkg.root;
    case 'solution':
      return `${node.pkg.root}::${node.run.solution.index}`;
    case 'group':
      return `${node.pkg.root}::${node.run.solution.index}::${node.group.name}`;
    case 'testcase':
      return `${node.pkg.root}::${node.run.solution.index}::${node.group.name}::${node.testcase.stem}`;
  }
}

/** A discovered package with whatever run is on disk for it, if any. */
export interface PackageRunView {
  readonly pkg: PackageLayout;
  readonly run: PackageRun | undefined;
  /**
   * What to call this package in the view.
   *
   * Supplied by the host rather than derived here, because telling two packages
   * named `prob` apart needs `vscode.workspace` to say which folder each sits
   * in -- and this module's value is being testable without the editor API.
   * Absent in tests and wherever the basename is unambiguous.
   */
  readonly label?: string;
}

/**
 * Every row in display order, each parent immediately before its children.
 *
 * The package level is dropped when the workspace holds exactly one package --
 * the common case, where making the user expand one node forever buys nothing.
 * The count is of discovered packages, not of packages that have run, so the
 * view does not gain and lose a level as runs come and go.
 */
export function flattenNodes(packages: readonly PackageRunView[]): RunNode[] {
  const showPackages = packages.length > 1;
  const nodes: RunNode[] = [];
  for (const { pkg, run, label } of packages) {
    if (run === undefined) {
      continue;
    }
    if (showPackages) {
      nodes.push({ kind: 'package', pkg, label });
    }
    const solo = run.solutions.length === 1;
    for (const solutionRun of run.solutions) {
      nodes.push({ kind: 'solution', pkg, run: solutionRun, solo });
      for (const group of solutionRun.groups) {
        nodes.push({ kind: 'group', pkg, run: solutionRun, group });
        for (const testcase of group.testcases) {
          nodes.push({ kind: 'testcase', pkg, run: solutionRun, group, testcase });
        }
      }
    }
  }
  return nodes;
}
