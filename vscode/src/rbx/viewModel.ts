/**
 * What each row of the run view *shows* -- decided once, here.
 *
 * The view needs three independent channels that a `TreeItem` cannot carry: the
 * expectation a package *declared*, the verdict a run *produced*, and whether
 * the two agreed. Folding them together is the bug this module exists to
 * remove: `sols/partial.cpp` declared `INCORRECT` and answering wrongly is the
 * package working, and it must not draw like the main solution breaking.
 *
 * So the three stay apart by construction. The gutter is the match axis and
 * nothing else writes to it; the chip is the verdict axis and never consults
 * `matchesExpectation`; the label hue is the declaration and never consults the
 * outcome. The renderer downstream re-decides none of this -- it is handed
 * strings, hues and booleans, and paints them.
 *
 * Pure by design, like nodes.ts: no `vscode` import, so `node --test` can hold
 * the whole thing to account.
 */
import * as path from 'path';

import { expectationDisplay } from './expectation';
import { Hue, hueOfThemeColor } from './hue';
import {
  GroupNode,
  PackageNode,
  PackageRunView,
  SolutionNode,
  TestcaseNode,
  flattenNodes,
  nodeId,
} from './nodes';
import { isAccepted, outcomeIcon, shortName } from './outcome';
import { GroupReport, SolutionReport } from './report';
import { SolutionRun, TestcaseRun } from './store';
import {
  Progress,
  formatMemory,
  formatScore,
  formatTime,
  isComplete,
  pendingDescription,
  progressOf,
} from './summary';

/** Whether a declared expectation was met -- `none` when none was declared. */
export type Gutter = 'none' | 'met' | 'missed';

export interface Span {
  readonly text: string;
  readonly hue?: Hue;
}

export interface VerdictChip {
  readonly icon: string;
  readonly hue: Hue;
  readonly short: string;
}

export interface HistogramSlice {
  readonly short: string;
  readonly hue: Hue;
  readonly count: number;
}

export interface MismatchDetail {
  readonly declared: string;
  readonly observed: string;
  readonly failedGroups: readonly string[];
}

export interface SolutionDetail {
  readonly mismatch?: MismatchDetail;
  readonly histogram: readonly HistogramSlice[];
  readonly maxTime?: string;
  readonly maxMemory?: string;
  readonly score?: string;
}

export interface Row {
  readonly id: string;
  readonly parentId?: string;
  readonly depth: number;
  readonly kind: 'package' | 'solution' | 'group' | 'testcase';
  readonly gutter: Gutter;
  readonly label: string;
  readonly labelHue?: Hue;
  readonly labelBold: boolean;
  readonly meta: readonly Span[];
  readonly verdict?: VerdictChip;
  readonly mismatch: boolean;
  readonly expandable: boolean;
  readonly defaultExpanded: boolean;
  readonly detail?: SolutionDetail;
  /** Lowercased haystack for the filter box. */
  readonly search: string;
  /** The `webviewSection` a context menu keys on. */
  readonly section: string;
  readonly primaryCommand?: string;
}

export interface RunViewModel {
  readonly rows: readonly Row[];
  readonly mismatches: number;
  readonly empty: boolean;
}

/**
 * What to call a package.
 *
 * The host disambiguates two packages both named `prob` by asking
 * `vscode.workspace` which folder each sits in, and passes the answer down --
 * importing that here would drag the editor API into a module whose whole value
 * is being testable without it. The basename is right whenever it did not.
 */
function packageName(node: PackageNode): string {
  return node.label ?? path.basename(node.pkg.root);
}

function chip(outcome: string | undefined): VerdictChip {
  const { icon, color } = outcomeIcon(outcome);
  // Note this reads the outcome, never `matchesExpectation`: a solution
  // declared INCORRECT that answers wrongly still gets the WA chip. Whether
  // that was wanted is the gutter's business.
  return { icon, hue: hueOfThemeColor(color), short: shortName(outcome) };
}

function matched(matches: boolean): Gutter {
  return matches ? 'met' : 'missed';
}

/**
 * The gutter for a solution row.
 *
 * `ANY` and an absent expectation both mean the setter declared nothing, so
 * there is nothing to have met or missed. A solution with no report yet is the
 * same case for a different reason: rbx publishes the report when the solution
 * *finishes*, so mid-run there is no verdict to compare against.
 */
function solutionGutter(run: SolutionRun): Gutter {
  const expected = run.solution.expectedOutcome;
  if (expected === undefined || expected === 'ANY' || run.report === undefined) {
    return 'none';
  }
  return matched(run.report.matchesExpectation);
}

