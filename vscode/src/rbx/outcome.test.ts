import * as assert from 'assert';
import { test } from 'node:test';

import { outcomeIcon, shortName } from './outcome';

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
