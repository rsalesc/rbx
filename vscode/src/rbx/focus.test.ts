import * as assert from 'assert';
import { test } from 'node:test';

import { EMPTY_FOCUS, focusCandidates, sameFocus } from './focus';

test('candidates are the problems under the contest directory, sorted', () => {
  const problems = ['/c/problems/b', '/elsewhere/x', '/c/problems/a', '/c2/a'];
  assert.deepStrictEqual(focusCandidates('/c', problems), ['/c/problems/a', '/c/problems/b']);
});

test('a sibling directory sharing the prefix is not a candidate', () => {
  // `/contest-old` starts with `/contest`, but is not inside it.
  assert.deepStrictEqual(focusCandidates('/contest', ['/contest-old/a', '/contest/a']), ['/contest/a']);
});

test('a problem at the contest root itself is a candidate', () => {
  assert.deepStrictEqual(focusCandidates('/c', ['/c']), ['/c']);
});

test('moving within one contest keeps the same focus', () => {
  const a = { contest: '/c', problems: ['/c/a', '/c/b'] };
  assert.ok(sameFocus(a, { contest: '/c', problems: ['/c/a', '/c/b'] }));
});

test('a different contest, problem set or no contest is a different focus', () => {
  const a = { contest: '/c', problems: ['/c/a', '/c/b'] };
  assert.ok(!sameFocus(a, { contest: '/d', problems: ['/c/a', '/c/b'] }));
  assert.ok(!sameFocus(a, { contest: '/c', problems: ['/c/a'] }));
  assert.ok(!sameFocus(a, { problems: ['/c/a', '/c/b'] }));
  assert.ok(!sameFocus(a, EMPTY_FOCUS));
});