/** A group is only judged when an `outcomePerGroup` declaration covers it. */
function groupGutter(report: GroupReport | undefined): Gutter {
  if (report === undefined || report.expectedOutcome === undefined) {
    return 'none';
  }
  return matched(report.matchesExpectation);
}

function span(text: string | undefined, hue: Hue): Span | undefined {
  return text === undefined || text === '' ? undefined : { text, hue };
}

function spans(candidates: readonly (Span | undefined)[]): Span[] {
  return candidates.filter((candidate): candidate is Span => candidate !== undefined);
}

/**
 * The meta line of a solution or group row.
 *
 * `solutionDescription`/`groupDescription` from summary.ts are deliberately not
 * reused: both fold the verdict and an "expected X, got Y" phrase into the
 * string, which is exactly the conflation this view splits into a chip and a
 * gutter. The formatters underneath them are reused as they are.
 */
function aggregateMeta(
  report: SolutionReport | GroupReport | undefined,
  progress: Progress,
): Span[] {
  if (report === undefined) {
    return spans([span(pendingDescription(progress), 'dim')]);
  }
  return spans([
    isComplete(progress) ? undefined : span(`${progress.done}/${progress.total}`, 'dim'),
    report.maxScore === 0
      ? undefined
      : span(formatScore(report.score, report.maxScore), 'neutral'),
    span(formatTime(report.maxTime), 'dim'),
    span(formatMemory(report.maxMemory), 'dim'),
  ]);
}

/**
 * `search` for one row: what the user is likely to type at it.
 *
 * The verdict's short name is appended to every row so `wa` filters, and the
 * literal `mismatch` only where there is one, so it is a usable token rather
 * than noise on every row.
 */
function haystack(subject: string, verdict: VerdictChip | undefined, mismatch: boolean): string {
  return [subject, verdict?.short, mismatch ? 'mismatch' : undefined]
    .filter((part): part is string => part !== undefined)
    .join(' ')
    .toLowerCase();
}

/**
 * Testcase outcomes by count, most frequent first, ties by outcome name.
 *
 * Ordered the way `formatCounts` orders its own, and for the reason its comment
 * gives: ordering by badness is `Outcome.worst_outcome`'s ranking, and
 * reproducing it here would put a copy of it back into this extension.
 */
