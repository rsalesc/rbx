import * as assert from 'assert';
import { test } from 'node:test';

import { ListedProblem } from './assetListing';
import { globPattern } from './globPattern';
import { Declaration, GlobRule, mergeListed } from './listedDeclarations';

const ROOT = '/c/A';

const rules: GlobRule[] = [
  {
    root: ROOT,
    asset: { path: 'solutions/good/*reference*.*', role: 'solution', expectation: 'ACCEPTED', score: [100, 100] },
    pattern: globPattern('/c/A/solutions/good/*reference*.*'),
  },
  {
    root: ROOT,
    asset: { path: 'solutions/good/*.*', role: 'solution', expectation: 'ACCEPTED' },
    pattern: globPattern('/c/A/solutions/good/*.*'),
  },
  {
    root: ROOT,
    asset: { path: 'solutions/wrong/*.*', role: 'solution', expectation: 'INCORRECT' },
    pattern: globPattern('/c/A/solutions/wrong/*.*'),
  },
];

const problem: ListedProblem = {
  shortName: 'A',
  root: ROOT,
  assets: [
    { category: 'manifest', path: '/c/A/problem.rbx.yml', detail: {} },
    { category: 'solution', path: '/c/A/solutions/good/reference.cpp', detail: { outcome: 'ACCEPTED', main: 'true' } },
    { category: 'solution', path: '/c/A/solutions/wrong/greedy.cpp', detail: { outcome: 'INCORRECT' } },
    { category: 'validator', path: '/c/A/validators/common-lines.py', detail: {} },
    { category: 'testplan', path: '/c/A/attic/testplan.txt', detail: { group: 'testplan', main: 'true' } },
    { category: 'checker', path: '/c/A/judge/wcmp.cpp', detail: {} },
  ],
};

test('a globbed file takes the first matching entry, with its own path', () => {
  const merged = mergeListed(new Map(), rules, [problem]);
  assert.deepStrictEqual(merged.get('/c/A/solutions/good/reference.cpp'), {
    root: ROOT,
    asset: { path: 'solutions/good/reference.cpp', role: 'solution', expectation: 'ACCEPTED', score: [100, 100] },
  });
  assert.strictEqual(merged.get('/c/A/solutions/wrong/greedy.cpp')?.asset.expectation, 'INCORRECT');
});

test('a file no glob explains is declared from what rbx said', () => {
  const merged = mergeListed(new Map(), rules, [problem]);
  assert.deepStrictEqual(merged.get('/c/A/validators/common-lines.py')?.asset, {
    path: 'validators/common-lines.py',
    role: 'validator',
  });
  assert.deepStrictEqual(merged.get('/c/A/attic/testplan.txt')?.asset, {
    path: 'attic/testplan.txt',
    role: 'generator',
    testplan: true,
  });
  assert.strictEqual(merged.has('/c/A/problem.rbx.yml'), false);
});

test("the manifest's exact declarations stand", () => {
  const exact: Declaration = { root: ROOT, asset: { path: 'judge/wcmp.cpp', role: 'checker' } };
  const merged = mergeListed(new Map([['/c/A/judge/wcmp.cpp', exact]]), rules, [problem]);
  assert.strictEqual(merged.get('/c/A/judge/wcmp.cpp'), exact);
});
