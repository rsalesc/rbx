/**
 * The Run view: solution -> group -> testcase.
 *
 * A custom TreeView rather than the VS Code Testing API (design D4). The Testing
 * API is shaped around *running* tests, which this extension deliberately never
 * does -- execution stays in the terminal, and rbx keeps sole ownership of it.
 */
import * as vscode from 'vscode';

import { runUri } from './decorations';
import { discoverPackages, packageLabel } from './discovery';
import { log } from './log';
import { groupExpectation, solutionExpectation } from './rbx/expectation';
import { PackageLayout } from './rbx/layout';
import {
  expectationIcon,
  expectedShortName,
  isAccepted,
  outcomeIcon,
  shortName,
} from './rbx/outcome';
import {
  ArtifactStore,
  GroupRun,
  PackageRun,
  SolutionRun,
  TestcaseRun,
} from './rbx/store';
import {
  Progress,
  formatCounts,
  formatMemory,
  formatScore,
  formatTime,
  groupDescription,
  progressOf,
  solutionDescription,
} from './rbx/summary';

export type RunNode = PackageNode | SolutionNode | GroupNode | TestcaseNode;

export interface PackageNode {
  readonly kind: 'package';
  readonly pkg: PackageLayout;
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

/**
 * The verdict's own icon, from the table in outcome.ts.
 *
 * Note this reads the *outcome*, not `matchesExpectation`: a solution declared
 * `WRONG_ANSWER` that answers wrongly is doing its job, and still gets the WA
 * icon. Whether that met the expectation is what the description and the
 * tooltip say -- same split the CLI makes, which also colors the verdict by
 * what happened rather than by whether it was wanted.
 */
function themeIconFor(outcome: string | undefined): vscode.ThemeIcon {
  const { icon, color } = outcomeIcon(outcome);
  return new vscode.ThemeIcon(icon, new vscode.ThemeColor(color));
}

/**
 * The icon for a row that has a declared expectation: the *expectation*, not
 * the verdict.
 *
 * A solution row is not a result, it is a claim the package makes -- `rbx run`
 * says the same thing by heading each solution's column with `solution.href()`
 * coloured by `ExpectedOutcome.full_style()`, and putting verdicts in the cells
 * below. What the run actually produced is in this row's description, and in
 * the testcase rows underneath, which keep the verdict icons from #664.
 *
 * Falls back to the verdict when nothing was declared or the declaration is
 * newer than this extension: the row then shows the only thing still known
 * about it.
 */
function expectationThemeIcon(
  declared: string | undefined,
  outcome: string | undefined,
): vscode.ThemeIcon {
  const expectation = expectationIcon(declared);
  if (expectation === undefined) {
    return themeIconFor(outcome);
  }
  return new vscode.ThemeIcon(
    expectation.icon,
    new vscode.ThemeColor(expectation.color),
  );
}

/**
 * The per-group breakdown, for the hover of a row that missed.
 *
 * Only the groups that actually missed, each naming both sides -- the same
 * lines `_group_failure_lines` prints, which is the detail you would otherwise
 * have to go back to the terminal for.
 */
function appendGroupFailures(
  tooltip: vscode.MarkdownString,
  groups: readonly GroupRun[],
): void {
  const missed = groups.filter(
    (group) => group.report !== undefined && !group.report.matchesExpectation,
  );
  if (missed.length === 0) {
    return;
  }
  tooltip.appendMarkdown('\nGroups that did not match:\n\n');
  for (const group of missed) {
    const report = group.report;
    tooltip.appendMarkdown(
      `- \`${group.name}\`: expected ${expectedShortName(report?.expectedOutcome)}, ` +
        `got ${shortName(report?.outcome)}\n`,
    );
  }
  tooltip.appendMarkdown('\n');
}

function testcaseItem(node: TestcaseNode): vscode.TreeItem {
  const { testcase } = node;
  const evaluation = testcase.evaluation;
  const item = new vscode.TreeItem(
    testcase.stem,
    vscode.TreeItemCollapsibleState.None,
  );
  item.id = `${node.pkg.root}::${node.run.solution.index}::${node.group.name}::${testcase.stem}`;
  item.iconPath = themeIconFor(evaluation?.outcome);
  item.contextValue = 'rbx.testcase';

  const parts = [shortName(evaluation?.outcome)];
  const time = formatTime(evaluation?.time);
  const memory = formatMemory(evaluation?.memory);
  if (time !== undefined) {
    parts.push(time);
  }
  if (memory !== undefined) {
    parts.push(memory);
  }
  if (evaluation?.message !== undefined && evaluation.message !== '') {
    parts.push(evaluation.message);
  }
  item.description = evaluation === undefined ? 'pending' : parts.join(' · ');

  const tooltip = new vscode.MarkdownString();
  tooltip.appendMarkdown(`**${node.group.name}/${testcase.entry.index}** \`${testcase.stem}\`\n\n`);
  if (testcase.entry.generatorName !== undefined) {
    const args = testcase.entry.generatorArgs ?? '';
    tooltip.appendMarkdown(`Generated by \`${testcase.entry.generatorName} ${args}\`\n\n`);
  } else if (testcase.entry.copiedFrom !== undefined) {
    tooltip.appendMarkdown(`Copied from \`${testcase.entry.copiedFrom}\`\n\n`);
  }
  if (evaluation?.message !== undefined && evaluation.message !== '') {
    tooltip.appendMarkdown(`${evaluation.message}\n`);
  }
  item.tooltip = tooltip;

  // Single click opens the most useful artifact: the diff for a failure, the
  // input for anything else.
  item.command =
    evaluation !== undefined && !isAccepted(evaluation.outcome)
      ? { command: 'rbx.diffOutput', title: 'Diff Output', arguments: [node] }
      : { command: 'rbx.openInput', title: 'Open Input', arguments: [node] };

  return item;
}

/**
 * The aggregate tooltip lines, from rbx's report.
 *
 * `aggregates` is absent until the solution finishes -- rbx publishes the
 * report per solution -- so mid-run the tooltip says how far it has got and
 * nothing about verdicts.
 */
function appendSummary(
  tooltip: vscode.MarkdownString,
  aggregates:
    | {
        outcome?: string;
        score: number;
        maxScore: number;
        maxTime?: number;
        maxMemory?: number;
      }
    | undefined,
  progress: Progress,
  testcases: readonly TestcaseRun[],
): void {
  if (aggregates === undefined) {
    tooltip.appendMarkdown(`Still running: ${progress.done}/${progress.total} tests\n`);
    return;
  }
  tooltip.appendMarkdown(`Verdict: **${shortName(aggregates.outcome)}**\n\n`);
  if (aggregates.maxScore > 0) {
    tooltip.appendMarkdown(
      `Score: ${formatScore(aggregates.score, aggregates.maxScore)}\n\n`,
    );
  }
  tooltip.appendMarkdown(`Tests: ${progress.done}/${progress.total}`);
  const counts = formatCounts(testcases);
  if (counts !== '') {
    tooltip.appendMarkdown(` (${counts})`);
  }
  tooltip.appendMarkdown('\n\n');
  // Max, not total: the slowest test is what the time limit is judged against.
  tooltip.appendMarkdown(`Max time: ${formatTime(aggregates.maxTime) ?? '-'}\n\n`);
  tooltip.appendMarkdown(`Max memory: ${formatMemory(aggregates.maxMemory) ?? '-'}\n`);
}

function groupItem(node: GroupNode): vscode.TreeItem {
  // Groups stay expanded even under a collapsed solution: collapsing them too
  // would put two clicks between the user and any testcase, and the group
  // breakdown is the reason to open a solution at all.
  const item = new vscode.TreeItem(
    node.group.name,
    vscode.TreeItemCollapsibleState.Expanded,
  );
  item.id = `${node.pkg.root}::${node.run.solution.index}::${node.group.name}`;
  const expectation = groupExpectation(node.group);
  item.contextValue =
    expectation?.status === 'missed' ? 'rbx.group.mismatch' : 'rbx.group';
  // Rows are addressed by a synthetic URI so the decoration provider can reach
  // them; it draws nothing for a group that declared no expectation of its own.
  item.resourceUri = runUri(node.pkg, node.run.solution.index, node.group.name);

  const report = node.group.report;
  const progress = progressOf(node.group.testcases);
  // A group only has an expectation when `outcomePerGroup` covers it; otherwise
  // the verdict is the only thing it has to show.
  item.iconPath = expectationThemeIcon(expectation?.declared, report?.outcome);
  item.description = groupDescription(report, progress);

  const tooltip = new vscode.MarkdownString();
  tooltip.supportThemeIcons = true;
  tooltip.appendMarkdown(`**${node.group.name}**\n\n`);
  if (expectation !== undefined) {
    tooltip.appendMarkdown(
      expectation.status === 'missed'
        ? `$(error) **Expected ${expectedShortName(expectation.declared)}, got ` +
            `${shortName(report?.outcome)}**\n\n`
        : `Expected: ${expectedShortName(expectation.declared)}\n\n`,
    );
  }
  appendSummary(tooltip, report, progress, node.group.testcases);
  item.tooltip = tooltip;
  return item;
}

function solutionItem(node: SolutionNode): vscode.TreeItem {
  const { solution } = node.run;
  const item = new vscode.TreeItem(
    solution.path,
    node.solo
      ? vscode.TreeItemCollapsibleState.Expanded
      : vscode.TreeItemCollapsibleState.Collapsed,
  );
  item.id = `${node.pkg.root}::${solution.index}`;
  // A synthetic URI, not the solution's own file: decorations are global per
  // URI, and pointing at the file would mark it in the Explorer and on its
  // editor tab too. Nothing else in the extension reads `resourceUri` -- the
  // commands all take the node.
  item.resourceUri = runUri(node.pkg, solution.index);

  const report = node.run.report;
  const expectation = solutionExpectation(node.run);
  // Suffixed rather than replaced: the existing menu `when` clauses match
  // `viewItem` by prefix regex, so they keep applying to a mismatched row.
  item.contextValue =
    expectation?.status === 'missed' ? 'rbx.solution.mismatch' : 'rbx.solution';
  const testcases = node.run.groups.flatMap((group) => group.testcases);
  const progress = progressOf(testcases);
  item.iconPath = expectationThemeIcon(solution.expectedOutcome, report?.outcome);
  item.description = solutionDescription(report, progress, solution.expectedOutcome);

  const tooltip = new vscode.MarkdownString();
  tooltip.supportThemeIcons = true;
  tooltip.appendMarkdown(`**${solution.path}**\n\n`);
  if (expectation?.status === 'missed') {
    // Lead with the miss, and say which layer caught it. A solution can satisfy
    // its pooled expectation and still be caught per group, and naming the
    // pooled one there would accuse an expectation that was met.
    tooltip.appendMarkdown(
      report !== undefined && report.failedGroups.length > 0
        ? `$(error) **Declared ${expectedShortName(solution.expectedOutcome)}, but ` +
            `${report.failedGroups.length} group(s) did not match**\n\n`
        : `$(error) **Expected ${expectedShortName(solution.expectedOutcome)}, got ` +
            `${shortName(report?.outcome)}**\n\n`,
    );
  } else {
    // From the skeleton, so it is there even before the report is.
    tooltip.appendMarkdown(`Expected: ${expectedShortName(solution.expectedOutcome)}\n\n`);
  }
  appendSummary(tooltip, report, progress, testcases);
  appendGroupFailures(tooltip, node.run.groups);
  item.tooltip = tooltip;
  return item;
}

export class RunTreeProvider implements vscode.TreeDataProvider<RunNode> {
  private readonly changed = new vscode.EventEmitter<RunNode | undefined>();
  readonly onDidChangeTreeData = this.changed.event;

