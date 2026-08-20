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

import { ExpectationDisplay, expectationDisplay } from './expectation';
import { Hue, hueOfScore, hueOfThemeColor } from './hue';
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
import { scoreRange } from './score';
import {
  DEFAULT_SOLUTION_LABEL_STYLE,
  SolutionLabelStyle,
  solutionLabels,
} from './solutionLabel';
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

/**
 * What a meta span *is*, so the stylesheet can drop them in priority order.
 *
 * The meta line used to be an anonymous list of strings, which meant it could
 * only be shown or hidden whole -- and the first thing a narrowing sidebar did
 * was take the score away along with the memory figure. Naming each span is
 * what lets the least useful one go first and the score go last.
 */
export type SpanRole = 'progress' | 'score' | 'time' | 'memory';

export interface Span {
  readonly text: string;
  readonly hue?: Hue;
  readonly role?: SpanRole;
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

/** One group that missed its own `outcomePerGroup` declaration. */
export interface GroupMismatch {
  readonly name: string;
  readonly declared: string;
  readonly declaredHue: Hue;
  readonly observed: string;
  readonly observedHue: Hue;
}

export interface Mismatched {
  readonly declared: string;
  readonly declaredHue: Hue;
  readonly observed: string;
  readonly observedHue: Hue;
}

export interface ScoreMismatch {
  readonly expected: string;
  readonly got: string;
  /** How the score it got reads on its own -- see `hueOfScore`. */
  readonly gotHue: Hue;
}

/**
 * What a caught solution got wrong, layer by layer.
 *
 * A solution declares its expectations in two independent layers -- pooled
 * `outcome` and per-group `outcomePerGroup` -- and either can be the one that
 * failed. The card used to name the pooled declaration and then list the
 * groups from `failedGroups` beside it, which reads as though those groups
 * missed *that* declaration. For `sols/mislabeled-groups.cpp` that is exactly
 * backwards: its pooled `INCORRECT` held, and only its per-group `TLE` was
 * missed, so the sentence accused the one expectation that was met.
 *
 * So the layers stay apart here too, and each carries its own declared/observed
 * pair. `pooled` is set only when the pooled layer is what failed -- the same
 * condition `get_verdict_markup` uses before it will print `Expected: X`.
 */
export interface MismatchDetail {
  readonly pooled?: Mismatched;
  /** The pooled declaration's label, set only when that layer *held*. */
  readonly pooledHeld?: string;
  readonly groups: readonly GroupMismatch[];
  readonly score?: ScoreMismatch;
}

export interface SolutionDetail {
  readonly mismatch?: MismatchDetail;
  readonly histogram: readonly HistogramSlice[];
  readonly maxTime?: string;
  readonly maxMemory?: string;
  readonly score?: string;
  /** Set exactly when `score` is -- see `hueOfScore`. */
  readonly scoreHue?: Hue;
}

export interface Row {
  readonly id: string;
  readonly parentId?: string;
  readonly depth: number;
  readonly kind: 'package' | 'solution' | 'group' | 'testcase';
  readonly gutter: Gutter;
  readonly label: string;
  /**
   * The whole of what the label is a shortening of, for the row's tooltip.
   *
   * Only solution rows carry one, and only because `rbx.solutionLabel` lets the
   * label stop short of the path: a user reading `main.cpp` under two packages
   * still has somewhere to find out which `sols/` it came from. Absent when the
   * label is already the whole truth.
   */
  readonly labelTitle?: string;
  readonly labelHue?: Hue;
  readonly labelBold: boolean;
  readonly meta: readonly Span[];
  /**
   * The expectation this row *declared*, spelled out.
   *
   * The label's hue carries the same fact, and on a solution row -- whose label
   * is a path the reader already knows -- that was enough. On a group row it is
   * not: `edge` drawn in yellow does not say `TIME_LIMIT_EXCEEDED`, and a group
   * that declares one through `outcomePerGroup` had no channel at all to say so.
   * Absent when nothing was declared, or when `ANY` declared nothing to miss.
   */
  readonly expectation?: ExpectationDisplay;
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
 * How to draw a declaration, or `undefined` when there is none to draw.
 *
 * `ANY` folds into `undefined` on purpose: it is the way a setter says "I am
 * declaring nothing about this", so spelling it out in the row would put a
 * chip on every solution that opted out of having one. It is the same rule the
 * gutter applies -- there is nothing to have met or missed -- and the two must
 * not disagree about whether a row declared anything.
 */
function declaredExpectation(expected: string | undefined): ExpectationDisplay | undefined {
  if (expected === undefined || expected === 'ANY') {
    return undefined;
  }
  return expectationDisplay(expected);
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

function span(text: string | undefined, hue: Hue, role?: SpanRole): Span | undefined {
  return text === undefined || text === '' ? undefined : { text, hue, role };
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
    return spans([span(pendingDescription(progress), 'dim', 'progress')]);
  }
  // Ordered by how long each survives a narrowing sidebar, widest-lived first,
  // so that hiding always removes a *suffix* of the line -- which is what keeps
  // the separators between them correct without the stylesheet having to know
  // which spans are left. See the container queries in style.css.
  return spans([
    isComplete(progress)
      ? undefined
      : span(`${progress.done}/${progress.total}`, 'dim', 'progress'),
    report.maxScore === 0
      ? undefined
      : span(
          formatScore(report.score, report.maxScore),
          hueOfScore(report.score, report.maxScore),
          'score',
        ),
    span(formatTime(report.maxTime), 'dim', 'time'),
    span(formatMemory(report.maxMemory), 'dim', 'memory'),
  ]);
}

/**
 * `search` for one row: what the user is likely to type at it.
 *
 * The verdict's short name is appended to every row so `wa` filters, and the
 * literal `mismatch` only where there is one, so it is a usable token rather
 * than noise on every row.
 */
function haystack(
  subject: string,
  verdict: VerdictChip | undefined,
  mismatch: boolean,
  expectation?: ExpectationDisplay,
): string {
  // The declaration joins the haystack so `tle` finds the groups that *wanted*
  // a TLE as well as the ones that got one -- which, on a solution declared
  // slow, are not the same rows. Deduplicated because on the common row the
  // two agree, and `sols/main.cpp ac ac` is a haystack that says nothing twice.
  const parts = [subject, verdict?.short, expectation?.label, mismatch ? 'mismatch' : undefined]
    .filter((part): part is string => part !== undefined)
    .map((part) => part.toLowerCase());
  return [...new Set(parts)].join(' ');
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
 * `40`, `40..`, `40..60` -- `get_expected_score_repr`'s spelling, so the card
 * and the console name a range the same way.
 */
function outcomeOf(outcome: string | undefined): { text: string; hue: Hue } {
  const { short, hue } = chip(outcome);
  return { text: short, hue };
}

/**
 * The groups that missed their own declaration, with what each one wanted.
 *
 * Read off `report.groups` rather than `report.failedGroups`: the two hold the
 * same names, but only the group records carry the `expectedOutcome` that makes
 * the line worth reading -- a bare list of names is what sent the reader
 * looking for a declaration that was not the one they missed.
 */
function groupMismatches(report: SolutionReport): GroupMismatch[] {
  return report.groups
    .filter((group) => group.expectedOutcome !== undefined && !group.matchesExpectation)
    .map((group) => {
      const declared = expectationDisplay(group.expectedOutcome);
      const observed = outcomeOf(group.outcome);
      return {
        name: group.name,
        declared: declared?.label ?? '',
        declaredHue: declared?.hue ?? 'neutral',
        observed: observed.text,
        observedHue: observed.hue,
      };
    });
}

/**
 * Whether the *pooled* declaration is one of the things that failed.
 *
 * rbx publishes the answer, and it is the only source that is right in every
 * case. The fallback is for a report written by an rbx that predates the field:
 * with no group failures to explain the mismatch, the pooled layer is the only
 * thing left that can have caused it. That inference is wrong only when both
 * layers failed at once, where it under-reports rather than accusing a layer
 * that held -- which is the direction this whole card is being moved in.
 */
function pooledMissed(report: SolutionReport, groups: readonly GroupMismatch[]): boolean {
  if (report.pooledMatchesExpectation !== undefined) {
    return !report.pooledMatchesExpectation;
  }
  return groups.length === 0 && report.status !== 'UNEXPECTED_SCORE';
}

/**
 * What a mismatched solution got wrong.
 *
 * Every clause is optional and the card prints only the ones that are set, so a
 * solution that missed one layer never has a sentence about the other put in
 * its mouth.
 */
function mismatchDetail(run: SolutionRun, report: SolutionReport): MismatchDetail {
  const groups = groupMismatches(report);
  const missed = pooledMissed(report, groups);
  // A missed gutter already implies a declaration, so the display is there; the
  // fallbacks below only satisfy the type.
  const declared = declaredExpectation(run.solution.expectedOutcome);
  const observed = outcomeOf(report.outcome);
  return {
    pooled: missed
      ? {
          declared: declared?.label ?? '',
          declaredHue: declared?.hue ?? 'neutral',
          observed: observed.text,
          observedHue: observed.hue,
        }
      : undefined,
    // Named only when it is the *other* layer that failed: the reader's first
    // guess is that the declaration on the solution line is the culprit, and
    // saying which one held is what stops them chasing it.
    pooledHeld: !missed && groups.length > 0 ? declared?.label : undefined,
    groups,
    score:
      report.status === 'UNEXPECTED_SCORE' && report.expectedScore !== undefined
        ? {
            expected: scoreRange(report.expectedScore),
            got: String(report.score),
            gotHue: hueOfScore(report.score, report.maxScore),
          }
        : undefined,
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
    scoreHue:
      report === undefined || report.maxScore === 0
        ? undefined
        : hueOfScore(report.score, report.maxScore),
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

function solutionRow(node: SolutionNode, depth: number, label: string, parentId?: string): Row {
  const { run, solo } = node;
  const gutter = solutionGutter(run);
  const mismatch = gutter === 'missed';
  const declared = declaredExpectation(run.solution.expectedOutcome);
  const testcases = run.groups.flatMap((group) => group.testcases);
  const verdict = chip(run.report?.outcome);
  return {
    id: nodeId(node),
    parentId,
    depth,
    kind: 'solution',
    gutter,
    label,
    labelTitle: label === run.solution.path ? undefined : run.solution.path,
    labelHue: declared?.hue,
    labelBold: declared?.bold ?? false,
    meta: aggregateMeta(run.report, progressOf(testcases)),
    expectation: declared,
    verdict,
    mismatch,
    expandable: true,
    // Mirrors the tree, which mirrors rbx's own `len(skeleton.solutions) == 1`
    // choice of the reporter that prints per-testcase lines.
    defaultExpanded: solo,
    detail: solutionDetail(run, mismatch),
    search: haystack(run.solution.path, verdict, mismatch, declared),
    section: 'rbx.solution',
  };
}

function groupRow(node: GroupNode, depth: number, parentId?: string): Row {
  const { group } = node;
  const gutter = groupGutter(group.report);
  const mismatch = gutter === 'missed';
  const verdict = chip(group.report?.outcome);
  // A group declares an expectation the same way a solution does -- through
  // `outcomePerGroup` -- so it is drawn the same way, in the same two channels.
  // Leaving the group level out of both is what made a run of groups that all
  // wanted a TLE look like four ordinary rows with a warning next to them.
  const declared = declaredExpectation(group.report?.expectedOutcome);
  return {
    id: nodeId(node),
    parentId,
    depth,
    kind: 'group',
    gutter,
    label: group.name,
    labelHue: declared?.hue,
    labelBold: declared?.bold ?? false,
    meta: aggregateMeta(group.report, progressOf(group.testcases)),
    expectation: declared,
    verdict,
    mismatch,
    expandable: true,
    // Groups stay open even under a collapsed solution: the group breakdown is
    // the reason to open a solution at all.
    defaultExpanded: true,
    search: haystack(group.name, verdict, mismatch, declared),
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
      span(formatTime(evaluation?.time), 'dim', 'time'),
      span(formatMemory(evaluation?.memory), 'dim', 'memory'),
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

/**
 * Every package's solution labels, by package root and then by solution path.
 *
 * Computed package by package, so the prefix `trimmed` drops is the one *that*
 * package's solutions share -- a contest workspace where one package keeps its
 * solutions somewhere unusual does not cost every other package its trimming.
 */
function labelsByPackage(
  packages: readonly PackageRunView[],
  style: SolutionLabelStyle,
): Map<string, Map<string, string>> {
  const labels = new Map<string, Map<string, string>>();
  for (const { pkg, run } of packages) {
    if (run === undefined) {
      continue;
    }
    const paths = run.solutions.map((solutionRun) => solutionRun.solution.path);
    labels.set(pkg.root, solutionLabels(paths, style));
  }
  return labels;
}

export function buildViewModel(
  packages: readonly PackageRunView[],
  style: SolutionLabelStyle = DEFAULT_SOLUTION_LABEL_STYLE,
): RunViewModel {
  const nodes = flattenNodes(packages);
  const labels = labelsByPackage(packages, style);
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
        case 'solution': {
          const path = node.run.solution.path;
          return solutionRow(node, depth, labels.get(node.pkg.root)?.get(path) ?? path, parentId);
        }
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
