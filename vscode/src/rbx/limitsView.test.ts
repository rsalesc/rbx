import * as assert from 'assert';
import { test } from 'node:test';
import { parse as parseYaml } from 'yaml';

import {
  expandedTimeLimit,
  limitLines,
  measuredTime,
  memoryAgainstLimit,
  solutionTimeLimits,
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

const CPP_TL = { time: 1000, expanded: 2000 };

function timeOf(raw: string, limits = CPP_TL) {
  const evaluation = parseEvaluation(parseYaml(raw));
  return measuredTime(evaluation?.time, evaluation?.outcome, evaluation?.limits, limits);
}

test('a time reads as rbx prints it, with the limit only in the hover', () => {
  assert.deepStrictEqual(timeOf(ACCEPTED_EVAL), {
    text: '181 ms',
    hue: 'dim',
    title: '181 ms of a 1000 ms time limit',
  });
});

test('a hard TLE is capped at the limit it was killed at, as rbx prints it', () => {
  assert.strictEqual(timeOf(HARD_TLE_EVAL)?.text, '>2000 ms');
  // The testcase's own recorded limits win over the solution's, which is the
  // order `get_capped_evals_formatted_time` reads them in.
  assert.strictEqual(timeOf(HARD_TLE_EVAL, { time: 500, expanded: 1000 })?.text, '>2000 ms');
});

test('an aggregate is capped the same way, off the solution limits', () => {
  assert.strictEqual(
    measuredTime(2.01198, 'time-limit-exceeded', undefined, CPP_TL)?.text,
    '>2000 ms',
  );
  assert.strictEqual(measuredTime(0.93, 'accepted', undefined, CPP_TL)?.text, '930 ms');
});

test('a soft TLE keeps its measured time: it finished, so the time is real', () => {
  assert.strictEqual(measuredTime(1.4, 'time-limit-exceeded', CPP, CPP_TL)?.text, '1400 ms');
});

test('a time close to its limit is not coloured: there is no threshold to draw', () => {
  assert.strictEqual(measuredTime(0.999, 'accepted', undefined, CPP_TL)?.hue, 'dim');
});

test('with no limit a time reads as it always did', () => {
  assert.deepStrictEqual(measuredTime(0.412, undefined, undefined, undefined), {
    text: '412 ms',
    hue: 'dim',
  });
  assert.strictEqual(measuredTime(undefined, 'accepted', undefined, CPP_TL), undefined);
});

test('memory keeps its text, carries the limit in its hover, and is never hued', () => {
  assert.deepStrictEqual(memoryAgainstLimit(10960896, 256), {
    text: '10 MiB',
    hue: 'dim',
    title: '10 MiB of a 256 MiB memory limit',
  });
  // rbx has no memory-margin warning, so nothing here turns yellow.
  assert.strictEqual(memoryAgainstLimit(250 * 1024 * 1024, 256)?.hue, 'dim');
  assert.deepStrictEqual(memoryAgainstLimit(1000, undefined), { text: '1000 B', hue: 'dim' });
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
