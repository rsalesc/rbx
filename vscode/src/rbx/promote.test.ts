import * as assert from 'assert';
import { test } from 'node:test';

import {
  Plan,
  Sink,
  commandLine,
  copyPathError,
  defaultManualGlob,
  defaultScriptPath,
  doneMessage,
  failureMessage,
  formRows,
  groupNameError,
  lastJson,
  listSinksArgs,
  manualGlobError,
  newScriptPathError,
  nothingToDo,
  parsePlan,
  parseSinks,
  pickRows,
  planArgs,
  planSummary,
  proposalLabel,
  promoteArgs,
  sameText,
  stemError,
  textChanges,
} from './promote';

const PLAN_SINK: Sink = {
  name: 'main',
  kind: 'plan',
  path: 'tests/plan.txt',
  scope: null,
  forms: ['recipe', 'copy'],
  form: 'recipe',
  suggested: 'tests/main/*.in',
  inPlace: true,
};

const GLOB_SINK: Sink = {
  name: 'samples',
  kind: 'glob',
  path: 'tests/samples/*.in',
  scope: null,
  forms: ['copy'],
  form: 'copy',
  suggested: 'tests/samples/*.in',
  inPlace: false,
};

test('lastJson takes the last line that parses, past a stray notice', () => {
  assert.deepStrictEqual(lastJson('Creating the cache…\n[{"a": 1}]\n\n'), [{ a: 1 }]);
  assert.deepStrictEqual(lastJson('{"x": 1}\nnot json\n'), { x: 1 });
  assert.strictEqual(lastJson(''), undefined);
  assert.strictEqual(lastJson('nothing here\n'), undefined);
});

test('the sink list is read, in order', () => {
  const stdout = `notice\n${JSON.stringify([PLAN_SINK, { ...GLOB_SINK, scope: 'large' }])}\n`;
  assert.deepStrictEqual(parseSinks(stdout), [PLAN_SINK, { ...GLOB_SINK, scope: 'large' }]);
  assert.deepStrictEqual(parseSinks('[]'), []);
});

test('a sink list with one malformed row is refused whole', () => {
  for (const row of [
    { ...PLAN_SINK, kind: 'script' },
    { ...PLAN_SINK, forms: ['input'] },
    { ...PLAN_SINK, inPlace: undefined },
    { ...PLAN_SINK, scope: 3 },
    null,
  ]) {
    assert.strictEqual(parseSinks(JSON.stringify([PLAN_SINK, row])), undefined, JSON.stringify(row));
  }
  assert.strictEqual(parseSinks('{"name": "main"}'), undefined);
});

const PLAN = {
  sink: { name: 'main', kind: 'plan', path: 'tests/plan.txt', scope: null },
  changes: [
    { path: '/p/tests/plan.txt', action: 'modify', before: 'gen 1\n', after: '@copy tests/main/000.in\n' },
    { path: '/p/tests/main/000.in', action: 'create', from: '/p/build/tests/main/000.in' },
    { path: '/p/tests/new.txt', action: 'create', content: 'gen 2\n' },
    { path: '/p/tests/old/001.in', action: 'delete' },
  ],
  promoted: [{ source: 'tests/plan.txt:1', form: 'copy', to: 'tests/main/000.in', inPlace: true, moved: true }],
  skipped: [],
};

test('the plan is read, every kind of change', () => {
  const plan = parsePlan(JSON.stringify(PLAN));
  assert.ok(plan !== undefined);
  assert.deepStrictEqual(plan.sink, { name: 'main', kind: 'plan', path: 'tests/plan.txt' });
  assert.deepStrictEqual(plan.changes, PLAN.changes);
  assert.deepStrictEqual(plan.promoted, PLAN.promoted);
});

test('a plan with a change rbx would not make is refused whole', () => {
  for (const change of [
    { path: '/p/a', action: 'rename' },
    { path: '/p/a', action: 'modify', before: '' },
    { path: '/p/a', action: 'create' },
    { action: 'delete' },
  ]) {
    assert.strictEqual(parsePlan(JSON.stringify({ ...PLAN, changes: [change] })), undefined, JSON.stringify(change));
  }
  assert.strictEqual(parsePlan('[]'), undefined);
});

