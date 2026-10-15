import * as assert from 'assert';
import { test } from 'node:test';

import {
  generatorCallFrom,
  irunArgs,
  isCommunication,
  solutionChoices,
  testSelector,
} from './irun';
import type { DeclaredAsset } from './manifest';

test('a testcase runs by its selector, the solutions named first', () => {
  assert.deepStrictEqual(
    irunArgs({ kind: 'test', selector: 'main/1' }, ['sols/a.cpp', 'sols/b.cpp']),
    ['sols/a.cpp', 'sols/b.cpp', '-t', 'main/1'],
  );
});

test('a generator call is passed whole, for the shell quoting to keep together', () => {
  assert.deepStrictEqual(irunArgs({ kind: 'generator', call: 'gen 10 20' }, []), [
    '-g',
    'gen 10 20',
  ]);
});

test('typed input runs from its file, checked against a typed answer when there is one', () => {
  const target = { kind: 'input', input: '/t/in.txt', answer: '/t/ans.txt' } as const;
  assert.deepStrictEqual(irunArgs(target, ['a.cpp']), [
    'a.cpp',
    '--input',
    '/t/in.txt',
    '--answer',
    '/t/ans.txt',
  ]);
  // Unchecked: the answer has nothing to be compared with, and rbx refuses both.
  assert.deepStrictEqual(irunArgs(target, ['a.cpp'], 'none'), [
    'a.cpp',
    '--input',
    '/t/in.txt',
    '--no-check',
  ]);
});

test('a testcase has a selector, the typed input of an ad-hoc run does not', () => {
  assert.strictEqual(testSelector({ group: 'samples', index: 2 }), 'samples/2');
  assert.strictEqual(testSelector({ group: 'interactive', index: 0 }), undefined);
});

test('only a communication manifest is interactive', () => {
  assert.strictEqual(isCommunication({ type: 'communication' }), true);
  assert.strictEqual(isCommunication({ type: 'batch' }), false);
  assert.strictEqual(isCommunication({}), false);
  assert.strictEqual(isCommunication(undefined), false);
});

const ASSETS: DeclaredAsset[] = [
  { path: 'sols/main.cpp', role: 'solution', expectation: 'ACCEPTED' },
  { path: 'sols/wa.cpp', role: 'solution', expectation: 'WRONG_ANSWER' },
  { path: 'sols/alt.py', role: 'solution', expectation: 'ACCEPTED' },
  { path: 'checker.cpp', role: 'checker' },
];

test('the picker ticks the solutions asked for, or the accepted ones', () => {
  assert.deepStrictEqual(
    solutionChoices(ASSETS, ['./sols/wa.cpp']).map((c) => [c.path, c.picked]),
    [
      ['sols/main.cpp', false],
      ['sols/wa.cpp', true],
      ['sols/alt.py', false],
    ],
  );
  assert.deepStrictEqual(
    solutionChoices(ASSETS).map((c) => [c.path, c.picked]),
    [
      ['sols/main.cpp', true],
      ['sols/wa.cpp', false],
      ['sols/alt.py', true],
    ],
  );
  // A preselection naming nothing the manifest has falls back the same way.
  assert.strictEqual(solutionChoices(ASSETS, ['gone.cpp'])[0].picked, true);
});

test('a generator call is read off a testplan line', () => {
  assert.strictEqual(generatorCallFrom('  gen 10 20 // big'), 'gen 10 20');
  assert.strictEqual(generatorCallFrom('gen 1 2 # note'), 'gen 1 2');
  assert.strictEqual(generatorCallFrom('@copy tests/a.in'), undefined);
  assert.strictEqual(generatorCallFrom('@testgroup big {'), undefined);
  assert.strictEqual(generatorCallFrom('}'), undefined);
  assert.strictEqual(generatorCallFrom('   '), undefined);
});
