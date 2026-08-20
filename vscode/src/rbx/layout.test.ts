import * as assert from 'assert';
import * as path from 'path';
import { test } from 'node:test';

import { packageLayout, solutionSourcePath } from './layout';

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
