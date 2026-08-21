import * as assert from 'assert';
import { test } from 'node:test';
import { parse as parseYaml } from 'yaml';

import {
  ParsedContest,
  isContestVariantFile,
  parseContest,
  problemIdentities,
} from './contest';

function contest(yaml: string): ParsedContest {
  return parseContest(parseYaml(yaml));
}

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
  // The problems are listed to pin the branch: rbx rejects this file outright,
  // and reading its list anyway would give a dispatcher directory letters that
  // belong to whichever variant is actually selected.
  assert.deepStrictEqual(parseContest({ use_variants: true, problems: [{ short_name: 'A' }] }), {
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

test('matches package roots to declared problems', () => {
  const identities = problemIdentities(
    '/c',
    parseContest({
      problems: [{ short_name: 'A' }, { short_name: 'B', path: 'problems/beta' }],
    }),
  );
  assert.deepStrictEqual(identities.get('/c/A'), {
    shortName: 'A',
    color: undefined,
    order: 0,
    contestRoot: '/c',
  });
  assert.deepStrictEqual(identities.get('/c/problems/beta'), {
    shortName: 'B',
    color: undefined,
    order: 1,
    // The contest that named it, even though it sits two levels down.
    contestRoot: '/c',
  });
});

test('normalizes a declared path before matching', () => {
  // Contest files are hand-written: `./A/` and `A` name the same directory.
  const identities = problemIdentities(
    '/c',
    parseContest({ problems: [{ short_name: 'A', path: './A/' }] }),
  );
  assert.strictEqual(identities.get('/c/A')?.shortName, 'A');
});

test('keeps the first of two problems naming the same directory', () => {
  // Duplicating a problem block is how a setter adds one, and the file is read
  // mid-keystroke -- before rbx has had any chance to reject the duplicate.
  const identities = problemIdentities(
    '/c',
    parseContest({
      problems: [{ short_name: 'A' }, { short_name: 'B', path: './A' }],
    }),
  );
  assert.strictEqual(identities.size, 1);
  assert.strictEqual(identities.get('/c/A')?.shortName, 'A');
});

test('declares nothing for a dispatcher', () => {
  assert.strictEqual(problemIdentities('/c', parseContest({ use_variants: true })).size, 0);
});

test('accepts exactly the variant filenames rbx would load', () => {
  // Variants merge first-wins in filename order, so a name rbx rejects does not
  // merely add noise -- `contest.div1.bak.rbx.yml` sorts before
  // `contest.div1.rbx.yml` and would hand the backup's letters to the contest.
  const accepted = [
    'contest.div1.rbx.yml',
    'contest.A.rbx.yml',
    'contest.a_b-c9.rbx.yml',
  ];
  const rejected = [
    'contest.rbx.yml', // The canonical, not a variant.
    'contest..rbx.yml', // Empty id; `.` sorts before every real sibling.
    'contest.div1.bak.rbx.yml', // A hand-made backup: `.` is not in the id set.
    'contest.9x.rbx.yml', // Leading digit.
    'contest.rbx.yml.bak', // Wrong suffix.
    'problem.rbx.yml',
  ];
  assert.deepStrictEqual(accepted.filter(isContestVariantFile), accepted);
  assert.deepStrictEqual(rejected.filter(isContestVariantFile), []);
});

/**
 * The shapes below come from YAML rather than object literals because they are
 * the ones only a real, hand-edited file produces: a key with nothing after it
 * parses as `null`, not as an absent key, and an unquoted letter-free
 * short_name arrives as a number.
 */
test('a key left blank reads as unset, not as a value', () => {
  const parsed = contest(`
problems:
  - short_name: A
    path:
    color:
`);
  assert.deepStrictEqual(parsed.problems, [
    { shortName: 'A', path: 'A', color: undefined, order: 0 },
  ]);
});

test('skips a short name YAML did not give us as a string', () => {
  const parsed = contest(`
problems:
  - short_name: 1
  - short_name: B
`);
  assert.deepStrictEqual(
    parsed.problems.map((p) => p.shortName),
    ['B'],
  );
});
