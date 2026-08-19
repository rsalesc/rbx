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

/** A codicon id and a theme color id -- what the tree needs to draw a verdict. */
export interface OutcomeIcon {
  readonly icon: string;
  readonly color: string;
}

interface OutcomeDisplay {
  /** Mirrors `Outcome.short_name()`. */
  readonly short: string;
  readonly icon: string;
  readonly color: string;
}

/**
 * How each verdict is spelled and drawn.
 *
 * The colors are the terminal palette of `get_outcome_style_verdict`
 * (rbx/box/solutions.py) transposed onto VS Code's `charts.*` hues, which is
 * the only family that offers all six the CLI uses. Deliberately the whole
 * palette and not a pass/fail pair: the tree sits next to the terminal that
 * printed the same run, and a TLE that is yellow there must not be red here.
 * `magenta`, which the CLI keeps for verdicts that are nobody's fault but the
 * setup's, becomes `charts.purple`; `bright_black` becomes the dim foreground
 * VS Code already uses for de-emphasized text.
 *
 * The icon, unlike the color, is one per verdict -- the whole point is that WA,
 * TLE and RTE stop looking alike -- so keep them distinguishable at 16px and
 * prefer a codicon whose usual meaning already fits.
 */
const DISPLAY: Record<string, OutcomeDisplay> = {
  accepted: { short: 'AC', icon: 'pass', color: 'charts.green' },
  skipped: {
    short: 'SKIP',
    icon: 'debug-step-over',
    color: 'descriptionForeground',
  },
  'wrong-answer': { short: 'WA', icon: 'close', color: 'charts.red' },
  'time-limit-exceeded': {
    short: 'TLE',
    icon: 'watch',
    color: 'charts.yellow',
  },
  'idleness-limit-exceeded': {
    short: 'ILE',
    icon: 'debug-pause',
    color: 'charts.yellow',
  },
  'memory-limit-exceeded': {
    short: 'MLE',
    icon: 'server',
    color: 'charts.yellow',
  },
  'runtime-error': { short: 'RTE', icon: 'zap', color: 'charts.blue' },
  'output-limit-exceeded': {
    short: 'OLE',
    icon: 'arrow-both',
    color: 'charts.orange',
  },
  'judge-failed': { short: 'FL', icon: 'law', color: 'charts.purple' },
  'internal-error': { short: 'IE', icon: 'alert', color: 'charts.purple' },
  'compilation-error': {
    short: 'CE',
    icon: 'tools',
    color: 'charts.blue',
  },
};

/** A verdict this extension is too old to know; `XX`, as rbx renders it too. */
const UNKNOWN: OutcomeDisplay = {
  short: 'XX',
  icon: 'question',
  color: 'charts.purple',
};

/**
 * No evaluation on disk yet: either still running, or the run was interrupted.
 * Indistinguishable in v1; both read as pending.
 */
const PENDING: OutcomeDisplay = {
  short: '?',
  icon: 'circle-outline',
  color: 'descriptionForeground',
};

function display(outcome: string | undefined): OutcomeDisplay {
  if (outcome === undefined) {
    return PENDING;
  }
  return DISPLAY[outcome] ?? UNKNOWN;
}

export function shortName(outcome: string | undefined): string {
  return display(outcome).short;
}

export function outcomeIcon(outcome: string | undefined): OutcomeIcon {
  const { icon, color } = display(outcome);
  return { icon, color };
}

export function isAccepted(outcome: string | undefined): boolean {
  return outcome === 'accepted';
}

export function isSkipped(outcome: string | undefined): boolean {
  return outcome === 'skipped';
}

