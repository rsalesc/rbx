import * as assert from 'assert';
import { test } from 'node:test';

import type { StressDeclarations } from '../rbx/stressDeclarations';
import { StressLaunch, defaultLaunch, stressArgv } from '../rbx/stressSpec';
import {
  LauncherAction,
  LauncherForm,
  commandLine,
  formOf,
  initialLaunch,
  launchOf,
  launchProblem,
  parseLaunch,
  reduce,
} from './launcherState';

const DECLS: StressDeclarations = {
  stresses: [
    { name: 'wa-small', generator: { name: 'gen', args: '[1..10] @' }, finder: '[sols/wa.cpp] ~ WA' },
    { name: 'bare', generator: { name: 'gen', args: '@' }, finder: '[sols/wa.cpp]' },
    { name: 'opaque', generator: { name: 'gen' }, finder: '!([sols/wa.cpp] ~ AC)' },
  ],
  generators: ['gen', 'other'],
  solutions: [
    { path: 'sols/main.cpp', outcome: 'ACCEPTED' },
    { path: 'sols/wa.cpp', outcome: 'WRONG_ANSWER' },
    { path: 'sols/slow.cpp', outcome: 'ACCEPTED_OR_TLE' },
  ],
  groups: ['samples', 'main'],
};

function fold(form: LauncherForm, ...actions: LauncherAction[]): LauncherForm {
  return actions.reduce((acc, action) => reduce(acc, action, DECLS), form);
}

function declaredForm(name: string): LauncherForm {
  return formOf(defaultLaunch({ kind: 'declared', name }), DECLS);
}

test('a blank launcher with nothing remembered starts on the first generator with a fresh seed', () => {
  const launch = initialLaunch(DECLS, undefined);
  assert.deepStrictEqual(launch.source, { kind: 'generator', expression: 'gen @' });
  assert.deepStrictEqual(initialLaunch({ ...DECLS, generators: [] }, undefined).source, {
    kind: 'generator',
    expression: '',
  });
});

test('a remembered launch is what a blank launcher starts from', () => {
  const remembered = defaultLaunch({ kind: 'fuzz', groups: ['main'] });
  assert.strictEqual(initialLaunch(DECLS, remembered), remembered);
});

test('a declared stress whose finder rows can say keeps it, and runs by name', () => {
  const form = declaredForm('wa-small');
  assert.strictEqual(form.declaredFinder, 'keep');
  assert.deepStrictEqual(form.finders.declared, {
    rows: [{ kind: 'break', solution: 'sols/wa.cpp', outcome: 'WRONG_ANSWER' }],
    join: 'all',
  });
  const launch = launchOf(form);
  assert.strictEqual(launch.finder, undefined);
  assert.deepStrictEqual(stressArgv(launch), ['stress', 'wa-small', '--no-promote']);
});

test('editing a kept row replaces the declared finder, spelled out as -g and -f', () => {
  const form = fold(declaredForm('wa-small'), { type: 'row', index: 0, field: 'outcome', value: 'TIME_LIMIT_EXCEEDED' });
  assert.strictEqual(form.declaredFinder, 'replace');
  const launch = launchOf(form);
  assert.deepStrictEqual(launch.finder, {
    rows: [{ kind: 'break', solution: 'sols/wa.cpp', outcome: 'TIME_LIMIT_EXCEEDED' }],
    join: 'all',
  });
  assert.strictEqual(
    commandLine(launch, DECLS),
    "rbx stress -g 'gen [1..10] @' -f '[sols/wa.cpp] ~ TIME_LIMIT_EXCEEDED' --no-promote",
  );
});

test('toggling the join is an edit too; using the declared finder again undoes every edit', () => {
  const edited = fold(declaredForm('wa-small'), { type: 'join', join: 'any' });
  assert.strictEqual(edited.declaredFinder, 'replace');
  const kept = fold(edited, { type: 'add-row', kind: 'disagree' }, { type: 'keep-finder' });
  assert.deepStrictEqual(kept, declaredForm('wa-small'));
});