  private packages: PackageLayout[] = [];
  private readonly stores = new Map<string, ArtifactStore>();
  /**
   * In-flight or completed discovery.
   *
   * Discovery must be tracked explicitly rather than inferred from
   * `packages.length`: a workspace with no rbx package is a legitimate steady
   * state, and re-running discovery whenever the list is empty would have
   * `getChildren` fire the change event, which makes VS Code call `getChildren`
   * again -- an endless loop behind a permanently empty view.
   */
  private discovery?: Promise<void>;

  /** Reload everything: rediscover packages and drop all cached artifacts. */
  async refresh(): Promise<void> {
    this.discovery = this.discover();
    await this.discovery;
    this.changed.fire(undefined);
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

  /** Drop cached artifacts for one package, in response to a filesystem event. */
  invalidate(root: string): void {
    this.stores.get(root)?.invalidate();
    this.changed.fire(undefined);
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

  /** Packages discovered so far. For the decoration provider, which is addressed
   * by URI and so has to map one back to the package that owns it. */
  knownPackages(): readonly PackageLayout[] {
    return this.packages;
  }

  getTreeItem(node: RunNode): vscode.TreeItem {
    switch (node.kind) {
      case 'package': {
        const item = new vscode.TreeItem(
          packageLabel(node.pkg),
          vscode.TreeItemCollapsibleState.Expanded,
        );
        item.id = node.pkg.root;
        item.contextValue = 'rbx.package';
        item.iconPath = new vscode.ThemeIcon('package');
        item.resourceUri = vscode.Uri.file(node.pkg.root);
        return item;
      }
      case 'solution':
        return solutionItem(node);
      case 'group':
        return groupItem(node);
      case 'testcase':
        return testcaseItem(node);
    }
  }

  async getChildren(node?: RunNode): Promise<RunNode[]> {
    if (node === undefined) {
      await this.ensureDiscovered();
      // A single-problem workspace is the common case; skip the package level
      // entirely rather than making the user expand one node forever.
      if (this.packages.length === 1) {
        return this.solutionsOf(this.packages[0]);
      }
      return this.packages.map((pkg): PackageNode => ({ kind: 'package', pkg }));
    }

    switch (node.kind) {
      case 'package':
        return this.solutionsOf(node.pkg);
      case 'solution':
        return node.run.groups.map(
          (group): GroupNode => ({ kind: 'group', pkg: node.pkg, run: node.run, group }),
        );
      case 'group':
        return node.group.testcases.map(
          (testcase): TestcaseNode => ({
            kind: 'testcase',
            pkg: node.pkg,
            run: node.run,
            group: node.group,
            testcase,
          }),
        );
      case 'testcase':
        return [];
    }
  }

  private async solutionsOf(pkg: PackageLayout): Promise<SolutionNode[]> {
    const report = await this.report(pkg);
    if (report === undefined) {
      log(`No readable run for ${pkg.root} -- run \`rbx run\` in that directory.`);
      return [];
    }
    log(`${pkg.root}: ${report.solutions.length} solution(s) in the last run.`);
    const solo = report.solutions.length === 1;
    return report.solutions.map((run): SolutionNode => ({ kind: 'solution', pkg, run, solo }));
  }
}
