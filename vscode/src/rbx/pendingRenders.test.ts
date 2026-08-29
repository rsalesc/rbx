import * as assert from 'assert';
import { test } from 'node:test';

import { pendingRenders } from './pendingRenders';
import { VarHint } from './statementVars';

function filtered(expression: string): VarHint {
  return { end: 0, expression, filtered: true };
}

function resolved(expression: string, text: string): VarHint {
  return { end: 0, expression, filtered: false, text };
}

test('only filtered references are asked about', () => {
  const hints = [resolved('N.max', '100000'), filtered('N.max | sci')];
  assert.deepStrictEqual(pendingRenders(hints, new Map()), ['N.max | sci']);
});

test('an expression already rendered is not asked about again', () => {
  const rendered = new Map([['N.max | sci', '10⁵']]);
  const hints = [filtered('N.max | sci'), filtered('M.max | sci')];
  assert.deepStrictEqual(pendingRenders(hints, rendered), ['M.max | sci']);
});

test('a bound repeated across a statement is asked about once', () => {
  // The canonical spelling is what the scanner emits, so two references
  // written `N.max|sci` and `N.max | sci` arrive here already identical.
  const hints = [filtered('N.max | sci'), filtered('N.max | sci')];
  assert.deepStrictEqual(pendingRenders(hints, new Map()), ['N.max | sci']);
});

test('first-appearance order is kept', () => {
  const hints = [filtered('b | sci'), filtered('a | sci'), filtered('b | sci')];
  assert.deepStrictEqual(pendingRenders(hints, new Map()), ['b | sci', 'a | sci']);
});

test('nothing filtered means nothing to ask', () => {
  assert.deepStrictEqual(pendingRenders([resolved('N.max', '5')], new Map()), []);
  assert.deepStrictEqual(pendingRenders([], new Map()), []);
});