test('an unrecognized declared finder shows no rows, and Replace with rows starts from none', () => {
  const form = declaredForm('opaque');
  assert.deepStrictEqual(form.finders.declared.rows, []);
  assert.strictEqual(launchOf(form).finder, undefined);
  assert.strictEqual(launchProblem(launchOf(form), DECLS), undefined);
  const replaced = fold(form, { type: 'replace-finder' });
  assert.strictEqual(replaced.declaredFinder, 'replace');
  assert.deepStrictEqual(launchOf(replaced).finder, { rows: [], join: 'all' });
  assert.match(launchProblem(launchOf(replaced), DECLS) ?? '', /at least one finder row/);
});

test('picking another declared stress drops the replacement made to the last one', () => {
  const form = fold(
    declaredForm('wa-small'),
    { type: 'add-row', kind: 'break' },
    { type: 'declared', name: 'bare' },
  );
  assert.strictEqual(form.declaredFinder, 'keep');
  assert.deepStrictEqual(form.finders.declared.rows, [
    { kind: 'break', solution: 'sols/wa.cpp', outcome: 'INCORRECT' },
  ]);
});

test('under Slowest a kept bare finder reads as ~ ANY, and a new row times its solution', () => {
  const form = fold(declaredForm('bare'), { type: 'slowest', on: true });
  assert.strictEqual(form.declaredFinder, 'keep');
  assert.deepStrictEqual(form.finders.declared.rows, [
    { kind: 'break', solution: 'sols/wa.cpp', outcome: 'ANY' },
  ]);
  const generator = fold(
    form,
    { type: 'mode', mode: 'generator' },
    { type: 'add-row', kind: 'break' },
    { type: 'row', index: 0, field: 'solution', value: 'sols/main.cpp' },
  );
  assert.deepStrictEqual(generator.finders.generator.rows, [
    { kind: 'break', solution: 'sols/main.cpp', outcome: 'ANY' },
  ]);
});

test("picking a Break row's solution preselects what its declaration says breaks it", () => {
  const form = fold(
    formOf(initialLaunch(DECLS, undefined), DECLS),
    { type: 'add-row', kind: 'break' },
    { type: 'add-row', kind: 'break' },
    { type: 'add-row', kind: 'break' },
    { type: 'row', index: 0, field: 'solution', value: 'sols/main.cpp' },
    { type: 'row', index: 1, field: 'solution', value: 'sols/wa.cpp' },
    { type: 'row', index: 2, field: 'solution', value: 'sols/slow.cpp' },
  );
  assert.deepStrictEqual(
    form.finders.generator.rows.map((row) => (row.kind === 'break' ? row.outcome : '')),
    ['INCORRECT', 'WRONG_ANSWER', 'WRONG_ANSWER'],
  );
});

test('rows edit only the current source, and each source keeps its own', () => {
  const form = fold(
    formOf(initialLaunch(DECLS, undefined), DECLS),
    { type: 'add-row', kind: 'disagree' },
    { type: 'row', index: 0, field: 'a', value: 'sols/main.cpp' },
    { type: 'row', index: 0, field: 'b', value: 'sols/wa.cpp' },
    { type: 'mode', mode: 'fuzz' },
  );
  assert.deepStrictEqual(form.finders.fuzz.rows, []);
  assert.strictEqual(launchOf(form).finder, undefined);
  assert.deepStrictEqual(stressArgv(launchOf(form)), ['stress', '--fuzz', '--no-promote']);
  const back = fold(form, { type: 'mode', mode: 'generator' });
  assert.strictEqual(
    commandLine(launchOf(back), DECLS),
    "rbx stress -g 'gen @' -f '[sols/main.cpp] != [sols/wa.cpp]' --no-promote",
  );
});

test('removing a row removes that row', () => {
  const form = fold(
    formOf(initialLaunch(DECLS, undefined), DECLS),
    { type: 'add-row', kind: 'break' },
    { type: 'add-row', kind: 'disagree' },
    { type: 'remove-row', index: 0 },
  );
  assert.deepStrictEqual(form.finders.generator.rows, [{ kind: 'disagree', a: '', b: '' }]);
});

test('fuzz groups are listed in declaration order, whatever order they were checked in', () => {
  const form = fold(
    formOf(defaultLaunch({ kind: 'fuzz', groups: [] }), DECLS),
    { type: 'group', group: 'main', on: true },
    { type: 'group', group: 'samples', on: true },
  );
  assert.deepStrictEqual(form.fuzzGroups, ['samples', 'main']);
  assert.deepStrictEqual(stressArgv(launchOf(form)), [
    'stress', '--fuzz-on', 'samples', '--fuzz-on', 'main', '--no-promote',
  ]);
  assert.deepStrictEqual(fold(form, { type: 'group', group: 'samples', on: false }).fuzzGroups, ['main']);
});

