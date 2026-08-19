import * as assert from 'assert';
import { test } from 'node:test';

import { decorationFor } from './decoration';
import { Role } from './role';

const ROLES: readonly Role[] = [
  'checker',
  'interactor',
  'validator',
  'visualizer',
  'generator',
  'statement',
];

test('a solution is drawn with its expectation', () => {
  assert.deepStrictEqual(
    decorationFor({ path: 'sols/ac.cpp', role: 'solution', expectation: 'ACCEPTED' }),
    {
      badge: '✓',
      colorId: 'rbx.expectedAccepted',
      tooltip: 'rbx solution — expected AC',
    },
  );
});

test('the pairs that share a colour are still told apart', () => {
  const of = (expectation: string) =>
    decorationFor({ path: 'sol.cpp', role: 'solution', expectation });

  const accepted = of('ACCEPTED');
  const acOrTle = of('ACCEPTED_OR_TLE');
  assert.strictEqual(accepted?.colorId, acOrTle?.colorId);
  assert.notStrictEqual(accepted?.badge, acOrTle?.badge);

  const wa = of('WRONG_ANSWER');
  const incorrect = of('INCORRECT');
  assert.strictEqual(wa?.colorId, incorrect?.colorId);
  assert.notStrictEqual(wa?.badge, incorrect?.badge);
});

test('a solution promising nothing says so, rather than saying nothing', () => {
  assert.deepStrictEqual(
    decorationFor({ path: 'sols/x.cpp', role: 'solution', expectation: 'ANY' }),
    {
      badge: '?',
      colorId: 'rbx.expectedAny',
      tooltip: 'rbx solution — no outcome declared',
    },
  );
});

test('every other role takes two letters in one neutral colour', () => {
  for (const role of ROLES) {
    const decoration = decorationFor({ path: 'file.cpp', role });
    assert.ok(decoration !== undefined);
    assert.strictEqual([...decoration.badge].length, 2, `${role} badge`);
    // A role makes no promise about how it will do, so it must not borrow a
    // hue that means one.
    assert.strictEqual(decoration.colorId, 'rbx.declaredRole', `${role} colour`);
  }
});

test('no two roles are badged alike', () => {
  const badges = ROLES.map((role) => decorationFor({ path: 'f', role })?.badge);
  assert.strictEqual(new Set(badges).size, ROLES.length);
});

test('a solution with no expectation at all is left undecorated', () => {
  assert.strictEqual(decorationFor({ path: 'sols/x.cpp', role: 'solution' }), undefined);
});
