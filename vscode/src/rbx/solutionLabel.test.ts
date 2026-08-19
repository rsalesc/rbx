import * as assert from 'assert';
import { test } from 'node:test';

import {
  SolutionLabelStyle,
  asSolutionLabelStyle,
  commonDirPrefix,
  solutionLabels,
} from './solutionLabel';

/** The labels in input order, which is the order the rows appear in. */
function labels(paths: readonly string[], style: SolutionLabelStyle): string[] {
  const map = solutionLabels(paths, style);
  return paths.map((solutionPath) => map.get(solutionPath) ?? '');
}

const SOLS = ['sols/main.cpp', 'sols/partial.cpp', 'sols/slow/tle.cpp'];

test('the full style shows the path relative to the package root', () => {
  assert.deepStrictEqual(labels(SOLS, 'full'), [
    'sols/main.cpp',
    'sols/partial.cpp',
    'sols/slow/tle.cpp',
  ]);
});

test('the trimmed style drops the directory every solution shares', () => {
  assert.deepStrictEqual(labels(SOLS, 'trimmed'), ['main.cpp', 'partial.cpp', 'slow/tle.cpp']);
});

test('the basename style drops every directory', () => {
  assert.deepStrictEqual(labels(SOLS, 'basename'), ['main.cpp', 'partial.cpp', 'tle.cpp']);
});

test('a shared prefix that is not a whole segment is not a prefix', () => {
  // `sols/` and `solutions/` share four characters and no directory.
  const mixed = ['sols/main.cpp', 'solutions/other.cpp'];
  assert.strictEqual(commonDirPrefix(mixed), '');
  assert.deepStrictEqual(labels(mixed, 'trimmed'), ['sols/main.cpp', 'solutions/other.cpp']);
});

test('the basename is never eaten by the prefix', () => {
  // Two files in the same directory whose names share a prefix: character-wise
  // trimming would show `n.cpp` and `_x.cpp`.
  const siblings = ['sols/main.cpp', 'sols/mai_x.cpp'];
  assert.strictEqual(commonDirPrefix(siblings), 'sols/');
  assert.deepStrictEqual(labels(siblings, 'trimmed'), ['main.cpp', 'mai_x.cpp']);
});

test('solutions at the package root are left alone', () => {
  const flat = ['main.cpp', 'wa.cpp'];
  assert.strictEqual(commonDirPrefix(flat), '');
  assert.deepStrictEqual(labels(flat, 'trimmed'), ['main.cpp', 'wa.cpp']);
});

test('a lone solution trims down to its basename', () => {
  assert.deepStrictEqual(labels(['sols/main.cpp'], 'trimmed'), ['main.cpp']);
});

test('nested directories are trimmed as deep as they agree', () => {
  const nested = ['a/b/c/one.cpp', 'a/b/c/two.cpp'];
  assert.strictEqual(commonDirPrefix(nested), 'a/b/c/');
  assert.deepStrictEqual(labels(nested, 'trimmed'), ['one.cpp', 'two.cpp']);
});

test('the prefix stops at the first directory the set disagrees on', () => {
  const forked = ['a/b/one.cpp', 'a/c/two.cpp'];
  assert.strictEqual(commonDirPrefix(forked), 'a/');
  assert.deepStrictEqual(labels(forked, 'trimmed'), ['b/one.cpp', 'c/two.cpp']);
});

test('windows separators are labelled like the posix paths they mirror', () => {
  const windows = ['sols\\main.cpp', 'sols\\wa.cpp'];
  assert.deepStrictEqual(labels(windows, 'trimmed'), ['main.cpp', 'wa.cpp']);
  assert.deepStrictEqual(labels(windows, 'full'), ['sols/main.cpp', 'sols/wa.cpp']);
});

test('an empty package has no prefix to compute', () => {
  assert.strictEqual(commonDirPrefix([]), '');
  assert.deepStrictEqual(labels([], 'trimmed'), []);
});

test('the configured style falls back to trimmed for anything unrecognized', () => {
  assert.strictEqual(asSolutionLabelStyle('full'), 'full');
  assert.strictEqual(asSolutionLabelStyle('trimmed'), 'trimmed');
  assert.strictEqual(asSolutionLabelStyle('basename'), 'basename');
  assert.strictEqual(asSolutionLabelStyle(undefined), 'trimmed');
  assert.strictEqual(asSolutionLabelStyle('relative'), 'trimmed');
  assert.strictEqual(asSolutionLabelStyle(3), 'trimmed');
});
