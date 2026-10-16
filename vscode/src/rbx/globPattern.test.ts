import * as assert from 'assert';
import { test } from 'node:test';

import { globPattern, isGlob } from './globPattern';

test('tells a glob from a plain path', () => {
  assert.strictEqual(isGlob('/p/solutions/good/*.*'), true);
  assert.strictEqual(isGlob('/p/solutions/main.cpp'), false);
});

test('a single star stays within one segment', () => {
  const pattern = globPattern('/p/solutions/good/*reference*.*');
  assert.ok(pattern.test('/p/solutions/good/reference.cpp'));
  assert.ok(pattern.test('/p/solutions/good/my-reference.py'));
  assert.ok(!pattern.test('/p/solutions/good/sub/reference.cpp'));
  assert.ok(!pattern.test('/p/solutions/good/main.cpp'));
});

test('a double star crosses segments, including none', () => {
  const pattern = globPattern('/p/documents/assets/**/*');
  assert.ok(pattern.test('/p/documents/assets/a.png'));
  assert.ok(pattern.test('/p/documents/assets/x/y/a.png'));
  assert.ok(!pattern.test('/p/documents/other/a.png'));
});

test('regex characters in names are literal', () => {
  const pattern = globPattern('/p/a+b (1)/sol.cpp');
  assert.ok(pattern.test('/p/a+b (1)/sol.cpp'));
  assert.ok(!pattern.test('/p/aab (1)/sol.cpp'));
});
