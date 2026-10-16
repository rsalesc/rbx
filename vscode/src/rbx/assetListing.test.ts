import * as assert from 'assert';
import { test } from 'node:test';

import {
  ASSET_LISTING_VERSION,
  assetListingArgs,
  assetNodes,
  parseAssetListing,
  problemLabel,
  problemSlots,
  slotCatalog,
} from './assetListing';

const PAYLOAD = {
  version: ASSET_LISTING_VERSION,
  scope: 'contest',
  contest: {
    root: '/c',
    manifest: '/c/contest.rbx.yml',
    variant: null,
    title: 'Finals',
    assets: [{ category: 'manifest', path: '/c/contest.rbx.yml', detail: {} }],
  },
  problems: [
    {
      short_name: 'A',
      name: 'cats',
      title: null,
      root: '/c/A',
      error: null,
      assets: [
        { category: 'manifest', path: '/c/A/problem.rbx.yml', detail: {} },
        { category: 'testplan', path: '/c/A/plan.txt', detail: { group: 'main' } },
        { category: 'solution', path: '/c/A/sols/wa.cpp', detail: { outcome: 'WRONG_ANSWER' } },
        { category: 'statement', path: '/c/A/st.tex', detail: { kind: 'statement', language: 'en', type: 'rbxTeX' } },
        { category: 'manual_test', path: '/c/A/manual/1.in', detail: { group: 'samples' } },
        { category: 'manual_test', path: '/c/A/manual/2.in', detail: { group: 'samples' } },
        { category: 'bogus', path: '/c/A/x', detail: {} },
      ],
    },
    { short_name: 'B', name: null, root: '/c/B', error: 'broken yaml', assets: [] },
  ],
  sources: ['/c/contest.rbx.yml', '/c/A/problem.rbx.yml'],
};

test('reads the listing and skips unknown categories', () => {
  const listing = parseAssetListing(`noise\n${JSON.stringify(PAYLOAD)}`);
  assert.ok(listing);
  assert.strictEqual(listing.contest?.title, 'Finals');
  assert.strictEqual(listing.contest?.variant, undefined);
  assert.strictEqual(listing.problems.length, 2);
  assert.strictEqual(listing.problems[0].assets.length, 6);
  assert.strictEqual(listing.problems[1].error, 'broken yaml');
  assert.strictEqual(problemLabel(listing.problems[0]), 'A · cats');
  assert.strictEqual(problemLabel(listing.problems[1]), 'B · B');
});

test('refuses an unknown version', () => {
  assert.strictEqual(parseAssetListing(JSON.stringify({ ...PAYLOAD, version: 99 })), undefined);
});

test('passes the variant to the contest command only', () => {
  assert.deepStrictEqual(assetListingArgs('problem', 'x'), ['assets', '--json']);
  assert.deepStrictEqual(assetListingArgs('contest'), ['contest', 'assets', '--json']);
  assert.deepStrictEqual(assetListingArgs('contest', 'finals'), ['contest', '-C', 'finals', 'assets', '--json']);
});

test('split mode: manifest on top, then categories in order, manual tests by directory', () => {
  const listing = parseAssetListing(JSON.stringify(PAYLOAD));
  assert.ok(listing);
  const nodes = assetNodes('p', listing.problems[0].assets, '/c/A', 'split');
  assert.deepStrictEqual(
    nodes.map((node) => [node.label, node.description]),
    [
      ['problem.rbx.yml', ''],
      ['Statements', 'en'],
      ['Solutions', ''],
      ['Tests', '1 testplan · 2 manual'],
    ],
  );
  const tests = nodes[3];
  assert.ok(tests.kind === 'category');
  assert.deepStrictEqual(
    tests.children.map((node) => [node.label, node.description]),
    [
      ['plan.txt', 'group main'],
      ['manual/', '2 manual · group samples'],
    ],
  );
  const solutions = nodes[2];
  assert.ok(solutions.kind === 'category');
  assert.strictEqual(solutions.children[0].description, 'expects WA');
});

test('flat mode: one row per asset, role first, sorted by category', () => {
  const listing = parseAssetListing(JSON.stringify(PAYLOAD));
  assert.ok(listing);
  const nodes = assetNodes('p', listing.problems[0].assets, '/c/A', 'flat');
  assert.deepStrictEqual(
    nodes.map((node) => [node.label, node.description]),
    [
      ['problem.rbx.yml', ''],
      ['st.tex', 'statement · en · rbxTeX'],
      ['sols/wa.cpp', 'solution · expects WA'],
      ['plan.txt', 'testplan · group main'],
      ['manual/1.in', 'manual test · group samples'],
      ['manual/2.in', 'manual test · group samples'],
    ],
  );
});

test('slots: line up the same asset across problems, main ones only', () => {
  const listing = parseAssetListing(
    JSON.stringify({
      ...PAYLOAD,
      problems: [
        {
          short_name: 'A',
          root: '/c/A',
          assets: [
            { category: 'statement', path: '/c/A/en.tex', detail: { kind: 'statement', language: 'en', variant: 'default' } },
            { category: 'statement', path: '/c/A/pt.tex', detail: { kind: 'statement', language: 'pt', variant: 'default' } },
            { category: 'solution', path: '/c/A/main.cpp', detail: { outcome: 'ACCEPTED', main: true } },
            { category: 'solution', path: '/c/A/wa.cpp', detail: { outcome: 'WRONG_ANSWER' } },
            { category: 'checker', path: '/c/A/checker.cpp', detail: {} },
          ],
        },
        {
          short_name: 'B',
          root: '/c/B',
          assets: [
            { category: 'statement', path: '/c/B/en.tex', detail: { kind: 'statement', language: 'en', variant: 'default' } },
            { category: 'statement', path: '/c/B/ed.tex', detail: { kind: 'tutorial', language: 'en', variant: 'default' } },
            { category: 'solution', path: '/c/B/main.py', detail: { outcome: 'ACCEPTED', main: true } },
          ],
        },
      ],
    }),
  );
  assert.ok(listing);
  assert.deepStrictEqual(
    slotCatalog(listing.problems).map((entry) => [entry.slot.label, entry.count]),
    [
      ['en statement', 2],
      ['pt statement', 1],
      ['en editorial', 1],
      ['Main solution', 2],
      ['Checker', 1],
    ],
  );
  assert.strictEqual(problemSlots(listing.problems[1]).get('solution:main')?.path, '/c/B/main.py');
  assert.strictEqual(problemSlots(listing.problems[1]).get('checker'), undefined);
});
