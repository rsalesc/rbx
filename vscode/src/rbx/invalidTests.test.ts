import * as assert from 'assert';
import { test } from 'node:test';

import { invalidTestsMessage } from './invalidTests';

test('a run with nothing invalid needs no notification', () => {
  assert.strictEqual(invalidTestsMessage(undefined), undefined);
  assert.strictEqual(invalidTestsMessage({ mode: 'warn', invalid: [] }), undefined);
  assert.strictEqual(invalidTestsMessage({ mode: 'off', invalid: [] }), undefined);
});

test('a testcase two validators rejected is counted once', () => {
  assert.strictEqual(
    invalidTestsMessage({
      mode: 'warn',
      invalid: [
        { group: 'main', index: 1, validator: 'a.cpp' },
        { group: 'main', index: 1, validator: 'b.cpp' },
      ],
    }),
    'rbx: 1 testcase failed validation (main/1); the run went ahead anyway. ' +
      'Verdicts on them are on inputs the problem never promises to give.',
  );
});

test('a long list names the first few and counts the rest', () => {
  const invalid = [1, 2, 3, 4, 5].map((index) => ({ group: 'g', index, validator: 'v.cpp' }));
  assert.match(
    invalidTestsMessage({ mode: 'warn', invalid }) ?? '',
    /^rbx: 5 testcases failed validation \(g\/1, g\/2, g\/3 and 2 more\)/,
  );
});
