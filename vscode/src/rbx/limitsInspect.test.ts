import * as assert from 'assert';
import { test } from 'node:test';

import { inspectArgs, parseInspect, profileLocation } from './limitsInspect';

test('profileLocation splits a profile path into root and name', () => {
  assert.deepStrictEqual(profileLocation('/a/b/prob/.limits/moj.yml'), {
    root: '/a/b/prob',
    profile: 'moj',
  });
  assert.strictEqual(profileLocation('/a/b/prob/limits/moj.yml'), undefined);
});

test('inspectArgs turns each edit into its flags', () => {
  assert.deepStrictEqual(inspectArgs('moj'), ['time-inspect', '-p', 'moj', '--stdin']);
  assert.deepStrictEqual(inspectArgs('moj', { kind: 'set', row: '1', ms: 1300 }).slice(4), [
    '--set',
    '1=1300',
  ]);
  assert.deepStrictEqual(inspectArgs('moj', { kind: 'revert', row: 'base' }).slice(4), [
    '--revert',
    'base',
  ]);
  assert.deepStrictEqual(inspectArgs('moj', { kind: 'inherit', value: false }).slice(4), [
    '--no-inherit',
  ]);
});

test('parseInspect reads the last JSON line and refuses other versions', () => {
  const ok = parseInspect('warning: something\n{"version": 1, "profile": "local", "path": "x", "errors": []}\n');
  assert.ok(ok.ok);
  const bad = parseInspect('{"version": 99, "profile": "local", "path": "x", "errors": []}');
  assert.ok(!bad.ok);
  assert.ok(!parseInspect('').ok);
});
