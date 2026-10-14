import * as assert from 'assert';
import { test } from 'node:test';
import { parse as parseYaml } from 'yaml';

import {
  aggregateTime,
  expandedTimeLimit,
  limitLines,
  memoryAgainstLimit,
  solutionTimeLimits,
  testcaseTime,
} from './limitsView';
import { parseEvaluation, parseSkeleton } from './model';

// Verbatim from a real `rbx run` of vscode/demo/sum-of-pairs: `sols/tle.cpp`
// on `main/1-gen-000`, a hard TLE -- killed at 2x a 1000 ms limit under -v4.
const HARD_TLE_EVAL = `
result:
  outcome: time-limit-exceeded
  sanitizer_warnings: false
testcase:
  index: 0
log:
  exitcode: -24
  exitstatus: timeout
  time: 2.01198
  wall_time: 2.0626422078348696
  memory: 10829824
  warnings: false
  metadata:
    language: cpp
    is_sanitized: false
    limits:
      time: 1000
      configuredTime: 1000
      memory: 256
      isDoubleTL: true
    timeLimit: 2000
    memoryLimit: 256
    retryIndex: 1
  exitindex: 0
`;

// The same run's `sols/slow-ok.cpp` on the same test: accepted, 181 ms.
const ACCEPTED_EVAL = `
result:
  outcome: accepted
  message: ok "7"
  sanitizer_warnings: false
  checker_timing:
    time: 0.007826
    wall_time: 0.006448167143389583
log:
  exitcode: 0
  exitstatus: ok
  time: 0.181881
  wall_time: 0.18389054108411074
  memory: 10960896
  metadata:
    language: cpp
    limits:
      time: 1000
      configuredTime: 1000
      memory: 256
      output: 4096
      isDoubleTL: true
    timeLimit: 2000
`;

const CPP = { time: 1000, configuredTime: 1000, memory: 256, isDoubleTL: true };

test('the expanded limit doubles only under double TL', () => {
  assert.strictEqual(expandedTimeLimit(CPP), 2000);
  assert.strictEqual(expandedTimeLimit({ ...CPP, isDoubleTL: false }), 1000);
  assert.strictEqual(expandedTimeLimit({ isDoubleTL: true }), undefined);
});

test("a solution's limits come off its skeleton entry, the report standing in", () => {
  assert.deepStrictEqual(solutionTimeLimits(CPP, undefined), { time: 1000, expanded: 2000 });
  // An old skeleton: the report says the 1x limit, and nothing about doubling,
  // so nothing gets capped -- the direction that hides no measurement.
  assert.deepStrictEqual(
    solutionTimeLimits(undefined, { timeLimit: 1.5 } as never),
    { time: 1500 },
  );
  // A sanitized run enforces no limit, and there is nothing to read against.
  assert.strictEqual(solutionTimeLimits({ isDoubleTL: false }, undefined), undefined);
});

test('a testcase reads its time against the 1x limit', () => {
  const evaluation = parseEvaluation(parseYaml(ACCEPTED_EVAL));
  assert.deepStrictEqual(testcaseTime(evaluation, { time: 1000, expanded: 2000 }, 0.8), {
    text: '181 / 1000 ms',
    hue: 'dim',
    title: '181 ms of a 1000 ms time limit (0.18×TL)',
  });
});

test("a hard TLE is capped at the limit it was killed at, as rbx prints it", () => {
  const evaluation = parseEvaluation(parseYaml(HARD_TLE_EVAL));
  assert.strictEqual(
    testcaseTime(evaluation, { time: 1000, expanded: 2000 }, 0.8)?.text,
    '>2000 ms',
  );
  // The testcase's own recorded limits win over the solution's, which is the
  // order `get_capped_evals_formatted_time` reads them in.
  assert.strictEqual(testcaseTime(evaluation, { time: 500, expanded: 1000 }, 0.8)?.text, '>2000 ms');
});

test('a soft TLE keeps its measured time: it finished, so the time is real', () => {
  const soft = { outcome: 'time-limit-exceeded', time: 1.4, limits: CPP };
  assert.strictEqual(testcaseTime(soft, { time: 1000, expanded: 2000 }, 0.8)?.text, '1400 / 1000 ms');
});

test('tight is drawn at the published ratio, and only inside the limit', () => {
  const at = (seconds: number, outcome = 'accepted') =>
    testcaseTime({ outcome, time: seconds }, { time: 1000, expanded: 2000 }, 0.8)?.hue;
  assert.strictEqual(at(0.799), 'dim');
  assert.strictEqual(at(0.8), 'yellow');
  assert.strictEqual(at(0.999), 'yellow');
  // Past the limit the chip already says TLE.
  assert.strictEqual(at(1.2, 'time-limit-exceeded'), 'dim');
});

test('with no published ratio nothing is tight: no second copy of the threshold', () => {
  const measured = testcaseTime({ outcome: 'accepted', time: 0.95 }, { time: 1000 }, undefined);
  assert.strictEqual(measured?.hue, 'dim');
});

test('with no limit a time reads as it always did', () => {
  assert.deepStrictEqual(testcaseTime({ time: 0.412 }, undefined, 0.8), {
    text: '412 ms',
    hue: 'dim',
  });
  assert.strictEqual(testcaseTime({ outcome: 'accepted' }, { time: 1000 }, 0.8), undefined);
});

test('an aggregate reads as a share of the limit', () => {
  assert.deepStrictEqual(aggregateTime(0.93, 'accepted', { time: 1000, expanded: 2000 }, 0.8), {
    text: '0.93×TL',
    hue: 'yellow',
    title: 'Max time 930 ms of a 1000 ms time limit',
  });
  assert.strictEqual(
    aggregateTime(2.01198, 'time-limit-exceeded', { time: 1000, expanded: 2000 }, 0.8)?.text,
    '>2.00×TL',
  );
  assert.strictEqual(aggregateTime(0.009, 'accepted', undefined, 0.8)?.text, '9 ms');
});

test('memory keeps its text and carries the limit in its hover', () => {
  assert.deepStrictEqual(memoryAgainstLimit(10960896, 256, 0.8), {
    text: '10 MiB',
    hue: 'dim',
    title: '10 MiB of a 256 MiB memory limit (0.04×ML)',
  });
  assert.strictEqual(memoryAgainstLimit(220 * 1024 * 1024, 256, 0.8)?.hue, 'yellow');
  assert.deepStrictEqual(memoryAgainstLimit(1000, undefined, 0.8), { text: '1000 B', hue: 'dim' });
});

test("the header's limit lines come off the skeleton's table", () => {
  // The `limits` block of the same run's skeleton.yml, plus a profiled
  // language and one with no limits at all, as a sanitized run writes it.
  const skeleton = parseSkeleton({
    solutions: [],
    entries: [],
    groups: [],
    limits: {
      cpp: { time: 1000, configuredTime: 1000, memory: 256, output: 4096, isDoubleTL: true },
      py: { time: 3000, memory: 512, isDoubleTL: true, profile: 'local' },
      java: { isDoubleTL: false },
    },
  });
  assert.deepStrictEqual(limitLines(skeleton?.limits ?? []), [
    { language: 'cpp', time: '1000 ms', memory: '256 MiB', profile: undefined, doubleTl: true },
    { language: 'py', time: '3000 ms', memory: '512 MiB', profile: 'local', doubleTl: true },
    {
      language: 'java',
      time: 'no time limit',
      memory: 'no memory limit',
      profile: undefined,
      doubleTl: false,
    },
  ]);
});
