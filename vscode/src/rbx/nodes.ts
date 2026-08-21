/**
 * The rows of the run view, and the walk that produces them.
 *
 * These types moved out of runTree.ts so nothing here imports `vscode`: the
 * view model that renders the webview is a pure function of these nodes, and it
 * can only stay pure -- and testable under plain `node --test` -- if the shape
 * it consumes carries no editor API with it.
 */
import { PackageLayout } from './layout';
import { CompilationWarning } from './model';
import { CompilationFinding, GroupRun, PackageRun, SolutionRun, TestcaseRun } from './store';

/**
 * The nodes the tree walk produces.
 *
 * Split out of `RunNode` so `flattenNodes` can promise it yields *only* these:
 * the compilation findings are a second surface with its own list, and folding
 * them into the walk would put them in the tree the walk describes.
 */
export type TreeNode = SolutionNode | GroupNode | TestcaseNode;

/** Everything a command can be invoked on, tree or panel. */
export type RunNode = TreeNode | FindingNode | FindingWarningNode;

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

/** One solution's row in the Compilation Findings panel. */
export interface FindingNode {
  readonly kind: 'finding';
  readonly pkg: PackageLayout;
  readonly finding: CompilationFinding;
}

/** One warning under an expanded finding row. */
export interface FindingWarningNode {
  readonly kind: 'findingWarning';
  readonly pkg: PackageLayout;
  readonly finding: CompilationFinding;
  readonly warning: CompilationWarning;
  /** Its position among the finding's warnings, which is what makes the id unique. */
  readonly index: number;
}

/**
 * The stable row id. Identical to the `TreeItem.id`s the tree used.
 *
 * Still rooted at the package directory even though no row draws that level:
 * the ids outlive the package on screen -- the client keeps a selection, and
 * the host resolves context-menu commands through a map of them -- so an id
 * from one package must never name a row of another.
 */
export function nodeId(node: RunNode): string {
  switch (node.kind) {
    // `compile` rather than a solution index: a solution that failed to compile
    // has no index, because it never entered the run.
    case 'finding':
      return `${node.pkg.root}::compile::${node.finding.entry.path}`;
    case 'findingWarning':
      return `${node.pkg.root}::compile::${node.finding.entry.path}::${node.index}`;
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
}

/**
 * Every row of one package's run, in display order, parents before children.
 *
 * One package, because the view shows one: the selector upstream decides which,
 * so there is no package level left to draw and no rule about when to draw it.
 */
export function flattenNodes(view: PackageRunView): TreeNode[] {
  const { pkg, run } = view;
  if (run === undefined) {
    return [];
  }
  const nodes: TreeNode[] = [];
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
  return nodes;
}

/**
 * Every compilation finding, and every warning under one, in skeleton order.
 *
 * A second walk rather than a branch of `flattenNodes`: these rows are not in
 * the tree, they answer a different question, and the panel that draws them is
 * absent whenever this returns nothing. The warnings are walked too so that a
 * click on one resolves to a node like any other row in the view.
 */
export function findingNodes(view: PackageRunView): (FindingNode | FindingWarningNode)[] {
  const { pkg, run } = view;
  const nodes: (FindingNode | FindingWarningNode)[] = [];
  for (const finding of run?.findings ?? []) {
    nodes.push({ kind: 'finding', pkg, finding });
    finding.entry.warnings.forEach((warning, index) => {
      nodes.push({ kind: 'findingWarning', pkg, finding, warning, index });
    });
  }
  return nodes;
}
