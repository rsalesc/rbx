import * as assert from 'assert';
import { test } from 'node:test';
import { parse as parseYaml } from 'yaml';

import {
  DeclaredAsset,
  normalizeExpectation,
  parseManifest,
  parseProblemName,
} from './manifest';

function assets(yaml: string): DeclaredAsset[] {
  return parseManifest(parseYaml(yaml));
}

function roleOf(list: DeclaredAsset[], path: string): string | undefined {
  return list.find((asset) => asset.path === path)?.role;
}

function expectationOf(list: DeclaredAsset[], path: string): string | undefined {
  return list.find((asset) => asset.path === path)?.expectation;
}

test('solutions carry the outcome the setter declared, as an enum member', () => {
  const list = assets(`
solutions:
  - path: sols/main.cpp
    outcome: accepted
  - path: sols/slow.cpp
    outcome: tle
`);
  assert.strictEqual(expectationOf(list, 'sols/main.cpp'), 'ACCEPTED');
  assert.strictEqual(expectationOf(list, 'sols/slow.cpp'), 'TIME_LIMIT_EXCEEDED');
  assert.strictEqual(roleOf(list, 'sols/main.cpp'), 'solution');
});

/**
 * Every spelling rbx accepts has to resolve here, because the badge is drawn
 * off the resolved member: a spelling this misses reads as a member from a
 * newer rbx and takes the neutral fallback, which silently downgrades a
 * perfectly ordinary `outcome: ac/tle` to a grey cross.
 *
 * `AutoEnum._normalize` lowercases and drops ` -_.:;,` -- but not `/` or `+`,
 * which is why both `ac/tle` and `ac+tle` have to be listed as aliases rather
 * than folded into one.
 */
test('every alias rbx accepts resolves to the same member', () => {
  const cases: Record<string, readonly string[]> = {
    ANY: ['any', 'ANY'],
    ACCEPTED: ['accepted', 'ac', 'correct', 'ACCEPTED', 'Accepted'],
    ACCEPTED_OR_TLE: [
      'accepted-or-tle',
      'accepted or tle',
      'accepted or time limit exceeded',
      'ac or tle',
      'ac/tle',
      'ac+tle',
      'ACCEPTED_OR_TLE',
    ],
    WRONG_ANSWER: ['wa', 'wrong answer', 'wrong-answer', 'WRONG_ANSWER'],
    INCORRECT: ['fail', 'incorrect', 'INCORRECT'],
    RUNTIME_ERROR: ['rte', 're', 'runtime error', 'RUNTIME_ERROR'],
    TIME_LIMIT_EXCEEDED: ['tle', 'tl', 'timeout', 'time limit exceeded'],
    MEMORY_LIMIT_EXCEEDED: ['mle', 'ml', 'memory limit exceeded'],
    OUTPUT_LIMIT_EXCEEDED: ['ole', 'ol', 'output limit exceeded'],
    TLE_OR_RTE: ['tle or rte', 'tle/rte', 'tle+rte', 'tle or re', 'tle+re'],
    JUDGE_FAILED: ['jf', 'judge failed'],
    COMPILATION_ERROR: ['ce', 'compilation error'],
  };
  for (const [member, spellings] of Object.entries(cases)) {
    for (const spelling of spellings) {
      assert.strictEqual(
        normalizeExpectation(spelling),
        member,
        `${spelling} should resolve to ${member}`,
      );
    }
  }
});

test('a spelling from a newer rbx is passed through rather than dropped', () => {
  // The setter declared *something*; rendering it as "nothing declared" would
  // disagree with rbx, which refuses to run the package at all.
  assert.strictEqual(normalizeExpectation('partially-accepted'), 'partially-accepted');
});

test('a solution with no outcome is ANY, which is not the same as undeclared', () => {
  const list = assets('solutions:\n  - path: sols/main.cpp\n');
  assert.strictEqual(expectationOf(list, 'sols/main.cpp'), 'ANY');
});

test('every other role the manifest names is collected', () => {
  const list = assets(`
checker: {path: checker.cpp}
interactor: {path: interactor.cpp}
validator: {path: validator.cpp}
visualizer: {path: viz.cpp}
generators:
  - {name: gen, path: gen.cpp}
statements:
  - {file: statement/problem.rbx.tex}
tutorials:
  - {file: statement/tutorial.rbx.tex}
`);
  assert.strictEqual(roleOf(list, 'checker.cpp'), 'checker');
  assert.strictEqual(roleOf(list, 'interactor.cpp'), 'interactor');
  assert.strictEqual(roleOf(list, 'validator.cpp'), 'validator');
  assert.strictEqual(roleOf(list, 'viz.cpp'), 'visualizer');
  assert.strictEqual(roleOf(list, 'gen.cpp'), 'generator');
  assert.strictEqual(roleOf(list, 'statement/problem.rbx.tex'), 'statement');
  assert.strictEqual(roleOf(list, 'statement/tutorial.rbx.tex'), 'statement');
});

test('a validator declared deep inside a group is still a validator', () => {
  const list = assets(`
testcases:
  - name: main
    validator: {path: validators/main.cpp}
    generatorScript: {path: gen/script.txt}
    subgroups:
      - name: edge
        validator: {path: validators/edge.cpp}
`);
  assert.strictEqual(roleOf(list, 'validators/main.cpp'), 'validator');
  assert.strictEqual(roleOf(list, 'validators/edge.cpp'), 'validator');
  assert.strictEqual(roleOf(list, 'gen/script.txt'), 'generator');
});

test('a file claimed twice takes the more specific role', () => {
  const list = assets(`
validator: {path: dual.cpp}
checker: {path: dual.cpp}
`);
  assert.strictEqual(list.length, 1);
  assert.strictEqual(roleOf(list, 'dual.cpp'), 'checker');
});

