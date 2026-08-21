import * as assert from 'assert';
import { test } from 'node:test';

import { problemChoices } from './problems';

const identity = (shortName: string, order: number, color?: string, contestRoot = '/c') => ({
  shortName,
  order,
  color,
  contestRoot,
});

test('orders contest problems by their declared order, not by path', () => {
  // `/c/z` is `A` and sorts first despite sorting last lexicographically --
  // which is the whole point of reading the contest file.
  const choices = problemChoices(
    ['/c/a', '/c/z'],
    new Map([
      ['/c/z', identity('A', 0)],
      ['/c/a', identity('B', 1)],
    ]),
    () => 'fallback',
  );
  assert.deepStrictEqual(
    choices.map((c) => c.label),
    ['A', 'B'],
  );
  assert.deepStrictEqual(
    choices.map((c) => c.root),
    ['/c/z', '/c/a'],
  );
});

test('labels an uncontested package with the host fallback, after the contest', () => {
  const choices = problemChoices(
    ['/loose', '/c/A'],
    new Map([['/c/A', identity('A', 0)]]),
    (root) => `label:${root}`,
  );
  assert.deepStrictEqual(
    choices.map((c) => c.label),
    ['A', 'label:/loose'],
  );
});

test('carries the declared colour through', () => {
  const choices = problemChoices(
    ['/c/A'],
    new Map([['/c/A', identity('A', 0, '#f00')]]),
    () => '',
  );
  assert.strictEqual(choices[0].color, '#f00');
});

test('groups by contest only when there is more than one group', () => {
  const one = problemChoices(['/c/A'], new Map([['/c/A', identity('A', 0)]]), () => '');
  assert.strictEqual(one[0].group, undefined);

  const two = problemChoices(
    ['/x/A', '/y/A'],
    new Map([
      ['/x/A', identity('A', 0, undefined, '/x')],
      ['/y/A', identity('A', 0, undefined, '/y')],
    ]),
    () => '',
  );
  assert.deepStrictEqual(
    two.map((c) => c.group),
    ['x', 'y'],
  );
});

test('heads a nested problem with its contest, not its parent directory', () => {
  // `path: problems/beta` puts the package two levels down. Grouping by the
  // parent would head this "problems" -- a name no contest has, and one every
  // contest that nests would share.
  const choices = problemChoices(
    ['/x/problems/beta', '/y/A'],
    new Map([
      ['/x/problems/beta', identity('A', 0, undefined, '/x')],
      ['/y/A', identity('A', 0, undefined, '/y')],
    ]),
    () => '',
  );
  assert.deepStrictEqual(
    choices.map((c) => c.group),
    ['x', 'y'],
  );
});

test('sorts uncontested packages by path', () => {
  const choices = problemChoices(['/b', '/a'], new Map(), (root) => root);
  assert.deepStrictEqual(
    choices.map((c) => c.root),
    ['/a', '/b'],
  );
});

test('breaks a collision between two variants by short name, not by root', () => {
  // `order` is counted per contest file, so two problems merged out of
  // `contest.div1.rbx.yml` and `contest.div2.rbx.yml` can both claim 1.
  // Discovery order must not be what decides which one shows first.
  //
  // The directories are named against the letters on purpose: sorting by root
  // would answer `C, B` here, so only the short name can produce `B, C`.
  const choices = problemChoices(
    ['/c/1', '/c/2'],
    new Map([
      ['/c/1', identity('C', 1)],
      ['/c/2', identity('B', 1)],
    ]),
    () => '',
  );
  assert.deepStrictEqual(
    choices.map((c) => c.label),
    ['B', 'C'],
  );
});

test('breaks a full collision by root', () => {
  // Two variants may go further and give one letter to two directories. The
  // root is the last thing left that tells them apart.
  const choices = problemChoices(
    ['/c/second', '/c/first'],
    new Map([
      ['/c/second', identity('B', 1)],
      ['/c/first', identity('B', 1)],
    ]),
    () => '',
  );
  assert.deepStrictEqual(
    choices.map((c) => c.root),
    ['/c/first', '/c/second'],
  );
});

test('heads the contest once an uncontested package shares the list', () => {
  // The loose packages are a group of their own: a contest butting straight up
  // against a run of bare folder names is exactly when a heading earns itself.
  const choices = problemChoices(
    ['/loose', '/c/A'],
    new Map([['/c/A', identity('A', 0)]]),
    (root) => root,
  );
  assert.deepStrictEqual(
    choices.map((c) => c.group),
    ['c', undefined],
  );
});

test('heads contests by the name the heading shows, not by their full path', () => {
  // `/z/alpha` and `/a/beta` head as `alpha` and `beta`; ordering by the full
  // root would print them the other way round.
  const choices = problemChoices(
    ['/z/alpha/A', '/a/beta/A'],
    new Map([
      ['/z/alpha/A', identity('A', 0, undefined, '/z/alpha')],
      ['/a/beta/A', identity('A', 0, undefined, '/a/beta')],
    ]),
    () => '',
  );
  assert.deepStrictEqual(
    choices.map((c) => c.group),
    ['alpha', 'beta'],
  );
});
