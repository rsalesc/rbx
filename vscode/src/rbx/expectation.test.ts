import * as assert from 'assert';
import { test } from 'node:test';

import { expectationDisplay } from './expectation';

// Transcribed by hand from `ExpectedOutcome` in rbx/box/schema.py. When rbx
// grows a member this list stops matching and the test below fails loudly --
// which is the whole point: the extension must never silently render a
// declaration it does not understand as if it were undeclared.
const MEMBERS = [
  'ANY',
  'ACCEPTED',
  'ACCEPTED_OR_TLE',
  'WRONG_ANSWER',
  'INCORRECT',
  'RUNTIME_ERROR',
  'TIME_LIMIT_EXCEEDED',
  'MEMORY_LIMIT_EXCEEDED',
  'OUTPUT_LIMIT_EXCEEDED',
  'TLE_OR_RTE',
  'JUDGE_FAILED',
  'COMPILATION_ERROR',
];

test('every ExpectedOutcome member declared in rbx has a display', () => {
  for (const member of MEMBERS) {
    const display = expectationDisplay(member);
    assert.notStrictEqual(display, undefined, `no display for ${member}`);
    // The unknown fallback is exactly a neutral, non-bold, raw-labelled row;
    // a member that lands on it is one the table forgot. ANY and INCORRECT
    // are legitimately labelled with their own name, hence the whole shape.
    assert.notDeepStrictEqual(
      display,
      { label: member, hue: 'neutral', bold: false, glyph: '✗' },
      `${member} fell through to the unknown fallback`,
    );
  }
});

test('nothing declared reads as undeclared, not as a display', () => {
  assert.strictEqual(expectationDisplay(undefined), undefined);
});

test('ACCEPTED is the bold green check', () => {
  assert.deepStrictEqual(expectationDisplay('ACCEPTED'), {
    label: 'AC',
    hue: 'green',
    bold: true,
    glyph: '✓',
  });
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

test('the compound expectations keep rbx spelling and hue', () => {
  assert.deepStrictEqual(expectationDisplay('ACCEPTED_OR_TLE'), {
    label: 'AC or TLE',
    hue: 'green',
    bold: false,
    glyph: '✓',
  });
  assert.deepStrictEqual(expectationDisplay('TLE_OR_RTE'), {
    label: 'TLE or RTE',
    hue: 'yellow',
    bold: false,
    glyph: '⧖',
  });
});

test('hues follow ExpectedOutcome.style()', () => {
  assert.strictEqual(expectationDisplay('ANY')?.hue, 'neutral');
  assert.strictEqual(expectationDisplay('WRONG_ANSWER')?.hue, 'red');
  assert.strictEqual(expectationDisplay('INCORRECT')?.hue, 'red');
  assert.strictEqual(expectationDisplay('TIME_LIMIT_EXCEEDED')?.hue, 'yellow');
  assert.strictEqual(expectationDisplay('MEMORY_LIMIT_EXCEEDED')?.hue, 'yellow');
  assert.strictEqual(expectationDisplay('RUNTIME_ERROR')?.hue, 'blue');
  assert.strictEqual(expectationDisplay('COMPILATION_ERROR')?.hue, 'blue');
  assert.strictEqual(expectationDisplay('OUTPUT_LIMIT_EXCEEDED')?.hue, 'purple');
  assert.strictEqual(expectationDisplay('JUDGE_FAILED')?.hue, 'purple');
});

test('ANY is the bold question mark', () => {
  assert.deepStrictEqual(expectationDisplay('ANY'), {
    label: 'ANY',
    hue: 'neutral',
    bold: true,
    glyph: '?',
  });
});
