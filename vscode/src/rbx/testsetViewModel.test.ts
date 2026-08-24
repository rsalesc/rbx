import * as assert from 'assert';
import { test } from 'node:test';

import type { Testset, TestsetTest } from './testset';
import {
  TestsetRow,
  buildTestsetViewModel,
  testsetNodeId,
  testsetNodes,
} from './testsetViewModel';

// The fixtures transcribe a two-group package: a scored `main` built from a
// generator call and a generator script, and a `samples` group copied from
// files. One test in `main` was rejected by the validator and one carries a
// visualization, which are the two facts a row has marks for.

function entry(over: Record<string, unknown> = {}) {
  return {
    group: 'main',
    index: 0,
    inputPath: '/w/a/build/tests/main/1-gen-000.in',
    generatorName: 'gen',
    generatorArgs: '1000 7',
    ...over,
  } as Testset['entries'][number];
}

function testFor(over: Partial<TestsetTest> = {}): TestsetTest {
  return { group: 'main', index: 0, inputSize: 4211, outputSize: 12, ...over };
}

const TESTSET: Testset = {
  version: 1,
  taskType: 'BATCH',
  groups: [
    { name: 'samples', score: 0, deps: [], subgroups: [], vars: {} },
    { name: 'main', score: 60, deps: ['samples'], subgroups: [], vars: { n: 1000 } },
    { name: 'big', score: 40, deps: [], subgroups: [], vars: {} },
  ],
  entries: [
    entry({
      group: 'samples',
      index: 0,
      inputPath: '/w/a/build/tests/samples/000.in',
      generatorName: undefined,
      generatorArgs: undefined,
      copiedFrom: 'tests/samples/000.in',
    }),
    entry(),
    entry({
      index: 1,
      inputPath: '/w/a/build/tests/main/1-gen-001.in',
      generatorScript: 'gens/script.txt',
      generatorScriptLine: 12,
    }),
    entry({ group: 'big', index: 0, inputPath: '/w/a/build/tests/big/2-gen-000.in' }),
  ],
  tests: [
    testFor({ group: 'samples', index: 0, inputSize: 12, outputSize: 4 }),
    testFor({
      validation: { ok: true, validator: 'validator.cpp' },
      visualization: { input: 'build/tests/main/visualization/1-gen-000.svg' },
    }),
    testFor({
      index: 1,
      validation: { ok: false, validator: 'validator.cpp', message: 'n must be at most 100' },
    }),
    testFor({ group: 'big', index: 0 }),
  ],
  validation: [{ group: 'main', validator: 'validator.cpp', bounds: {} }],
};

function rowById(rows: readonly TestsetRow[], id: string): TestsetRow {
  const row = rows.find((candidate) => candidate.id === id);
  assert.ok(row !== undefined, `no row ${id} among ${rows.map((r) => r.id).join(', ')}`);
  return row;
}

test('every group is a row, with its tests under it in manifest order', () => {
  const { rows } = buildTestsetViewModel(TESTSET);
  assert.deepStrictEqual(
    rows.map((row) => row.id),
    [
      'samples',
      'samples::000',
      'main',
      'main::1-gen-000',
      'main::1-gen-001',
      'big',
      'big::2-gen-000',
    ],
  );
  assert.deepStrictEqual(
    rows.map((row) => [row.kind, row.depth, row.parentId]),
    [
      ['group', 0, undefined],
      ['testcase', 1, 'samples'],
      ['group', 0, undefined],
      ['testcase', 1, 'main'],
      ['testcase', 1, 'main'],
      ['group', 0, undefined],
      ['testcase', 1, 'big'],
    ],
  );
});

test('a group row carries its share of the score and how many tests it holds', () => {
  const { rows } = buildTestsetViewModel(TESTSET);
  assert.deepStrictEqual(rowById(rows, 'main').meta, [
    { text: '[60/100]', hue: 'dim', role: 'score' },
    { text: '2 tests', hue: 'dim', role: 'count' },
  ]);
  // The score comes first so the responsive ladder only ever hides a suffix of
  // the line -- see the container queries in style.css.
  assert.deepStrictEqual(rowById(rows, 'main').meta[0].role, 'score');
  // A zero score is nothing to say, not `[0/100]`.
  assert.deepStrictEqual(rowById(rows, 'samples').meta, [
    { text: '1 test', hue: 'dim', role: 'count' },
  ]);
});

test('a testset with no scores shows no score span at all', () => {
  const unscored: Testset = {
    ...TESTSET,
    groups: TESTSET.groups.map((group) => ({ ...group, score: undefined })),
  };
  const { rows } = buildTestsetViewModel(unscored);
  assert.ok(rows.every((row) => row.meta.every((span) => span.role !== 'score')));
});

