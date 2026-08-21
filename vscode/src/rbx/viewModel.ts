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
import { ExpectationDisplay, expectationDisplay } from './expectation';
import { Hue, hueOfScore, hueOfThemeColor } from './hue';
import {
  FindingNode,
  GroupNode,
  PackageRunView,
  SolutionNode,
  TestcaseNode,
  findingNodes,
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
import { PackageRun, SolutionRun, TestcaseRun } from './store';
import {
  Progress,
  formatMemory,
  formatScore,
  formatTime,
  isComplete,
  pendingDescription,
  progressOf,
} from './summary';

/**
 * The one column that says how a row came out, worst news first.
 *
 * `none` when nothing was declared, `met` when the declaration held cleanly,
 * `warned` when it held but rbx warned about the run anyway, `missed` when it
 * did not hold. The last two are ordered: a row that missed its declaration
 * *and* carries a warning draws `missed`, because the miss is the more serious
 * of the two and the warning is still spelled out in the card underneath.
 *
 * This used to be the match axis alone -- met or missed, nothing else -- with
 * warnings drawn as a separate mark at the far end of the row. That put a
 * yellow clock immediately beside the TLE verdict's own yellow clock, since a
 * double-TL warning only ever lands on a TLE row, and the mark disappeared into
 * the chip it sat next to. One column carrying all three states is what makes
 * a warned row findable by scanning, which is the whole point of having a
 * gutter.
 */
export type Gutter = 'none' | 'met' | 'warned' | 'missed';

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
  /**
   * The verdict a soft TLE hid, on the testcase rows worth showing it on.
   *
   * Under `-v4` a solution is judged at 2x its time limit, so a run that
   * crosses 1x is reported TLE while the checker still sees its output -- and
   * `TLE` on that row can mean either "too slow" or "wrong, and too slow got
   * there first". Those are different bugs and the chip alone cannot tell them
   * apart.
   *
   * Set only where rbx says no expectation accepts the hidden verdict, so a
   * solution declared `incorrect` that answers wrongly under a soft TLE stays
   * quiet: the setter declared that themselves.
   */
  readonly under?: WarningVerdict;
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

/**
 * What a run warned about while still *passing*.
 *
 * A fourth channel, alongside the gutter, the chip and the label hue, and it
 * exists because none of those three can carry this. All of them answer some
 * form of "did the declaration hold", and for a double-TL warning the answer is
 * yes: rbx sets `status: OK` and `matchesExpectation: true` on exactly these
 * solutions. A view built only on those three draws `sols/slow.cpp` as a clean
 * green row while rbx is printing a WARNING about it in the terminal.
 *
 * Which run deserves a warning is rbx's decision, published in `report.yml`; the
 * only thing decided here is which words and which glyph carry it.
 */
export type WarningKind = 'double-tl-passed' | 'double-tl-verdicts';

export interface WarningVerdict {
  readonly text: string;
  readonly hue: Hue;
}

export interface RunWarning {
  readonly kind: WarningKind;
  /** Set for `double-tl-verdicts`, empty otherwise. */
  readonly verdicts: readonly WarningVerdict[];
  /**
   * The groups this fact came from, when any group is narrower than "the whole
   * solution" about it -- the same attribution `_on_groups_markup` prints.
   * Empty on a group row, where the row itself is already the attribution, and
   * on a solution whose pooled layer raised the warning with no group doing so.
   */
  readonly groups: readonly string[];
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
  /**
   * Warnings about a run that passed -- see `RunWarning`.
   *
   * Optional like every other clause of this card, which the renderer prints
   * only when it is set; `Row.warnings` is the required one, because a row that
   * forgot to answer the question would silently draw no mark.
   */
  readonly warnings?: readonly RunWarning[];
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
  readonly kind: 'solution' | 'group' | 'testcase';
  readonly gutter: Gutter;
  readonly label: string;
  /**
   * The whole of what the label is a shortening of, for the row's tooltip.
   *
   * Only solution rows carry one, and only because `rbx.solutionLabel` lets the
   * label stop short of the path: a user reading `main.cpp` still has somewhere
   * to find out which `sols/` it came from. Absent when the label is already
   * the whole truth.
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
  /**
   * Warnings this row carries, in the order the console prints them.
   *
   * Deliberately not folded into `mismatch`: a warned row still matched its
   * declaration, and counting it as a mismatch would report a working package
   * as broken -- the same reason `mismatches` counts misses and not failures.
   */
  readonly warnings: readonly RunWarning[];
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

/** One warning line under an expanded finding row. */
export interface FindingWarning {
  readonly id: string;
  readonly line: number;
  /** `-Wshadow`; empty for a warning the compiler attributed to no flag. */
  readonly flag: string;
  /** The whole message -- a hover title, never a line of the panel. */
  readonly title: string;
}

/**
 * One solution the compile phase had something to say about.
 *
 * A fifth channel, and the first that is not about the run at all. The gutter,
 * the chip, the label hue and the warning mark all answer a question about
 * *running* a solution; a solution that failed to compile never ran, and is not
 * even in `rows` -- rbx filters it out of the skeleton's `solutions` before the
 * run starts. It exists here or nowhere.
 *
 * Identity and severity stay separate, as they do upstairs: the label is hued
 * by what the solution *declared*, so a row here is recognisably the same
 * solution as the row above it, and how badly it compiled is carried by
 * `severity` alone.
 */
export interface FindingRow {
  readonly id: string;
  readonly label: string;
  readonly labelTitle?: string;
  readonly labelHue?: Hue;
  readonly labelBold: boolean;
  readonly severity: 'error' | 'warning';
  /** `CE`, or `3 warns`. */
  readonly summary: string;
  /** Why it failed, when rbx could say in one line. The row's hover title. */
  readonly reason?: string;
  readonly warnings: readonly FindingWarning[];
  /** The `webviewSection` a context menu keys on. */
  readonly section: string;
}

export interface Findings {
  readonly rows: readonly FindingRow[];
  /** Rows, not warnings: the badge must agree with what opening it shows. */
  readonly badge: number;
  readonly hue: 'red' | 'yellow';
  /** Whether anything failed to compile -- what the panel auto-opens on. */
  readonly errors: boolean;
  /**
   * What the client compares to decide the findings are a *new* run's.
   *
   * The webview cannot otherwise tell "the same findings, re-posted by a
   * file-watcher tick" from "a fresh run": both arrive as a whole new model.
   * Auto-opening on the former would reopen, on every tick, a panel the user
   * had just closed.
   */
  readonly signature: string;
}

export interface RunViewModel {
  readonly rows: readonly Row[];
  readonly mismatches: number;
  /** Solutions that passed but carry at least one warning. */
  readonly warned: number;
  readonly empty: boolean;
  /**
   * What the compile phase reported, or nothing at all.
   *
   * Absent rather than empty when every solution compiled cleanly: the panel's
   * presence is itself the signal, exactly as the header strip's is.
   */
  readonly findings?: Findings;
}

/**
 * The model of a view with no problem behind it at all.
 *
 * Distinct from `buildViewModel` of a package with no run: there is no package,
 * so there is no layout to invent one for. Shared by both halves so the client's
 * starting state and the host's answer for an empty workspace cannot drift.
 */
export const EMPTY_MODEL: RunViewModel = { rows: [], mismatches: 0, warned: 0, empty: true };

function chip(outcome: string | undefined, under?: WarningVerdict): VerdictChip {
  const { icon, color } = outcomeIcon(outcome);
  // Note this reads the outcome, never `matchesExpectation`: a solution
  // declared INCORRECT that answers wrongly still gets the WA chip. Whether
  // that was wanted is the gutter's business.
  // Spread rather than `under` outright: an explicit `under: undefined` is a key
  // every chip in the view would carry to say nothing, and it makes a chip that
  // has no hidden verdict unequal to one written without the field.
  return {
    icon,
    hue: hueOfThemeColor(color),
    short: shortName(outcome),
    ...(under === undefined ? {} : { under }),
  };
}

/**
 * The gutter for a row that declared something, given how it came out.
 *
 * `missed` outranks `warned`: a solution can both miss its declaration and
 * carry a warning, and the gutter has one glyph to spend on saying which of
 * those the reader should look at first.
 */
function matched(matches: boolean, warnings: readonly RunWarning[]): Gutter {
  if (!matches) {
    return 'missed';
  }
  return warnings.length > 0 ? 'warned' : 'met';
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
function solutionGutter(run: SolutionRun, warnings: readonly RunWarning[]): Gutter {
  const expected = run.solution.expectedOutcome;
  if (expected === undefined || expected === 'ANY' || run.report === undefined) {
    // A warning still shows, even with nothing declared to have met: rbx raised
    // it about the run, not about the declaration. It cannot happen today --
    // every double-TL fact needs a slow expectation to be raised against -- but
    // swallowing a warning rbx published is the one outcome worth ruling out.
    return warnings.length > 0 ? 'warned' : 'none';
  }
  return matched(run.report.matchesExpectation, warnings);
}

/** A group is only judged when an `outcomePerGroup` declaration covers it. */
function groupGutter(
  report: GroupReport | undefined,
  warnings: readonly RunWarning[],
): Gutter {
  if (report === undefined || report.expectedOutcome === undefined) {
    return warnings.length > 0 ? 'warned' : 'none';
  }
  return matched(report.matchesExpectation, warnings);
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
  warnings: readonly RunWarning[] = [],
): string {
  // The declaration joins the haystack so `tle` finds the groups that *wanted*
  // a TLE as well as the ones that got one -- which, on a solution declared
  // slow, are not the same rows. Deduplicated because on the common row the
  // two agree, and `sols/main.cpp ac ac` is a haystack that says nothing twice.
  // `warning` and `double-tl` both filter to a warned row: the first is what a
  // user scanning for anything wrong types, the second what someone who already
  // knows what they are hunting types.
  const parts = [
    subject,
    verdict?.short,
    // So `wa` finds the testcases where a soft TLE hid one, which are exactly
    // the rows a WA filter would otherwise miss.
    verdict?.under?.text,
    expectation?.label,
    mismatch ? 'mismatch' : undefined,
    ...(warnings.length === 0 ? [] : ['warning', 'double-tl']),
    ...warnings.flatMap((warning) => warning.verdicts.map((verdict) => verdict.text)),
  ]
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
 * The verdict a soft TLE hid on this testcase, when it is worth showing.
 *
 * Two independent conditions, and neither is decided here. The evaluation has a
 * `noTleOutcome` only when the TLE was *soft* -- the run finished inside double
 * TL and the checker saw its output -- and rbx lists it in the group's
 * `unexpectedNoTleVerdicts` only when no expectation covering that testcase
 * accepts it. The second is an `ExpectedOutcome.match` against two declaration
 * layers, which is exactly the matcher this extension refuses to own.
 *
 * Nothing to show with no group report yet: mid-run there is no published
 * answer, and guessing one would put the matcher back.
 */
function hiddenVerdict(
  testcase: TestcaseRun,
  report: GroupReport | undefined,
): WarningVerdict | undefined {
  const hidden = testcase.evaluation?.noTleOutcome;
  if (hidden === undefined || report === undefined) {
    return undefined;
  }
  return report.unexpectedNoTleVerdicts.includes(hidden) ? outcomeOf(hidden) : undefined;
}

/**
 * The groups that raised one of the two double-TL facts.
 *
 * The same attribution `_on_groups_markup` prints beside the console warning,
 * and read off the group records for the reason `groupMismatches` reads off
 * them too: `failedGroups` has no equivalent here, and a warning that cannot
 * say where it came from sends the reader through every group looking.
 */
function warnedGroups(
  report: SolutionReport,
  raised: (group: GroupReport) => boolean,
): string[] {
  return report.groups.filter(raised).map((group) => group.name);
}

/**
 * The warnings on a report, pooled or per-group.
 *
 * The two facts are independent and each gets its own entry, never one merged
 * sentence: both are unions over the pooled layer and every group, so two
 * different groups can each contribute one, and attributing both to a single
 * group list is how the second was lost entirely on the console side (#607).
 *
 * `groups` is empty for a group's own report, where the row already says where
 * the warning came from.
 */
function warningsOf(
  report: SolutionReport | GroupReport | undefined,
  attribute: boolean,
): RunWarning[] {
  if (report === undefined) {
    return [];
  }
  const solution = attribute ? (report as SolutionReport) : undefined;
  const warnings: RunWarning[] = [];
  if (report.runUnderDoubleTl) {
    warnings.push({
      kind: 'double-tl-passed',
      verdicts: [],
      groups:
        solution === undefined ? [] : warnedGroups(solution, (group) => group.runUnderDoubleTl),
    });
  }
  if (report.doubleTlVerdicts.length > 0) {
    warnings.push({
      kind: 'double-tl-verdicts',
      verdicts: report.doubleTlVerdicts.map((outcome) => outcomeOf(outcome)),
      groups:
        solution === undefined
          ? []
          : warnedGroups(solution, (group) => group.doubleTlVerdicts.length > 0),
    });
  }
  return warnings;
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

function solutionDetail(
  run: SolutionRun,
  mismatch: boolean,
  warnings: readonly RunWarning[],
): SolutionDetail {
  const report = run.report;
  const testcases = run.groups.flatMap((group) => group.testcases);
  return {
    mismatch: mismatch && report !== undefined ? mismatchDetail(run, report) : undefined,
    warnings,
    histogram: histogram(testcases),
    maxTime: report === undefined ? undefined : formatTime(report.maxTime),
    maxMemory: report === undefined ? undefined : formatMemory(report.maxMemory),
    // No limit denominator yet. There is now one to divide by -- `skeleton.yml`
    // carries each solution's resolved limits -- but showing a time against it
    // is a decision about what "close to the limit" means, and nobody has made
    // it. Absence here is a gap, no longer an impossibility.
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

function solutionRow(node: SolutionNode, depth: number, label: string, parentId?: string): Row {
  const { run, solo } = node;
  const warnings = warningsOf(run.report, true);
  const gutter = solutionGutter(run, warnings);
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
    warnings,
    mismatch,
    expandable: true,
    // Mirrors the tree, which mirrors rbx's own `len(skeleton.solutions) == 1`
    // choice of the reporter that prints per-testcase lines.
    defaultExpanded: solo,
    detail: solutionDetail(run, mismatch, warnings),
    search: haystack(run.solution.path, verdict, mismatch, declared, warnings),
    section: 'rbx.solution',
    // The row names a file, so the most obvious gesture in the view -- arrow
    // down to `sols/wa.cpp` and press Enter -- opens it. A solution row also
    // expands, so a single click still only expands; opening is Enter and the
    // double click (see webview/gesture.ts).
    primaryCommand: 'rbx.openSolution',
  };
}

function groupRow(node: GroupNode, depth: number, parentId?: string): Row {
  const { group } = node;
  // No group attribution on a group row: the row is the attribution.
  const warnings = warningsOf(group.report, false);
  const gutter = groupGutter(group.report, warnings);
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
    warnings,
    mismatch,
    expandable: true,
    // Groups stay open even under a collapsed solution: the group breakdown is
    // the reason to open a solution at all.
    defaultExpanded: true,
    search: haystack(group.name, verdict, mismatch, declared, warnings),
    section: 'rbx.group',
  };
}

function testcaseRow(node: TestcaseNode, depth: number, parentId?: string): Row {
  const { testcase } = node;
  const evaluation = testcase.evaluation;
  const verdict = chip(evaluation?.outcome, hiddenVerdict(testcase, node.group.report));
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
    // A double-TL fact is decided over a whole group or a whole solution, never
    // over one testcase: a single soft TLE says nothing until it is weighed
    // against the expectation the layer above it declared.
    warnings: [],
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

/** How deep each kind sits, counting the solution as the top level. */
const DEPTHS: Record<Row['kind'], number> = {
  solution: 0,
  group: 1,
  testcase: 2,
};

/**
 * Every path the labels are computed over, for one package.
 *
 * The findings' paths join the solutions': a solution that failed to compile is
 * not in `solutions`, and labelling it on its own would trim it against a
 * different prefix from every row above it.
 */
function labelledPaths(run: PackageRun | undefined): string[] {
  return [
    ...(run?.solutions ?? []).map((solutionRun) => solutionRun.solution.path),
    ...(run?.findings ?? []).map((finding) => finding.entry.path),
  ];
}

/**
 * `3 warns`, `1 warn`, `CE`.
 *
 * The count is of warnings, not of rows, because it is the only number on a
 * finding row and it should say how much there is to read once opened.
 */
function findingSummary(node: FindingNode): string {
  const entry = node.finding.entry;
  if (entry.status === 'FAILED') {
    // The same two letters `ExpectedOutcome.COMPILATION_ERROR` draws with, so a
    // package that *declared* a compile error and one that suffered one read as
    // the same event in the two places they appear.
    return 'CE';
  }
  const count = entry.warnings.length;
  return count === 1 ? '1 warn' : `${count} warns`;
}

function findingRow(node: FindingNode, label: string): FindingRow {
  const entry = node.finding.entry;
  const declared = declaredExpectation(entry.expectedOutcome);
  return {
    id: nodeId(node),
    label,
    labelTitle: label === entry.path ? undefined : entry.path,
    labelHue: declared?.hue,
    labelBold: declared?.bold ?? false,
    severity: entry.status === 'FAILED' ? 'error' : 'warning',
    summary: findingSummary(node),
    reason: entry.reason,
    warnings: entry.warnings.map((warning, index) => ({
      id: `${nodeId(node)}::${index}`,
      line: warning.line,
      flag: warning.flag ?? '',
      // The whole message is the hover title and never a line of the panel:
      // the panel is a third of a narrow sidebar, and `comparison of integer
      // expressions of different signedness` is most of a row on its own.
      title: warning.msg,
    })),
    section: 'rbx.finding',
  };
}

/**
 * The panel's whole model, or `undefined` when there is nothing to report.
 *
 * `undefined` and not an empty list: the panel is absent from the view when the
 * compile phase was clean, so a package whose solutions all compiled does not
 * carry a header saying so.
 */
function buildFindings(
  view: PackageRunView,
  labels: ReadonlyMap<string, string>,
): Findings | undefined {
  const rows = findingNodes(view)
    .filter((node): node is FindingNode => node.kind === 'finding')
    .map((node) => {
      const path = node.finding.entry.path;
      return findingRow(node, labels.get(path) ?? path);
    });
  if (rows.length === 0) {
    return undefined;
  }
  const errors = rows.some((row) => row.severity === 'error');
  return {
    rows,
    badge: rows.length,
    hue: errors ? 'red' : 'yellow',
    errors,
    // Severity is in the signature as well as identity: a solution whose
    // warnings turn into an error between two runs is a new thing to be shown,
    // even though the same file is named both times.
    signature: rows.map((row) => `${row.id}:${row.severity}:${row.summary}`).join('|'),
  };
}

export function buildViewModel(
  view: PackageRunView,
  style: SolutionLabelStyle = DEFAULT_SOLUTION_LABEL_STYLE,
): RunViewModel {
  const nodes = flattenNodes(view);
  // Over the selected package's paths alone, which is what the label styles
  // have always meant: the prefix `trimmed` drops is the one *this* package's
  // solutions share, so a sibling keeping its solutions somewhere unusual
  // cannot cost this one its trimming. It no longer even can -- the sibling
  // does not reach this function any more.
  const labels = solutionLabels(labelledPaths(view.run), style);
  // The most recent row at each level, so a child can name its parent without
  // the walk having to carry a stack.
  const parents = new Map<number, string>();

  const rows: Row[] = [];
  for (const node of nodes) {
    const depth = DEPTHS[node.kind];
    const parentId = parents.get(depth - 1);
    const row = ((): Row => {
      switch (node.kind) {
        case 'solution': {
          const path = node.run.solution.path;
          return solutionRow(node, depth, labels.get(path) ?? path, parentId);
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
    // Warned *and* matching: a solution that already reads as a mismatch is
    // counted once, in the channel that is the more serious of the two.
    warned: rows.filter(
      (row) => row.kind === 'solution' && row.gutter !== 'missed' && row.warnings.length > 0,
    ).length,
    // `rows` is not consulted: a run whose every solution failed to compile has
    // no solution rows at all, and it is precisely the run with most to say.
    empty: !rows.some((row) => row.kind === 'solution'),
    findings: buildFindings(view, labels),
  };
}
