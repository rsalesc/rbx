import * as assert from 'assert';
import { test } from 'node:test';

import { packageLayout } from './layout';
import {
  interpretVisualizeExit,
  parseVisualizationPath,
  solutionVisualizationDest,
  stripAnsi,
  visualizeArgs,
} from './visualizeRun';

/**
 * The real bytes `rbx visualize` writes on success.
 *
 * Captured from an actual run, not imagined: rbx restores the cursor as it
 * exits, so the path line is followed by an escape and a stray space even
 * though nothing rendered a spinner. A parser that trusted "stdout is the
 * path" would hand the panel a filename with an escape sequence glued to it.
 */
const REAL_STDOUT = '/pkg/build/tests/main/visualization/000.html\n[?25h ';

test('stripAnsi removes the cursor-restore rbx emits on exit', () => {
  assert.strictEqual(stripAnsi('[?25hx'), 'x');
  assert.strictEqual(stripAnsi('[1;33mwarn[0m'), 'warn');
});

test('stripAnsi leaves a bracket that is part of a path alone', () => {
  // The escape byte is part of the pattern, so an ordinary bracket survives.
  assert.strictEqual(stripAnsi('/pkg/[weird]/000.html'), '/pkg/[weird]/000.html');
});

test('parseVisualizationPath reads the path out of real rbx stdout', () => {
  assert.strictEqual(
    parseVisualizationPath(REAL_STDOUT),
    '/pkg/build/tests/main/visualization/000.html',
  );
});

test('parseVisualizationPath returns undefined when nothing was printed', () => {
  assert.strictEqual(parseVisualizationPath(''), undefined);
  assert.strictEqual(parseVisualizationPath('[?25h \n'), undefined);
});

test('exit 0 with a path opens it', () => {
  const outcome = interpretVisualizeExit(0, REAL_STDOUT, '');
  assert.deepStrictEqual(outcome, {
    kind: 'opened',
    filePath: '/pkg/build/tests/main/visualization/000.html',
  });
});

test('exit 0 without a path is a failure, not a silent no-op', () => {
  const outcome = interpretVisualizeExit(0, '', '');
  assert.strictEqual(outcome.kind, 'failed');
});

test('exit 42 is interactive success, not an error', () => {
  assert.deepStrictEqual(interpretVisualizeExit(42, '', ''), { kind: 'interactive' });
});

test('exit 3 is cache skew', () => {
  assert.deepStrictEqual(interpretVisualizeExit(3, '', 'refusing'), {
    kind: 'cache-skew',
  });
});

test('a failure carries rbx stderr, with markup stripped', () => {
  const outcome = interpretVisualizeExit(
    1,
    '',
    '[1;31mFailed compiling visualizer[0m\n',
  );
  assert.deepStrictEqual(outcome, {
    kind: 'failed',
    message: 'Failed compiling visualizer',
  });
});

test('a failure with an empty stderr still says something', () => {
  const outcome = interpretVisualizeExit(1, '', '');
  assert.strictEqual(outcome.kind, 'failed');
  assert.match(
    (outcome as { message: string }).message,
    /exited with 1/,
  );
});

test('input argv carries only what the input visualizer takes', () => {
  assert.deepStrictEqual(
    visualizeArgs({ kind: 'input', inputPath: 'build/tests/main/000.in' }),
    ['visualize', 'input', '--input', 'build/tests/main/000.in'],
  );
});

test('an answer is ignored for the input visualizer', () => {
  // `rbx visualize input` has no `--answer`; sending one would be a usage error.
  assert.deepStrictEqual(
    visualizeArgs({
      kind: 'input',
      inputPath: 'a.in',
      answerPath: 'a.out',
    }),
    ['visualize', 'input', '--input', 'a.in'],
  );
});

test('output argv carries the output, the answer and the destination', () => {
  assert.deepStrictEqual(
    visualizeArgs({
      kind: 'output',
      inputPath: 'build/tests/main/000.in',
      outputPath: '.rbx/runs/2/main/000.out',
      answerPath: 'build/tests/main/000.out',
      dest: 'build/visualizations/runs/2/main/000',
    }),
    [
      'visualize',
      'output',
      '--input',
      'build/tests/main/000.in',
      '--output',
      '.rbx/runs/2/main/000.out',
      '--answer',
      'build/tests/main/000.out',
      '--dest',
      'build/visualizations/runs/2/main/000',
    ],
  );
});

test('--use-stderr is never sent; the stderr file is passed as the output', () => {
  // Its suffix substitution is wrong on a communication task, where the
  // solution's stderr is `.sol.err`. Passing the file directly cannot guess.
  const args = visualizeArgs({
    kind: 'output',
    inputPath: 'a.in',
    outputPath: '.rbx/runs/2/main/000.sol.err',
  });
  assert.ok(!args.includes('--use-stderr'));
  assert.ok(args.includes('.rbx/runs/2/main/000.sol.err'));
});

test('a solution visualization lands under build, never under the cache dir', () => {
  // The extension watches `**/.rbx/**`, so an artifact written there would
  // invalidate the run view on every click. Nothing watches the build tree.
  const dest = solutionVisualizationDest(packageLayout('/pkg'), 2, 'main', '000');
  assert.strictEqual(dest, '/pkg/build/visualizations/runs/2/main/000');
  assert.ok(!dest.includes('.rbx'));
});

test('two solutions do not collide on one testcase', () => {
  const pkg = packageLayout('/pkg');
  assert.notStrictEqual(
    solutionVisualizationDest(pkg, 1, 'main', '000'),
    solutionVisualizationDest(pkg, 2, 'main', '000'),
  );
});

test('the destination follows a renamed build directory', () => {
  const dest = solutionVisualizationDest(
    packageLayout('/pkg', 'build.rbx'),
    0,
    'main',
    '000',
  );
  assert.ok(dest.startsWith('/pkg/build.rbx/'));
});