test('a testcase row carries its input size and nothing else on the meta line', () => {
  const { rows } = buildTestsetViewModel(TESTSET);
  assert.deepStrictEqual(rowById(rows, 'main::1-gen-000').meta, [
    { text: '4 KiB', hue: 'dim', role: 'size' },
  ]);
});

test('the marks say what a row has and what is wrong with it', () => {
  const { rows } = buildTestsetViewModel(TESTSET);
  assert.deepStrictEqual(
    rowById(rows, 'main::1-gen-000').flags.map((flag) => flag.kind),
    ['visualization'],
  );
  const rejected = rowById(rows, 'main::1-gen-001').flags;
  assert.deepStrictEqual(rejected.map((flag) => flag.kind), ['invalid']);
  // The validator's own sentence is the hover: there is nowhere on a 22px row
  // for it, and the card repeats it in full.
  assert.strictEqual(rejected[0].title, 'n must be at most 100');
  assert.strictEqual(rejected[0].hue, 'red');
  // A test that passed validation carries no mark at all.
  assert.deepStrictEqual(rowById(rows, 'big::2-gen-000').flags, []);
});

test('a group warns when any of its tests was rejected', () => {
  const { rows } = buildTestsetViewModel(TESTSET);
  assert.deepStrictEqual(rowById(rows, 'main').flags.map((flag) => flag.kind), ['invalid']);
  assert.strictEqual(
    rowById(rows, 'main').flags[0].title,
    '1 test in this group was rejected by the validator.',
  );
  assert.deepStrictEqual(rowById(rows, 'samples').flags, []);
});

test('the haystack carries what the TUI searches, lowercased and deduplicated', () => {
  const { rows } = buildTestsetViewModel(TESTSET);
  const search = rowById(rows, 'main::1-gen-000').search;
  assert.ok(search.includes('main/1-gen-000'), search);
  assert.ok(search.includes('gen 1000 7'), search);
  assert.ok(search.includes('visualization'), search);
  assert.ok(!search.includes('invalid'), search);
  // The script's `path:line`, the same spelling the card and the opener use.
  assert.ok(rowById(rows, 'main::1-gen-001').search.includes('gens/script.txt:12'));
  assert.ok(rowById(rows, 'main::1-gen-001').search.includes('invalid'));
  // Copied-from is a path the setter typed, and typing it should find the test.
  assert.ok(rowById(rows, 'samples::000').search.includes('tests/samples/000.in'));
});

test('the card carries provenance, sizes and what the validator said', () => {
  const { rows } = buildTestsetViewModel(TESTSET);
  const card = rowById(rows, 'main::1-gen-001').card;
  assert.ok(card !== undefined);
  assert.strictEqual(card.title, 'main/1-gen-001');
  assert.deepStrictEqual(card.origins, [
    { text: 'gen 1000 7', title: 'Generated by gen 1000 7' },
    {
      text: 'gens/script.txt:12',
      open: 'rbx.openGeneratorScript',
      title: 'Generated from gens/script.txt:12',
    },
  ]);
  assert.deepStrictEqual(card.values, [
    { label: 'Input', text: '4 KiB' },
    { label: 'Answer', text: '12 B' },
  ]);
  assert.deepStrictEqual(card.validation, {
    ok: false,
    hue: 'red',
    text: 'Rejected by the validator',
    validator: 'validator.cpp',
    message: 'n must be at most 100',
  });
  assert.strictEqual(card.visualization, undefined);
});

test('a copied-from card offers the file it was copied from, first', () => {
  const { rows } = buildTestsetViewModel(TESTSET);
  assert.deepStrictEqual(rowById(rows, 'samples::000').card?.origins, [
    {
      text: 'tests/samples/000.in',
      open: 'rbx.openCopiedFrom',
      title: 'Copied from tests/samples/000.in',
    },
  ]);
});

test('a group row has no card: the card describes a testcase', () => {
  const { rows } = buildTestsetViewModel(TESTSET);
  assert.strictEqual(rowById(rows, 'main').card, undefined);
});

test('the header states the size and when it was built, and claims nothing else', () => {
  const built = Date.parse('2026-08-24T12:00:00Z');
  const model = buildTestsetViewModel(TESTSET, {
    builtAt: built,
    now: built + 3 * 60 * 1000 + 20_000,
  });
  assert.deepStrictEqual(model.header, { built: 'built 3m ago', summary: '4 tests · 3 groups' });
  // No mtime to read is no claim at all, rather than a guess.
  assert.strictEqual(buildTestsetViewModel(TESTSET).header?.built, undefined);
});

