import * as assert from 'assert';
import * as path from 'path';
import { test } from 'node:test';

import {
  Ext,
  findingAnswerPath,
  findingArtifactPath,
  findingDir,
  findingInputPath,
  packageLayout,
  reportPath,
  runArtifactPath,
  skeletonPath,
  solutionSourcePath,
  stressDir,
  stressManifestPath,
  testArtifactPath,
} from './layout';

const pkg = packageLayout(path.join(path.sep, 'work', 'prob'));

test('solutionSourcePath resolves a solution against the package root', () => {
  assert.strictEqual(
    solutionSourcePath(pkg, 'sols/wa.cpp'),
    path.join(path.sep, 'work', 'prob', 'sols', 'wa.cpp'),
  );
});

test('solutionSourcePath reads a path recorded on Windows', () => {
  assert.strictEqual(
    solutionSourcePath(pkg, 'sols\\wa.cpp'),
    path.join(path.sep, 'work', 'prob', 'sols', 'wa.cpp'),
  );
});

test('solutionSourcePath keeps a solution sitting at the package root', () => {
  assert.strictEqual(
    solutionSourcePath(pkg, 'main.cpp'),
    path.join(path.sep, 'work', 'prob', 'main.cpp'),
  );
});

test('the stress session lives under runs/.stress, one directory per finding', () => {
  const stress = path.join(path.sep, 'work', 'prob', '.rbx', 'runs', '.stress');
  const finding = path.join(stress, 'findings', '2');
  assert.strictEqual(stressDir(pkg), stress);
  assert.strictEqual(stressManifestPath(pkg), path.join(stress, 'stress.yml'));
  assert.strictEqual(findingDir(pkg, 2), finding);
  assert.strictEqual(findingInputPath(pkg, 2), path.join(finding, 'input.in'));
  assert.strictEqual(findingAnswerPath(pkg, 2), path.join(finding, 'input.ans'));
  assert.strictEqual(findingArtifactPath(pkg, 2, 1, Ext.Eval), path.join(finding, '1.eval'));
  assert.strictEqual(findingArtifactPath(pkg, 2, 0, Ext.Output), path.join(finding, '0.out'));
  assert.strictEqual(findingArtifactPath(pkg, 2, 0, Ext.Stderr), path.join(finding, '0.err'));
});

test('an ad-hoc run lives under runs/.irun, with no group level and its own inputs', () => {
  const runs = path.join(path.sep, 'work', 'prob', '.rbx', 'runs');
  const irun = path.join(runs, '.irun');
  assert.strictEqual(skeletonPath(pkg, 'irun'), path.join(irun, 'skeleton.yml'));
  assert.strictEqual(reportPath(pkg, 'irun'), path.join(irun, 'report.yml'));
  assert.strictEqual(
    runArtifactPath(pkg, 1, 'samples', '000', Ext.Eval, 'irun'),
    path.join(irun, '1', '000.eval'),
  );
  assert.strictEqual(
    testArtifactPath(pkg, 'samples', '000', Ext.Input, 'irun'),
    path.join(irun, 'inputs', '000.in'),
  );
  // And the main run is what every caller that names no source still gets.
  assert.strictEqual(
    runArtifactPath(pkg, 1, 'samples', '000', Ext.Eval),
    path.join(runs, '1', 'samples', '000.eval'),
  );
});
