/**
 * The store against an ad-hoc run on disk, laid out as `rbx irun` writes it
 * (#907): its own root under `runs/.irun`, no group level under a solution,
 * and the one testcase's input copied into `.irun/inputs`.
 */
import * as assert from 'assert';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { test } from 'node:test';

import { planRefresh } from './artifactEvents';
import { Limiter, YamlFileCache } from './fileReader';
import { packageLayout } from './layout';
import { ArtifactStore } from './store';

function irunDir(root: string): string {
  return path.join(root, '.rbx', 'runs', '.irun');
}

/** What `rbx irun -t samples/1` leaves behind, two solutions, one finished. */
function makeAdhocRun(): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rbx-irun-'));
  const irun = irunDir(root);
  fs.mkdirSync(path.join(irun, 'inputs'), { recursive: true });
  fs.writeFileSync(
    path.join(irun, 'skeleton.yml'),
    [
      'solutions:',
      '  - {path: sols/main.cpp, outcome: ACCEPTED}',
      '  - {path: sols/wa.cpp, outcome: WRONG_ANSWER}',
      'groups: []',
      'entries:',
      '  - group_entry: {group: samples, index: 1}',
      '    subgroup_entry: {group: samples, index: 1}',
      '    metadata:',
      '      copied_to: {inputPath: .rbx/runs/.irun/inputs/000.in}',
      '',
    ].join('\n'),
  );
  fs.writeFileSync(
    path.join(irun, 'report.yml'),
    [
      'version: 1',
      'solutions:',
      '  - path: sols/main.cpp',
      '    index: 0',
      '    status: OK',
      '    matchesExpectation: true',
      '    outcome: ACCEPTED',
      '    groups:',
      '      - {name: samples, outcome: ACCEPTED, matchesExpectation: true, score: 0, maxScore: 0}',
      '',
    ].join('\n'),
  );
  writeEval(root, 0, 'ACCEPTED');
  return root;
}

function writeEval(root: string, solution: number, outcome: string): void {
  const dir = path.join(irunDir(root), String(solution));
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, '000.eval'), `result: {outcome: ${outcome}}\nlog: {time: 0.01}\n`);
}

function setup() {
  const root = makeAdhocRun();
  const store = new ArtifactStore(packageLayout(root, 'build'), {
    files: new YamlFileCache(new Limiter(4)),
  });
  return { root, store };
}

test('an ad-hoc run reads through the same model as a run', async () => {
  const { root, store } = setup();

  const run = await store.load('irun');

  assert.deepStrictEqual(
    run?.solutions.map((s) => s.solution.path),
    ['sols/main.cpp', 'sols/wa.cpp'],
  );
  const [main, wa] = run?.solutions ?? [];
  assert.strictEqual(main.report?.outcome, 'ACCEPTED');
  assert.strictEqual(main.groups[0].name, 'samples');
  const testcase = main.groups[0].testcases[0];
  assert.strictEqual(testcase.evaluation?.outcome, 'ACCEPTED');
  // Not under `<build>/tests/samples`, and no group level under the solution.
  assert.strictEqual(testcase.inputPath, path.join(irunDir(root), 'inputs', '000.in'));
  assert.strictEqual(testcase.answerPath, path.join(irunDir(root), 'inputs', '000.out'));
  assert.strictEqual(testcase.outputPath, path.join(irunDir(root), '0', '000.out'));
  // The second solution has not finished: no verdict, no report.
  assert.strictEqual(wa.groups[0].testcases[0].evaluation, undefined);
  assert.strictEqual(wa.report, undefined);
});

test('an ad-hoc run is not the main run, and the other way round', async () => {
  const { store } = setup();

  assert.strictEqual(await store.load('run'), undefined);
  assert.notStrictEqual(await store.load('irun'), undefined);
});

test('an irun event re-reads the ad-hoc run, even a verdict rewritten in place', async () => {
  const { root, store } = setup();
  const before = await store.load('irun');
  assert.strictEqual(before?.solutions[1].groups[0].testcases[0].evaluation, undefined);

  writeEval(root, 1, 'WRONG_ANSWER');
  // The same path, rewritten: the cached parse of the first must not survive.
  writeEval(root, 0, 'TIME_LIMIT_EXCEEDED');
  store.apply(planRefresh([{ kind: 'irun', started: false }]));
  const after = await store.load('irun');

  assert.strictEqual(after?.solutions[0].groups[0].testcases[0].evaluation?.outcome, 'TIME_LIMIT_EXCEEDED');
  assert.strictEqual(after?.solutions[1].groups[0].testcases[0].evaluation?.outcome, 'WRONG_ANSWER');
});

test('an event about the main run keeps the ad-hoc run cached', async () => {
  const { store } = setup();
  const first = store.load('irun');

  store.apply(planRefresh([{ kind: 'skeleton' }]));

  assert.strictEqual(store.load('irun'), first);
});
