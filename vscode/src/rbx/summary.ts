/**
 * How a run's aggregates are *rendered*. Nothing here computes them.
 *
 * The verdict, the score and the max time and memory all arrive already decided
 * in `.rbx/runs/report.yml` (report.ts). This file turns them into the strings
 * the tree shows, and counts how many testcases have landed so far -- which is
 * a count of files on disk, not a judgement about them.
 *
 * The units deliberately match `rbx run` itself: two surfaces reporting the
 * same run should not disagree on whether 32 MiB is "32MB".
 */
import type { Evaluation } from './model';
import type { GroupReport, SolutionReport } from './report';
import { expectedShortName, shortName } from './outcome';

export interface SummarizableTestcase {
  readonly evaluation?: Evaluation;
}

/** How much of a solution or group has been evaluated so far. */
export interface Progress {
  readonly done: number;
  readonly total: number;
}

export function progressOf(testcases: readonly SummarizableTestcase[]): Progress {
  return {
    done: testcases.filter((testcase) => testcase.evaluation !== undefined).length,
    total: testcases.length,
  };
}

export function isComplete(progress: Progress): boolean {
  return progress.done === progress.total;
}

/** Mirrors `rbx.box.formatting.get_formatted_time`, including its truncation. */
export function formatTime(seconds: number | undefined): string | undefined {
  if (seconds === undefined) {
    return undefined;
  }
  return `${Math.trunc(seconds * 1000)} ms`;
}

/** Mirrors `rbx.box.formatting.get_formatted_memory`: B / KiB / MiB, not MB. */
export function formatMemory(bytes: number | undefined): string | undefined {
  if (bytes === undefined) {
    return undefined;
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KiB`;
  }
  return `${Math.round(bytes / (1024 * 1024))} MiB`;
}

/** Mirrors `get_solution_score_markup`, whose brackets are literal: `[70/100 pts]`. */
export function formatScore(score: number, maxScore: number): string {
  return `[${score}/${maxScore} pts]`;
}

function join(parts: (string | undefined)[]): string {
  return parts.filter((part): part is string => part !== undefined && part !== '').join(' · ');
}

function progressPart(progress: Progress): string | undefined {
  return isComplete(progress) ? undefined : `${progress.done}/${progress.total}`;
}

function scorePart(score: number, maxScore: number): string | undefined {
  return maxScore === 0 ? undefined : formatScore(score, maxScore);
}

/**
 * A node whose report has not been written yet.
 *
 * rbx publishes the report once a solution *finishes*, so mid-run there is
 * nothing to aggregate from and the row shows only how far it has got. That is
 * the deliberate cost of having no aggregation here: a "worst verdict so far"
 * computed in this file is exactly the duplication the report exists to remove.
 */
export function pendingDescription(
  progress: Progress,
  expected?: string,
): string {
  const done = progress.total === 0 ? 'pending' : `${progress.done}/${progress.total}`;
  // What a solution promises comes from the skeleton, so it is known before the
  // run starts and all the way through it -- the one thing a row can say while
  // it has no verdict yet. `ANY` promises nothing and is left out.
  const declared =
    expected === undefined || expected === 'ANY'
      ? undefined
      : `expects ${expectedShortName(expected)}`;
  return join([declared, done]);
}

export function groupDescription(
  report: GroupReport | undefined,
  progress: Progress,
): string {
  if (report === undefined) {
    return pendingDescription(progress);
  }
  // Only what happened. What was *wanted* is the row's icon, so spelling it
  // out again here would cost the width that the score and timings need.
  const verdict = report.matchesExpectation
    ? shortName(report.outcome)
    : `got ${shortName(report.outcome)}`;
  return join([
    progressPart(progress),
    verdict,
    scorePart(report.score, report.maxScore),
    formatTime(report.maxTime),
    formatMemory(report.maxMemory),
  ]);
}

export function solutionDescription(
  report: SolutionReport | undefined,
  progress: Progress,
  expected?: string,
): string {
  if (report === undefined) {
    return pendingDescription(progress, expected);
  }
  return join([
    progressPart(progress),
    solutionVerdict(report),
    scorePart(report.score, report.maxScore),
    formatTime(report.maxTime),
    formatMemory(report.maxMemory),
  ]);
}

/**
 * The headline finding: a solution that did not behave as declared.
 *
 * A solution declares its expectations in two layers and rbx checks both, so
 * saying which one failed matters. `sols/mislabeled-groups.cpp` in the sample
 * package satisfies its pooled `INCORRECT` -- it does fail somewhere -- and is
 * caught only by its per-group expectations. Naming the pooled expectation
 * there would accuse one that was in fact met, so the groups are named instead.
 *
 * The declared expectation itself is never spelled out: it is the row's icon.
 */
function solutionVerdict(report: SolutionReport): string {
  if (report.matchesExpectation) {
    return shortName(report.outcome);
  }
  if (report.failedGroups.length > 0) {
    return `failed ${report.failedGroups.join(', ')}`;
  }
  return `got ${shortName(report.outcome)}`;
}

/**
 * `14 AC, 2 WA`, most frequent first.
 *
 * Ordered by count rather than by how bad each outcome is: that ranking is
 * `Outcome.worst_outcome`'s business, and reproducing its order here would put
 * a copy of it back in this file.
 */
export function formatCounts(testcases: readonly SummarizableTestcase[]): string {
  const counts = new Map<string, number>();
  for (const testcase of testcases) {
    const outcome = testcase.evaluation?.outcome;
    if (outcome !== undefined) {
      counts.set(outcome, (counts.get(outcome) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort(([nameA, countA], [nameB, countB]) => countB - countA || nameA.localeCompare(nameB))
    .map(([outcome, count]) => `${count} ${shortName(outcome)}`)
    .join(', ');
}
