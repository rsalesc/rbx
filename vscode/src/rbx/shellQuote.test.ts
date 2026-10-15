import * as assert from 'assert';
import { test } from 'node:test';

import { shellQuote } from './shellQuote';

test('a plainly safe argument is left bare', () => {
  for (const arg of ['stress', '--group', 'tests/stress.txt', '3']) {
    assert.strictEqual(shellQuote(arg), arg);
  }
});

test('anything else is single-quoted, with a single quote escaped', () => {
  assert.strictEqual(shellQuote('tests/hard/*.in'), "'tests/hard/*.in'");
  assert.strictEqual(shellQuote('[a] ~ WA && [b]'), "'[a] ~ WA && [b]'");
  assert.strictEqual(shellQuote("it's"), "'it'\\''s'");
});
