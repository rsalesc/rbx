import * as assert from 'assert';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { test } from 'node:test';

import { DEFAULT_BUILD_DIR, resetBuildDirs, resolveBuildDir } from './environment';

/**
 * Real files, not a mocked fs: what is under test is agreement with rbx about
 * where a name lives on disk, and a fake that answers whatever the test says
 * would agree with itself rather than with rbx.
 */
function tree(files: Record<string, string>): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rbx-env-'));
  for (const [relative, contents] of Object.entries(files)) {
    const target = path.join(root, ...relative.split('/'));
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, contents);
  }
  resetBuildDirs();
  return root;
}

const PRESET = 'name: p\nenv: env.rbx.yml\n';

test('a package with no preset above it builds into rbx\'s default', () => {
  const root = tree({ 'prob/problem.rbx.yml': 'name: prob\n' });
  assert.strictEqual(resolveBuildDir(path.join(root, 'prob')), DEFAULT_BUILD_DIR);
});

test('a renamed buildDir reaches a package nested under the preset', () => {
  const root = tree({
    '.local.rbx/preset.rbx.yml': PRESET,
    '.local.rbx/env.rbx.yml': 'buildDir: "build.rbx"\n',
    'problems/seq/problem.rbx.yml': 'name: seq\n',
  });
  assert.strictEqual(resolveBuildDir(path.join(root, 'problems', 'seq')), 'build.rbx');
});

test('an environment that says nothing about buildDir keeps the default', () => {
  const root = tree({
    '.local.rbx/preset.rbx.yml': PRESET,
    '.local.rbx/env.rbx.yml': 'sandbox: "stupid"\n',
    'prob/problem.rbx.yml': 'name: prob\n',
  });
  assert.strictEqual(resolveBuildDir(path.join(root, 'prob')), DEFAULT_BUILD_DIR);
});

test('a preset with no env at all keeps the default', () => {
  const root = tree({
    '.local.rbx/preset.rbx.yml': 'name: p\n',
    'prob/problem.rbx.yml': 'name: prob\n',
  });
  assert.strictEqual(resolveBuildDir(path.join(root, 'prob')), DEFAULT_BUILD_DIR);
});

test('a preset under development is read from its bare manifest', () => {
  // No `.local.rbx` anywhere: this is a preset checkout, which rbx falls back
  // to in `find_nested_preset`.
  const root = tree({
    'preset.rbx.yml': PRESET,
    'env.rbx.yml': 'buildDir: "out"\n',
    'problem/problem.rbx.yml': 'name: prob\n',
  });
  assert.strictEqual(resolveBuildDir(path.join(root, 'problem')), 'out');
});

test('an installed preset above wins over a bare manifest below it', () => {
  // rbx looks for every `.local.rbx` before it considers a bare manifest, so a
  // preset checkout vendored inside a contest must not capture the contest's
  // problems.
  const root = tree({
    '.local.rbx/preset.rbx.yml': PRESET,
    '.local.rbx/env.rbx.yml': 'buildDir: "build.rbx"\n',
    'vendor/preset.rbx.yml': PRESET,
    'vendor/env.rbx.yml': 'buildDir: "out"\n',
    'vendor/prob/problem.rbx.yml': 'name: prob\n',
  });
  assert.strictEqual(resolveBuildDir(path.join(root, 'vendor', 'prob')), 'build.rbx');
});

test('unparseable yaml is treated as a package with no preset', () => {
  const root = tree({
    '.local.rbx/preset.rbx.yml': PRESET,
    '.local.rbx/env.rbx.yml': 'buildDir: "[unclosed\n',
    'prob/problem.rbx.yml': 'name: prob\n',
  });
  assert.strictEqual(resolveBuildDir(path.join(root, 'prob')), DEFAULT_BUILD_DIR);
});

test('an absolute buildDir is refused rather than escaping the package', () => {
  const root = tree({
    '.local.rbx/preset.rbx.yml': PRESET,
    '.local.rbx/env.rbx.yml': `buildDir: "${path.join(path.sep, 'tmp', 'elsewhere')}"\n`,
    'prob/problem.rbx.yml': 'name: prob\n',
  });
  assert.strictEqual(resolveBuildDir(path.join(root, 'prob')), DEFAULT_BUILD_DIR);
});

test('a buildDir that is not a string is refused', () => {
  const root = tree({
    '.local.rbx/preset.rbx.yml': PRESET,
    '.local.rbx/env.rbx.yml': 'buildDir: 3\n',
    'prob/problem.rbx.yml': 'name: prob\n',
  });
  assert.strictEqual(resolveBuildDir(path.join(root, 'prob')), DEFAULT_BUILD_DIR);
});

test('resetBuildDirs is what lets an edited preset move the build directory', () => {
  const root = tree({
    '.local.rbx/preset.rbx.yml': PRESET,
    '.local.rbx/env.rbx.yml': 'buildDir: "build.rbx"\n',
    'prob/problem.rbx.yml': 'name: prob\n',
  });
  const pkg = path.join(root, 'prob');
  assert.strictEqual(resolveBuildDir(pkg), 'build.rbx');
  fs.writeFileSync(path.join(root, '.local.rbx', 'env.rbx.yml'), 'buildDir: "out"\n');
  assert.strictEqual(resolveBuildDir(pkg), 'build.rbx', 'cached until told otherwise');
  resetBuildDirs();
  assert.strictEqual(resolveBuildDir(pkg), 'out');
});
