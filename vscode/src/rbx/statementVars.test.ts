import * as assert from 'assert';
import { test } from 'node:test';

import { scanStatementVars, Vars } from './statementVars';

/**
 * The foreign-scope keys are deliberately *resolvable*. A nested var block
 * named `g` really does flatten to the key `g.N.max` in `rbx vars --json`, so
 * without them the scope guard would be untestable: every foreign name would
 * be turned away by the lookup rather than by the guard.
 */
const VARS: Vars = {
  'N.max': 100000,
  'A.max': 1000000000,
  flag: true,
  name: 'foo',
  'g.N.max': 7,
  'groups.g.vars.N.max': 7,
  'p.N.max': 7,
  'problem.N.max': 7,
  'contest.year': 7,
  'vars.problem.N.max': 7,
};

const scan = (text: string) => scanStatementVars(text, VARS);

test('the shorthand and the long form both resolve', () => {
  assert.deepStrictEqual(scan('$N \\le \\VAR{N.max}$'), [{ end: 18, text: '100000' }]);
  assert.deepStrictEqual(
    scan('$N \\le \\VAR{vars.N.max}$').map((hint) => hint.text),
    ['100000'],
  );
});

test('a filter pipeline is ignored, the raw value is shown', () => {
  assert.deepStrictEqual(
    scan('\\VAR{N.max | sci}').map((hint) => hint.text),
    ['100000'],
  );
});

test('several references on one line each get a hint', () => {
  assert.deepStrictEqual(
    scan('$\\VAR{N.max}$ and $\\VAR{A.max}$').map((hint) => hint.text),
    ['100000', '1000000000'],
  );
});

test('non-root scopes are left alone', () => {
  for (const expression of [
    'g.N.max',
    'groups.g.vars.N.max',
    'p.N.max',
    'problem.N.max',
    'contest.year',
    'vars.problem.N.max',
  ]) {
    assert.deepStrictEqual(scan(`\\VAR{${expression}}`), [], expression);
  }
});

test('expressions that are not a plain name are left alone', () => {
  for (const expression of ['N.max + 1', 'len(x)', "N.max if x else 'y'", '']) {
    assert.deepStrictEqual(scan(`\\VAR{${expression}}`), [], expression);
  }
});

test('an unknown name gets no hint, which is how a typo shows up', () => {
  assert.deepStrictEqual(scan('\\VAR{N.mx}'), []);
});

test('a name inherited from Object.prototype is not a var', () => {
  for (const expression of ['constructor', 'toString', 'hasOwnProperty']) {
    assert.deepStrictEqual(scan(`\\VAR{${expression}}`), [], expression);
  }
});

test('a commented line is skipped', () => {
  assert.deepStrictEqual(scan('%# $\\VAR{N.max}$'), []);
  assert.deepStrictEqual(scan('  % $\\VAR{N.max}$'), []);
});

test('a comment opened mid-line is skipped too', () => {
  assert.deepStrictEqual(scan('$N$ is bounded. % TODO: \\VAR{N.max}'), []);
});

test('an escaped percent does not open a comment', () => {
  assert.deepStrictEqual(
    scan('50\\% of \\VAR{N.max}').map((hint) => hint.text),
    ['100000'],
  );
  // A literal backslash before the percent: the percent is a real comment.
  assert.deepStrictEqual(scan('a \\\\% b \\VAR{N.max}'), []);
});

test('an escaped VAR is not a reference', () => {
  assert.deepStrictEqual(scan('\\\\VAR{N.max}'), []);
  // ...but a literal backslash followed by a real reference still is.
  assert.deepStrictEqual(
    scan('\\\\\\VAR{N.max}').map((hint) => hint.text),
    ['100000'],
  );
});

test('non-numeric values render as themselves', () => {
  assert.deepStrictEqual(
    scan('\\VAR{flag} \\VAR{name}').map((hint) => hint.text),
    ['true', 'foo'],
  );
});

test('the hint sits just after the closing brace', () => {
  const text = 'abc \\VAR{N.max} def';
  const [hint] = scan(text);
  assert.strictEqual(text[hint.end - 1], '}');
});

test('offsets are absolute across lines, and a comment ends at its newline', () => {
  const text = '% $\\VAR{A.max}$\n$N \\le \\VAR{N.max}$\n';
  const hints = scan(text);
  assert.deepStrictEqual(
    hints.map((hint) => hint.text),
    ['100000'],
  );
  assert.strictEqual(text.slice(hints[0].end - 6, hints[0].end), 'N.max}');
});

test('scanning is repeatable, so no regex state leaks between calls', () => {
  const text = '\\VAR{N.max} \\VAR{A.max}';
  assert.deepStrictEqual(scan(text), scan(text));
});
