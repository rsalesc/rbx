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
  /** Mirrors `get_outcome_markup_verdict` (rbx/box/solutions.py). */
  readonly glyph: string;
}

/**
 * The one symbol alphabet, shared by both vocabularies below.
 *
 * rbx draws an outcome and an expectation with the same four marks -- an
 * *expected* WA and a *got* WA both read `✗` -- and the two tables in this file
 * must not quietly grow a fifth. Named rather than inlined so that is visible.
 */
const GLYPH = {
  ok: '✓',
  bad: '✗',
  slow: '⧖',
  skipped: '⊘',
  unknown: '?',
} as const;

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
  accepted: { short: 'AC', icon: 'pass', color: 'charts.green', glyph: GLYPH.ok },
  skipped: {
    short: 'SKIP',
    icon: 'debug-step-over',
    color: 'descriptionForeground',
    glyph: GLYPH.skipped,
  },
  'wrong-answer': { short: 'WA', icon: 'close', color: 'charts.red', glyph: GLYPH.bad },
  'time-limit-exceeded': {
    short: 'TLE',
    icon: 'watch',
    color: 'charts.yellow',
    glyph: GLYPH.slow,
  },
  'idleness-limit-exceeded': {
    short: 'ILE',
    icon: 'debug-pause',
    color: 'charts.yellow',
    glyph: GLYPH.slow,
  },
  'memory-limit-exceeded': {
    short: 'MLE',
    icon: 'server',
    color: 'charts.yellow',
    glyph: GLYPH.bad,
  },
  'runtime-error': { short: 'RTE', icon: 'zap', color: 'charts.blue', glyph: GLYPH.bad },
  'output-limit-exceeded': {
    short: 'OLE',
    icon: 'arrow-both',
    color: 'charts.orange',
    glyph: GLYPH.bad,
  },
  'judge-failed': { short: 'FL', icon: 'law', color: 'charts.purple', glyph: GLYPH.bad },
  'internal-error': { short: 'IE', icon: 'alert', color: 'charts.purple', glyph: GLYPH.bad },
  'compilation-error': {
    short: 'CE',
    icon: 'tools',
    color: 'charts.blue',
    glyph: GLYPH.bad,
  },
};

/** A verdict this extension is too old to know; `XX`, as rbx renders it too. */
const UNKNOWN: OutcomeDisplay = {
  short: 'XX',
  icon: 'question',
  color: 'charts.purple',
  glyph: GLYPH.unknown,
};

/**
 * No evaluation on disk yet: either still running, or the run was interrupted.
 * Indistinguishable in v1; both read as pending.
 */