test('the relative time is coarse, and never counts seconds', () => {
  const at = Date.parse('2026-08-24T12:00:00Z');
  const built = (elapsed: number): string | undefined =>
    buildTestsetViewModel(TESTSET, { builtAt: at, now: at + elapsed }).header?.built;
  assert.strictEqual(built(5_000), 'built just now');
  assert.strictEqual(built(90 * 60 * 1000), 'built 1h ago');
  assert.strictEqual(built(50 * 60 * 60 * 1000), 'built 2d ago');
});

test('no manifest is the empty state, with nothing to summarize', () => {
  const model = buildTestsetViewModel(undefined);
  assert.deepStrictEqual(model, { rows: [], empty: true });
});

test('a manifest with no tests is not the empty state', () => {
  // Built, and empty: telling the reader to run a build that has already run
  // would send them to fix the wrong thing.
  const model = buildTestsetViewModel({ groups: [], entries: [], tests: [] });
  assert.strictEqual(model.empty, false);
  assert.deepStrictEqual(model.rows, []);
  assert.strictEqual(model.header?.summary, '0 tests · 0 groups');
});

test('a build with -v0 says nothing about validation anywhere in the tree', () => {
  // `validation: undefined` is "never computed", which is a different thing
  // from "computed and nothing failed" -- and neither draws a mark, because
  // per-test verdicts are the `tests` list's business and it has none here.
  const unvalidated: Testset = {
    ...TESTSET,
    validation: undefined,
    tests: TESTSET.tests.map((test) => ({ ...test, validation: undefined })),
  };
  const { rows } = buildTestsetViewModel(unvalidated);
  assert.ok(rows.every((row) => row.flags.every((flag) => flag.kind !== 'invalid')));
  assert.strictEqual(rowById(rows, 'main::1-gen-001').card?.validation, undefined);
});

test('an entry the tests list does not cover still gets a row', () => {
  // What a subset build, or an older rbx, leaves behind: the two halves of the
  // manifest fail independently, so a row draws whatever it has.
  const partial: Testset = { ...TESTSET, tests: [] };
  const { rows } = buildTestsetViewModel(partial);
  const row = rowById(rows, 'main::1-gen-000');
  assert.deepStrictEqual(row.meta, []);
  assert.deepStrictEqual(row.flags, []);
  assert.deepStrictEqual(row.card?.values, []);
  assert.strictEqual(row.card?.validation, undefined);
  // The provenance survives, because it rides on the entry rather than the
  // extras.
  assert.strictEqual(row.card?.origins.length, 1);
});

test('a group only the entries mention is drawn after the declared ones', () => {
  const merged: Testset = {
    ...TESTSET,
    groups: TESTSET.groups.filter((group) => group.name !== 'big'),
  };
  const { rows } = buildTestsetViewModel(merged);
  assert.deepStrictEqual(
    rows.filter((row) => row.kind === 'group').map((row) => row.id),
    ['samples', 'main', 'big'],
  );
  // With no declaration there is no score to state, only a count.
  assert.deepStrictEqual(rowById(rows, 'big').meta, [
    { text: '1 test', hue: 'dim', role: 'count' },
  ]);
});

test('a tests row naming an entry that is not there is ignored, not drawn', () => {
  const orphaned: Testset = {
    ...TESTSET,
    tests: [...TESTSET.tests, { group: 'ghost', index: 9, inputSize: 1 }],
  };
  const { rows } = buildTestsetViewModel(orphaned);
  assert.ok(!rows.some((row) => row.id.startsWith('ghost')));
});

test('nodes and rows share one walk, so every row id resolves to a node', () => {
  const { rows } = buildTestsetViewModel(TESTSET);
  const nodes = new Map(
    testsetNodes({ root: '/w/a' }, TESTSET).map((node) => [testsetNodeId(node), node]),
  );
  assert.deepStrictEqual([...nodes.keys()], rows.map((row) => row.id));
  const node = nodes.get('main::1-gen-001');
  assert.strictEqual(node?.kind, 'testsetTestcase');
  assert.strictEqual(node.kind === 'testsetTestcase' ? node.stem : '', '1-gen-001');
  assert.strictEqual(
    node.kind === 'testsetTestcase' ? node.test?.validation?.ok : undefined,
    false,
  );
});

test('no manifest is no nodes', () => {
  assert.deepStrictEqual(testsetNodes({ root: '/w/a' }, undefined), []);
});

test('every testcase row opens the two panes, and no group row opens anything', () => {
  const { rows } = buildTestsetViewModel(TESTSET);
  for (const row of rows) {
    assert.strictEqual(
      row.primaryCommand,
      row.kind === 'testcase' ? 'rbx.openBuiltTestcase' : undefined,
    );
    assert.strictEqual(row.expandable, row.kind === 'group');
    assert.strictEqual(
      row.section,
      row.kind === 'group' ? 'rbx.testsetGroup' : 'rbx.testsetTestcase',
    );
  }
});
