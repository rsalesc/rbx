/**
 * What a row was declared to do, and whether it did it.
 *
 * The two facts a run row carries are deliberately kept on separate axes: the
 * icon reports the *outcome* (see outcome.ts and #664), and everything here
 * feeds the decoration that reports the *expectation*. `rbx run` makes the same
 * split -- `_render_detailed_group_table` heads each solution's column with
 * `solution.href()`, coloured by what was declared, and fills the cells with
 * what happened.
 *
 * Nothing is decided here. `matchesExpectation` was computed by
 * `rbx.box.run_report`; this only picks which of the two sources to read it
 * from.
 */
import type { ExpectationStatus } from './outcome';
import type { GroupRun, SolutionRun } from './store';

export interface Expectation {
  /** The declared `ExpectedOutcome`, e.g. `WRONG_ANSWER`. */
  readonly declared: string;
  /** The verdict the run produced, absent until it has one. */
  readonly outcome?: string;
  readonly status: ExpectationStatus;
  /**
   * Groups that missed a per-group expectation, as rbx named them.
   *
   * Non-empty means the *pooled* expectation was not the one that failed, which
   * the hover has to say rather than blaming `declared` for a miss it did not
   * cause. Always empty for a group, which has only the one layer.
   */
  readonly failedGroups: readonly string[];
}

/**
 * A solution's expectation, available before its run finishes.
 *
 * The declaration comes from the skeleton when the report has none, which is
 * what lets a row show what it promises while it is still running -- rbx
 * publishes the report only once a solution completes. Until then the status is
 * `unknown`: not yet judged is not the same as met.
 */
export function solutionExpectation(run: SolutionRun): Expectation | undefined {
  const declared = run.report?.expectedOutcome ?? run.solution.expectedOutcome;
  if (declared === undefined) {
    return undefined;
  }
  if (run.report === undefined) {
    return { declared, status: 'unknown', failedGroups: [] };
  }
  return {
    declared,
    outcome: run.report.outcome,
    status: run.report.matchesExpectation ? 'met' : 'missed',
    failedGroups: run.report.failedGroups,
  };
}

/**
 * A group's expectation, which exists only when one was declared for it.
 *
 * `GroupReport.expectedOutcome` is set exactly when the solution declares an
 * `outcomePerGroup` covering this group, so its absence is the signal that this
 * group has nothing of its own to say and should not be decorated at all.
 */
export function groupExpectation(group: GroupRun): Expectation | undefined {
  const report = group.report;
  if (report?.expectedOutcome === undefined) {
    return undefined;
  }
  return {
    declared: report.expectedOutcome,
    outcome: report.outcome,
    status: report.matchesExpectation ? 'met' : 'missed',
    failedGroups: [],
  };
}

/** How many solutions finished having missed what they declared. */
export function mismatchCount(runs: readonly SolutionRun[]): number {
  return runs.filter((run) => solutionExpectation(run)?.status === 'missed').length;
}
