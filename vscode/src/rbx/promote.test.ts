import * as assert from 'assert';
import { test } from 'node:test';

import {
  MANUAL_SEPARATOR,
  SCRIPT_SEPARATOR,
  addToGroupArgs,
  commandLine,
  defaultManualGlob,
  defaultScriptPath,
  dryRunArgs,
  failureMessage,
  groupNameError,
  lastJson,
  listGroupsArgs,
  manualGlobError,
  newManualArgs,
  newScriptArgs,
  newScriptPathError,
  parseDryRun,
  parseGroupList,
  pickRows,
  proposalLabel,
  sameText,
  scriptGroupName,
} from './promote';

test('lastJson takes the last line that parses, past a stray notice', () => {
  assert.deepStrictEqual(lastJson('Creating the cache…\n[{"a": 1}]\n\n'), [{ a: 1 }]);
  assert.deepStrictEqual(lastJson('{"x": 1}\nnot json\n'), { x: 1 });
  assert.strictEqual(lastJson(''), undefined);
  assert.strictEqual(lastJson('nothing here\n'), undefined);
});

test('the group list is read, in order', () => {
  const stdout =
    '[{"name": "main", "kind": "script", "path": "tests/testplan.txt"},' +
    ' {"name": "corner", "kind": "manual", "path": "tests/corner/*.in"}]\n';
  assert.deepStrictEqual(parseGroupList(stdout), [
    { name: 'main', kind: 'script', path: 'tests/testplan.txt' },
    { name: 'corner', kind: 'manual', path: 'tests/corner/*.in' },
  ]);
  assert.deepStrictEqual(parseGroupList('[]'), []);
});

test('a group list with one malformed row is refused whole', () => {
  for (const stdout of [
    '{"name": "main"}',
    '[{"name": "main", "kind": "generator", "path": "x"}]',
    '[{"name": "main", "kind": "script"}]',
    '[null]',
    '',
  ]) {
    assert.strictEqual(parseGroupList(stdout), undefined, stdout);
  }
});

test('the dry run is read, and refused when a field is missing', () => {
  assert.deepStrictEqual(
    parseDryRun('{"file": "/p/tests/a.txt", "before": "gen 1\\n", "after": "gen 1\\ngen 2\\n"}'),
    { file: '/p/tests/a.txt', before: 'gen 1\n', after: 'gen 1\ngen 2\n' },
  );
  assert.strictEqual(parseDryRun('{"file": "/p/a.txt", "before": ""}'), undefined);
  assert.strictEqual(parseDryRun('[]'), undefined);
});

test('sameText ignores line endings and a BOM only', () => {
  assert.ok(sameText('a\r\nb\r\n', 'a\nb\n'));
  assert.ok(sameText('a\rb\r', 'a\nb\n'));
  assert.ok(sameText('\uFEFFgen 1\n', 'gen 1\n'));
  assert.ok(!sameText('a\nb\n', 'a\nb'));
  assert.ok(!sameText('gen 1\n', 'gen 2\n'));
});

test('a proposal is labelled by its package-relative path', () => {
  assert.strictEqual(proposalLabel('tests/testplan.txt'), 'tests/testplan.txt');
  assert.strictEqual(proposalLabel('./tests/testplan.txt'), 'tests/testplan.txt');
  assert.strictEqual(proposalLabel('tests\\sub\\plan.txt'), 'tests/sub/plan.txt');
  assert.strictEqual(proposalLabel('../shared/plan.txt'), 'plan.txt');
  assert.strictEqual(proposalLabel('/abs/plan.txt'), 'plan.txt');
  assert.strictEqual(proposalLabel('C:\\abs\\plan.txt'), 'plan.txt');
});

test('the argv tails', () => {
  assert.deepStrictEqual(listGroupsArgs(), ['--list-groups', '--json']);
  assert.deepStrictEqual(dryRunArgs(3, 'main'), ['3', '--group', 'main', '--dry-run', '--json']);
  assert.deepStrictEqual(addToGroupArgs(3, 'corner'), ['3', '--group', 'corner']);
  assert.deepStrictEqual(newScriptArgs(1, 'tests/stress.txt'), ['1', '--new-script', 'tests/stress.txt']);
  assert.deepStrictEqual(newManualArgs(2, 'hard', 'tests/hard/*.in'), [
    '2',
    '--new-manual',
    'hard',
    '--glob',
    'tests/hard/*.in',
  ]);
});

test('the picker puts script groups first, then manual, then the new ones', () => {
  const rows = pickRows([
    { name: 'corner', kind: 'manual', path: 'tests/corner/*.in' },
    { name: 'main', kind: 'script', path: 'tests/testplan.txt' },
  ]);
  assert.deepStrictEqual(
    rows.map((row) => [row.kind, row.label]),
    [
      ['separator', SCRIPT_SEPARATOR],
      ['group', 'main'],
      ['separator', MANUAL_SEPARATOR],
      ['group', 'corner'],
      ['separator', 'New group'],
      ['new-script', 'New script group…'],
      ['new-manual', 'New manual group…'],
    ],
  );
  const main = rows[1];
  assert.ok(main.kind === 'group');
  assert.strictEqual(main.description, 'tests/testplan.txt');
});

test('a kind with no groups gets no separator', () => {
  const rows = pickRows([{ name: 'corner', kind: 'manual', path: 'tests/corner/*.in' }]);
  assert.ok(!rows.some((row) => row.label === SCRIPT_SEPARATOR));
  assert.deepStrictEqual(
    pickRows([]).map((row) => row.kind),
    ['separator', 'new-script', 'new-manual'],
  );
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

test('a new script group is named after its stem', () => {
  assert.strictEqual(scriptGroupName('tests/stress.txt'), 'stress');
  assert.strictEqual(scriptGroupName('tests/stress'), 'stress');
  assert.strictEqual(scriptGroupName('a\\b\\hard-1.txt'), 'hard-1');
});

test('a manual glob must hold a * and end in .in, inside the package', () => {
  assert.strictEqual(manualGlobError('tests/hard/*.in'), undefined);
  assert.ok(manualGlobError('tests/hard/a.in') !== undefined);
  assert.ok(manualGlobError('tests/hard/*.txt') !== undefined);
  assert.ok(manualGlobError('../hard/*.in') !== undefined);
});

test('the defaults are free names', () => {
  assert.strictEqual(defaultScriptPath([]), 'tests/stress.txt');
  assert.strictEqual(defaultScriptPath(['stress', 'stress-2']), 'tests/stress-3.txt');
  assert.strictEqual(defaultManualGlob('hard'), 'tests/hard/*.in');
});

test('the command line to paste quotes what a shell would read', () => {
  assert.strictEqual(
    commandLine(newManualArgs(2, 'hard', 'tests/hard/*.in')),
    "rbx testcases add-finding 2 --new-manual hard --glob 'tests/hard/*.in'",
  );
});

test('a failure says what rbx said, or the exit code', () => {
  assert.strictEqual(failureMessage(1, '\u001b[31mTest group x does not exist.\u001b[0m\n'), 'Test group x does not exist.');
  assert.strictEqual(failureMessage(2, '  '), 'rbx exited with 2.');
  assert.strictEqual(failureMessage(null, ''), 'rbx did not finish.');
  const long = Array.from({ length: 10 }, (_, i) => `line ${i}`).join('\n');
  assert.strictEqual(failureMessage(1, long), 'line 4\nline 5\nline 6\nline 7\nline 8\nline 9');
});
