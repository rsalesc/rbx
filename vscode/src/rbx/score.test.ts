import * as assert from 'assert';
import { test } from 'node:test';

import { scoreRange, scoreText } from './score';

// Each expected string is what `partial.format_score` prints for the same
// double, so the editor and `rbx run` agree to the cent.
test('a score prints to the cent, without trailing zeros, as rbx prints it', () => {
  const cases: [number, string][] = [
    [0, '0'],
    [100, '100'],
    [50, '50'],
    [82.5, '82.5'],
    [74.05624, '74.06'],
    // The double nearest 0.045 sits below it, and 12.345's above it: both
    // round the binary value, not the decimal one.
    [0.00045 * 100, '0.04'],
    [12.345, '12.35'],
    [2.675, '2.67'],
    [1.005, '1'],
    [33.335, '33.34'],
  ];
  for (const [score, expected] of cases) {
    assert.strictEqual(scoreText(score), expected, `scoreText(${score})`);
  }
});

test('an exact tie between two cents goes to the even one, as Python rounds', () => {
  assert.strictEqual(scoreText(0.125), '0.12');
  assert.strictEqual(scoreText(0.375), '0.38');
  assert.strictEqual(scoreText(0.625), '0.62');
  assert.strictEqual(scoreText(0.875), '0.88');
  assert.strictEqual(scoreText(10.125), '10.12');
});

test('a score range prints each bound to the cent', () => {
  assert.strictEqual(scoreRange([100, 100]), '100');
  assert.strictEqual(scoreRange([50, 80]), '50..80');
  assert.strictEqual(scoreRange([50, 1e9]), '50..');
  assert.strictEqual(scoreRange([33.333, 66.667]), '33.33..66.67');
});

test('a range whose bounds print the same is one score', () => {
  assert.strictEqual(scoreRange([33.333, 33.334]), '33.33');
});
