import * as assert from 'assert';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

import {
  FINDER_OUTCOMES,
  FinderRow,
  compileFinder,
  defaultOutcomeFor,
  finderPathProblem,
  recognizeFinder,
} from './finder';

const brk = (solution: string, outcome = 'INCORRECT'): FinderRow => ({
  kind: 'break',
  solution,
  outcome,
});
const disagree = (a: string, b: string): FinderRow => ({ kind: 'disagree', a, b });

test('rows compile to one expression, joined the way the toggle says', () => {
  const rows = [brk('sols/a.cpp', 'WRONG_ANSWER'), disagree('sols/b.cpp', 'sols/c.cpp')];
  assert.strictEqual(
    compileFinder(rows, 'all'),
    '[sols/a.cpp] ~ WRONG_ANSWER && [sols/b.cpp] != [sols/c.cpp]',
  );
  assert.strictEqual(
    compileFinder(rows, 'any'),
    '[sols/a.cpp] ~ WRONG_ANSWER || [sols/b.cpp] != [sols/c.cpp]',
  );
  assert.strictEqual(compileFinder([], 'all'), '');
});

test('a path using a character the grammar reserves is quoted; any other is not', () => {
  assert.strictEqual(compileFinder([brk('sols/my sol.cpp')], 'all'), '["sols/my sol.cpp"] ~ INCORRECT');
  for (const reserved of ['(', ')', '[', ']', '|', '&', '!', '~', '=', '$', '@', ':', '\t']) {
    const path = `sols/a${reserved}b.cpp`;
    assert.strictEqual(compileFinder([brk(path)], 'all'), `["${path}"] ~ INCORRECT`, path);
  }
  for (const plain of ['sols/a+b.cpp', 'sols/a,b#1%.cpp', 'sols/{x}.py']) {
    assert.strictEqual(compileFinder([brk(plain)], 'all'), `[${plain}] ~ INCORRECT`, plain);
  }
});

test('a path no finder can name is reported', () => {
  assert.strictEqual(finderPathProblem('sols/a.cpp'), undefined);
  assert.strictEqual(finderPathProblem('sols/a b.cpp'), undefined);
  assert.match(finderPathProblem('sols/a"b.cpp') ?? '', /double quote/);
  assert.match(finderPathProblem('sols/a\nb.cpp') ?? '', /line break/);
  assert.match(finderPathProblem('') ?? '', /solution/);
  assert.match(finderPathProblem("sols/it's.cpp") ?? '', /single quote/);
});

test('whatever compileFinder emits is recognized back', () => {
  const cases: { rows: FinderRow[]; join: 'all' | 'any' }[] = [
    { rows: [brk('sols/a.cpp', 'WRONG_ANSWER')], join: 'all' },
    { rows: [brk('sols/a.cpp'), brk('sols/b.cpp', 'TIME_LIMIT_EXCEEDED')], join: 'any' },
    { rows: [disagree('sols/a.cpp', 'sols/my sol.cpp'), brk('x$y.cpp', 'ACCEPTED_OR_TLE')], join: 'all' },
    { rows: [brk('sols/a.cpp', 'TLE_OR_RTE'), disagree('a', 'b'), brk('c', 'ANY')], join: 'any' },
  ];
  for (const { rows, join } of cases) {
    assert.deepStrictEqual(recognizeFinder(compileFinder(rows, join)), { rows, join });
  }
});

test('a bare path, bracketed or not, is a break row for INCORRECT', () => {
  const expected = { rows: [brk('sols/wa.cpp')], join: 'all' };
  assert.deepStrictEqual(recognizeFinder('sols/wa.cpp'), expected);
  assert.deepStrictEqual(recognizeFinder('[sols/wa.cpp]'), expected);
  assert.deepStrictEqual(recognizeFinder('  [ sols/wa.cpp ]  '), expected);
  assert.deepStrictEqual(recognizeFinder('"sols/w a.cpp"'), {
    rows: [brk('sols/w a.cpp')],
    join: 'all',
  });
});

