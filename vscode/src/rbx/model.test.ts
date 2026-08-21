import * as assert from 'assert';
import { test } from 'node:test';

import { parseSkeleton } from './model';

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
