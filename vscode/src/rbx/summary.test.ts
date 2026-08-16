import * as assert from 'assert';
import { test } from 'node:test';

import {
  SummarizableGroup,
  failingGroups,
  formatCounts,
  formatMemory,
  formatScore,
  formatTime,
  groupDescription,
  solutionDescription,
  summarizeGroup,
  summarizeSolution,
} from './summary';

/** A testcase with an outcome and, optionally, time (seconds) and memory (bytes). */
function tc(outcome?: string, time?: number, memory?: number) {
  return outcome === undefined ? {} : { evaluation: { outcome, time, memory } };
}

function group(name: string, score: number, testcases: ReturnType<typeof tc>[]): SummarizableGroup {
  return { name, score, testcases };
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

test('a group summary takes the worst outcome and the max time and memory', () => {
  const summary = summarizeGroup(
    group('main', 0, [
      tc('accepted', 0.01, 1024 * 1024),
      tc('wrong-answer', 0.34, 8 * 1024 * 1024),
      tc('accepted', 0.12, 2 * 1024 * 1024),
    ]),
  );
  assert.strictEqual(summary.outcome, 'wrong-answer');
  assert.strictEqual(summary.time, 0.34);
  assert.strictEqual(summary.memory, 8 * 1024 * 1024);
  assert.strictEqual(summary.done, 3);
  assert.strictEqual(summary.total, 3);
});

test('an unevaluated testcase counts towards total but not done', () => {
  const summary = summarizeGroup(group('main', 0, [tc('accepted', 0.01), tc(), tc()]));
  assert.strictEqual(summary.done, 1);
  assert.strictEqual(summary.total, 3);
  assert.strictEqual(summary.outcome, 'accepted');
});

test('a group earns its full score only when every testcase is accepted', () => {
  assert.strictEqual(summarizeGroup(group('main', 40, [tc('accepted'), tc('accepted')])).score, 40);
  assert.strictEqual(summarizeGroup(group('main', 40, [tc('accepted'), tc('wrong-answer')])).score, 0);
  // Still running: nothing earned yet, even though what has run so far passed.
  assert.strictEqual(summarizeGroup(group('main', 40, [tc('accepted'), tc()])).score, 0);
  // A skipped testcase means the group was cut short; rbx does not award it.
  assert.strictEqual(summarizeGroup(group('main', 40, [tc('accepted'), tc('skipped')])).score, 0);
});

test('a solution sums group scores and aggregates across all groups', () => {
  const summary = summarizeSolution({
    groups: [
      group('samples', 0, [tc('accepted', 0.01, 1024)]),
      group('easy', 30, [tc('accepted', 0.05, 4096)]),
      group('hard', 70, [tc('accepted', 0.4, 1024 * 1024), tc('time-limit-exceeded', 2.0)]),
    ],
  });
  assert.strictEqual(summary.outcome, 'time-limit-exceeded');
  assert.strictEqual(summary.score, 30);
  assert.strictEqual(summary.maxScore, 100);
  assert.strictEqual(summary.time, 2.0);
  assert.strictEqual(summary.total, 4);
});

test('failingGroups names only the groups whose worst outcome is not accepted', () => {
  const names = failingGroups({
    groups: [
      group('samples', 0, [tc('accepted')]),
      group('easy', 0, [tc('wrong-answer')]),
      group('hard', 0, [tc()]),
    ],
  }).map((g) => g.name);
  assert.deepStrictEqual(names, ['easy']);
});

test('formatCounts orders outcomes best to worst', () => {
  const summary = summarizeGroup(
    group('main', 0, [tc('wrong-answer'), tc('accepted'), tc('accepted')]),
  );
  assert.strictEqual(formatCounts(summary), '2 AC, 1 WA');
});

test('a completed group description carries verdict, time and memory', () => {
  const summary = summarizeGroup(
    group('main', 0, [tc('accepted', 0.12, 32 * 1024 * 1024), tc('accepted', 0.01, 1024)]),
  );
  assert.strictEqual(groupDescription(summary), 'AC · 120 ms · 32 MiB');
});

test('an in-progress group description leads with the progress counter', () => {
  const summary = summarizeGroup(
    group('main', 0, [tc('accepted', 0.09), tc(), tc(), tc(), tc(), tc(), tc(), tc()]),
  );
  assert.strictEqual(groupDescription(summary), '1/8 · AC · 90 ms');
});

test('a group with points shows them once complete, and never mid-run', () => {
  const complete = summarizeGroup(group('hard', 70, [tc('accepted', 0.12)]));
  assert.strictEqual(groupDescription(complete), 'AC · [70/70 pts] · 120 ms');

  const running = summarizeGroup(group('hard', 70, [tc('accepted', 0.12), tc()]));
  assert.strictEqual(groupDescription(running), '1/2 · AC · 120 ms');
});

test('a solution matching its expectation shows the plain verdict', () => {
  const summary = summarizeSolution({
    groups: [group('main', 0, [tc('accepted', 0.12, 32 * 1024 * 1024)])],
  });
  assert.strictEqual(solutionDescription(summary, 'ACCEPTED'), 'AC · 120 ms · 32 MiB');
});

test('a solution contradicting its expectation leads with the mismatch', () => {
  const summary = summarizeSolution({
    groups: [group('main', 0, [tc('wrong-answer', 0.34, 32 * 1024 * 1024)])],
  });
  assert.strictEqual(
    solutionDescription(summary, 'ACCEPTED'),
    'expected AC, got WA · 340 ms · 32 MiB',
  );
});

test('a solution whose expectation covers the outcome is not a mismatch', () => {
  const summary = summarizeSolution({ groups: [group('main', 0, [tc('time-limit-exceeded', 2)])] });
  assert.strictEqual(solutionDescription(summary, 'ACCEPTED_OR_TLE'), 'TLE · 2000 ms');
});

test('an in-progress solution never claims a mismatch it cannot yet know', () => {
  // Only the samples have run and they failed, but the declared WRONG_ANSWER
  // expectation may still be met -- do not shout "expected WA, got WA" either.
  const summary = summarizeSolution({
    groups: [group('main', 0, [tc('wrong-answer', 0.34), tc(), tc()])],
  });
  assert.strictEqual(solutionDescription(summary, 'ACCEPTED'), '1/3 · WA · 340 ms');
});

test('a solution with nothing evaluated yet reads as pending', () => {
  const summary = summarizeSolution({ groups: [group('main', 0, [tc(), tc()])] });
  assert.strictEqual(solutionDescription(summary, 'ACCEPTED'), '0/2 · pending');
});
