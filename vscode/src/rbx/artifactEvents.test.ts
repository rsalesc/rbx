import * as assert from 'assert';
import { test } from 'node:test';

import {
  ArtifactEvent,
  classifyCachePath,
  classifyPath,
  planRefresh,
  touchesStress,
  touchesTestset,
} from './artifactEvents';

const ROOT = '/w/pkg';

function event(fsPath: string): ArtifactEvent | undefined {
  const classified = classifyCachePath(fsPath);
  if (classified !== undefined) {
    assert.strictEqual(classified.root, ROOT);
  }
  return classified?.event;
}

test('the cache directory itself is a cache event, which `rbx clean` sends', () => {
  assert.deepStrictEqual(event(`${ROOT}/.rbx`), { kind: 'cache' });
});

test('the runs directory itself is a cache event, which a new run sends', () => {
  assert.deepStrictEqual(event(`${ROOT}/.rbx/runs`), { kind: 'cache' });
});

test('the skeleton and the report are told apart', () => {
  assert.deepStrictEqual(event(`${ROOT}/.rbx/runs/skeleton.yml`), { kind: 'skeleton' });
  assert.deepStrictEqual(event(`${ROOT}/.rbx/runs/report.yml`), { kind: 'report' });
});

test('an evaluation names the testcase it belongs to', () => {
  assert.deepStrictEqual(event(`${ROOT}/.rbx/runs/3/samples/007.eval`), {
    kind: 'eval',
    solution: 3,
    group: 'samples',
    stem: '007',
  });
});

test('everything nothing reads is ignored', () => {
  for (const ignored of [
    `${ROOT}/.rbx/.storage/ab/cdef`,
    `${ROOT}/.rbx/.cache.db`,
    `${ROOT}/.rbx/runs/compilation/0.log`,
    `${ROOT}/.rbx/runs/.irun/0/main/000.eval`,
    `${ROOT}/.rbx/runs/.stress/0/main/000.eval`,
    `${ROOT}/.rbx/runs/.stress/findings/1/0.eval`,
    `${ROOT}/.rbx/runs/.stress/findings/1/input.in`,
    `${ROOT}/.rbx/runs/.stress/findings`,
    `${ROOT}/.rbx/runs/.stress/.stress.yml.tmp42`,
    // `write_text_atomic`'s temp file, renamed over stress.yml.
    `${ROOT}/.rbx/runs/.stress/.stress.yml.k3j2x9`,
    // The scratch input each iteration overwrites.
    `${ROOT}/.rbx/runs/.stress/input`,
    `${ROOT}/.rbx/runs/.stress/findings/1/stress.yml`,
    `${ROOT}/.rbx/runs/0/samples/000.out`,
    `${ROOT}/.rbx/runs/0/samples/000.err`,
    `${ROOT}/.rbx/runs/0/samples/.000.eval.tmp123`,
    `${ROOT}/.rbx/runs/0/samples/output_visualization/000.eval`,
    `${ROOT}/.rbx/runs/0/samples/.eval`,
    `${ROOT}/sols/main.cpp`,
  ]) {
    assert.strictEqual(classifyCachePath(ignored), undefined, ignored);
  }
});

test('a testset manifest belongs to whichever package claims it', () => {
  const claim = (fsPath: string) => (fsPath === `${ROOT}/build/testset.yml` ? ROOT : undefined);

  assert.deepStrictEqual(classifyPath(`${ROOT}/build/testset.yml`, claim), {
    root: ROOT,
    event: { kind: 'testset' },
  });
  assert.strictEqual(classifyPath('/w/stray/testset.yml', claim), undefined);
});

test('a batch of evaluations patches exactly those, once each', () => {
  const plan = planRefresh([
    { kind: 'eval', solution: 0, group: 'main', stem: '001' },
    { kind: 'eval', solution: 0, group: 'main', stem: '001' },
    { kind: 'eval', solution: 1, group: 'main', stem: '001' },
  ]);

  assert.deepStrictEqual(plan, {
    run: 'patch',
    report: false,
    evals: [
      { solution: 0, group: 'main', stem: '001' },
      { solution: 1, group: 'main', stem: '001' },
    ],
    testset: false,
    manifest: false,
    stress: false,
  });
});

test('a new skeleton reloads the run and patches nothing in it', () => {
  const plan = planRefresh([
    { kind: 'eval', solution: 0, group: 'main', stem: '001' },
    { kind: 'report' },
    { kind: 'skeleton' },
  ]);

  assert.deepStrictEqual(plan, {
    run: 'reload',
    report: false,
    evals: [],
    testset: false,
    manifest: false,
    stress: false,
  });
});

test('a testset landing leaves the run alone, and the other way round', () => {
  assert.deepStrictEqual(planRefresh([{ kind: 'testset' }]), {
    run: 'keep',
    report: false,
    evals: [],
    testset: true,
    manifest: false,
    stress: false,
  });
  const run = planRefresh([{ kind: 'report' }]);
  assert.strictEqual(run.testset, false);
  assert.strictEqual(touchesTestset(run), false);
});

test('a rediscovery may have moved the testset', () => {
  assert.strictEqual(touchesTestset(undefined), true);
  assert.strictEqual(touchesTestset(planRefresh([{ kind: 'manifest' }])), true);
});

test('the stress manifest, and .stress itself, are stress events', () => {
  assert.deepStrictEqual(event(`${ROOT}/.rbx/runs/.stress/stress.yml`), { kind: 'stress' });
  assert.deepStrictEqual(event(`${ROOT}/.rbx/runs/.stress`), { kind: 'stress' });
});

test('a stress event leaves the run, the testset and the manifest alone', () => {
  const plan = planRefresh([{ kind: 'stress' }]);
  assert.deepStrictEqual(plan, {
    run: 'keep',
    report: false,
    evals: [],
    testset: false,
    manifest: false,
    stress: true,
  });
  assert.strictEqual(touchesStress(plan), true);
  assert.strictEqual(touchesTestset(plan), false);
});

test('only a vanished cache, of the run events, touches the stress session', () => {
  assert.strictEqual(touchesStress(planRefresh([{ kind: 'cache' }])), true);
  assert.strictEqual(touchesStress(planRefresh([{ kind: 'skeleton' }])), false);
  assert.strictEqual(
    touchesStress(planRefresh([{ kind: 'eval', solution: 0, group: 'main', stem: '001' }])),
    false,
  );
  assert.strictEqual(touchesStress(undefined), true);
});
