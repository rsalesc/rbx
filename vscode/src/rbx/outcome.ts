/**
 * How rbx's two outcome vocabularies are *displayed*. Nothing here decides
 * anything.
 *
 * This file used to be a port: the outcome ranking, `Outcome.worst_outcome()`
 * and `ExpectedOutcome.match()`, all re-implemented from Python with nothing
 * checking the copies against each other. Those answers now arrive already
 * decided in `.rbx/runs/report.yml` (see report.ts), and what is left is the
 * mapping from a value to the two-or-three letters shown in the tree.
 *
 * The two vocabularies are still genuinely different types and must not be
 * conflated:
 *
 *   - `Outcome` (rbx.grading.steps.Outcome) is what a run *produced*. It is a
 *     plain Enum, so it serializes as its lowercase kebab value: `wrong-answer`.
 *   - `ExpectedOutcome` (rbx.box.schema.ExpectedOutcome) is what problem.rbx.yml
 *     *declared*. It is an AutoEnum whose __str__ is the member name, so it
 *     serializes upper snake-case: `WRONG_ANSWER` -- not the `wa` alias the user
 *     typed, and not the `Outcome` spelling either.
 */

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

export function isSkipped(outcome: string | undefined): boolean {
  return outcome === 'skipped';
}

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
