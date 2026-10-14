/**
 * The store against a real package on disk, counting what it reads.
 *
 * The targets #902 set: one `.eval` landing reads one file, not the run; a
 * report landing reads no `.eval` at all; a read that fails is not pending.
 */
import * as assert from 'assert';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { test } from 'node:test';

import { planRefresh } from './artifactEvents';
import { Limiter, YamlFileCache } from './fileReader';
import { packageLayout } from './layout';
import { ArtifactStore, PackageRun } from './store';

const SOLUTIONS = 3;
const TESTS = 20;

function makePackage(): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rbx-store-'));
  const runs = path.join(root, '.rbx', 'runs');
  fs.mkdirSync(runs, { recursive: true });
  const solutions = Array.from(
    { length: SOLUTIONS },
    (_, i) => `  - path: sols/s${i}.cpp\n    outcome: ACCEPTED`,
  );
  const entries = Array.from(
    { length: TESTS },
    (_, i) => `  - group_entry: {group: main, index: ${i}}`,
  );
  fs.writeFileSync(
    path.join(runs, 'skeleton.yml'),
    [
      'solutions:',
      ...solutions,
      'groups:',
      '  - name: main',
      'entries:',
      ...entries,
      'compilation:',
      '  - {path: sols/s0.cpp, status: WARNINGS, log: compilation/0.log, warnings: []}',
      '',
    ].join('\n'),
  );
  return root;
}

function writeEval(root: string, solution: number, stem: string, outcome: string): void {
  const dir = path.join(root, '.rbx', 'runs', String(solution), 'main');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, `${stem}.eval`), `result: {outcome: ${outcome}}\nlog: {time: 0.01}\n`);
}

function setup() {
  const root = makePackage();
  const files = new YamlFileCache(new Limiter(4));
  const store = new ArtifactStore(packageLayout(root, 'build'), { files });
  return { root, files, store };
}

function testcase(run: PackageRun | undefined, solution: number, stem: string) {
  return run?.solutions[solution].groups[0].testcases.find((t) => t.stem === stem);
}

test('a first load reads every evaluation that is there', async () => {
  const { root, files, store } = setup();
  writeEval(root, 0, '000', 'accepted');

  const run = await store.load();

  assert.strictEqual(run?.solutions.length, SOLUTIONS);
  assert.strictEqual(testcase(run, 0, '000')?.evaluation?.outcome, 'accepted');
  assert.strictEqual(testcase(run, 0, '001')?.evaluation, undefined);
  assert.strictEqual(files.stats.reads, 1);
  assert.strictEqual(files.stats.missing, SOLUTIONS * TESTS - 1);
});

test('one evaluation landing reads that one file and patches that one testcase', async () => {
  const { root, files, store } = setup();
  const before = await store.load();
  const reads = files.stats.reads + files.stats.missing;

  writeEval(root, 1, '007', 'wrong-answer');
  store.apply(planRefresh([{ kind: 'eval', solution: 1, group: 'main', stem: '007' }]));
  const after = await store.load();

  assert.strictEqual(files.stats.reads + files.stats.missing - reads, 1);
  assert.strictEqual(testcase(after, 1, '007')?.evaluation?.outcome, 'wrong-answer');
  // Everything the event did not name is the very object it was.
  assert.strictEqual(after?.solutions[0], before?.solutions[0]);
  assert.strictEqual(after?.solutions[2], before?.solutions[2]);
  assert.strictEqual(testcase(after, 1, '006'), testcase(before, 1, '006'));
});

test('a report landing reads no evaluation, and carries the end of the run', async () => {
  const { root, files, store } = setup();
  const before = await store.load();
  const reads = files.stats.reads + files.stats.missing;

  fs.writeFileSync(
    path.join(root, '.rbx', 'runs', 'report.yml'),
    'version: 1\nsolutions: []\nfinished: true\nexitStatus: interrupted\n',
  );
  store.apply(planRefresh([{ kind: 'report' }]));
  const after = await store.load();

  assert.strictEqual(files.stats.reads + files.stats.missing, reads);
  assert.deepStrictEqual(after?.ended, { status: 'interrupted', endedAt: undefined });
  assert.strictEqual(after?.solutions[0], before?.solutions[0]);
});

test('patches arriving back to back all land', async () => {
  const { root, store } = setup();
  await store.load();

  for (const stem of ['000', '001', '002']) {
    writeEval(root, 0, stem, 'accepted');
    store.apply(planRefresh([{ kind: 'eval', solution: 0, group: 'main', stem }]));
  }
  const run = await store.load();

  for (const stem of ['000', '001', '002']) {
    assert.strictEqual(testcase(run, 0, stem)?.evaluation?.outcome, 'accepted', stem);
  }
});

test('a new skeleton reloads the run from scratch', async () => {
  const { root, store } = setup();
  writeEval(root, 0, '000', 'accepted');
  await store.load();

  fs.rmSync(path.join(root, '.rbx', 'runs', '0'), { recursive: true });
  store.apply(planRefresh([{ kind: 'skeleton' }]));

  assert.strictEqual(testcase(await store.load(), 0, '000')?.evaluation, undefined);
});

test('an evaluation that will not read is an error, not pending', async () => {
  const { root, store } = setup();
  // A directory where the file should be: it stats, and then cannot be read.
  fs.mkdirSync(path.join(root, '.rbx', 'runs', '0', 'main', '000.eval'), { recursive: true });

  const run = await store.load();

  assert.match(testcase(run, 0, '000')?.readError ?? '', /EISDIR/);
  assert.strictEqual(testcase(run, 0, '001')?.readError, undefined);
});

test('the compile findings come from the skeleton alone', async () => {
  const { root, files, store } = setup();
  writeEval(root, 0, '000', 'accepted');

  const findings = await store.findings();

  assert.deepStrictEqual(
    findings.map((finding) => finding.entry.path),
    ['sols/s0.cpp'],
  );
  assert.strictEqual(files.stats.reads + files.stats.missing, 0);
});

test('a rediscovery reuses every evaluation that did not change', async () => {
  const { root, files, store } = setup();
  writeEval(root, 0, '000', 'accepted');
  await store.load();

  store.invalidate();
  await store.load();

  assert.strictEqual(files.stats.reads, 1);
  assert.strictEqual(files.stats.hits, 1);
});
