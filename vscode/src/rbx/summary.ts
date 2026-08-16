/**
 * Aggregate facts about a solution or a test group, and how they render.
 *
 * Kept apart from the tree provider so it stays free of the `vscode` module and
 * can be unit tested: everything here is outcomes in, strings out.
 *
 * The wording and the units deliberately match what `rbx run` prints -- two
 * surfaces reporting the same run should not disagree on whether 32 MiB is
 * "32MB". See docs/plans/2026-08-16-vscode-run-summaries-design.md.
 */
import type { Evaluation } from './model';
import { expectedShortName, matches, outcomeRank, shortName, worstOutcome } from './outcome';

/**
 * The shape summarising needs, rather than the full `TestcaseRun`/`GroupRun`.
 *
 * Structural, so `store.ts`'s richer types satisfy it without a conversion and
 * tests do not have to invent artifact paths they never look at.
 */
export interface SummarizableTestcase {
  readonly evaluation?: Evaluation;
}

export interface SummarizableGroup {
  readonly name: string;
  /** Points this group is worth, from the skeleton; 0 under binary scoring. */
  readonly score: number;
  readonly testcases: readonly SummarizableTestcase[];
}

export interface SummarizableSolution {
  readonly groups: readonly SummarizableGroup[];
}

export interface RunSummary {
  /** Worst outcome observed so far; absent when nothing has been evaluated. */
  readonly outcome?: string;
  readonly done: number;
  readonly total: number;
  /**
   * Max over evaluated testcases, not sum or mean -- the worst test is the one
   * judged against the time limit, and the only one worth a glance.
   */
  readonly time?: number;
  readonly memory?: number;
  /** Testcases per outcome, worst-first, for the tooltip. */
  readonly counts: ReadonlyMap<string, number>;
  /** Points earned; see D3 -- group dependencies are not modelled. */
  readonly score: number;
  readonly maxScore: number;
}

export function isComplete(summary: RunSummary): boolean {
  return summary.done === summary.total;
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

/**
 * Did this group earn its points?
 *
 * rbx awards a group's score all-or-nothing, and additionally zeroes it when a
 * group it depends on failed (`_check_deps`). The skeleton carries no
 * dependency graph, so that gate is not applied here -- a deliberate
 * over-report on dependent groups, documented in D3.
 */
function groupPassed(summary: RunSummary): boolean {
  return isComplete(summary) && summary.outcome === 'accepted';
}

function summarize(
  testcases: readonly SummarizableTestcase[],
  scored: { score: number; maxScore: number },
): RunSummary {
  const outcomes: (string | undefined)[] = [];
  const counts = new Map<string, number>();
  let done = 0;
  let time: number | undefined;
  let memory: number | undefined;

  for (const testcase of testcases) {
    const evaluation = testcase.evaluation;
    if (evaluation === undefined) {
      continue;
    }
    done += 1;
    outcomes.push(evaluation.outcome);
    if (evaluation.outcome !== undefined) {
      counts.set(evaluation.outcome, (counts.get(evaluation.outcome) ?? 0) + 1);
    }
    if (evaluation.time !== undefined) {
      time = time === undefined ? evaluation.time : Math.max(time, evaluation.time);
    }
    if (evaluation.memory !== undefined) {
      memory = memory === undefined ? evaluation.memory : Math.max(memory, evaluation.memory);
    }
  }

  return {
    outcome: worstOutcome(outcomes),
    done,
    total: testcases.length,
    time,
    memory,
    counts,
    score: scored.score,
    maxScore: scored.maxScore,
  };
}

export function summarizeGroup(group: SummarizableGroup): RunSummary {
  const provisional = summarize(group.testcases, { score: 0, maxScore: group.score });
  return { ...provisional, score: groupPassed(provisional) ? group.score : 0 };
}

export function summarizeSolution(solution: SummarizableSolution): RunSummary {
  const testcases = solution.groups.flatMap((group) => group.testcases);
  let score = 0;
  let maxScore = 0;
  for (const group of solution.groups) {
    score += summarizeGroup(group).score;
    maxScore += group.score;
  }
  return summarize(testcases, { score, maxScore });
}

/** Groups whose worst outcome is a failure, for the solution tooltip. */
export function failingGroups(solution: SummarizableSolution): SummarizableGroup[] {
  return solution.groups.filter((group) => {
    const outcome = summarizeGroup(group).outcome;
    return outcome !== undefined && outcome !== 'accepted';
  });
}

function join(parts: (string | undefined)[]): string {
  return parts.filter((part): part is string => part !== undefined && part !== '').join(' · ');
}

/**
 * Score is shown only once the run is complete: a half-finished group has
 * earned nothing yet, and `[0/100 pts]` mid-run reads as a failure.
 */
function scorePart(summary: RunSummary): string | undefined {
  if (summary.maxScore === 0 || !isComplete(summary)) {
    return undefined;
  }
  return formatScore(summary.score, summary.maxScore);
}

function progressPart(summary: RunSummary): string | undefined {
  return isComplete(summary) ? undefined : `${summary.done}/${summary.total}`;
}

export function groupDescription(summary: RunSummary): string {
  return join([
    progressPart(summary),
    summary.done === 0 ? 'pending' : shortName(summary.outcome),
    scorePart(summary),
    formatTime(summary.time),
    formatMemory(summary.memory),
  ]);
}

export function solutionDescription(
  summary: RunSummary,
  expectedOutcome: string | undefined,
): string {
  // A verdict that contradicts problem.rbx.yml is the headline finding of a
  // run, so it replaces the bare verdict rather than sitting next to it.
  const mismatched =
    isComplete(summary) &&
    summary.outcome !== undefined &&
    !matches(expectedOutcome, summary.outcome);
  const verdict = mismatched
    ? `expected ${expectedShortName(expectedOutcome)}, got ${shortName(summary.outcome)}`
    : summary.done === 0
      ? 'pending'
      : shortName(summary.outcome);

  return join([
    progressPart(summary),
    verdict,
    scorePart(summary),
    formatTime(summary.time),
    formatMemory(summary.memory),
  ]);
}

/** `14 AC, 2 WA`, worst outcome last -- the order `OUTCOMES` ranks by. */
export function formatCounts(summary: RunSummary): string {
  return [...summary.counts.entries()]
    .sort(([a], [b]) => outcomeRank(a) - outcomeRank(b))
    .map(([outcome, count]) => `${count} ${shortName(outcome)}`)
    .join(', ');
}
