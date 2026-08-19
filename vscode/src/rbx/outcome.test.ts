import * as assert from 'assert';
import { test } from 'node:test';

import {
  expectationColor,
  expectationIcon,
  expectedShortName,
  outcomeIcon,
  shortName,
} from './outcome';

// The colors are asserted against the CLI palette in
// `get_outcome_style_verdict` (rbx/box/solutions.py) rather than against
// "green means good": the two views are read side by side, so a verdict that
// is yellow in the terminal must not be red in the tree.
const CLI_PALETTE: Record<string, string> = {
  accepted: 'charts.green',
  'wrong-answer': 'charts.red',
  'time-limit-exceeded': 'charts.yellow',
  'idleness-limit-exceeded': 'charts.yellow',
  'memory-limit-exceeded': 'charts.yellow',
  'output-limit-exceeded': 'charts.orange',
  'runtime-error': 'charts.blue',
  'compilation-error': 'charts.blue',
  'judge-failed': 'charts.purple',
  'internal-error': 'charts.purple',
  skipped: 'descriptionForeground',
};

test('every outcome carries the color the CLI prints it in', () => {
  for (const [outcome, color] of Object.entries(CLI_PALETTE)) {
    assert.strictEqual(outcomeIcon(outcome).color, color, outcome);
  }
});

test('every outcome gets its own codicon', () => {
  const icons = Object.keys(CLI_PALETTE).map((o) => outcomeIcon(o).icon);
  assert.strictEqual(new Set(icons).size, icons.length, icons.join(','));
});

test('an unevaluated testcase reads as pending, not as a failure', () => {
  assert.deepStrictEqual(outcomeIcon(undefined), {
    icon: 'circle-outline',
    color: 'descriptionForeground',
  });
});

test('an outcome rbx grew after this extension shipped is not called a pass', () => {
  // Same fallback `shortName` takes: unknown is unknown, never green.
  assert.strictEqual(shortName('teleported'), 'XX');
  assert.deepStrictEqual(outcomeIcon('teleported'), {
    icon: 'question',
    color: 'charts.purple',
  });
});

// Every member of `ExpectedOutcome` (rbx/box/schema.py), so a variant rbx adds
// fails here rather than silently rendering as unknown in the tree.
const EXPECTED_OUTCOMES = [
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

test('every declared expectation has a name of its own', () => {
  // This is what replaced deriving an `Outcome` key by lowercasing an
  // `ExpectedOutcome` name: the enums have different members, so the old
  // derivation held only by coincidence.
  for (const expected of EXPECTED_OUTCOMES) {
    assert.notStrictEqual(expectedShortName(expected), 'XX', expected);
  }
});

test('expectation names are unchanged by the move to a table', () => {
  assert.strictEqual(expectedShortName('ACCEPTED'), 'AC');
  assert.strictEqual(expectedShortName('ACCEPTED_OR_TLE'), 'AC or TLE');
  assert.strictEqual(expectedShortName('TLE_OR_RTE'), 'TLE or RTE');
  assert.strictEqual(expectedShortName('INCORRECT'), 'INCORRECT');
  assert.strictEqual(expectedShortName('MEMORY_LIMIT_EXCEEDED'), 'MLE');
  assert.strictEqual(expectedShortName('JUDGE_FAILED'), 'FL');
  assert.strictEqual(expectedShortName(undefined), '?');
  assert.strictEqual(expectedShortName('TELEPORTED'), 'XX');
});

test('every declared expectation gets an icon of its own', () => {
  // One to one: the icon *is* the expectation in the tree, so two different
  // promises must not draw the same thing. This is what rules out reusing a
  // coarse pass/fail/slow set -- ACCEPTED and ACCEPTED_OR_TLE would collide,
  // and so would WRONG_ANSWER and INCORRECT.
  const icons = EXPECTED_OUTCOMES.map((expected) => expectationIcon(expected)?.icon);
  assert.ok(
    icons.every((icon) => icon !== undefined),
    `missing icon: ${EXPECTED_OUTCOMES.filter((_, i) => icons[i] === undefined).join(',')}`,
  );
  assert.strictEqual(new Set(icons).size, icons.length, icons.join(','));
});

test('the pairs that a coarse icon set would have collapsed stay distinct', () => {
  assert.notStrictEqual(
    expectationIcon('ACCEPTED')?.icon,
    expectationIcon('ACCEPTED_OR_TLE')?.icon,
  );
  assert.notStrictEqual(
    expectationIcon('WRONG_ANSWER')?.icon,
    expectationIcon('INCORRECT')?.icon,
  );
  assert.notStrictEqual(
    expectationIcon('TIME_LIMIT_EXCEEDED')?.icon,
    expectationIcon('TLE_OR_RTE')?.icon,
  );
});

test('an expectation naming one outcome borrows that outcome icon', () => {
  // So an ACCEPTED row and an accepted testcase beneath it draw the same mark.
  // Only the four that name no single outcome are allowed their own.
  for (const [expected, outcome] of [
    ['ACCEPTED', 'accepted'],
    ['WRONG_ANSWER', 'wrong-answer'],
    ['TIME_LIMIT_EXCEEDED', 'time-limit-exceeded'],
    ['MEMORY_LIMIT_EXCEEDED', 'memory-limit-exceeded'],
    ['RUNTIME_ERROR', 'runtime-error'],
    ['OUTPUT_LIMIT_EXCEEDED', 'output-limit-exceeded'],
    ['COMPILATION_ERROR', 'compilation-error'],
    ['JUDGE_FAILED', 'judge-failed'],
  ]) {
    assert.strictEqual(
      expectationIcon(expected)?.icon,
      outcomeIcon(outcome).icon,
      expected,
    );
  }
});

test('expectation colours are the ones rbx prints for a declaration', () => {
  // `ExpectedOutcome.style()`, not `get_outcome_style_verdict`. They disagree
  // -- a declared OLE is magenta while an OLE verdict is orange -- and copying
  // the verdict palette over would invent a colour rbx never prints.
  const CLI_EXPECTED_PALETTE: Record<string, string> = {
    ACCEPTED: 'charts.green',
    ACCEPTED_OR_TLE: 'charts.green',
    WRONG_ANSWER: 'charts.red',
    INCORRECT: 'charts.red',
    RUNTIME_ERROR: 'charts.blue',
    TIME_LIMIT_EXCEEDED: 'charts.yellow',
    TLE_OR_RTE: 'charts.yellow',
    MEMORY_LIMIT_EXCEEDED: 'charts.yellow',
    OUTPUT_LIMIT_EXCEEDED: 'charts.purple',
    JUDGE_FAILED: 'charts.purple',
    COMPILATION_ERROR: 'charts.blue',
  };
  for (const [expected, color] of Object.entries(CLI_EXPECTED_PALETTE)) {
    assert.strictEqual(expectationIcon(expected)?.color, color, expected);
  }
});

test('an expectation this extension does not know draws no icon', () => {
  // The row falls back to its verdict rather than inventing a mark.
  assert.strictEqual(expectationIcon('TELEPORTED'), undefined);
  assert.strictEqual(expectationIcon(undefined), undefined);
});

test('only a miss is coloured, so misses are the only coloured rows', () => {
  assert.strictEqual(expectationColor('missed'), 'charts.red');
  assert.strictEqual(expectationColor('met'), undefined);
  assert.strictEqual(expectationColor('unknown'), undefined);
});
