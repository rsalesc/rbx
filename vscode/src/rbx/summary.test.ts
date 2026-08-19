import * as assert from 'assert';
import { test } from 'node:test';

import type { GroupReport, SolutionReport } from './report';
import {
  formatCounts,
  formatMemory,
  formatScore,
  formatTime,
  groupDescription,
  isComplete,
  progressOf,
  solutionDescription,
} from './summary';

// Only formatting and progress are tested here. Deciding the verdict, the score
// and whether a solution met its expectation is rbx's job now, covered by
// tests/rbx/box/run_report_test.py -- asserting it again in TypeScript is what
// let the two implementations drift in the first place.

function tc(outcome?: string) {
  return outcome === undefined ? {} : { evaluation: { outcome } };
}

function group(over: Partial<GroupReport> = {}): GroupReport {
  return {
    name: 'main',
    outcome: 'accepted',
    matchesExpectation: true,
    score: 0,
    maxScore: 0,
    ...over,
  };
}

function solution(over: Partial<SolutionReport> = {}): SolutionReport {
  return {
    path: 'sols/main.cpp',
    index: 0,
    expectedOutcome: 'ACCEPTED',
    outcome: 'accepted',
    status: 'OK',
    matchesExpectation: true,
    score: 0,
    maxScore: 0,
    failedGroups: [],
    groups: [],
    ...over,
  };
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

test('a completed group carries verdict, time and memory', () => {
  const report = group({ maxTime: 0.12, maxMemory: 32 * 1024 * 1024 });
  assert.strictEqual(
    groupDescription(report, { done: 2, total: 2 }),
    'AC · 120 ms · 32 MiB',
  );
});

test('a scored group shows its points', () => {
  const report = group({ score: 70, maxScore: 70, maxTime: 0.12 });
  assert.strictEqual(
    groupDescription(report, { done: 1, total: 1 }),
    'AC · [70/70 pts] · 120 ms',
  );
});

test('a group that missed says what it got, not what it wanted', () => {
  const report = group({
    outcome: 'accepted',
    expectedOutcome: 'TIME_LIMIT_EXCEEDED',
    matchesExpectation: false,
    maxTime: 0.013,
  });
  assert.strictEqual(
    groupDescription(report, { done: 1, total: 1 }),
    // The declared TLE is the row's icon; repeating it here would cost the
    // width the timings need.
    'got AC · 13 ms',
  );
});

test('a solution matching its expectation shows the plain verdict', () => {
  const report = solution({
    score: 100,
    maxScore: 100,
    maxTime: 0.008,
    maxMemory: 10485760,
  });
  assert.strictEqual(
    solutionDescription(report, { done: 4, total: 4 }),
    'AC · [100/100 pts] · 8 ms · 10 MiB',
  );
});

test('a solution contradicting its pooled expectation says what it got', () => {
  const report = solution({
    outcome: 'wrong-answer',
    status: 'UNEXPECTED_VERDICTS',
    matchesExpectation: false,
    maxTime: 0.34,
  });
  assert.strictEqual(
    solutionDescription(report, { done: 4, total: 4 }),
    'got WA · 340 ms',
  );
});

test('a solution caught only per group names the groups, not the expectation', () => {
  // Its pooled INCORRECT *is* satisfied -- it does fail somewhere -- so saying
  // "expected INCORRECT, got WA" would name an expectation that was met. The
  // groups are the finding; the pooled declaration is not.
  const report = solution({
    expectedOutcome: 'INCORRECT',
    outcome: 'wrong-answer',
    status: 'UNEXPECTED_VERDICTS',
    matchesExpectation: false,
    failedGroups: ['small', 'big'],
    maxTime: 0.013,
  });
  assert.strictEqual(
    solutionDescription(report, { done: 2, total: 2 }),
    'failed small, big · 13 ms',
  );
});

test('a binary-scored solution shows no points at all', () => {
  const report = solution({ maxTime: 0.008 });
  assert.strictEqual(solutionDescription(report, { done: 1, total: 1 }), 'AC · 8 ms');
});

test('a solution with no report yet shows only how far it has got', () => {
  // rbx publishes the report when the solution finishes, so mid-run there is
  // nothing to aggregate from -- and computing a "worst so far" here is exactly
  // the duplication the report exists to remove.
  assert.strictEqual(solutionDescription(undefined, { done: 12, total: 40 }), '12/40');
  assert.strictEqual(groupDescription(undefined, { done: 3, total: 8 }), '3/8');
});

test('a solution with no testcases at all reads as pending', () => {
  assert.strictEqual(solutionDescription(undefined, { done: 0, total: 0 }), 'pending');
});

test('a report that arrives before every eval is on disk still shows progress', () => {
  // The report is written per solution, but the watcher may see it before the
  // last `.eval` symlink lands. Showing both is more honest than either alone.
  const report = solution({ maxTime: 0.008 });
  assert.strictEqual(
    solutionDescription(report, { done: 3, total: 4 }),
    '3/4 · AC · 8 ms',
  );
});

test('formatCounts groups testcases by outcome, most frequent first', () => {
  assert.strictEqual(
    formatCounts([tc('wrong-answer'), tc('accepted'), tc('accepted')]),
    '2 AC, 1 WA',
  );
  assert.strictEqual(formatCounts([tc(), tc()]), '');
});

test('a running solution says what it promised before it has a verdict', () => {
  // The declaration is in the skeleton, so this is the one thing a row can say
  // while rbx has published no report for it.
  assert.strictEqual(
    solutionDescription(undefined, { done: 3, total: 10 }, 'ACCEPTED'),
    'expects AC \u00b7 3/10',
  );
  // `ANY` promises nothing, so it adds nothing.
  assert.strictEqual(
    solutionDescription(undefined, { done: 3, total: 10 }, 'ANY'),
    '3/10',
  );
  assert.strictEqual(solutionDescription(undefined, { done: 0, total: 0 }), 'pending');
});