test('a plan says what it does', () => {
  const plan = parsePlan(JSON.stringify(PLAN)) as Plan;
  assert.strictEqual(planSummary(plan), '2 files created, 1 file edited, 1 file deleted');
  assert.deepStrictEqual(
    textChanges(plan).map((change) => change.path),
    ['/p/tests/plan.txt', '/p/tests/new.txt'],
  );
  assert.strictEqual(doneMessage('tests/plan.txt:1', plan), 'turned tests/plan.txt:1 into a copy at tests/main/000.in, in place.');
  const moved = { ...plan, promoted: [{ ...plan.promoted[0], inPlace: false, form: 'recipe' as const }] };
  assert.strictEqual(doneMessage('finding #2', moved), 'moved finding #2 into main, as its generator call.');
  assert.strictEqual(
    nothingToDo({ ...plan, changes: [], skipped: [{ source: 'finding:1', reason: 'main already has it' }] }),
    'finding:1: main already has it.',
  );
});

test('sameText ignores line endings and a BOM only', () => {
  assert.ok(sameText('a\r\nb\r\n', 'a\nb\n'));
  assert.ok(sameText('a\rb\r', 'a\nb\n'));
  assert.ok(sameText('﻿gen 1\n', 'gen 1\n'));
  assert.ok(!sameText('a\nb\n', 'a\nb'));
  assert.ok(!sameText('gen 1\n', 'gen 2\n'));
});

test('a proposal is labelled by its package-relative path', () => {
  assert.strictEqual(proposalLabel('tests/testplan.txt'), 'tests/testplan.txt');
  assert.strictEqual(proposalLabel('./tests/testplan.txt'), 'tests/testplan.txt');
  assert.strictEqual(proposalLabel('tests\\sub\\plan.txt'), 'tests/sub/plan.txt');
  assert.strictEqual(proposalLabel('../shared/plan.txt'), 'plan.txt');
  assert.strictEqual(proposalLabel('/abs/plan.txt'), 'plan.txt');
});

test('the argv tails', () => {
  assert.deepStrictEqual(listSinksArgs(['tests/plan.txt:3']), ['tests/plan.txt:3', '--list-sinks', '--json']);
  assert.deepStrictEqual(promoteArgs(['main/2'], { kind: 'sink', name: 'samples' }), ['main/2', '--to', 'samples']);
  assert.deepStrictEqual(
    planArgs(['finding:3'], { kind: 'sink', name: 'main' }, {
      form: 'copy',
      path: 'tests/edge/*.in',
      keepSource: true,
      session: '2026-10-15T12:00:00',
    }),
    [
      'finding:3',
      '--session',
      '2026-10-15T12:00:00',
      '--to',
      'main',
      '--as',
      'copy',
      '--path',
      'tests/edge/*.in',
      '--keep-source',
      '--dry-run',
      '--json',
    ],
  );
  assert.deepStrictEqual(planArgs(['file:/tmp/a.in'], { kind: 'new-manual', name: 'hard', glob: 'tests/hard/*.in' }, { name: 'big' }), [
    'file:/tmp/a.in',
    '--new-manual',
    'hard',
    '--glob',
    'tests/hard/*.in',
    '--name',
    'big',
    '--dry-run',
    '--json',
  ]);
  assert.deepStrictEqual(planArgs(['main/0'], { kind: 'new-script', path: 'tests/edge.txt' }, { path: '' }), [
    'main/0',
    '--new-script',
    'tests/edge.txt',
    '--dry-run',
    '--json',
  ]);
});

test('the picker puts where the test is first, then the rest, then new groups', () => {
  const rows = pickRows([PLAN_SINK, GLOB_SINK]);
  assert.deepStrictEqual(
    rows.map((row) => [row.kind, row.label]),
    [
      ['separator', 'Where it is now'],
      ['sink', 'main'],
      ['separator', 'Test groups'],
      ['sink', 'samples'],
      ['separator', 'New group'],
      ['new-script', 'New script group…'],
      ['new-manual', 'New manual group…'],
    ],
  );
  const main = rows[1];
  assert.ok(main.kind === 'sink');
  assert.strictEqual(main.description, 'testplan tests/plan.txt');
  assert.match(main.detail ?? '', /freeze/);
  const scoped = pickRows([{ ...PLAN_SINK, inPlace: false, scope: 'large' }])[1];
  assert.ok(scoped.kind === 'sink');
  assert.strictEqual(scoped.description, 'testplan tests/plan.txt · @testgroup large');
  assert.deepStrictEqual(
    pickRows([]).map((row) => row.kind),
    ['separator', 'new-script', 'new-manual'],
  );
});

