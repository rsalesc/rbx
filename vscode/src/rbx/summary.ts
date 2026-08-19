/**
 * How a run's aggregates are *rendered*. Nothing here computes them.
 *
 * The verdict, the score and the max time and memory all arrive already decided
 * in `.rbx/runs/report.yml` (report.ts). This file formats them, and counts how
 * many testcases have landed so far -- which is a count of files on disk, not a
 * judgement about them.
 *
 * It used to compose whole description strings too, which is how the verdict,
 * the expectation and the mismatch all ended up folded into one line of dim
 * grey. viewModel.ts now keeps them in separate channels and reaches only for
 * the formatters below.
 *
 * The units deliberately match `rbx run` itself: two surfaces reporting the
 * same run should not disagree on whether 32 MiB is "32MB".
 */
import type { Evaluation } from './model';
import { shortName } from './outcome';

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

/**
 * `[70/100]` -- `get_solution_score_markup`'s literal brackets, without its
 * `pts`.
 *
 * The console has a whole terminal to spend and the unit earns its place there.
 * In a sidebar it is four characters of a row that has to fit a path, a score,
 * two measurements and two verdicts, and it is the only one of them carrying no
 * information: the brackets already say this is the score, and nothing else in
 * the meta line is a bare ratio.
 */
export function formatScore(score: number, maxScore: number): string {
  return `[${score}/${maxScore}]`;
}

/**
 * A node whose report has not been written yet.
 *
 * rbx publishes the report once a solution *finishes*, so mid-run there is
 * nothing to aggregate from and the row shows only how far it has got. That is
 * the deliberate cost of having no aggregation here: a "worst verdict so far"
 * computed in this file is exactly the duplication the report exists to remove.
 */
export function pendingDescription(progress: Progress): string {
  return progress.total === 0 ? 'pending' : `${progress.done}/${progress.total}`;
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
