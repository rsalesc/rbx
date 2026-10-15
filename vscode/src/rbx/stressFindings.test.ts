import * as assert from 'assert';
import * as path from 'path';
import { test } from 'node:test';

import { packageLayout } from './layout';
import { StressFinding, StressManifest } from './stress';
import {
  compareCandidates,
  everythingSelection,
  findingFiles,
  inputSelection,
  outputSelection,
  sessionOf,
} from './stressFindings';

test('a row acts on its own session only', () => {
  const manifest: StressManifest = {
    state: 'done',
    spec: { slowest: false, doubleTL: false },
    startedAt: 'T1',
    elapsed: 0,
    executed: 0,
    skipped: 0,
    solutions: [],
    findings: [],
  };
  assert.strictEqual(sessionOf(manifest, 'T1'), manifest);
  assert.strictEqual(sessionOf(manifest, 'T0'), undefined);
  assert.strictEqual(sessionOf(undefined, 'T1'), undefined);
  // Nothing to tell sessions apart by: taken at its word.
  assert.strictEqual(sessionOf(manifest, undefined), manifest);
  assert.strictEqual(sessionOf({ ...manifest, startedAt: undefined }, 'T1')?.startedAt, undefined);
});

const PKG = packageLayout('/p');
const DIR = path.join('/p', '.rbx', 'runs', '.stress', 'findings', '2');
const SOLUTIONS = ['sols/main.cpp', 'sols/wa.cpp', 'brute.py'];
const FINDING: StressFinding = {
  index: 2,
  generator: { name: 'gen', args: '5' },
  results: [{ solution: 1, outcome: 'wrong-answer' }],
};

test('every file on disk, labelled with the finding, in solution order', () => {
  const files = findingFiles(
    PKG,
    SOLUTIONS,
    FINDING,
    new Map([
      ['input.in', 10],
      ['input.ans', 3],
      ['2.out', 3],
      ['1.out', 3],
      ['1.err', 0],
      ['2.err', 12],
    ]),
  );
  assert.deepStrictEqual(files, {
    input: {
      kind: 'input',
      path: path.join(DIR, 'input.in'),
      label: 'stress/#2/#2 input.in',
      name: 'input',
    },
    answer: {
      kind: 'answer',
      path: path.join(DIR, 'input.ans'),
      label: 'stress/#2/#2 answer.ans',
      name: 'expected answer',
    },
    outputs: [
      {
        kind: 'output',
        path: path.join(DIR, '1.out'),
        label: 'stress/#2/sols/#2 wa.cpp.out',
        name: 'sols/wa.cpp',
        solution: 1,
      },
      {
        kind: 'output',
        path: path.join(DIR, '2.out'),
        label: 'stress/#2/#2 brute.py.out',
        name: 'brute.py',
        solution: 2,
      },
    ],
    // An empty stderr is no stderr at all.
    stderrs: [
      {
        kind: 'stderr',
        path: path.join(DIR, '2.err'),
        label: 'stress/#2/#2 brute.py.err',
        name: 'brute.py stderr',
        solution: 2,
      },
    ],
  });
  assert.deepStrictEqual(
    compareCandidates(files).map((file) => file.name),
    ['expected answer', 'sols/wa.cpp', 'brute.py'],
  );
});

test('a wiped finding has nothing to open', () => {
  const files = findingFiles(PKG, SOLUTIONS, FINDING, new Map());
  assert.deepStrictEqual(files, { input: undefined, answer: undefined, outputs: [], stderrs: [] });
  assert.deepStrictEqual(compareCandidates(files), []);
});

test('no label ends in a bare testcase pane title', () => {
  const files = findingFiles(
    PKG,
    ['output.out'],
    FINDING,
    new Map([
      ['input.in', 1],
      ['0.out', 1],
    ]),
  );
  for (const file of [files.input, ...files.outputs]) {
    const title = file?.label.split('/').pop();
    assert.ok(title !== 'input.in' && title !== 'output.out', title);
  }
});

const ALL = findingFiles(
  PKG,
  SOLUTIONS,
  FINDING,
  new Map([
    ['input.in', 10],
    ['input.ans', 3],
    ['1.out', 3],
  ]),
);

test('a row click opens the input alone', () => {
  assert.deepStrictEqual(inputSelection(ALL), { active: ALL.input, beside: [] });
});

test('a chip opens the input and that solution output beside it', () => {
  assert.deepStrictEqual(outputSelection(ALL, 1), {
    active: ALL.input,
    beside: [ALL.outputs[0]],
    missingOutput: false,
  });
});

test('a chip whose solution left no output opens the input and says so', () => {
  assert.deepStrictEqual(outputSelection(ALL, 0), {
    active: ALL.input,
    beside: [],
    missingOutput: true,
  });
});

test('Open opens everything, and falls back to the first file without an input', () => {
  assert.deepStrictEqual(everythingSelection(ALL), {
    active: ALL.input,
    beside: [ALL.answer, ALL.outputs[0]],
  });
  const noInput = { ...ALL, input: undefined };
  assert.deepStrictEqual(everythingSelection(noInput), {
    active: ALL.answer,
    beside: [ALL.outputs[0]],
  });
  assert.deepStrictEqual(inputSelection(noInput), { active: undefined, beside: [] });
});
