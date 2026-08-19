import * as assert from 'assert';
import { test } from 'node:test';

import { ExpectationDisplay, expectationDisplay } from './expectation';

/**
 * Every member of `ExpectedOutcome`, with the display each one's `style()`,
 * `full_style()` and `icon()` produce, transcribed by hand from
 * rbx/box/schema.py as of 2026-08-19.
 *
 * Asserted as one whole table rather than member by member, because the
 * columns that are easiest to get wrong are the ones a spot check skips:
 * MEMORY_LIMIT_EXCEEDED sits between two `⧖` rows and Python decides its glyph
 * via `is_slow()`, which MLE fails. Pinning every column of every row is one
 * assertion and catches all of them.
 *
 * Note what this does *not* do: rbx growing a thirteenth member cannot fail a
 * list maintained by hand on this side. The new member would take the neutral
 * raw-label fallback, which is the designed graceful degradation -- so what
 * this table guards is a member being dropped or mistranscribed here, not rbx
 * moving underneath it. Re-check it against schema.py when bumping rbx.
 */
const EXPECTED: Record<string, ExpectationDisplay> = {
  ANY: { label: 'ANY', hue: 'neutral', bold: true, glyph: '?' },
  ACCEPTED: { label: 'AC', hue: 'green', bold: true, glyph: '✓' },
  ACCEPTED_OR_TLE: { label: 'AC or TLE', hue: 'green', bold: false, glyph: '✓' },
  WRONG_ANSWER: { label: 'WA', hue: 'red', bold: false, glyph: '✗' },
  INCORRECT: { label: 'INCORRECT', hue: 'red', bold: false, glyph: '✗' },
  RUNTIME_ERROR: { label: 'RTE', hue: 'blue', bold: false, glyph: '✗' },
  TIME_LIMIT_EXCEEDED: { label: 'TLE', hue: 'yellow', bold: false, glyph: '⧖' },
  MEMORY_LIMIT_EXCEEDED: { label: 'MLE', hue: 'yellow', bold: false, glyph: '✗' },
  OUTPUT_LIMIT_EXCEEDED: { label: 'OLE', hue: 'purple', bold: false, glyph: '✗' },
  TLE_OR_RTE: { label: 'TLE or RTE', hue: 'yellow', bold: false, glyph: '⧖' },
  JUDGE_FAILED: { label: 'FL', hue: 'purple', bold: false, glyph: '✗' },
  COMPILATION_ERROR: { label: 'CE', hue: 'blue', bold: false, glyph: '✗' },
};

const MEMBERS = Object.keys(EXPECTED);

test('every ExpectedOutcome member is displayed exactly as rbx draws it', () => {
  const actual = Object.fromEntries(
    MEMBERS.map((member) => [member, expectationDisplay(member)]),
  );
  assert.deepStrictEqual(actual, EXPECTED);
});

test('nothing declared reads as undeclared, not as a display', () => {
  assert.strictEqual(expectationDisplay(undefined), undefined);
});


test('a member from a newer rbx still renders, labelled with its raw name', () => {
  assert.deepStrictEqual(expectationDisplay('PARTIALLY_ACCEPTED'), {
    label: 'PARTIALLY_ACCEPTED',
    hue: 'neutral',
    bold: false,
    glyph: '✗',
  });
});

test('a name off Object.prototype is unknown, not whatever it inherits', () => {
  assert.deepStrictEqual(expectationDisplay('constructor'), {
    label: 'constructor',
    hue: 'neutral',
    bold: false,
    glyph: '✗',
  });
});



