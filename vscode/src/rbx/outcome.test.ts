import * as assert from 'assert';
import { test } from 'node:test';

import {
  expectationBadge,
  expectationColor,
  expectationTooltip,
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

test('badges use the same alphabet rbx marks outcomes with', () => {
  // One vocabulary across both axes, as in the CLI, where an *expected* WA and
  // a *got* WA both read the same mark. A badge outside this set means the two
  // tables have grown apart.
  const alphabet = new Set(['\u2713', '\u2717', '\u29d6', '\u2298']);
  for (const expected of EXPECTED_OUTCOMES) {
    const badge = expectationBadge(expected);
    if (badge !== undefined) {
      assert.ok(alphabet.has(badge), `${expected} -> ${badge}`);
    }
  }
});

test('a compound expectation is marked by what it wants, not by what it allows', () => {
  // Both are traps for deriving the glyph from the outcomes an expectation
  // matches: ACCEPTED_OR_TLE matches TLE but wants a pass, and INCORRECT
  // matches five outcomes including slow ones but wants a failure.
  assert.strictEqual(expectationBadge('ACCEPTED_OR_TLE'), '\u2713');
  assert.strictEqual(expectationBadge('TLE_OR_RTE'), '\u29d6');
  assert.strictEqual(expectationBadge('INCORRECT'), '\u2717');
});

test('nothing declared and nothing known are both left unbadged', () => {
  // `ANY` promises nothing, and an expectation newer than this extension is
  // not guessed at -- inventing a mark is worse than leaving the row alone.
  assert.strictEqual(expectationBadge('ANY'), undefined);
  assert.strictEqual(expectationBadge(undefined), undefined);
  assert.strictEqual(expectationBadge('TELEPORTED'), undefined);
});

test('only a miss is coloured, so misses are the only coloured rows', () => {
  assert.strictEqual(expectationColor('missed'), 'charts.red');
  assert.strictEqual(expectationColor('met'), undefined);
  assert.strictEqual(expectationColor('unknown'), undefined);
});

test('the hover names both sides in rbx own spelling', () => {
  assert.strictEqual(
    expectationTooltip('WRONG_ANSWER', 'wrong-answer', 'met'),
    'Expected \u2717 WA, got \u2717 WA',
  );
  assert.strictEqual(
    expectationTooltip('ACCEPTED', 'time-limit-exceeded', 'missed'),
    'Expected \u2713 AC, but got \u29d6 TLE',
  );
  // Nothing is claimed about an outcome that does not exist yet.
  assert.strictEqual(
    expectationTooltip('ACCEPTED', undefined, 'unknown'),
    'Expected \u2713 AC',
  );
});

test('a miss caught only per group does not accuse the pooled expectation', () => {
  // `sols/mislabeled.cpp` in the outcome-per-group fixture: its pooled
  // INCORRECT is satisfied -- it does fail -- and only the per-group layer
  // catches it, so naming INCORRECT as the broken promise would be wrong.
  assert.strictEqual(
    expectationTooltip('INCORRECT', 'wrong-answer', 'missed', ['small', 'big']),
    'Declared \u2717 INCORRECT, but small, big did not match',
  );
});
