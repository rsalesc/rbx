import * as assert from 'assert';
import { test } from 'node:test';

import { FinderRow } from './finder';
import { StressLaunch, generatorCallString, stressArgv, validateLaunch } from './stressSpec';

const WA_ROW: FinderRow = { kind: 'break', solution: 'sols/wa.cpp', outcome: 'WRONG_ANSWER' };

/** Every budget at rbx's default, so a test changes only what it is about. */
function launch(overrides: Partial<StressLaunch> = {}): StressLaunch {
  return {
    source: { kind: 'generator', expression: 'gens/gen.cpp [1..1000]' },
    finder: { rows: [WA_ROW], join: 'all' },
    slowest: false,
    timeout: 10,
    findings: 1,
    tl: { kind: 'normal' },
    sanitized: false,
    skipInvalid: false,
    validate: true,
    ...overrides,
  };
}

const DECLARED = { generator: { name: 'gens/gen.cpp', args: '[1..10]' }, finder: '[sols/a.cpp]' };

test('a generator call with rows is -g and -f, and nothing rbx would assume anyway', () => {
  assert.deepStrictEqual(stressArgv(launch()), [
    'stress',
    '-g',
    'gens/gen.cpp [1..1000]',
    '-f',
    '[sols/wa.cpp] ~ WRONG_ANSWER',
    '--no-promote',
  ]);
});

test('a declared stress keeping its finder runs by name', () => {
  assert.deepStrictEqual(
    stressArgv(launch({ source: { kind: 'declared', name: 'wa-small' }, finder: undefined })),
    ['stress', 'wa-small', '--no-promote'],
  );
});

test('a declared stress with replaced rows is spelled out as its generator plus the rows', () => {
  const replaced = launch({ source: { kind: 'declared', name: 'wa-small' } });
  assert.deepStrictEqual(stressArgv(replaced, DECLARED), [
    'stress',
    '-g',
    'gens/gen.cpp [1..10]',
    '-f',
    '[sols/wa.cpp] ~ WRONG_ANSWER',
    '--no-promote',
  ]);
  assert.throws(() => stressArgv(replaced), /wa-small/);
});

test('fuzzing every group, or some, with or without a finder', () => {
  assert.deepStrictEqual(
    stressArgv(launch({ source: { kind: 'fuzz', groups: [] }, finder: undefined })),
    ['stress', '--fuzz', '--no-promote'],
  );
  assert.deepStrictEqual(stressArgv(launch({ source: { kind: 'fuzz', groups: ['main', 'big'] } })), [
    'stress',
    '--fuzz-on',
    'main',
    '--fuzz-on',
    'big',
    '-f',
    '[sols/wa.cpp] ~ WRONG_ANSWER',
    '--no-promote',
  ]);
});

test('every budget and advanced option that differs from the default is passed', () => {
  assert.deepStrictEqual(
    stressArgv(
      launch({
        source: { kind: 'declared', name: 'tle' },
        finder: undefined,
        slowest: true,
        timeout: 60,
        findings: 5,
        tl: { kind: 'custom', ms: 2500 },
        sanitized: true,
        skipInvalid: true,
        validate: false,
        reference: 'sols/main.cpp',
      }),
    ),
    [
      'stress',
      'tle',
      '--slowest',
      '--timeout',
      '60',
      '--findings',
      '5',
      '--timelimit',
      '2500',
      '--sanitized',
      '--skip-invalid',
      '--no-validate',
      '--reference',
      'sols/main.cpp',
      '--no-promote',
    ],
  );
  assert.ok(stressArgv(launch({ tl: { kind: 'double' } })).includes('--double-tl'));
});

test('a generator call is name then args, as rbx prints one', () => {
  assert.strictEqual(generatorCallString({ name: 'gens/gen.cpp' }), 'gens/gen.cpp');
  assert.strictEqual(generatorCallString({ name: 'gens/gen.cpp', args: '' }), 'gens/gen.cpp');
  assert.strictEqual(generatorCallString({ name: 'g', args: '1 2' }), 'g 1 2');
});

test('a complete launch is valid', () => {
  assert.strictEqual(validateLaunch(launch()), undefined);
  assert.strictEqual(
    validateLaunch(launch({ source: { kind: 'fuzz', groups: [] }, finder: undefined })),
    undefined,
  );
  assert.strictEqual(
    validateLaunch(launch({ source: { kind: 'declared', name: 'x' }, finder: undefined })),
    undefined,
  );
});

test('a generator call needs an expression and at least one row, even under Slowest', () => {
  assert.match(
    validateLaunch(launch({ source: { kind: 'generator', expression: '  ' } })) ?? '',
    /generator call/,
  );
  assert.match(validateLaunch(launch({ finder: undefined })) ?? '', /finder row/);
  assert.match(validateLaunch(launch({ finder: { rows: [], join: 'all' } })) ?? '', /finder row/);
  assert.match(
    validateLaunch(launch({ finder: undefined, slowest: true })) ?? '',
    /solutions to time/,
  );
});

test('rows replacing a finder must be rows', () => {
  assert.match(
    validateLaunch(
      launch({ source: { kind: 'declared', name: 'x' }, finder: { rows: [], join: 'all' } }),
    ) ?? '',
    /own finder/,
  );
  assert.match(
    validateLaunch(launch({ source: { kind: 'fuzz', groups: [] }, finder: { rows: [], join: 'any' } })) ??
      '',
    /main solution/,
  );
  assert.match(validateLaunch(launch({ source: { kind: 'declared', name: '' } })) ?? '', /declared/);
});

test('rows that cannot be written are caught before dispatch', () => {
  const rows = (...each: FinderRow[]) => launch({ finder: { rows: each, join: 'all' } });
  assert.match(validateLaunch(rows({ kind: 'disagree', a: 'a', b: 'a' })) ?? '', /two different/);
  assert.match(validateLaunch(rows({ kind: 'break', solution: '', outcome: 'WA' })) ?? '', /solution/);
  assert.match(validateLaunch(rows({ kind: 'break', solution: 'a"b', outcome: 'WA' })) ?? '', /quote/);
  assert.match(validateLaunch(rows({ kind: 'break', solution: 'a', outcome: '' })) ?? '', /outcome/);
});

test('budgets are positive whole numbers', () => {
  for (const timeout of [0, -1, 1.5, Number.NaN]) {
    assert.match(validateLaunch(launch({ timeout })) ?? '', /seconds/, String(timeout));
  }
  assert.match(validateLaunch(launch({ findings: 0 })) ?? '', /findings/);
  assert.match(validateLaunch(launch({ tl: { kind: 'custom', ms: 0 } })) ?? '', /milliseconds/);
  assert.match(validateLaunch(launch({ reference: ' ' })) ?? '', /reference/);
});
