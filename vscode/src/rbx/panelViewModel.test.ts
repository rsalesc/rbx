import * as assert from 'assert';
import { test } from 'node:test';

import {
  buildPanelViewModel,
  cellForTestId,
  testcaseId,
  visualizationKind,
} from './panelViewModel';
import type { Testset, TestsetGroup, TestsetTest } from './testset';

// The fixtures are written as a parsed `Testset` rather than as YAML: what the
// bytes mean is testset.test.ts's contract, and going through the parser here
// would make these tests fail for its reasons.

function group(name: string, over: Partial<TestsetGroup> = {}): TestsetGroup {
  return { name, deps: [], subgroups: [], vars: {}, ...over };
}

function test_(group: string, index: number, over: Partial<TestsetTest> = {}): TestsetTest {
  return { group, index, ...over };
}

function testset(over: Partial<Testset> = {}): Testset {
  return { groups: [], entries: [], tests: [], ...over };
}

test('an unknown extension is offered as a file, never guessed at as an image', () => {
  assert.strictEqual(visualizationKind('build/tests/main/visualization/1.svg'), 'image');
  assert.strictEqual(visualizationKind('a/b/1.PNG'), 'image');
  assert.strictEqual(visualizationKind('a/b/1.jpeg'), 'image');
  assert.strictEqual(visualizationKind('a/b/1.webp'), 'image');
  assert.strictEqual(visualizationKind('a/b/1.html'), 'html');
  // The two that matter: a visualizer emitting anything else, and a file with
  // no extension at all.
  assert.strictEqual(visualizationKind('a/b/1.dat'), 'other');
  assert.strictEqual(visualizationKind('a/b/plot'), 'other');
  // A dotted directory must not lend its extension to an extensionless file.
  assert.strictEqual(visualizationKind('a.d/plot'), 'other');
});

test('the gallery carries one cell per channel, and counts the testcases with none', () => {
  const model = buildPanelViewModel(
    '/w/a',
    testset({
      groups: [group('main')],
      entries: [
        { group: 'main', index: 0, inputPath: '/w/a/build/tests/main/000.in' },
        { group: 'main', index: 1, inputPath: '/w/a/build/tests/main/001.in' },
      ],
      tests: [
        test_('main', 0, {
          visualization: {
            input: 'build/tests/main/visualization/000.svg',
            output: 'build/tests/main/visualization/000.out.txt',
          },
        }),
        test_('main', 1),
      ],
    }),
  );
  assert.deepStrictEqual(
    model.gallery.cells.map((cell) => [cell.id, cell.kind, cell.channel]),
    [
      ['main::000::input', 'image', 'input'],
      ['main::000::output', 'other', 'output'],
    ],
  );
  assert.strictEqual(model.gallery.withoutVisualization, 1);
});

test('a sidebar id finds the cell of the testcase it names', () => {
  const model = buildPanelViewModel(
    '/w/a',
    testset({
      groups: [group('samples'), group('main')],
      entries: [
        { group: 'samples', index: 0, inputPath: '/w/a/build/tests/samples/000.in' },
        { group: 'main', index: 0, inputPath: '/w/a/build/tests/main/000.in' },
      ],
      tests: [
        test_('samples', 0, { visualization: { input: 'v/s0.png' } }),
        test_('main', 0, { visualization: { input: 'v/m0.png' } }),
      ],
    }),
  );
  assert.strictEqual(model.gallery.cells.length, 2);
  // A testcase id without a channel resolves to the input picture, and one the
  // sidebar prefixed with its package root still lands.
  assert.strictEqual(
    cellForTestId(model.gallery, testcaseId('main', '000'))?.id,
    'main::000::input',
  );
  assert.strictEqual(
    cellForTestId(model.gallery, '/w/a::main::000')?.id,
    'main::000::input',
  );
  assert.strictEqual(cellForTestId(model.gallery, 'main::999'), undefined);
});

test('a build without validation says so rather than reporting empty coverage', () => {
  const model = buildPanelViewModel('/w/a', testset({ groups: [group('main')] }));
  assert.strictEqual(model.coverage.reported, false);
  assert.deepStrictEqual(model.coverage.rows, []);
  // And a validated build that found nothing is a *different* state.
  const validated = buildPanelViewModel('/w/a', testset({ validation: [] }));
  assert.strictEqual(validated.coverage.reported, true);
});

