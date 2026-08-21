import * as assert from 'assert';
import { test } from 'node:test';

import type { PackageLayout } from './layout';
import { PackageRunView, flattenNodes, nodeId } from './nodes';
import type { GroupRun, PackageRun, SolutionRun, TestcaseRun } from './store';

function testcase(stem: string): TestcaseRun {
  return {
    entry: { group: 'main', index: 0 },
    stem,
    inputPath: '',
    answerPath: '',
    outputPath: '',
    stderrPaths: [],
    interactionPath: '',
  };
}

function group(name: string, stems: readonly string[]): GroupRun {
  return { name, testcases: stems.map(testcase) };
}

function solution(index: number, groups: readonly GroupRun[]): SolutionRun {
  return { solution: { path: `sols/${index}.cpp`, index }, groups };
}

function run(solutions: readonly SolutionRun[]): PackageRun {
  return {
    skeleton: { solutions: [], entries: [], groups: [], compilation: [] },
    solutions,
    findings: [],
  };
}

const PKG: PackageLayout = { root: '/w/a' };
const OTHER: PackageLayout = { root: '/w/b' };

const ONE: PackageRunView = {
  pkg: PKG,
  run: run([solution(0, [group('main', ['000', '001'])])]),
};

test('ids spell out the path from package root down to testcase stem', () => {
  const nodes = flattenNodes([ONE, { pkg: OTHER, run: run([solution(0, [])]) }]);
  assert.deepStrictEqual(nodes.map(nodeId), [
    '/w/a',
    '/w/a::0',
    '/w/a::0::main',
    '/w/a::0::main::000',
    '/w/a::0::main::001',
    '/w/b',
    '/w/b::0',
  ]);
});

test('a single package is flattened away, since there is nothing to choose', () => {
  assert.deepStrictEqual(
    flattenNodes([ONE]).map((node) => node.kind),
    ['solution', 'group', 'testcase', 'testcase'],
  );
});

test('two packages keep their package rows, parents before their children', () => {
  const nodes = flattenNodes([ONE, { pkg: OTHER, run: run([solution(3, [])]) }]);
  assert.deepStrictEqual(
    nodes.map((node) => node.kind),
    ['package', 'solution', 'group', 'testcase', 'testcase', 'package', 'solution'],
  );
});

test('a package with no run on disk contributes nothing', () => {
  const nodes = flattenNodes([ONE, { pkg: OTHER, run: undefined }]);
  assert.deepStrictEqual(nodes.map(nodeId), [
    '/w/a',
    '/w/a::0',
    '/w/a::0::main',
    '/w/a::0::main::000',
    '/w/a::0::main::001',
  ]);
});

test('solo is true only when the package ran exactly one solution', () => {
  const solos = flattenNodes([ONE])
    .filter((node) => node.kind === 'solution')
    .map((node) => (node.kind === 'solution' ? node.solo : undefined));
  assert.deepStrictEqual(solos, [true]);

  const many = flattenNodes([
    { pkg: PKG, run: run([solution(0, []), solution(1, [])]) },
  ])
    .filter((node) => node.kind === 'solution')
    .map((node) => (node.kind === 'solution' ? node.solo : undefined));
  assert.deepStrictEqual(many, [false, false]);
});
