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
  'time-limit-exceeded': { short: 'TLE', icon: 'watch', color: 'charts.yellow' },
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
  'compilation-error': { short: 'CE', icon: 'tools', color: 'charts.blue' },
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
  // `hasOwn`, not `??`: the key comes out of a `.eval` file, and a malformed
  // one naming `constructor` would otherwise reach Object.prototype's, which is
  // truthy -- so the fallback never fires and every field reads `undefined`.
  return Object.hasOwn(DISPLAY, outcome) ? DISPLAY[outcome] : UNKNOWN;
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
