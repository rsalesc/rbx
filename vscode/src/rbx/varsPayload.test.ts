import * as assert from 'assert';
import { test } from 'node:test';

import { parseVarsPayload } from './varsPayload';

test('a flat map of display strings is accepted', () => {
  assert.deepStrictEqual(parseVarsPayload('{"N.max": "100000", "flag": "True"}'), {
    'N.max': '100000',
    flag: 'True',
  });
});

test('malformed or unexpected output yields no vars, never a throw', () => {
  for (const stdout of ['', 'not json', '[]', 'null', '{"a": {"b": 1}}', '{"a": [1]}']) {
    assert.strictEqual(parseVarsPayload(stdout), undefined, stdout);
  }
});

test('a nested object of strings is rejected too', () => {
  // The one shape a retry loop could mistake for a payload: skipping past the
  // outer brace would find a perfectly well-formed flat map inside, and badge
  // `b` with a value no statement can reference.
  assert.strictEqual(parseVarsPayload('{"a": {"b": "1"}}'), undefined);
});

test('a non-string value is rejected rather than coerced', () => {
  // The contract is display strings. A number here means the CLI changed
  // shape, and coercing it would reintroduce the precision bug that made
  // the contract strings in the first place.
  assert.strictEqual(parseVarsPayload('{"N.max": 100000}'), undefined);
});

test('leading noise before the object is tolerated', () => {
  // A shell wrapper or a venv activation can print before rbx does.
  assert.deepStrictEqual(parseVarsPayload('warning: x\n{"N.max": "5"}'), {
    'N.max': '5',
  });
});

test('a brace inside the leading noise does not hide the payload', () => {
  assert.deepStrictEqual(parseVarsPayload('warning: {weird}\n{"N.max": "5"}'), {
    'N.max': '5',
  });
});

test('an empty var block is a valid, empty result', () => {
  assert.deepStrictEqual(parseVarsPayload('{}'), {});
});

test('a var spelled like a prototype key stays an own property', () => {
  // `Object.hasOwn` is how statementVars.ts looks a name up, so a var named
  // `__proto__` has to survive parsing as an own property rather than being
  // swallowed by the setter -- and must not reshape the object's prototype.
  const vars = parseVarsPayload('{"__proto__": "1", "constructor": "2"}');
  assert.ok(vars !== undefined);
  assert.ok(Object.hasOwn(vars, '__proto__'));
  assert.strictEqual(Object.hasOwn(vars, 'toString'), false);
  assert.strictEqual(vars['constructor'], '2');
});