/**
 * How each declared expectation is spelled and drawn.
 *
 * One record per member of `ExpectedOutcome` (rbx/box/schema.py), mirroring
 * that enum the way `DISPLAY` above mirrors `Outcome`. It is spelled out rather
 * than derived from `DISPLAY`, because the enums have different members --
 * `INCORRECT`, `ANY` and `TLE_OR_RTE` exist only here, `SKIPPED` only there --
 * and reaching an `Outcome` key by lowercasing an `ExpectedOutcome` name, which
 * this file used to do, holds by coincidence rather than by contract.
 *
 * **The icon is the expectation, one to one.** In the tree this is what a
 * solution or group row draws on its left, so two expectations that are not the
 * same expectation must not share an icon: `ACCEPTED` and `ACCEPTED_OR_TLE` are
 * different promises, and so are `WRONG_ANSWER` and `INCORRECT`. Where an
 * expectation names exactly one outcome it borrows that outcome's icon from
 * `DISPLAY`, so the two vocabularies rhyme -- an `ACCEPTED` row and an accepted
 * testcase under it both draw `pass`. The four that name no single outcome get
 * an icon of their own:
 *
 *   - `ANY`             `dash`          nothing was declared
 *   - `ACCEPTED_OR_TLE` `pass-filled`   a pass, tolerating slow
 *   - `INCORRECT`       `circle-slash`  must fail, any way at all
 *   - `TLE_OR_RTE`      `flame`         must hang or crash
 *
 * The colours are `ExpectedOutcome.style()` transposed onto `charts.*`, the
 * same transposition `DISPLAY` makes for `get_outcome_style_verdict`. That is
 * exact CLI parity: `rbx run` colours each solution's column header by this
 * function, and the header is precisely what this icon replaces. Note it does
 * not always agree with the *outcome* palette -- a declared
 * `OUTPUT_LIMIT_EXCEEDED` is magenta here while an OLE verdict is orange there
 * -- because those are two different functions in rbx, and copying one onto the
 * other would be inventing a colour rbx never prints.
 */
interface ExpectedDisplay {
  /** Kept identical to what this file rendered before the table existed. */
  readonly short: string;
  readonly icon: string;
  readonly color: string;
}

const EXPECTED: Record<string, ExpectedDisplay> = {
  ANY: { short: 'ANY', icon: 'dash', color: 'foreground' },
  ACCEPTED: { short: 'AC', icon: 'pass', color: 'charts.green' },
  ACCEPTED_OR_TLE: {
    short: 'AC or TLE',
    icon: 'pass-filled',
    color: 'charts.green',
  },
  WRONG_ANSWER: { short: 'WA', icon: 'close', color: 'charts.red' },
  INCORRECT: { short: 'INCORRECT', icon: 'circle-slash', color: 'charts.red' },
  RUNTIME_ERROR: { short: 'RTE', icon: 'zap', color: 'charts.blue' },
  TIME_LIMIT_EXCEEDED: {
    short: 'TLE',
    icon: 'watch',
    color: 'charts.yellow',
  },
  TLE_OR_RTE: { short: 'TLE or RTE', icon: 'flame', color: 'charts.yellow' },
  MEMORY_LIMIT_EXCEEDED: {
    short: 'MLE',
    icon: 'server',
    color: 'charts.yellow',
  },
  OUTPUT_LIMIT_EXCEEDED: {
    short: 'OLE',
    icon: 'arrow-both',
    color: 'charts.purple',
  },
  JUDGE_FAILED: { short: 'FL', icon: 'law', color: 'charts.purple' },
  COMPILATION_ERROR: { short: 'CE', icon: 'tools', color: 'charts.blue' },
};

/** Whether a run honoured what the package declared for it. */
export type ExpectationStatus = 'met' | 'missed' | 'unknown';

/**
 * The mark a mismatched row wears on its right.
 *
 * `FileDecoration.badge` is a `string`, so this is the one place a codicon
 * cannot go. It is not a second vocabulary though -- it says nothing about
 * *which* expectation or *which* verdict, only that the two disagree, and it
 * appears on no other row.
 */
export const MISMATCH_BADGE = '✗';

/** Display form of an expectation, e.g. `ACCEPTED_OR_TLE` -> `AC or TLE`. */
export function expectedShortName(expected: string | undefined): string {
  if (expected === undefined) {
    return '?';
  }
  // `XX`, matching how an unknown *outcome* reads: an expectation this
  // extension is too old to know is named as unknown, never guessed at.
  return EXPECTED[expected]?.short ?? UNKNOWN.short;
}

/**
 * The icon and colour a row draws for what it was declared to do.
 *
 * Absent when nothing was declared or the declaration comes from an rbx newer
 * than this extension; the caller then falls back to what actually happened,
 * which is the only thing it still knows.
 */
export function expectationIcon(
  expected: string | undefined,
): OutcomeIcon | undefined {
  const display = expected === undefined ? undefined : EXPECTED[expected];
  return display === undefined
    ? undefined
    : { icon: display.icon, color: display.color };
}

/**
 * The colour a row's *label* takes for whether that declaration held.
 *
 * Only a miss is coloured, and it is the one thing in the view that is: a row
 * whose text is red is a row where the package disagrees with itself. Verdict
 * colour lives in the icon, so this channel is free to mean exactly one thing.
 */
export function expectationColor(status: ExpectationStatus): string | undefined {
  return status === 'missed' ? 'charts.red' : undefined;
}