test('the form picker offers what the sink takes, the default first', () => {
  assert.deepStrictEqual(
    formRows(PLAN_SINK).map((row) => row.form),
    ['recipe', 'copy'],
  );
  assert.deepStrictEqual(
    formRows(GLOB_SINK).map((row) => row.form),
    ['copy'],
  );
});

test('a @copy path is a file or a pattern ending in .in, in the package', () => {
  for (const ok of ['tests/edge/*.in', 'tests/edge/big.in', 'tests/edge/edge-*.in']) {
    assert.strictEqual(copyPathError(ok), undefined, ok);
  }
  assert.ok(copyPathError('') !== undefined);
  assert.match(copyPathError('tests/edge/*.txt') ?? '', /\.in/);
  assert.match(copyPathError('../edge/*.in') ?? '', /inside the package/);
  assert.match(copyPathError('tests/*/a.in') ?? '', /file name/);
});

test('stems allow empty (auto) and plain names only', () => {
  assert.strictEqual(stemError(''), undefined);
  assert.strictEqual(stemError('big-1.v2'), undefined);
  assert.notStrictEqual(stemError('a b'), undefined);
  assert.notStrictEqual(stemError('sub/x'), undefined);
  assert.notStrictEqual(stemError('..'), undefined);
});

test('group names follow rbx: 3 to 32, letters, digits, - and _', () => {
  for (const ok of ['abc', 'stress-2', 'a_b', '1st', 'x'.repeat(32)]) {
    assert.strictEqual(groupNameError(ok), undefined, ok);
  }
  for (const bad of ['ab', 'x'.repeat(33), '-abc', '_abc', 'a b c', 'a.b.c', 'naïve']) {
    assert.ok(groupNameError(bad) !== undefined, bad);
  }
  assert.match(groupNameError('main', ['main']) ?? '', /already exists/);
});

test('a new script must be a .txt (or bare) path inside the package, named as a group', () => {
  for (const ok of ['tests/stress.txt', 'tests/stress', 'stress.txt', 'a/b/c-1.txt']) {
    assert.strictEqual(newScriptPathError(ok), undefined, ok);
  }
  assert.match(newScriptPathError('tests/stress.in') ?? '', /\.txt/);
  assert.match(newScriptPathError('/abs/stress.txt') ?? '', /inside the package/);
  assert.match(newScriptPathError('../stress.txt') ?? '', /inside the package/);
  assert.match(newScriptPathError('tests/ab.txt') ?? '', /not a valid test group name/);
  assert.match(newScriptPathError('tests/main.txt', ['main']) ?? '', /already exists/);
  assert.ok(newScriptPathError('') !== undefined);
});

test('a manual glob must hold a * and end in .in, inside the package', () => {
  assert.strictEqual(manualGlobError('tests/hard/*.in'), undefined);
  assert.ok(manualGlobError('tests/hard/a.in') !== undefined);
  assert.ok(manualGlobError('tests/hard/*.txt') !== undefined);
  assert.ok(manualGlobError('../hard/*.in') !== undefined);
});

test('the defaults are free names', () => {
  assert.strictEqual(defaultScriptPath([]), 'tests/edge.txt');
  assert.strictEqual(defaultScriptPath(['edge', 'edge-2']), 'tests/edge-3.txt');
  assert.strictEqual(defaultManualGlob('hard'), 'tests/hard/*.in');
});

test('the command line to paste quotes what a shell would read', () => {
  assert.strictEqual(
    commandLine(promoteArgs(['finding:2'], { kind: 'new-manual', name: 'hard', glob: 'tests/hard/*.in' })),
    "rbx testcases promote finding:2 --new-manual hard --glob 'tests/hard/*.in'",
  );
});

test('a failure says what rbx said, or the exit code', () => {
  assert.strictEqual(failureMessage(1, '\u001b[31mTest group x does not exist.\u001b[0m\n'), 'Test group x does not exist.');
  assert.strictEqual(failureMessage(2, '  '), 'rbx exited with 2.');
  assert.strictEqual(failureMessage(null, ''), 'rbx did not finish.');
  const long = Array.from({ length: 10 }, (_, i) => `line ${i}`).join('\n');
  assert.strictEqual(failureMessage(1, long), 'line 4\nline 5\nline 6\nline 7\nline 8\nline 9');
});