test("a solution doubling as a generator keeps its expectation", () => {
  const list = assets(`
solutions:
  - path: both.cpp
    outcome: wa
generators:
  - {name: gen, path: both.cpp}
`);
  assert.strictEqual(roleOf(list, 'both.cpp'), 'solution');
  assert.strictEqual(expectationOf(list, 'both.cpp'), 'WRONG_ANSWER');
});

/**
 * The manifest is edited by hand, so the watcher reads it mid-keystroke all the
 * time. Every shape below is something a half-typed file really produces, and
 * all of them must cost at most a missing badge.
 */
test('a manifest that makes no sense yields no badges rather than an error', () => {
  assert.deepStrictEqual(parseManifest(undefined), []);
  assert.deepStrictEqual(parseManifest('name: problem'), []);
  assert.deepStrictEqual(parseManifest([1, 2, 3]), []);
  assert.deepStrictEqual(assets('solutions: not-a-list\n'), []);
  assert.deepStrictEqual(assets('solutions:\n  - outcome: ac\n'), []);
  assert.deepStrictEqual(assets('checker: checker.cpp\n'), []);
  assert.deepStrictEqual(assets('solutions:\n  - path: ""\n'), []);
});

function perGroupOf(list: DeclaredAsset[], path: string) {
  return list.find((asset) => asset.path === path)?.perGroup;
}

test('a solution carries its per-group overrides, in the order they were declared', () => {
  const list = assets(`
scoring: points
solutions:
  - path: sols/partial.cpp
    outcome: incorrect
    outcomePerGroup:
      '*': accepted
      group3: tle
`);
  assert.strictEqual(expectationOf(list, 'sols/partial.cpp'), 'INCORRECT');
  assert.deepStrictEqual(perGroupOf(list, 'sols/partial.cpp'), [
    { group: '*', expectation: 'ACCEPTED' },
    { group: 'group3', expectation: 'TIME_LIMIT_EXCEEDED' },
  ]);
});

test('a solution declaring no per-group override carries none', () => {
  const list = assets('solutions:\n  - path: sols/main.cpp\n    outcome: ac\n');
  assert.strictEqual(perGroupOf(list, 'sols/main.cpp'), undefined);
});

test('a half-typed outcomePerGroup costs its entries, not the solution', () => {
  assert.strictEqual(
    perGroupOf(assets('solutions:\n  - path: s.cpp\n    outcomePerGroup: tle\n'), 's.cpp'),
    undefined,
  );
  assert.deepStrictEqual(
    perGroupOf(
      assets('solutions:\n  - path: s.cpp\n    outcomePerGroup:\n      main:\n      g2: ac\n'),
      's.cpp',
    ),
    [{ group: 'g2', expectation: 'ACCEPTED' }],
  );
});

test('a group nested past any real depth stops rather than spinning', () => {
  // YAML aliases can describe a cycle; rbx's schema cannot, but a hand-edited
  // file is not the schema, and an extension host that hangs is worse than a
  // badge that is missing.
  const cyclic: Record<string, unknown> = { name: 'main' };
  cyclic.subgroups = [cyclic];
  assert.deepStrictEqual(parseManifest({ testcases: [cyclic] }), []);
});

function scoreOf(list: DeclaredAsset[], path: string) {
  return list.find((asset) => asset.path === path)?.score;
}

test('an exact expected score reads as a range of one', () => {
  const list = assets('solutions:\n  - path: sols/main.cpp\n    score: 100\n');
  assert.deepStrictEqual(scoreOf(list, 'sols/main.cpp'), [100, 100]);
});

test('a declared score range keeps both bounds', () => {
  const list = assets('solutions:\n  - path: s.cpp\n    score: [50, 80]\n');
  assert.deepStrictEqual(scoreOf(list, 's.cpp'), [50, 80]);
});

/**
 * `expected_score_range` fills an omitted bound with 0 and 10^9, and the run
 * report arrives already filled in the same way. Doing it here too is what lets
 * one formatter draw a range whichever side it came from.
 */
test('an open bound is filled the way rbx fills it', () => {
  assert.deepStrictEqual(
    scoreOf(assets('solutions:\n  - path: s.cpp\n    score: [50, null]\n'), 's.cpp'),
    [50, 1e9],
  );
  assert.deepStrictEqual(
    scoreOf(assets('solutions:\n  - path: s.cpp\n    score: [null, 80]\n'), 's.cpp'),
    [0, 80],
  );
});

test('reads the name a package declares', () => {
  assert.strictEqual(parseProblemName(parseYaml('name: sum-of-pairs\n')), 'sum-of-pairs');
});

test('a package that declares no usable name has none', () => {
  // Each of these is a manifest mid-edit rather than one whose name is
  // genuinely blank, and the selector must fall back to the bare letter.
  for (const yaml of ['timeLimit: 1000\n', 'name:\n', "name: ''\n", 'name: [a, b]\n']) {
    assert.strictEqual(parseProblemName(parseYaml(yaml)), undefined);
  }
  for (const raw of [undefined, null, 'a string', 42, []]) {
    assert.strictEqual(parseProblemName(raw), undefined);
  }
});

test('a score that is not a number or a pair is read as none at all', () => {
  assert.strictEqual(scoreOf(assets('solutions:\n  - path: s.cpp\n'), 's.cpp'), undefined);
  assert.strictEqual(
    scoreOf(assets('solutions:\n  - path: s.cpp\n    score: full\n'), 's.cpp'),
    undefined,
  );
  assert.strictEqual(
    scoreOf(assets('solutions:\n  - path: s.cpp\n    score: [1, 2, 3]\n'), 's.cpp'),
    undefined,
  );
});
