import * as assert from 'assert';
import { test } from 'node:test';

import {
  LISTING_VERSION,
  StatementListing,
  listingArgs,
  mergeStatementSources,
  parseStatementListing,
} from './statementListing';

const PROBLEM = {
  version: LISTING_VERSION,
  scope: 'problem',
  root: '/c/A',
  statements: [
    { kind: 'statement', language: 'en', variant: 'default', type: 'rbxTeX', file: '/c/A/st-en.tex', name: null, contest: null },
    { kind: 'tutorial', language: 'en', variant: 'default', type: 'rbxTeX', file: '/c/A/ed-en.tex', name: null, contest: null },
  ],
  sources: ['/c/A/problem.rbx.yml', '/c/contest.rbx.yml', '/c/shared.rbx.yml'],
};

test('a listing is read whole, with absent names and files reading as absent', () => {
  const listing = parseStatementListing(JSON.stringify(PROBLEM));
  assert.deepStrictEqual(listing, {
    scope: 'problem',
    root: '/c/A',
    statements: [
      { kind: 'statement', language: 'en', variant: 'default', file: '/c/A/st-en.tex' },
      { kind: 'tutorial', language: 'en', variant: 'default', file: '/c/A/ed-en.tex' },
    ],
    sources: ['/c/A/problem.rbx.yml', '/c/contest.rbx.yml', '/c/shared.rbx.yml'],
  });
});

test('noise before the payload and a cursor escape after it are tolerated', () => {
  const stdout = `activating venv {sic}\n${JSON.stringify(PROBLEM)}\n\u001b[?25h`;
  assert.strictEqual(parseStatementListing(stdout)?.root, '/c/A');
});

test('another version, scope or a single malformed entry reads as no listing', () => {
  assert.strictEqual(parseStatementListing(JSON.stringify({ ...PROBLEM, version: 2 })), undefined);
  assert.strictEqual(parseStatementListing(JSON.stringify({ ...PROBLEM, scope: 'preset' })), undefined);
  assert.strictEqual(
    parseStatementListing(
      JSON.stringify({ ...PROBLEM, statements: [...PROBLEM.statements, { kind: 'poster', language: 'en' }] }),
    ),
    undefined,
  );
  assert.strictEqual(parseStatementListing(JSON.stringify({ ...PROBLEM, sources: [1] })), undefined);
  assert.strictEqual(parseStatementListing('Error: No such command "ls".'), undefined);
});

test('the command asked depends on the scope', () => {
  assert.deepStrictEqual(listingArgs('problem'), ['statements', 'ls', '--json']);
  assert.deepStrictEqual(listingArgs('contest'), ['contest', 'statements', 'ls', '--json']);
});

const listing = (scope: 'problem' | 'contest', root: string, files: string[]): StatementListing => ({
  scope,
  root,
  statements: files.map((file) => ({ kind: 'statement', language: 'en', variant: 'default', file })),
  sources: [],
});

test("rbx's answer replaces the fallback for its root, and only for its root", () => {
  const merged = mergeStatementSources(
    [listing('problem', '/c/A', ['/c/A/st-en.tex'])],
    [
      // The template the manifest parse could not expand: superseded.
      { file: '/c/A/st-{lang}.tex', root: '/c/A' },
      // A package rbx did not answer for keeps its fallback.
      { file: '/c/B/st-en.tex', root: '/c/B' },
    ],
  );
  assert.deepStrictEqual([...merged.keys()].sort(), ['/c/A/st-en.tex', '/c/B/st-en.tex']);
  assert.deepStrictEqual(merged.get('/c/B/st-en.tex'), { root: '/c/B', scope: 'problem', kind: 'statement' });
});

test('a file both a problem and its contest list belongs to the problem', () => {
  const merged = mergeStatementSources(
    [listing('contest', '/c', ['/c/shared.tex', '/c/contest.tex']), listing('problem', '/c/A', ['/c/shared.tex'])],
    [],
  );
  assert.deepStrictEqual(merged.get('/c/shared.tex'), { root: '/c/A', scope: 'problem', kind: 'statement' });
  assert.deepStrictEqual(merged.get('/c/contest.tex'), { root: '/c', scope: 'contest', kind: 'statement' });
});
