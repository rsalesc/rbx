/**
 * How a *declared* expectation is drawn -- `ExpectedOutcome`, never `Outcome`.
 *
 * The table below is written out one member at a time, transcribed from
 * `ExpectedOutcome.style()`, `full_style()` and `icon()` in rbx/box/schema.py,
 * and deliberately derives nothing from the `Outcome` table in outcome.ts. The
 * two enums merely happen to share some spellings; lowercasing an
 * `ExpectedOutcome` name to reach an `Outcome` key -- which is what the
 * `expectedShortName` this file replaced used to do -- works only by
 * coincidence, and silently mislabels every member where the coincidence stops
 * (INCORRECT, TLE_OR_RTE, ANY). An explicit record per member is the point.
 */
import { Hue } from './hue';

export interface ExpectationDisplay {
  /** e.g. `AC`, `INCORRECT`, `AC or TLE`. */
  readonly label: string;
  readonly hue: Hue;
  readonly bold: boolean;
  /** Mirrors `ExpectedOutcome.icon()`. */
  readonly glyph: string;
}

const CHECK = '✓';
const CROSS = '✗';
/** `is_slow()`: the expectation tolerates a solution that runs out of time. */
const HOURGLASS = '⧖';

const DISPLAY: Record<string, ExpectationDisplay> = {
  ANY: { label: 'ANY', hue: 'neutral', bold: true, glyph: '?' },
  ACCEPTED: { label: 'AC', hue: 'green', bold: true, glyph: CHECK },
  ACCEPTED_OR_TLE: {
    label: 'AC or TLE',
    hue: 'green',
    bold: false,
    glyph: CHECK,
  },
  WRONG_ANSWER: { label: 'WA', hue: 'red', bold: false, glyph: CROSS },
  INCORRECT: { label: 'INCORRECT', hue: 'red', bold: false, glyph: CROSS },
  RUNTIME_ERROR: { label: 'RTE', hue: 'blue', bold: false, glyph: CROSS },
  TIME_LIMIT_EXCEEDED: {
    label: 'TLE',
    hue: 'yellow',
    bold: false,
    glyph: HOURGLASS,
  },
  MEMORY_LIMIT_EXCEEDED: {
    label: 'MLE',
    hue: 'yellow',
    bold: false,
    glyph: CROSS,
  },
  OUTPUT_LIMIT_EXCEEDED: {
    label: 'OLE',
    hue: 'purple',
    bold: false,
    glyph: CROSS,
  },
  TLE_OR_RTE: {
    label: 'TLE or RTE',
    hue: 'yellow',
    bold: false,
    glyph: HOURGLASS,
  },
  JUDGE_FAILED: { label: 'FL', hue: 'purple', bold: false, glyph: CROSS },
  COMPILATION_ERROR: { label: 'CE', hue: 'blue', bold: false, glyph: CROSS },
};

/**
 * How to draw `expected`; `undefined` when nothing was declared.
 *
 * A member this extension is too old to know still gets a display, labelled
 * with the raw string. Folding it into `undefined` would render a declaration
 * the setter wrote as if they had written none, which is a lie about their
 * package rather than a gap in ours.
 */
export function expectationDisplay(
  expected: string | undefined,
): ExpectationDisplay | undefined {
  if (expected === undefined) {
    return undefined;
  }
  // `hasOwn`, not a plain lookup: the key comes straight out of the package's
  // YAML, and a member spelled `constructor` would otherwise resolve to
  // something inherited from Object.prototype instead of reading as unknown.
  if (Object.hasOwn(DISPLAY, expected)) {
    return DISPLAY[expected];
  }
  return { label: expected, hue: 'neutral', bold: false, glyph: CROSS };
}