function histogram(testcases: readonly TestcaseRun[]): HistogramSlice[] {
  const counts = new Map<string, number>();
  for (const testcase of testcases) {
    const outcome = testcase.evaluation?.outcome;
    if (outcome !== undefined) {
      counts.set(outcome, (counts.get(outcome) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort(([nameA, countA], [nameB, countB]) => countB - countA || nameA.localeCompare(nameB))
    .map(([outcome, count]) => {
      const { hue, short } = chip(outcome);
      return { short, hue, count };
    });
}

/**
 * What a mismatched solution got wrong.
 *
 * `failedGroups` verbatim rather than a phrase naming the pooled expectation:
 * `sols/mislabeled.cpp` in the `outcome-per-group` fixture *satisfies* its
 * pooled `INCORRECT` -- it does fail somewhere -- and is caught only by its
 * per-group declarations, so "expected INCORRECT, got WA" would name an
 * expectation that was in fact met. See `solutionVerdict` in summary.ts.
 */
function mismatchDetail(run: SolutionRun, report: SolutionReport): MismatchDetail {
  // A missed gutter already implies a declaration, so the display is there; the
  // fallback only satisfies the type.
  const declared = expectationDisplay(run.solution.expectedOutcome);
  return {
    declared: declared?.label ?? '',
    observed: shortName(report.outcome),
    failedGroups: report.failedGroups,
  };
}

function solutionDetail(run: SolutionRun, mismatch: boolean): SolutionDetail {
  const report = run.report;
  const testcases = run.groups.flatMap((group) => group.testcases);
  return {
    mismatch: mismatch && report !== undefined ? mismatchDetail(run, report) : undefined,
    histogram: histogram(testcases),
    maxTime: report === undefined ? undefined : formatTime(report.maxTime),
    maxMemory: report === undefined ? undefined : formatMemory(report.maxMemory),
    // No limit denominator: the extension reads only `.rbx` artifacts and never
    // problem.rbx.yml, so there is nothing here to divide by.
    score:
      report === undefined || report.maxScore === 0
        ? undefined
        : formatScore(report.score, report.maxScore),
  };
}

function packageRow(node: PackageNode, depth: number, parentId?: string): Row {
  const label = packageName(node);
  return {
    id: nodeId(node),
    parentId,
    depth,
    kind: 'package',
    gutter: 'none',
    label,
    labelBold: false,
    meta: [],
    mismatch: false,
    expandable: true,
    defaultExpanded: true,
    search: haystack(label, undefined, false),
    section: 'rbx.package',
  };
}

function solutionRow(node: SolutionNode, depth: number, parentId?: string): Row {
  const { run, solo } = node;
  const gutter = solutionGutter(run);
  const mismatch = gutter === 'missed';
  const declared = expectationDisplay(run.solution.expectedOutcome);
  const testcases = run.groups.flatMap((group) => group.testcases);
  const verdict = chip(run.report?.outcome);
  return {
    id: nodeId(node),
    parentId,
    depth,
    kind: 'solution',
    gutter,
    label: run.solution.path,
    labelHue: declared?.hue,
    labelBold: declared?.bold ?? false,
    meta: aggregateMeta(run.report, progressOf(testcases)),
    verdict,
    mismatch,
    expandable: true,
    // Mirrors the tree, which mirrors rbx's own `len(skeleton.solutions) == 1`
    // choice of the reporter that prints per-testcase lines.
    defaultExpanded: solo,
    detail: solutionDetail(run, mismatch),
    search: haystack(run.solution.path, verdict, mismatch),
    section: 'rbx.solution',
  };
}

function groupRow(node: GroupNode, depth: number, parentId?: string): Row {
  const { group } = node;
  const gutter = groupGutter(group.report);
  const mismatch = gutter === 'missed';
  const verdict = chip(group.report?.outcome);
  return {
    id: nodeId(node),
    parentId,
    depth,
    kind: 'group',
    gutter,
    label: group.name,
    labelBold: false,
    meta: aggregateMeta(group.report, progressOf(group.testcases)),
    verdict,
    mismatch,
    expandable: true,
    // Groups stay open even under a collapsed solution: the group breakdown is
    // the reason to open a solution at all.
    defaultExpanded: true,
    search: haystack(group.name, verdict, mismatch),
    section: 'rbx.group',
  };
}

function testcaseRow(node: TestcaseNode, depth: number, parentId?: string): Row {
  const { testcase } = node;
  const evaluation = testcase.evaluation;
  const verdict = chip(evaluation?.outcome);
  return {
    id: nodeId(node),
    parentId,
    depth,
    kind: 'testcase',
    // A testcase declares no expectation of its own; only the solution and, via
    // `outcomePerGroup`, the group do.
    gutter: 'none',
    label: testcase.stem,
    labelBold: false,
    // The checker's message is deliberately left out. It is a free-form line
    // written by the package's own checker, so it is as long as that checker
    // felt like being, and in a sidebar it pushed the timings out of a row that
    // is only 22px tall. It belongs somewhere that can wrap.
    meta: spans([
      span(formatTime(evaluation?.time), 'dim'),
      span(formatMemory(evaluation?.memory), 'dim'),
    ]),
    verdict,
    mismatch: false,
    expandable: false,
    defaultExpanded: false,
    search: haystack(`${node.group.name}/${testcase.stem}`, verdict, false),
    section: 'rbx.testcase',
    // Single click opens the most useful artifact: the diff for a failure, the
    // input for anything else -- what the tree's `item.command` does today.
    primaryCommand:
      evaluation !== undefined && !isAccepted(evaluation.outcome)
        ? 'rbx.diffOutput'
        : 'rbx.openInput',
  };
}

/** How deep each kind sits, given whether the walk emitted package rows. */
const DEPTHS: Record<Row['kind'], number> = {
  package: 0,
  solution: 1,
  group: 2,
  testcase: 3,
};

export function buildViewModel(packages: readonly PackageRunView[]): RunViewModel {
  const nodes = flattenNodes(packages);
  // `flattenNodes` drops the package level for a single package, so the offset
  // has to come from the walk it actually performed rather than from the input.
  const hasPackages = nodes.some((node) => node.kind === 'package');
  const offset = hasPackages ? 0 : 1;
  // The most recent row at each level, so a child can name its parent without
  // the walk having to carry a stack.
  const parents = new Map<number, string>();

  const rows: Row[] = [];
  for (const node of nodes) {
    const depth = DEPTHS[node.kind] - offset;
    const parentId = parents.get(depth - 1);
    const row = ((): Row => {
      switch (node.kind) {
        case 'package':
          return packageRow(node, depth, parentId);
        case 'solution':
          return solutionRow(node, depth, parentId);
        case 'group':
          return groupRow(node, depth, parentId);
        case 'testcase':
          return testcaseRow(node, depth, parentId);
      }
    })();
    rows.push(row);
    parents.set(depth, row.id);
  }

  return {
    rows,
    // Mismatches, not failures: a solution that fails on purpose is the package
    // working, and counting it would report the package's own test suite as a
    // problem.
    mismatches: rows.filter((row) => row.kind === 'solution' && row.gutter === 'missed').length,
    empty: !rows.some((row) => row.kind === 'solution'),
  };
}
