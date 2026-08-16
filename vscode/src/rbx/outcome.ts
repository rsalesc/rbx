/**
 * The two outcome vocabularies rbx serializes, and the matching rule between them.
 *
 * They are genuinely different types and must not be conflated:
 *
 *   - `Outcome` (rbx.grading.steps.Outcome) is what a run *produced*. It is a
 *     plain Enum, so it serializes as its lowercase kebab value: `wrong-answer`.
 *   - `ExpectedOutcome` (rbx.box.schema.ExpectedOutcome) is what problem.rbx.yml
 *     *declared*. It is an AutoEnum whose __str__ is the member name, so it
 *     serializes upper snake-case: `WRONG_ANSWER` -- not the `wa` alias the user
 *     typed, and not the `Outcome` spelling either.
 *
 * An expectation can cover several outcomes (`ACCEPTED_OR_TLE`, `INCORRECT`),
 * so "did this solution behave as declared?" is a real predicate, ported here
 * from `ExpectedOutcome.match()`.
 */

/** Serialized `Outcome` values, best to worst -- the declaration order rbx ranks by. */
export const OUTCOMES = [
  'accepted',
  'skipped',
  'wrong-answer',
  'memory-limit-exceeded',
  'time-limit-exceeded',
  'idleness-limit-exceeded',
  'runtime-error',
  'output-limit-exceeded',
  'judge-failed',
  'internal-error',
  'compilation-error',
] as const;

export type Outcome = (typeof OUTCOMES)[number];

/** Mirrors `Outcome.short_name()`; unknown values render `XX`, as rbx does. */
const SHORT_NAMES: Record<string, string> = {
  accepted: 'AC',
  skipped: 'SKIP',
  'wrong-answer': 'WA',
  'time-limit-exceeded': 'TLE',
  'idleness-limit-exceeded': 'ILE',
  'memory-limit-exceeded': 'MLE',
  'runtime-error': 'RTE',
  'output-limit-exceeded': 'OLE',
  'judge-failed': 'FL',
  'internal-error': 'IE',
  'compilation-error': 'CE',
};

export function shortName(outcome: string | undefined): string {
  if (outcome === undefined) {
    return '?';
  }
  return SHORT_NAMES[outcome] ?? 'XX';
}

export function isAccepted(outcome: string | undefined): boolean {
  return outcome === 'accepted';
}

/** Mirrors `Outcome.is_slow()`. */
export function isSlow(outcome: string): boolean {
  return outcome === 'time-limit-exceeded' || outcome === 'idleness-limit-exceeded';
}

/**
 * How bad an outcome is, by the declaration index rbx ranks with.
 *
 * Outcomes this extension does not know come from a newer rbx and rank worst,
 * so they surface instead of hiding behind a green group.
 */
export function outcomeRank(outcome: string): number {
  const known = OUTCOMES.indexOf(outcome as Outcome);
  return known === -1 ? OUTCOMES.length : known;
}

/**
 * Worst of a set of outcomes, mirroring `Outcome.worst_outcome()` -- which ranks
 * by declaration index, so SKIPPED is worse than ACCEPTED but better than any
 * real failure.
 */
export function worstOutcome(outcomes: Iterable<string | undefined>): string | undefined {
  let worst: string | undefined;
  let worstRank = -1;
  for (const outcome of outcomes) {
    if (outcome === undefined) {
      continue;
    }
    const rank = outcomeRank(outcome);
    if (rank > worstRank) {
      worstRank = rank;
      worst = outcome;
    }
  }
  return worst;
}

/** Serialized `ExpectedOutcome` member names. */
export type ExpectedOutcome =
  | 'ANY'
  | 'ACCEPTED'
  | 'ACCEPTED_OR_TLE'
  | 'WRONG_ANSWER'
  | 'INCORRECT'
  | 'RUNTIME_ERROR'
  | 'TIME_LIMIT_EXCEEDED'
  | 'MEMORY_LIMIT_EXCEEDED'
  | 'OUTPUT_LIMIT_EXCEEDED'
  | 'TLE_OR_RTE'
  | 'JUDGE_FAILED'
  | 'COMPILATION_ERROR';

/** Display form of an expectation, e.g. `ACCEPTED_OR_TLE` -> `AC or TLE`. */
export function expectedShortName(expected: string | undefined): string {
  switch (expected) {
    case undefined:
      return '?';
    case 'ANY':
      return 'ANY';
    case 'ACCEPTED_OR_TLE':
      return 'AC or TLE';
    case 'TLE_OR_RTE':
      return 'TLE or RTE';
    case 'INCORRECT':
      return 'INCORRECT';
    default:
      return shortName(expected.toLowerCase().replace(/_/g, '-'));
  }
}

/**
 * Does `outcome` satisfy `expected`? A faithful port of `ExpectedOutcome.match()`.
 *
 * An unrecognized expectation returns `true`: it comes from a newer rbx, and
 * claiming a mismatch we cannot actually judge would be worse than staying quiet.
 */
export function matches(expected: string | undefined, outcome: string): boolean {
  if (expected === undefined || expected === 'ANY') {
    return true;
  }
  // A skipped testcase was not awarded, so it satisfies any expectation that
  // does not demand success.
  if (outcome === 'skipped') {
    return expected !== 'ACCEPTED';
  }
  switch (expected) {
    case 'COMPILATION_ERROR':
      return outcome === 'compilation-error';
    case 'ACCEPTED':
      return outcome === 'accepted';
    case 'ACCEPTED_OR_TLE':
      return outcome === 'accepted' || isSlow(outcome);
    case 'WRONG_ANSWER':
      return outcome === 'wrong-answer';
    case 'INCORRECT':
      return (
        outcome === 'wrong-answer' ||
        outcome === 'runtime-error' ||
        outcome === 'memory-limit-exceeded' ||
        outcome === 'output-limit-exceeded' ||
        isSlow(outcome)
      );
    case 'RUNTIME_ERROR':
      return outcome === 'runtime-error';
    case 'TIME_LIMIT_EXCEEDED':
      return isSlow(outcome);
    case 'MEMORY_LIMIT_EXCEEDED':
      return outcome === 'memory-limit-exceeded';
    case 'TLE_OR_RTE':
      return outcome === 'runtime-error' || isSlow(outcome);
    case 'OUTPUT_LIMIT_EXCEEDED':
      return outcome === 'output-limit-exceeded';
    case 'JUDGE_FAILED':
      return outcome === 'judge-failed';
    default:
      return true;
  }
}
