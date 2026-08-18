import * as assert from 'assert';
import { test } from 'node:test';
import { parse as parseYaml } from 'yaml';

import { parseReport } from './report';

/** Verbatim from a real `rbx run` of tests/e2e/testdata/outcome-per-group. */
const REAL_REPORT = `
version: 1
solutions:
- path: sols/main.cpp
  index: 0
  expectedOutcome: ACCEPTED
  outcome: accepted
  status: OK
  matchesExpectation: true
  score: 100
  maxScore: 100
  maxTime: 0.009687
  maxMemory: 11042816
  failedGroups: []
  groups:
  - name: small
    outcome: accepted
    matchesExpectation: true
    score: 40
    maxScore: 40
    maxTime: 0.009687
    maxMemory: 10878976
  - name: big
    outcome: accepted
    matchesExpectation: true
    score: 60
    maxScore: 60
    maxTime: 0.009497
    maxMemory: 11042816
- path: sols/mislabeled.cpp
  index: 2
  expectedOutcome: INCORRECT
  outcome: wrong-answer
  status: UNEXPECTED_VERDICTS
  matchesExpectation: false
  score: 40
  maxScore: 100
  maxTime: 0.013336
  maxMemory: 10878976
  failedGroups:
  - small
  - big
  groups:
  - name: small
    outcome: accepted
    expectedOutcome: TIME_LIMIT_EXCEEDED
    matchesExpectation: false
    score: 40
    maxScore: 40
`;

test('a real report parses into its aggregates', () => {
  const report = parseReport(parseYaml(REAL_REPORT));
  assert.ok(report !== undefined);
  assert.strictEqual(report.solutions.length, 2);

  const main = report.solutions[0];
  assert.strictEqual(main.outcome, 'accepted');
  assert.strictEqual(main.score, 100);
  assert.strictEqual(main.maxScore, 100);
  assert.strictEqual(main.matchesExpectation, true);
  assert.strictEqual(main.groups[1].name, 'big');
  assert.strictEqual(main.groups[1].score, 60);
});

test('a per-group expectation failure survives the wire', () => {
  // The extension could not show this at all before: it only ever read the
  // pooled `solution.outcome`, which this solution satisfies.
  const report = parseReport(parseYaml(REAL_REPORT));
  const mislabeled = report!.solutions[1];
  assert.strictEqual(mislabeled.index, 2);
  assert.strictEqual(mislabeled.matchesExpectation, false);
  assert.deepStrictEqual([...mislabeled.failedGroups], ['small', 'big']);
  assert.strictEqual(mislabeled.groups[0].expectedOutcome, 'TIME_LIMIT_EXCEEDED');
  assert.strictEqual(mislabeled.groups[0].matchesExpectation, false);
});

test('an absent time or memory stays absent rather than becoming zero', () => {
  const report = parseReport({
    version: 1,
    solutions: [
      { path: 's.cpp', index: 0, status: 'OK', groups: [{ name: 'g' }] },
    ],
  });
  const solution = report!.solutions[0];
  assert.strictEqual(solution.maxTime, undefined);
  assert.strictEqual(solution.maxMemory, undefined);
  assert.strictEqual(solution.groups[0].outcome, undefined);
});

test('a report of an unknown version is ignored rather than guessed at', () => {
  assert.strictEqual(parseReport({ version: 2, solutions: [] }), undefined);
  assert.strictEqual(parseReport({ solutions: [] }), undefined);
});

test('a missing or malformed report reads as no report', () => {
  assert.strictEqual(parseReport(undefined), undefined);
  assert.strictEqual(parseReport('not a report'), undefined);
});

test('a solution missing its identity is dropped, not defaulted', () => {
  const report = parseReport({
    version: 1,
    solutions: [{ index: 0, status: 'OK' }, { path: 'ok.cpp', index: 1, status: 'OK' }],
  });
  assert.deepStrictEqual(report?.solutions.map((s) => s.path), ['ok.cpp']);
});
