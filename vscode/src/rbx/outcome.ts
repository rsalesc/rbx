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
    color: 'charts.yellow'
  },
  'idleness-limit-exceeded': {
    short: 'ILE',
    icon: 'debug-pause',
    color: 'charts.yellow'
  },
  'memory-limit-exceeded': {
    short: 'MLE',
    icon: 'server',
    color: 'charts.yellow'
  },
  'runtime-error': { short: 'RTE', icon: 'zap', color: 'charts.blue' },
  'output-limit-exceeded': {
    short: 'OLE',
    icon: 'arrow-both',
    color: 'charts.orange'
  },
  'judge-failed': { short: 'FL', icon: 'law', color: 'charts.purple' },
  'internal-error': { short: 'IE', icon: 'alert', color: 'charts.purple' },
  'compilation-error': {
    short: 'CE',
    icon: 'tools',
    color: 'charts.blue'
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

/**
 * The prefix of the contributed mismatch icons, which `contributes.icons` in
 * package.json declares and `scripts/build-mismatch-font.py` generates. One per
 * verdict icon, the same glyph with a mark in its corner.
 */
function mismatchIcon(icon: string): string {
  return `rbx-${icon}-mismatch`;
}

/**
 * The icon a row draws: which verdict, and whether it was the declared one.
 *
 * On a match this is #664's table untouched -- the verdict's own codicon in the
 * hue `rbx run` prints it in, so the tree and the terminal beside it agree.
 *
 * On a miss the icon switches to the same verdict's *mismatch* variant, which
 * is that codicon with a small circled cross in the top-right, and turns red.
 * The verdict is still legible -- a solution that missed by timing out still
 * shows a clock -- but the row stops claiming the run went to plan. Red rather
 * than the verdict's own hue is deliberate and is the one place this view
 * departs from the terminal palette: on a row that broke its promise the
 * interesting fact is the promise, not the verdict, and this is the only
 * channel left saying so once colour moved to the declaration.
 */
export function outcomeIcon(
  outcome: string | undefined,
  status: ExpectationStatus = 'unknown',
): OutcomeIcon {
  const { icon, color } = display(outcome);
  if (status !== 'missed') {
    return { icon, color };
  }
  // PENDING has no mismatch variant and needs none: a row with no verdict
  // cannot have missed anything. Fall back to its plain icon rather than
  // naming a glyph the font does not carry, which renders as blank.
  if (outcome === undefined) {
    return { icon, color };
  }
  return { icon: mismatchIcon(icon), color: 'charts.red' };
}

export function isAccepted(outcome: string | undefined): boolean {
  return outcome === 'accepted';
}

export function isSkipped(outcome: string | undefined): boolean {
  return outcome === 'skipped';
}

/**
 * How each declared expectation is spelled and badged.
 *
 * One record per member of `ExpectedOutcome` (rbx/box/schema.py), mirroring
 * that enum the way `DISPLAY` above mirrors `Outcome`. It is spelled out rather
 * than derived from `DISPLAY` because the two enums have different members:
 * `INCORRECT`, `ANY` and `TLE_OR_RTE` exist only here, `SKIPPED` only there.
 * Reaching an `Outcome` key by lowercasing an `ExpectedOutcome` name -- which
 * is what this file used to do -- holds today by coincidence, not by contract.
 *
 * `badge` is what the tree, the Explorer and the editor tab show. It is the
 * two-letter spelling rbx itself accepts for the expectation in
 * problem.rbx.yml -- `ac`, `wa`, `tl`, `ml`, `ol`, `re`, `jf`, `ce` -- so the
 * mark on the row is the same token the setter typed into the file, and the
 * view introduces no vocabulary of its own. The compound expectations use
 * rbx's `+` spelling from its `ac+tle` and `tle+re` aliases, which is also the
 * honest rendering: `A+` says "accepted, and more is tolerated".
 *
 * `ANY` deliberately has no badge: nothing was declared, and marking every
 * undeclared solution would put a symbol carrying no information on most rows.
 *
 * Two hard constraints on `badge`, both enforced by the test suite:
 *
 *   - **At most two characters.** `FileDecoration.validate` in VS Code throws
 *     on a longer badge, so an over-long entry here is a runtime failure in the
 *     view, not a cosmetic slip.
 *   - **Letters, not symbols.** The row already carries a codicon for the
 *     outcome (#664), and a second symbolic alphabet beside it reads as noise;
 *     letters also survive the badge's ~11px far better than `⧖` does. A
 *     codicon cannot be used here at all -- `FileDecoration.badge` is a
 *     `string`, not a `ThemeIcon`.
 */
interface ExpectedDisplay {
  /** Long form, for descriptions and hovers. */
  readonly short: string;
  /** At most two characters; absent for `ANY`. */
  readonly badge?: string;
  /** Hue of the declaration, from `ExpectedOutcome.style()`. */
  readonly color?: string;
}

const EXPECTED: Record<string, ExpectedDisplay> = {
  ANY: { short: 'ANY' },
  ACCEPTED: { short: 'AC', badge: 'AC', color: 'charts.green' },
  ACCEPTED_OR_TLE: { short: 'AC or TLE', badge: 'A+', color: 'charts.green' },
  WRONG_ANSWER: { short: 'WA', badge: 'WA', color: 'charts.red' },
  INCORRECT: { short: 'INCORRECT', badge: 'IN', color: 'charts.red' },
  RUNTIME_ERROR: { short: 'RTE', badge: 'RE', color: 'charts.blue' },
  TIME_LIMIT_EXCEEDED: { short: 'TLE', badge: 'TL', color: 'charts.yellow' },
  TLE_OR_RTE: { short: 'TLE or RTE', badge: 'T+', color: 'charts.yellow' },
  MEMORY_LIMIT_EXCEEDED: { short: 'MLE', badge: 'ML', color: 'charts.yellow' },
  // Purple, not the orange an OLE *outcome* draws: `ExpectedOutcome.style()`
  // has no branch for it and falls through to magenta, the same hue it gives
  // JUDGE_FAILED. Faithful to rbx rather than to the outcome palette, because
  // this colours a declaration and not a verdict.
  OUTPUT_LIMIT_EXCEEDED: { short: 'OLE', badge: 'OL', color: 'charts.purple' },
  JUDGE_FAILED: { short: 'FL', badge: 'JF', color: 'charts.purple' },
  COMPILATION_ERROR: { short: 'CE', badge: 'CE', color: 'charts.blue' },
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
  return expected === undefined ? undefined : EXPECTED[expected]?.badge;
}

/**
 * The colour a row wears for what it was declared to do.
 *
 * This is `ExpectedOutcome.style()` transposed onto the `charts.*` family, the
 * same transposition #664 made for the verdict palette -- so a solution
 * declared TLE is yellow here exactly as `rbx run` prints it yellow.
 *
 * Note what this colour is *not*: it does not say whether the declaration held.
 * That fact is carried by the icon, which grows a mark in its corner on a miss
 * (see `outcomeIcon`). A `FileDecoration` has one colour and no font styling --
 * rbx separates ACCEPTED from ACCEPTED_OR_TLE by weight, `bold green` against
 * plain `green`, which has no equivalent here -- so the two facts cannot share
 * this channel, and the badge spelling (`AC` against `A+`) carries the
 * distinction instead.
 */
export function expectationColor(expected: string | undefined): string | undefined {
  return expected === undefined ? undefined : EXPECTED[expected]?.color;
}

/**
 * Hover text for a decorated row: `Expected AC, got TLE`.
 *
 * A port of `ExpectedOutcome.full_markup()` joined to
 * `get_full_outcome_markup_verdict` -- the same sentence rbx prints, minus the
 * marks and the colour. rbx can afford `✓ ACCEPTED` there because a terminal
 * renders whatever it is given; `FileDecoration.tooltip` is a plain `string`,
 * so it can carry neither a codicon nor rbx's glyphs, and names alone are
 * clearer than a symbol the hover cannot explain.
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
  const declared = expectedShortName(expected);
  if (status === 'unknown') {
    return `Expected ${declared}`;
  }
  const got = shortName(outcome);
  if (status === 'met') {
    return `Expected ${declared}, got ${got}`;
  }
  return failedGroups.length > 0
    ? `Declared ${declared}, but ${failedGroups.join(', ')} did not match`
    : `Expected ${declared}, but got ${got}`;
}
