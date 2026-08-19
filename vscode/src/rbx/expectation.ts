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
  /**
   * The Explorer badge: at most two characters, because two is all a
   * `FileDecoration` renders.
   *
   * Two rules generate the whole column, and both are load-bearing:
   *
   * 1. The first character *is* `glyph`, so a badge can never contradict what
   *    `rbx run` prints in the terminal for the same declaration.
   * 2. A second character appears only when the expectation is not the
   *    canonical member of its glyph's family, and says how it differs: `⧖`
   *    "or slow", `!` "or crashing", `?` "unspecified which failure", or a
   *    letter naming a rarer specific verdict.
   *
   * Rule 2 is what keeps apart the pairs that share a hue and a glyph, and so
   * would otherwise be indistinguishable here: AC from AC-or-TLE, and WA from
   * INCORRECT. A `FileDecoration` has a badge, a colour and a tooltip and
   * nothing else, so the badge is the only channel left to tell them with.
   */
  readonly badge: string;
}

const CHECK = '✓';
const CROSS = '✗';
/** `is_slow()`: the expectation tolerates a solution that runs out of time. */
const HOURGLASS = '⧖';
/** Second badge character for the expectations that admit a crash. */
const CRASH = '!';

const DISPLAY: Record<string, ExpectationDisplay> = {
  ANY: { label: 'ANY', hue: 'neutral', bold: true, glyph: '?', badge: '?' },
  ACCEPTED: {
    label: 'AC',
    hue: 'green',
    bold: true,
    glyph: CHECK,
    badge: CHECK,
  },
  ACCEPTED_OR_TLE: {
    label: 'AC or TLE',
    hue: 'green',
    bold: false,
    glyph: CHECK,
    badge: CHECK + HOURGLASS,
  },
  WRONG_ANSWER: {
    label: 'WA',
    hue: 'red',
    bold: false,
    glyph: CROSS,
    badge: CROSS,
  },
  INCORRECT: {
    label: 'INCORRECT',
    hue: 'red',
    bold: false,
    glyph: CROSS,
    badge: `${CROSS}?`,
  },
  RUNTIME_ERROR: {
    label: 'RTE',
    hue: 'blue',
    bold: false,
    glyph: CROSS,
    badge: CROSS + CRASH,
  },
  TIME_LIMIT_EXCEEDED: {
    label: 'TLE',
    hue: 'yellow',
    bold: false,
    glyph: HOURGLASS,
    badge: HOURGLASS,
  },
  MEMORY_LIMIT_EXCEEDED: {
    label: 'MLE',
    hue: 'yellow',
    bold: false,
    glyph: CROSS,
    badge: `${CROSS}M`,
  },
  OUTPUT_LIMIT_EXCEEDED: {
    label: 'OLE',
    hue: 'purple',
    bold: false,
    glyph: CROSS,
    badge: `${CROSS}O`,
  },
  TLE_OR_RTE: {
    label: 'TLE or RTE',
    hue: 'yellow',
    bold: false,
    glyph: HOURGLASS,
    badge: HOURGLASS + CRASH,
  },
  JUDGE_FAILED: {
    label: 'FL',
    hue: 'purple',
    bold: false,
    glyph: CROSS,
    badge: `${CROSS}J`,
  },
  COMPILATION_ERROR: {
    label: 'CE',
    hue: 'blue',
    bold: false,
    glyph: CROSS,
    badge: `${CROSS}C`,
  },
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
  return {
    label: expected,
    hue: 'neutral',
    bold: false,
    glyph: CROSS,
    // No second character. Rule 2 says what makes an expectation differ from
    // its family's canonical member, and for a member this extension has never
    // heard of there is no honest answer -- so the badge claims only the little
    // that is known: something is declared here, and it is not a plain pass.
    badge: CROSS,
  };
}
