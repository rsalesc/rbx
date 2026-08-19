import * as assert from 'assert';
import { test } from 'node:test';

import { groupExpectation, mismatchCount, solutionExpectation } from './expectation';
import type { GroupReport, SolutionReport } from './report';
import type { GroupRun, SolutionRun } from './store';

function solutionReport(over: Partial<SolutionReport> = {}): SolutionReport {
  return {
    path: 'sols/wa.cpp',
    index: 1,
    expectedOutcome: 'WRONG_ANSWER',
    outcome: 'wrong-answer',
    status: 'OK',
    matchesExpectation: true,
    score: 0,
    maxScore: 0,
    failedGroups: [],
    groups: [],
    ...over,
  };
}

function run(over: Partial<SolutionRun> = {}): SolutionRun {
  return {
    solution: { path: 'sols/wa.cpp', expectedOutcome: 'WRONG_ANSWER', index: 1 },
    groups: [],
    report: solutionReport(),
    ...over,
  };
}

function groupRun(report?: Partial<GroupReport>): GroupRun {
  return {
    name: 'main',
    testcases: [],
    report:
      report === undefined
        ? undefined
        : {
            name: 'main',
            outcome: 'accepted',
            matchesExpectation: true,
            score: 0,
            maxScore: 0,
            ...report,
          },
  };
}

test('a solution that failed as declared reads as met, not as a failure', () => {
  // The whole point of the expectation channel: `sols/wa.cpp` answering wrongly
  // is the package working, and must not look like the main solution breaking.
  assert.deepStrictEqual(solutionExpectation(run()), {
    declared: 'WRONG_ANSWER',
    outcome: 'wrong-answer',
    status: 'met',
    failedGroups: [],
  });
});

test('a solution that missed its expectation reads as missed', () => {
  const missed = run({
    report: solutionReport({ outcome: 'accepted', matchesExpectation: false }),
  });
  assert.strictEqual(solutionExpectation(missed)?.status, 'missed');
});

test('a solution still running knows what it promised but not whether it kept it', () => {
  // The declaration comes from the skeleton, so a row can say `expects AC`
  // before rbx has published any report for it.
  assert.deepStrictEqual(solutionExpectation(run({ report: undefined })), {
    declared: 'WRONG_ANSWER',
    status: 'unknown',
    failedGroups: [],
  });
});

test('unknown is not met: an unjudged solution claims nothing', () => {
  assert.notStrictEqual(solutionExpectation(run({ report: undefined }))?.status, 'met');
});

test('a solution with no declaration at all has no expectation', () => {
  const undeclared = run({
    solution: { path: 'sols/x.cpp', index: 2 },
    report: undefined,
  });
  assert.strictEqual(solutionExpectation(undeclared), undefined);
});

test('a group is only decorated when it declared something of its own', () => {
  // `GroupReport.expectedOutcome` is set exactly when `outcomePerGroup` covers
  // the group, so its absence -- not a default -- is what suppresses the badge.
  assert.strictEqual(groupExpectation(groupRun()), undefined);
  assert.strictEqual(groupExpectation(groupRun({})), undefined);
  assert.deepStrictEqual(groupExpectation(groupRun({ expectedOutcome: 'ACCEPTED' })), {
    declared: 'ACCEPTED',
    outcome: 'accepted',
    status: 'met',
    failedGroups: [],
  });
});

test('the badge count reports misses, not failures', () => {
  const runs = [
    run(),
    run({ report: solutionReport({ matchesExpectation: false }) }),
    run({ report: undefined }),
  ];
  assert.strictEqual(mismatchCount(runs), 1);
});

test('a solution carries the groups rbx blamed, so the hover can name them', () => {
  const perGroup = run({
    report: solutionReport({
      expectedOutcome: 'INCORRECT',
      matchesExpectation: false,
      failedGroups: ['small', 'big'],
    }),
  });
  assert.deepStrictEqual(solutionExpectation(perGroup)?.failedGroups, ['small', 'big']);
});
