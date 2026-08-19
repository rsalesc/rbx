import * as assert from 'assert';
import { test } from 'node:test';

import {
  formatCounts,
  formatMemory,
  formatScore,
  formatTime,
  isComplete,
  progressOf,
} from './summary';

// Only formatting and progress are tested here. Deciding the verdict, the score
// and whether a solution met its expectation is rbx's job now, covered by
// tests/rbx/box/run_report_test.py -- asserting it again in TypeScript is what
// let the two implementations drift in the first place.

function tc(outcome?: string) {
  return outcome === undefined ? {} : { evaluation: { outcome } };
}


test('formatTime truncates to whole milliseconds, as rbx does', () => {
  assert.strictEqual(formatTime(0.1209), '120 ms');
  assert.strictEqual(formatTime(0), '0 ms');
  assert.strictEqual(formatTime(undefined), undefined);
});

test('formatMemory walks the B / KiB / MiB ladder', () => {
  assert.strictEqual(formatMemory(512), '512 B');
  assert.strictEqual(formatMemory(2048), '2 KiB');
  assert.strictEqual(formatMemory(32 * 1024 * 1024), '32 MiB');
  assert.strictEqual(formatMemory(undefined), undefined);
});

test('formatScore renders rbx literal brackets', () => {
  assert.strictEqual(formatScore(70, 100), '[70/100 pts]');
});

test('progress counts the evaluations on disk, not the verdicts in them', () => {
  const progress = progressOf([tc('accepted'), tc('wrong-answer'), tc(), tc()]);
  assert.deepStrictEqual(progress, { done: 2, total: 4 });
  assert.strictEqual(isComplete(progress), false);
  assert.strictEqual(isComplete(progressOf([tc('accepted')])), true);
});

test('formatCounts groups testcases by outcome, most frequent first', () => {
  assert.strictEqual(
    formatCounts([tc('wrong-answer'), tc('accepted'), tc('accepted')]),
    '2 AC, 1 WA',
  );
  assert.strictEqual(formatCounts([tc(), tc()]), '');
});
