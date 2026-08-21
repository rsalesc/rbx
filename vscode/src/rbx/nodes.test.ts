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

const ONE: PackageRunView = {
  pkg: PKG,
  run: run([solution(0, [group('main', ['000', '001'])])]),
};

test('ids spell out the path from package root down to testcase stem', () => {
  // The root still leads every id even though no row draws it: ids outlive the
  // rows the client is showing, and two packages must never collide in the map
  // the host resolves context-menu commands through.
  assert.deepStrictEqual(flattenNodes(ONE).map(nodeId), [
    '/w/a::0',
    '/w/a::0::main',
    '/w/a::0::main::000',
    '/w/a::0::main::001',
  ]);
});

test('emits no package row', () => {
  const kinds = new Set(flattenNodes(ONE).map((node) => node.kind));
  // `'package'` is not in `RunNode` at all any more, so writing the comparison
  // would not even compile -- hence the set of what is left.
  assert.deepStrictEqual([...kinds], ['solution', 'group', 'testcase']);
});

test('two packages laid out alike never share a row id', () => {
  // Why the root still leads every id although no row draws it: the host
  // resolves a context-menu command through a map of ids, and the client keeps
  // a selection across a switch of problem. Two packages laid out identically
  // -- which is what a contest's problems are -- must not collide there.
  const ids = (root: string): string[] => flattenNodes({ pkg: { root }, run: ONE.run }).map(nodeId);
  const here = ids('/w/a');
  const there = ids('/w/b');
  assert.strictEqual(here.length, there.length);
  assert.strictEqual(
    here.some((id) => there.includes(id)),
    false,
  );
});

test('yields nothing for a package with no run', () => {
  assert.deepStrictEqual(flattenNodes({ pkg: PKG, run: undefined }), []);
});

test('every solution is emitted before its own groups and testcases', () => {
  const nodes = flattenNodes({
    pkg: PKG,
    run: run([solution(0, [group('main', ['000'])]), solution(1, [group('edge', ['100'])])]),
  });
  assert.deepStrictEqual(nodes.map(nodeId), [
    '/w/a::0',
    '/w/a::0::main',
    '/w/a::0::main::000',
    '/w/a::1',
    '/w/a::1::edge',
    '/w/a::1::edge::100',
  ]);
});

test('solo is true only when the package ran exactly one solution', () => {
  const solos = flattenNodes(ONE)
    .filter((node) => node.kind === 'solution')
    .map((node) => (node.kind === 'solution' ? node.solo : undefined));
  assert.deepStrictEqual(solos, [true]);

  const many = flattenNodes({ pkg: PKG, run: run([solution(0, []), solution(1, [])]) })
    .filter((node) => node.kind === 'solution')
    .map((node) => (node.kind === 'solution' ? node.solo : undefined));
  assert.deepStrictEqual(many, [false, false]);
});
