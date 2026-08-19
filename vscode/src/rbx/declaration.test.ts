import * as assert from 'assert';
import { test } from 'node:test';

import {
  declarationFor,
  lensTitle,
  statusDetail,
  statusText,
} from './declaration';
import { DeclaredAsset } from './manifest';

const PARTIAL: DeclaredAsset = {
  path: 'sols/partial.cpp',
  role: 'solution',
  expectation: 'ACCEPTED_OR_TLE',
  perGroup: [{ group: 'group3', expectation: 'TIME_LIMIT_EXCEEDED' }],
};

const EVERY_MEMBER: readonly string[] = [
  'ANY',
  'ACCEPTED',
  'ACCEPTED_OR_TLE',
  'WRONG_ANSWER',
  'INCORRECT',
  'RUNTIME_ERROR',
  'TIME_LIMIT_EXCEEDED',
  'MEMORY_LIMIT_EXCEEDED',
  'OUTPUT_LIMIT_EXCEEDED',
  'TLE_OR_RTE',
  'JUDGE_FAILED',
  'COMPILATION_ERROR',
];

test('the lens leads with a codicon and says the declaration in words', () => {
  assert.strictEqual(
    lensTitle(declarationFor(PARTIAL)!),
    '$(pass) accepted-or-tle · group3: time-limit-exceeded',
  );
});

test('the wildcard override is spelled out rather than left as a glyph', () => {
  const declaration = declarationFor({
    path: 'sols/partial.cpp',
    role: 'solution',
    expectation: 'INCORRECT',
    perGroup: [
      { group: '*', expectation: 'ACCEPTED' },
      { group: 'group3', expectation: 'TIME_LIMIT_EXCEEDED' },
    ],
  })!;
  assert.strictEqual(
    lensTitle(declaration),
    '$(error) incorrect · each group: accepted · group3: time-limit-exceeded',
  );
});

test('a solution promising nothing says so in words', () => {
  const declaration = declarationFor({
    path: 'sols/x.cpp',
    role: 'solution',
    expectation: 'ANY',
  })!;
  assert.strictEqual(lensTitle(declaration), '$(question) no outcome declared');
});

test('an expectation from a newer rbx is shown as the setter spelled it', () => {
  const declaration = declarationFor({
    path: 'sols/x.cpp',
    role: 'solution',
    expectation: 'partially-accepted',
  })!;
  assert.ok(lensTitle(declaration).includes('partially-accepted'));
});

test('every expectation resolves to a codicon that exists', () => {
  // The glyphs in expectation.ts are terminal characters; a CodeLens draws in
  // the UI font, where `⧖` is not guaranteed to have a glyph at all. Every
  // member must therefore land on a codicon, and only on one of the four the
  // icon table knows.
  const icons = new Set(['pass', 'watch', 'error', 'question']);
  for (const expectation of EVERY_MEMBER) {
    const declaration = declarationFor({ path: 's.cpp', role: 'solution', expectation });
    assert.ok(declaration !== undefined, expectation);
    assert.ok(icons.has(declaration.icon), `${expectation} -> ${declaration.icon}`);
  }
});

test('only solutions declare anything', () => {
  assert.strictEqual(declarationFor({ path: 'gen.cpp', role: 'generator' }), undefined);
  assert.strictEqual(declarationFor({ path: 'sols/x.cpp', role: 'solution' }), undefined);
});

/**
 * The right-hand slot is the last run's, and ships empty: laying the space out
 * is this issue, filling it is the next one. The title must read as a finished
 * sentence with nothing in it.
 */
test('the lens keeps a slot for the last run, and reads without it', () => {
  const declaration = declarationFor(PARTIAL)!;
  const withRun = lensTitle(declaration, 'last run — WA');
  assert.ok(withRun.startsWith(lensTitle(declaration)), withRun);
  assert.ok(withRun.endsWith('last run — WA'), withRun);
});

/**
 * The status item is one line in a crowded bar, so the pooled outcome is all it
 * shows; the per-group layer moves to the detail line underneath, which is only
 * there when there is one.
 */
test('the status item keeps the pooled outcome and moves the groups to the detail', () => {
  const declaration = declarationFor(PARTIAL)!;
  assert.strictEqual(statusText(declaration), '$(pass) accepted-or-tle');
  assert.strictEqual(statusDetail(declaration), 'group3: time-limit-exceeded');
});

test('a solution with no per-group override has no detail line', () => {
  const declaration = declarationFor({
    path: 'sols/main.cpp',
    role: 'solution',
    expectation: 'ACCEPTED',
  })!;
  assert.strictEqual(statusText(declaration), '$(pass) accepted');
  assert.strictEqual(statusDetail(declaration), undefined);
});

test('the tooltip spells every layer out in the labels the run view uses', () => {
  const tooltip = declarationFor(PARTIAL)!.tooltip;
  assert.ok(tooltip.includes('AC or TLE'), tooltip);
  assert.ok(tooltip.includes('group3'), tooltip);
  assert.ok(tooltip.includes('TLE'), tooltip);
});