test('a variable hit in one group and missed in another is neither green nor a finding', () => {
  const model = buildPanelViewModel(
    '/w/a',
    testset({
      groups: [
        group('main', { vars: { n: 100000 } }),
        group('big', { vars: { n: 1000000, m: { max: 5 } } }),
      ],
      validation: [
        {
          group: 'main',
          validator: 'validator.cpp',
          bounds: { n: { minHit: true, maxHit: true }, m: { minHit: false, maxHit: false } },
        },
        {
          group: 'big',
          bounds: { n: { minHit: false, maxHit: true }, m: { minHit: false, maxHit: false } },
        },
      ],
    }),
  );
  const coverage = model.coverage;
  assert.deepStrictEqual(coverage.groups, ['main', 'big']);
  assert.deepStrictEqual(coverage.validators, ['validator.cpp', undefined]);
  assert.deepStrictEqual(
    coverage.rows.map((row) => [row.variable, row.cells.map((cell) => cell?.hue)]),
    [
      ['n', ['green', 'yellow']],
      ['m', ['red', 'red']],
    ],
  );
  // Each group's own declared value rides along, non-scalars as their JSON.
  assert.deepStrictEqual(
    coverage.rows[0].cells.map((cell) => cell?.value),
    ['100000', '1000000'],
  );
  assert.strictEqual(coverage.rows[1].cells[1]?.value, '{"max":5}');
  // Only `m` is never hit anywhere; `n` is hit in both, differently.
  assert.deepStrictEqual(coverage.neverHit, ['m']);
});

test('a group missing from the report gets no cell rather than a red one', () => {
  const model = buildPanelViewModel(
    '/w/a',
    testset({
      groups: [group('main'), group('big')],
      validation: [
        { group: 'main', bounds: { n: { minHit: true, maxHit: false } } },
        { group: 'big', bounds: { m: { minHit: true, maxHit: true } } },
      ],
    }),
  );
  assert.deepStrictEqual(
    model.coverage.rows.map((row) => [row.variable, row.cells.map((cell) => cell?.hue)]),
    [
      ['n', ['yellow', undefined]],
      ['m', [undefined, 'green']],
    ],
  );
  assert.deepStrictEqual(model.coverage.neverHit, []);
});

test('stats aggregate sizes from the manifest, and score against the testset total', () => {
  const model = buildPanelViewModel(
    '/w/a',
    testset({
      taskType: 'BATCH',
      groups: [
        group('samples', { score: 0 }),
        group('main', { score: 40, deps: ['samples'], subgroups: ['small', 'large'] }),
        group('big', { score: 60 }),
      ],
      entries: [
        { group: 'samples', index: 0, inputPath: '/w/a/build/tests/samples/000.in' },
        {
          group: 'main',
          index: 0,
          subgroup: 'small',
          inputPath: '/w/a/build/tests/main/000.in',
        },
        {
          group: 'main',
          index: 1,
          subgroup: 'small',
          inputPath: '/w/a/build/tests/main/001.in',
        },
        { group: 'big', index: 0, inputPath: '/w/a/build/tests/big/000.in' },
      ],
      tests: [
        test_('samples', 0, { inputSize: 12, outputSize: 4 }),
        test_('main', 0, { inputSize: 2048, outputSize: 100 }),
        test_('main', 1, { inputSize: 4096, outputSize: 200 }),
        // `big` has an entry but no stamped sizes: an rbx too old to write
        // them, which must read as "unknown" and not as zero.
        test_('big', 0),
      ],
    }),
  );
  assert.deepStrictEqual(
    model.stats.groups.map((stats) => [
      stats.group,
      stats.count,
      stats.score,
      stats.deps,
      stats.subgroups,
      stats.maxInput,
      stats.totalInput,
      stats.maxOutput,
    ]),
    [
      ['samples', 1, '[0/100]', [], [], '12 B', '12 B', '4 B'],
      [
        'main',
        2,
        '[40/100]',
        ['samples'],
        [
          { name: 'small', count: 2 },
          { name: 'large', count: 0 },
        ],
        '4 KiB',
        '6 KiB',
        '200 B',
      ],
      ['big', 1, '[60/100]', [], [], undefined, undefined, undefined],
    ],
  );
  assert.strictEqual(model.stats.count, 4);
  assert.strictEqual(model.stats.samples, 1);
  assert.strictEqual(model.stats.maxInput, '4 KiB');
  assert.strictEqual(model.stats.totalInput, '6 KiB');
  assert.strictEqual(model.taskType, 'BATCH');
});

test('a testset that scores nothing leaves the score column empty', () => {
  const model = buildPanelViewModel(
    '/w/a',
    testset({
      groups: [group('main', { score: 0 })],
      entries: [{ group: 'main', index: 0 }],
    }),
  );
  assert.strictEqual(model.stats.groups[0].score, undefined);
});

test('a group only the entries mention still gets a stats row', () => {
  // What a subset build leaves behind: the manifest's `groups` and `entries`
  // can legitimately disagree, and neither is authoritative.
  const model = buildPanelViewModel(
    '/w/a',
    testset({ groups: [group('main')], entries: [{ group: 'extra', index: 0 }] }),
  );
  assert.deepStrictEqual(
    model.stats.groups.map((stats) => stats.group),
    ['main', 'extra'],
  );
});

test('no manifest is an empty model, not a crash', () => {
  const model = buildPanelViewModel('/w/a', undefined);
  assert.strictEqual(model.empty, true);
  assert.strictEqual(model.root, '/w/a');
  assert.strictEqual(model.coverage.reported, false);
});
