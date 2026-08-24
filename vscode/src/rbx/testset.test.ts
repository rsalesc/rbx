import * as assert from 'assert';
import { test } from 'node:test';

import {
  boundsForGroup,
  orderedTestsetGroups,
  parseTestset,
  testcasesForGroup,
  testsetTestcases,
} from './testset';

// Same premise as model.test.ts: the extension and the installed `rbx-cp` drift
// independently, so every case below is a manifest this extension is the wrong
// age for. None of them may throw -- the Tests view emptying itself the day rbx
// grows a field is the failure being designed against.

function entry(group: string, index: number, stem: string) {
  return {
    group_entry: { group, index },
    metadata: { copied_to: { inputPath: `/abs/build/tests/${group}/${stem}.in` } },
  };
}

const FULL = {
  version: 1,
  task_type: 'BATCH',
  groups: [
    {
      name: 'samples',
      score: 0,
      deps: [],
      subgroups: [],
      vars: {},
    },
    {
      name: 'main',
      score: 100,
      deps: ['samples'],
      subgroups: ['1'],
      vars: { MAX_N: 100000, limits: { n: [1, 10] } },
    },
  ],
  entries: [entry('samples', 0, '000'), entry('main', 0, '1-gen-000')],
  tests: [
    {
      group: 'samples',
      index: 0,
      validation: { ok: true, validator: 'validator.cpp', message: null },
      input_size: 4,
      output_size: 2,
    },
    {
      group: 'main',
      index: 0,
      validation: { ok: false, validator: 'validator.cpp', message: 'n too large' },
      visualization: {
        input: 'build/tests/main/visualization/1-gen-000.svg',
        output: null,
      },
      input_size: 4211,
      output_size: 12,
    },
  ],
  validation: [
    {
      group: 'main',
      validator: 'validator.cpp',
      bounds: { n: [true, false], m: [true, true] },
    },
  ],
};

test('a well-formed manifest is read whole', () => {
  const testset = parseTestset(FULL);
  assert.strictEqual(testset?.version, 1);
  assert.strictEqual(testset?.taskType, 'BATCH');
  assert.deepStrictEqual(testset?.groups[1], {
    name: 'main',
    score: 100,
    deps: ['samples'],
    subgroups: ['1'],
    vars: { MAX_N: 100000, limits: { n: [1, 10] } },
  });
  assert.deepStrictEqual(testset?.entries.map((e) => [e.group, e.index]), [
    ['samples', 0],
    ['main', 0],
  ]);
  assert.deepStrictEqual(testset?.tests[1], {
    group: 'main',
    index: 0,
    validation: { ok: false, validator: 'validator.cpp', message: 'n too large' },
    // `output: null` is dropped rather than carried: YAML's null and a missing
    // key mean the same thing here, and the panel asks whether there is
    // something to show.
    visualization: {
      input: 'build/tests/main/visualization/1-gen-000.svg',
      output: undefined,
    },
    inputSize: 4211,
    outputSize: 12,
  });
  assert.deepStrictEqual(boundsForGroup(testset!, 'main')?.bounds, {
    n: { minHit: true, maxHit: false },
    m: { minHit: true, maxHit: true },
  });
});

test('entries carry the provenance the skeleton parser already reads', () => {
  const testset = parseTestset({
    ...FULL,
    entries: [
      {
        group_entry: { group: 'main', index: 0 },
        subgroup_entry: { group: '1' },
        metadata: {
          copied_to: { inputPath: '/abs/build/tests/main/1-gen-000.in' },
          generator_call: { name: 'gen', args: '10 20' },
          generator_script: { path: 'gen.txt', line: 3 },
        },
      },
    ],
  });
  assert.deepStrictEqual(testset?.entries[0], {
    group: 'main',
    index: 0,
    subgroup: '1',
    inputPath: '/abs/build/tests/main/1-gen-000.in',
    outputPath: undefined,
    generatorName: 'gen',
    generatorArgs: '10 20',
    copiedFrom: undefined,
    generatorScript: 'gen.txt',
    generatorScriptLine: 3,
  });
});

test('the join pairs each entry with its extras by group and index', () => {
  const testcases = testsetTestcases(parseTestset(FULL)!);
  assert.deepStrictEqual(
    testcases.map((testcase) => [testcase.stem, testcase.test?.inputSize]),
    [
      ['000', 4],
      ['1-gen-000', 4211],
    ],
  );
  assert.deepStrictEqual(
    testcasesForGroup(parseTestset(FULL)!, 'main').map((testcase) => testcase.stem),
    ['1-gen-000'],
  );
});

test('a validator that accepted leaves nothing to show', () => {
  // rbx dumps an empty message rather than omitting the key, and a row that
  // tested the field alone would offer an empty tooltip on every passing test.
  const testset = parseTestset({
    ...FULL,
    tests: [{ group: 'main', index: 0, validation: { ok: true, message: '' } }],
  });
  assert.deepStrictEqual(testset?.tests[0].validation, {
    ok: true,
    validator: undefined,
    message: undefined,
  });
});

test('an index colliding across groups does not cross the join', () => {
  // Indices restart per group, so a key of the index alone would hand
  // `samples[0]`'s size to `main[0]` -- a silently wrong row, which is the same
  // class of bug `entryStem` exists to prevent.
  const testcases = testsetTestcases(parseTestset(FULL)!);
  assert.strictEqual(testcases[0].test?.group, 'samples');
  assert.strictEqual(testcases[1].test?.group, 'main');
});