test('quoted paths are read on either side of a row', () => {
  assert.deepStrictEqual(recognizeFinder('["a b.cpp"] ~ WA'), {
    rows: [brk('a b.cpp', 'WRONG_ANSWER')],
    join: 'all',
  });
  assert.deepStrictEqual(recognizeFinder('[a] != "b"'), {
    rows: [disagree('a', 'b')],
    join: 'all',
  });
});

test('a bare path under --slowest stands for ANY, which the caller can say', () => {
  assert.deepStrictEqual(recognizeFinder('[sols/wa.cpp]', 'ANY'), {
    rows: [brk('sols/wa.cpp', 'ANY')],
    join: 'all',
  });
});

test('an outcome is read the way rbx reads it, and written back as the member name', () => {
  assert.deepStrictEqual(recognizeFinder('[sols/a.cpp] ~ wa'), {
    rows: [brk('sols/a.cpp', 'WRONG_ANSWER')],
    join: 'all',
  });
  assert.deepStrictEqual(recognizeFinder('sols/a.cpp ~ ac+tle'), {
    rows: [brk('sols/a.cpp', 'ACCEPTED_OR_TLE')],
    join: 'all',
  });
});

test('anything the rows cannot express is not recognized', () => {
  for (const expr of [
    '',
    '   ',
    '[a] ~ WA && [b] ~ WA || [c]',
    '([a] ~ WA)',
    '!([a] ~ WA)',
    '[a] !~ WA',
    '[a] == [b]',
    '[a] != WA',
    '[a] != b',
    '[a ON checker.cpp] ~ WA',
    '[a ON 2:checker.cpp] ~ WA',
    '[a ON :nil]',
    '[$] ~ WA',
    '[@remote.cpp] ~ WA',
    '[a] ~ NOT_AN_OUTCOME',
    '[a] ~',
    '[a] &&',
    '&& [a]',
    '[a',
    '[a] [b]',
    '"unterminated',
    // The grammar ignores spaces, and nothing else.
    '[a]\t~ WA',
    '[a] ~ WA &&\n[b]',
  ]) {
    assert.strictEqual(recognizeFinder(expr), undefined, expr);
  }
});

test('the outcomes offered are exactly ExpectedOutcome, which the finder resolves', () => {
  const enums = JSON.parse(
    readFileSync(join(__dirname, '..', '..', 'src', 'rbx', 'rbxEnums.json'), 'utf8'),
  ) as { ExpectedOutcome: Record<string, unknown> };
  assert.deepStrictEqual([...FINDER_OUTCOMES].sort(), Object.keys(enums.ExpectedOutcome).sort());
});

test('a break row preselects what the solution declared, or INCORRECT for a correct one', () => {
  assert.strictEqual(defaultOutcomeFor(undefined), 'INCORRECT');
  assert.strictEqual(defaultOutcomeFor('ACCEPTED'), 'INCORRECT');
  assert.strictEqual(defaultOutcomeFor('ac'), 'INCORRECT');
  assert.strictEqual(defaultOutcomeFor('ANY'), 'INCORRECT');
  // INCORRECT would count the timeouts the declaration allows.
  assert.strictEqual(defaultOutcomeFor('ACCEPTED_OR_TLE'), 'WRONG_ANSWER');
  assert.strictEqual(defaultOutcomeFor('ac/tle'), 'WRONG_ANSWER');
  assert.strictEqual(defaultOutcomeFor('WRONG_ANSWER'), 'WRONG_ANSWER');
  assert.strictEqual(defaultOutcomeFor('wa'), 'WRONG_ANSWER');
  assert.strictEqual(defaultOutcomeFor('tle'), 'TIME_LIMIT_EXCEEDED');
  assert.strictEqual(defaultOutcomeFor('TLE_OR_RTE'), 'TLE_OR_RTE');
  assert.strictEqual(defaultOutcomeFor('fail'), 'INCORRECT');
  assert.strictEqual(defaultOutcomeFor('something newer'), 'INCORRECT');
});
