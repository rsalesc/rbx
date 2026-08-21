import * as assert from 'assert';
import { test } from 'node:test';

import { parseContest } from './contest';

test('parses declared problems in file order', () => {
  const contest = parseContest({
    problems: [
      { short_name: 'A', color: '#ff0000' },
      { short_name: 'B', path: 'problems/beta' },
    ],
  });
  assert.deepStrictEqual(contest, {
    useVariants: false,
    problems: [
      { shortName: 'A', path: 'A', color: '#ff0000', order: 0 },
      { shortName: 'B', path: 'problems/beta', color: undefined, order: 1 },
    ],
  });
});

test('defaults a problem path to its short name', () => {
  const contest = parseContest({ problems: [{ short_name: 'C' }] });
  assert.strictEqual(contest.problems[0].path, 'C');
});

test('reports a dispatcher as declaring no problems', () => {
  assert.deepStrictEqual(parseContest({ use_variants: true }), {
    useVariants: true,
    problems: [],
  });
});

test('tolerates a file that is not a contest at all', () => {
  // Never throws: the walk in contestIndex reads whatever it finds, and a
  // malformed file must degrade to "no identity", not take the view down.
  for (const raw of [undefined, null, 'a string', 42, {}, { problems: 'not a list' }]) {
    assert.deepStrictEqual(parseContest(raw), { useVariants: false, problems: [] });
  }
});

test('skips entries with no usable short name', () => {
  const contest = parseContest({ problems: [{ color: '#fff' }, { short_name: 'B' }] });
  assert.deepStrictEqual(
    contest.problems.map((p) => p.shortName),
    ['B'],
  );
});

test('numbers order by surviving position, not by input index', () => {
  // `order` drives display order downstream, so a skipped entry must not leave
  // a hole that sorts a later problem into the wrong slot.
  const contest = parseContest({ problems: [{}, { short_name: 'A' }, { short_name: 'B' }] });
  assert.deepStrictEqual(
    contest.problems.map((p) => p.order),
    [0, 1],
  );
});