test('an entry with no matching test row still yields a testcase', () => {
  const testcases = testsetTestcases(parseTestset({ ...FULL, tests: [] })!);
  assert.deepStrictEqual(
    testcases.map((testcase) => [testcase.stem, testcase.test]),
    [
      ['000', undefined],
      ['1-gen-000', undefined],
    ],
  );
});

test('a manifest truncated mid-write reads as far as it got', () => {
  // What the watcher catches when it fires on a partially flushed file that
  // still happens to parse as YAML.
  const testset = parseTestset({
    version: 1,
    task_type: 'BATCH',
    groups: [{ name: 'main', score: 100 }],
    entries: [entry('main', 0, '1-gen-000')],
  });
  assert.deepStrictEqual(testset?.groups[0].deps, []);
  assert.deepStrictEqual(testset?.groups[0].subgroups, []);
  assert.deepStrictEqual(testset?.groups[0].vars, {});
  assert.deepStrictEqual(testset?.tests, []);
  assert.strictEqual(testset?.validation, undefined);
});

test('a build run with -v0 reports no coverage, which is not empty coverage', () => {
  assert.strictEqual(
    parseTestset({ ...FULL, validation: undefined })?.validation,
    undefined,
  );
  assert.deepStrictEqual(parseTestset({ ...FULL, validation: [] })?.validation, []);
});

test('fields of the wrong shape read as absent, taking nothing else with them', () => {
  const testset = parseTestset({
    version: '1',
    task_type: 42,
    groups: [
      { name: 'main', score: 'lots', deps: 'samples', subgroups: [1, '2'], vars: [] },
      { score: 100 },
    ],
    entries: [entry('main', 0, '1-gen-000'), { group_entry: { group: 'main' } }],
    tests: [
      { group: 'main', index: 0, validation: { ok: 'yes' }, input_size: '4211' },
      { index: 0 },
    ],
    validation: [
      { group: 'main', bounds: { n: [true, false], m: true, k: [true], j: ['x', 'y'] } },
      { bounds: {} },
    ],
  });
  assert.strictEqual(testset?.version, undefined);
  assert.strictEqual(testset?.taskType, undefined);
  assert.deepStrictEqual(testset?.groups, [
    { name: 'main', score: undefined, deps: [], subgroups: ['2'], vars: {} },
  ]);
  assert.deepStrictEqual(testset?.entries.map((e) => e.index), [0]);
  assert.deepStrictEqual(testset?.tests, [
    {
      group: 'main',
      index: 0,
      validation: undefined,
      visualization: undefined,
      inputSize: undefined,
      outputSize: undefined,
    },
  ]);
  assert.deepStrictEqual(testset?.validation, [
    {
      group: 'main',
      validator: undefined,
      bounds: { n: { minHit: true, maxHit: false } },
    },
  ]);
});

test('a manifest from a future version keeps what this reader knows', () => {
  const testset = parseTestset({
    version: 7,
    task_type: 'COMMUNICATION',
    interactor: { path: 'interactor.cpp' },
    groups: [{ name: 'main', score: 100, deps: [], subgroups: [], vars: {}, weight: 3 }],
    entries: [{ ...entry('main', 0, '1-gen-000'), origin: 'IMPORTED' }],
    tests: [{ group: 'main', index: 0, input_size: 10, checksum: 'deadbeef' }],
  });
  assert.strictEqual(testset?.version, 7);
  assert.strictEqual(testset?.taskType, 'COMMUNICATION');
  assert.strictEqual(testset?.groups[0].name, 'main');
  assert.strictEqual(testset?.tests[0].inputSize, 10);
  assert.deepStrictEqual(
    testsetTestcases(testset).map((testcase) => testcase.stem),
    ['1-gen-000'],
  );
});

test('a package that was never built reads as no testset at all', () => {
  // `readYamlFile` hands back undefined for a missing or half-written file, and
  // the store passes it straight through: absence is a state the view draws,
  // not an error it reports.
  assert.strictEqual(parseTestset(undefined), undefined);
  assert.strictEqual(parseTestset(null), undefined);
  assert.strictEqual(parseTestset(''), undefined);
  assert.strictEqual(parseTestset([]), undefined);
});

test('an empty manifest is a testset with nothing in it', () => {
  const testset = parseTestset({});
  assert.deepStrictEqual(testset, {
    version: undefined,
    taskType: undefined,
    groups: [],
    entries: [],
    tests: [],
    validation: undefined,
  });
  assert.deepStrictEqual(testsetTestcases(testset!), []);
  assert.deepStrictEqual(orderedTestsetGroups(testset!), []);
});

test('a subset build leaves groups only the entries still mention', () => {
  // `rbx build --groups main` merges rather than truncating, so the two lists
  // can disagree; neither is authoritative over the other.
  const testset = parseTestset({
    ...FULL,
    groups: [{ name: 'main', score: 100 }],
    entries: [entry('main', 0, '1-gen-000'), entry('extra', 0, '000')],
  });
  assert.deepStrictEqual(orderedTestsetGroups(testset!), ['main', 'extra']);
});