test('the budget reads its numbers as typed, and an empty field is refused, not zero', () => {
  const form = fold(
    formOf(initialLaunch(DECLS, undefined), DECLS),
    { type: 'add-row', kind: 'break' },
    { type: 'row', index: 0, field: 'solution', value: 'sols/wa.cpp' },
    { type: 'field', field: 'timeout', value: '30' },
    { type: 'field', field: 'findings', value: '3' },
    { type: 'tl', tl: 'custom' },
    { type: 'field', field: 'tlMs', value: '2500' },
    { type: 'flag', field: 'validate', on: false },
    { type: 'field', field: 'reference', value: 'sols/main.cpp' },
  );
  assert.strictEqual(
    commandLine(launchOf(form), DECLS),
    "rbx stress -g 'gen @' -f '[sols/wa.cpp] ~ WRONG_ANSWER' --timeout 30 --findings 3 " +
      '--timelimit 2500 --no-validate --reference sols/main.cpp --no-promote',
  );
  const empty = fold(form, { type: 'field', field: 'timeout', value: '' });
  assert.match(launchProblem(launchOf(empty), DECLS) ?? '', /time budget/);
});

test('a declared stress that is no longer declared cannot run, even by name', () => {
  assert.match(
    launchProblem(defaultLaunch({ kind: 'declared', name: 'gone' }), DECLS) ?? '',
    /not declared/,
  );
});

test('a form survives a manifest edit, and a kept finder follows it', () => {
  const form = declaredForm('wa-small');
  const edited: StressDeclarations = {
    ...DECLS,
    stresses: [{ name: 'wa-small', generator: { name: 'gen' }, finder: '[sols/main.cpp] ~ TLE' }],
  };
  assert.deepStrictEqual(reduce(form, { type: 'declarations' }, edited).finders.declared.rows, [
    { kind: 'break', solution: 'sols/main.cpp', outcome: 'TIME_LIMIT_EXCEEDED' },
  ]);
  const replaced = fold(form, { type: 'join', join: 'any' });
  assert.deepStrictEqual(reduce(replaced, { type: 'declarations' }, edited), replaced);
});

test('a launch round-trips through its form', () => {
  const launches: StressLaunch[] = [
    {
      ...defaultLaunch({ kind: 'declared', name: 'wa-small' }),
      finder: { rows: [{ kind: 'disagree', a: 'sols/main.cpp', b: 'sols/wa.cpp' }], join: 'any' },
      slowest: true,
      tl: { kind: 'double' },
      sanitized: true,
    },
    { ...defaultLaunch({ kind: 'fuzz', groups: ['main'] }), timeout: 60, reference: 'sols/main.cpp' },
    defaultLaunch({ kind: 'declared', name: 'wa-small' }),
  ];
  for (const launch of launches) {
    assert.deepStrictEqual(launchOf(formOf(launch, DECLS)), launch);
  }
});

test('parseLaunch rebuilds a launch and refuses anything else', () => {
  const launch: StressLaunch = {
    ...defaultLaunch({ kind: 'generator', expression: 'gen @' }),
    finder: { rows: [{ kind: 'break', solution: 'a', outcome: 'WRONG_ANSWER' }], join: 'all' },
    tl: { kind: 'custom', ms: 100 },
    reference: 'sols/main.cpp',
  };
  assert.deepStrictEqual(parseLaunch(JSON.parse(JSON.stringify(launch))), launch);
  assert.deepStrictEqual(parseLaunch({ ...launch, extra: 1 }), launch);
  for (const bad of [
    undefined,
    null,
    'stress',
    { ...launch, source: { kind: 'shell', command: 'rm' } },
    { ...launch, timeout: '10' },
    { ...launch, tl: { kind: 'custom' } },
    { ...launch, finder: { rows: [{ kind: 'break', solution: 1, outcome: 'WA' }], join: 'all' } },
    { ...launch, finder: { rows: [], join: 'xor' } },
    { ...launch, reference: 3 },
  ]) {
    assert.strictEqual(parseLaunch(bad), undefined, JSON.stringify(bad));
  }
});