const PENDING: OutcomeDisplay = {
  short: '?',
  icon: 'circle-outline',
  color: 'descriptionForeground',
  glyph: GLYPH.unknown,
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
 * How each declared expectation is spelled and marked.
 *
 * One record per member of `ExpectedOutcome` (rbx/box/schema.py), mirroring
 * that enum the way `DISPLAY` above mirrors `Outcome`. It is spelled out rather
 * than derived from `DISPLAY` for two reasons, and both are load-bearing:
 *
 *   - The two enums have different members. `INCORRECT`, `ANY` and `TLE_OR_RTE`
 *     exist only here; `SKIPPED` only there. Reaching an `Outcome` key by
 *     lowercasing an `ExpectedOutcome` name -- which is what this file used to
 *     do -- holds today by coincidence, not by contract.
 *   - The glyph is not the glyph of the outcomes an expectation matches.
 *     `ACCEPTED_OR_TLE` matches both `ACCEPTED` and TLE yet rbx marks it `✓`,
 *     and `INCORRECT` matches five outcomes yet is marked `✗`. Any derivation
 *     gets both of those wrong; `ExpectedOutcome.icon()` is a table, so this is
 *     a table.
 *
 * `glyph` is what the tree badges a solution with, so `ANY` deliberately has
 * none: nothing was declared, and marking every undeclared solution would put
 * a symbol carrying no information on most rows in the view.
 */
interface ExpectedDisplay {
  /** Kept identical to what this file rendered before the table existed. */
  readonly short: string;
  /** Mirrors `ExpectedOutcome.icon()`; absent for `ANY`. */
  readonly glyph?: string;
}

const EXPECTED: Record<string, ExpectedDisplay> = {
  ANY: { short: 'ANY' },
  ACCEPTED: { short: 'AC', glyph: GLYPH.ok },
  ACCEPTED_OR_TLE: { short: 'AC or TLE', glyph: GLYPH.ok },
  WRONG_ANSWER: { short: 'WA', glyph: GLYPH.bad },
  INCORRECT: { short: 'INCORRECT', glyph: GLYPH.bad },
  RUNTIME_ERROR: { short: 'RTE', glyph: GLYPH.bad },
  TIME_LIMIT_EXCEEDED: { short: 'TLE', glyph: GLYPH.slow },
  TLE_OR_RTE: { short: 'TLE or RTE', glyph: GLYPH.slow },
  MEMORY_LIMIT_EXCEEDED: { short: 'MLE', glyph: GLYPH.bad },
  OUTPUT_LIMIT_EXCEEDED: { short: 'OLE', glyph: GLYPH.bad },
  JUDGE_FAILED: { short: 'FL', glyph: GLYPH.bad },
  COMPILATION_ERROR: { short: 'CE', glyph: GLYPH.bad },
};

/** Whether a run honoured what the package declared for it. */
export type ExpectationStatus = 'met' | 'missed' | 'unknown';

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
 * The mark a row wears for what it was declared to do.
 *
 * Absent means "do not decorate this row at all": either nothing was declared
 * (`ANY`), or the declaration is from an rbx newer than this extension, in
 * which case an invented badge would be worse than none.
 */
export function expectationBadge(expected: string | undefined): string | undefined {
  return expected === undefined ? undefined : EXPECTED[expected]?.glyph;
}

/**
 * The colour a row wears for whether that declaration held.
 *
 * Only a miss is coloured. This is the one deliberate divergence from the CLI,
 * which tints the expectation by its own hue (`ExpectedOutcome.style()`): a
 * single channel cannot carry both facts, and colouring by what was *declared*
 * leaves a mismatch with no colour of its own -- which is the thing the reader
 * most needs to find. Everything else stays uncoloured so that misses are the
 * only coloured rows in the view.
 */
export function expectationColor(status: ExpectationStatus): string | undefined {
  return status === 'missed' ? 'charts.red' : undefined;
}

/**
 * Hover text for a decorated row: `Expected ✓ AC, got ⧖ TLE`.
 *
 * A port of `ExpectedOutcome.full_markup()` (`f'{icon} {name}'`) joined to
 * `get_full_outcome_markup_verdict`, which is the same sentence rbx prints --
 * minus the colour, which the decoration itself is carrying.
 *
 * `failedGroups` is not decoration: a solution declares its expectations in two
 * layers and rbx checks both, so a miss caught only by the per-group layer must
 * not be reported as if the pooled one had been violated. `sols/mislabeled.cpp`
 * in the `outcome-per-group` fixture is the case -- its pooled `INCORRECT` is
 * satisfied, it does fail, and saying "expected INCORRECT, but got WA" would
 * accuse an expectation that was in fact met. Same distinction
 * `solutionVerdict` (summary.ts) draws, for the same reason.
 */
export function expectationTooltip(
  expected: string | undefined,
  outcome: string | undefined,
  status: ExpectationStatus,
  failedGroups: readonly string[] = [],
): string {
  const badge = expectationBadge(expected);
  const declared = `${badge === undefined ? '' : `${badge} `}${expectedShortName(expected)}`;
  if (status === 'unknown') {
    return `Expected ${declared}`;
  }
  const got = `${display(outcome).glyph} ${shortName(outcome)}`;
  if (status === 'met') {
    return `Expected ${declared}, got ${got}`;
  }
  return failedGroups.length > 0
    ? `Declared ${declared}, but ${failedGroups.join(', ')} did not match`
    : `Expected ${declared}, but got ${got}`;
}
