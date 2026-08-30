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
  // shape, and coercing it would reintroduce the precision bug that made the
  // contract strings in the first place -- this bound is a plausible modulus
  // and JSON.parse cannot carry it, as the assertion below shows.
  const modulus = '1000000000000000007';
  assert.strictEqual(JSON.parse(`{"N": ${modulus}}`).N.toString(), '1000000000000000000');
  assert.strictEqual(parseVarsPayload(`{"N.max": ${modulus}}`), undefined);
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

test('trailing noise drops the payload rather than salvaging it', () => {
  // The stated limit: only leading noise is tolerated. Output after the object
  // means something wrote over rbx's stdout, and no badges beats guessing.
  assert.strictEqual(parseVarsPayload('{"N.max": "5"}\nwarning: x'), undefined);
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

test('the cursor escape rbx really emits does not eat the payload', () => {
  // Not hypothetical: with FORCE_COLOR set in the environment the editor
  // inherited, Rich restores the cursor on exit and rbx's stdout ends with a
  // show-cursor sequence. Captured verbatim from a real `rbx vars --json`.
  // Left unstripped it fails JSON.parse and the feature draws nothing at all
  // -- on some machines and not others, depending on how the editor started.
  const real = '{"A.min": "0", "A.max": "2147483647"}\n\u001b[?25h';
  assert.deepStrictEqual(parseVarsPayload(real), {
    'A.min': '0',
    'A.max': '2147483647',
  });
});

test('the render map is read by this same parser', () => {
  // `rbx vars --render` prints the same flat map of strings, keyed by the
  // expression rather than by a name -- pipes, spaces and all. Nothing here
  // cares which it is. The superscripts arrive as themselves because the
  // command dumps its JSON with ensure_ascii=False and this reads UTF-8.
  assert.deepStrictEqual(
    parseVarsPayload('{"N.max | sci": "10⁵", "M.max | rsci": "2×10⁹ + 7"}'),
    { 'N.max | sci': '10⁵', 'M.max | rsci': '2×10⁹ + 7' },
  );
});

test('an empty render map is a valid answer, not a failure', () => {
  // What every expression failing to render looks like: the command drops each
  // one and still exits 0, so `{}` is the whole payload.
  assert.deepStrictEqual(parseVarsPayload('{}\n\u001b[?25h'), {});
});

test('colour sequences around the payload are stripped too', () => {
  assert.deepStrictEqual(parseVarsPayload('\u001b[32m{"N.max": "5"}\u001b[0m\n'), {
    'N.max': '5',
  });
});
