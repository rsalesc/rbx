import * as assert from 'assert';
import { test } from 'node:test';

import { parseEvaluation, parseSkeleton } from './model';

// The extension and the installed `rbx-cp` drift independently, so every one of
// these is about a skeleton this extension is the wrong age for. None of them
// may throw: a reader that fails on an unknown shape is a view that empties
// itself the day rbx grows a field.

const MINIMAL = { solutions: [], entries: [], groups: [] };

test('a skeleton written before compilation findings existed reads as clean', () => {
  const skeleton = parseSkeleton(MINIMAL);
  assert.deepStrictEqual(skeleton?.compilation, []);
});

test('a compilation record is read whole', () => {
  const skeleton = parseSkeleton({
    ...MINIMAL,
    compilation: [
      {
        path: 'sols/main.cpp',
        outcome: 'ACCEPTED',
        status: 'WARNINGS',
        log: 'compilation/0.log',
        warnings: [{ file: 'sols/main.cpp', line: 41, flag: '-Wsign-compare', msg: 'comparison' }],
      },
    ],
  });
  assert.deepStrictEqual(skeleton?.compilation, [
    {
      path: 'sols/main.cpp',
      expectedOutcome: 'ACCEPTED',
      status: 'WARNINGS',
      log: 'compilation/0.log',
      // `file` is kept, not dropped in favour of `path`: a diagnostic has to
      // land on the file the compiler named, which is not always the file that
      // was being compiled.
      warnings: [
        { file: 'sols/main.cpp', line: 41, flag: '-Wsign-compare', msg: 'comparison' },
      ],
      reason: undefined,
    },
  ]);
});

test('a failure carries its reason and needs no warnings', () => {
  const skeleton = parseSkeleton({
    ...MINIMAL,
    compilation: [
      {
        path: 'sols/broken.cpp',
        outcome: 'WRONG_ANSWER',
        status: 'FAILED',
        log: 'compilation/0.log',
        reason: "'g++' was not found",
      },
    ],
  });
  assert.strictEqual(skeleton?.compilation[0].status, 'FAILED');
  assert.strictEqual(skeleton?.compilation[0].reason, "'g++' was not found");
  assert.deepStrictEqual(skeleton?.compilation[0].warnings, []);
});

test('a record missing what a row cannot be drawn without is dropped', () => {
  const skeleton = parseSkeleton({
    ...MINIMAL,
    compilation: [
      { path: 'sols/a.cpp', status: 'WARNINGS' }, // no log
      { status: 'FAILED', log: 'compilation/0.log' }, // no path
      { path: 'sols/c.cpp', status: 'SOMETHING_NEW', log: 'compilation/1.log' },
      { path: 'sols/d.cpp', status: 'FAILED', log: 'compilation/2.log' },
    ],
  });
  assert.deepStrictEqual(
    skeleton?.compilation.map((entry) => entry.path),
    ['sols/d.cpp'],
  );
});

test('a malformed warning is dropped without taking its record with it', () => {
  const skeleton = parseSkeleton({
    ...MINIMAL,
    compilation: [
      {
        path: 'sols/a.cpp',
        status: 'WARNINGS',
        log: 'compilation/0.log',
        warnings: [
          { file: 'sols/a.cpp', line: 'not a number', msg: 'x' },
          // No `file`, so there is nowhere to put a diagnostic: dropped too.
          { line: 5, msg: 'homeless' },
          { file: 'sols/a.cpp', line: 7, msg: 'kept' },
          'garbage',
        ],
      },
    ],
  });
  assert.deepStrictEqual(skeleton?.compilation[0].warnings, [
    { file: 'sols/a.cpp', line: 7, flag: undefined, msg: 'kept' },
  ]);
});

test('a compilation field of the wrong shape reads as absent', () => {
  assert.deepStrictEqual(parseSkeleton({ ...MINIMAL, compilation: 'nope' })?.compilation, []);
});

test('a testcase entry carries where it came from', () => {
  const skeleton = parseSkeleton({
    ...MINIMAL,
    entries: [
      {
        group_entry: { group: 'main', index: 0 },
        metadata: {
          copied_to: { inputPath: '/w/a/.rbx/tests/main/1-gen-000.in' },
          generator_call: { name: 'gen_random', args: '5 3 --seed=7' },
          // A `GeneratorScriptEntry` is a real path and line, which is what
          // makes this the one piece of provenance the card can open.
          generator_script: { path: 'gens/script.txt', line: 12 },
        },
      },
    ],
  });
  const entry = skeleton?.entries[0];
  assert.strictEqual(entry?.generatorName, 'gen_random');
  assert.strictEqual(entry?.generatorArgs, '5 3 --seed=7');
  assert.strictEqual(entry?.generatorScript, 'gens/script.txt');
  assert.strictEqual(entry?.generatorScriptLine, 12);
});

test('a testcase entry written by an rbx that records no script reads clean', () => {
  // The tolerance every one of these tests is about: a copied testcase has no
  // generator at all, and must not throw on the way in.
  const skeleton = parseSkeleton({
    ...MINIMAL,
    entries: [
      {
        group_entry: { group: 'samples', index: 0 },
        metadata: {
          copied_to: { inputPath: '/w/a/.rbx/tests/samples/000.in' },
          copied_from: { inputPath: 'tests/manual/01.in' },
        },
      },
    ],
  });
  const entry = skeleton?.entries[0];
  assert.strictEqual(entry?.copiedFrom, 'tests/manual/01.in');
  assert.strictEqual(entry?.generatorScript, undefined);
  assert.strictEqual(entry?.generatorScriptLine, undefined);
});


test('an evaluation carries the sanitizer flag off its own .eval', () => {
  // The one warning a testcase row can raise on its own account: no
  // expectation has to be matched to know a sanitizer fired here.
  const evaluation = parseEvaluation({
    result: { outcome: 'accepted', sanitizer_warnings: true },
    log: { time: 0.01 },
  });
  assert.strictEqual(evaluation?.outcome, 'accepted');
  assert.strictEqual(evaluation?.sanitizerWarnings, true);
});

test('an evaluation that tripped nothing leaves the flag alone', () => {
  const evaluation = parseEvaluation({ result: { outcome: 'accepted' }, log: {} });
  assert.strictEqual(evaluation?.sanitizerWarnings, undefined);
});
