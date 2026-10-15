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
  solutionSourcePath,
  stressDir,
  stressManifestPath,
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
