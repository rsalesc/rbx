import * as assert from 'assert';
import { test } from 'node:test';
import { parse as parseYaml } from 'yaml';

import {
  parseVisualizerDeclarations,
  resolveDeclaredVisualizers,
} from './declaredVisualizers';

/**
 * These pin the precedence this module duplicates from rbx
 * (`testcase_extractors.py:180-195,368-374`). If rbx's rules move, one of these
 * should fail rather than the buttons quietly going wrong.
 */
function resolve(yaml: string, path: string | undefined) {
  return resolveDeclaredVisualizers(
    parseVisualizerDeclarations(parseYaml(yaml)),
    path,
  );
}

const PACKAGE_ONLY = `
name: p
visualizer:
  path: viz.py
  extension: html
testcases:
  - name: main
`;

test('a package-level visualizer covers a plain group', () => {
  assert.deepStrictEqual(resolve(PACKAGE_ONLY, 'main'), {
    input: true,
    // No solutionVisualizer, so the input one stands in -- rbx's own fallback.
    output: true,
  });
});

test('a package declaring nothing offers nothing', () => {
  assert.deepStrictEqual(resolve('name: p\ntestcases:\n  - name: main\n', 'main'), {
    input: false,
    output: false,
  });
});

const GROUP_OVERRIDE = `
name: p
visualizer:
  path: pkg.py
  extension: html
testcases:
  - name: plain
  - name: fancy
    visualizer:
      path: group.py
      extension: html
`;

test('a group override is still a declaration, so both groups offer buttons', () => {
  // Which program runs differs, but that is rbx's business; both are visualizable.
  assert.deepStrictEqual(resolve(GROUP_OVERRIDE, 'plain'), {
    input: true,
    output: true,
  });
  assert.deepStrictEqual(resolve(GROUP_OVERRIDE, 'fancy'), {
    input: true,
    output: true,
  });
});

const GROUP_ONLY = `
name: p
testcases:
  - name: plain
  - name: fancy
    visualizer:
      path: group.py
      extension: html
`;

test('a group-only visualizer is offered on that group and nowhere else', () => {
  // The case a package-level check gets wrong in both directions.
  assert.deepStrictEqual(resolve(GROUP_ONLY, 'fancy'), { input: true, output: true });
  assert.deepStrictEqual(resolve(GROUP_ONLY, 'plain'), { input: false, output: false });
});

const SUBGROUP_ONLY = `
name: p
testcases:
  - name: main
    subgroups:
      - name: deep
        visualizer:
          path: sub.py
          extension: html
`;

test('a subgroup declaration is reached through the subgroup path', () => {
  assert.deepStrictEqual(resolve(SUBGROUP_ONLY, 'main/deep'), {
    input: true,
    output: true,
  });
  // The group itself declares nothing.
  assert.deepStrictEqual(resolve(SUBGROUP_ONLY, 'main'), {
    input: false,
    output: false,
  });
});

const SOLUTION_ONLY = `
name: p
solutionVisualizer:
  path: out.py
  extension: html
testcases:
  - name: main
`;

test('a solutionVisualizer alone offers the output channel only', () => {
  // There is no fallback in this direction: an output visualizer says nothing
  // about how to draw an input.
  assert.deepStrictEqual(resolve(SOLUTION_ONLY, 'main'), {
    input: false,
    output: true,
  });
});

const INDEPENDENT = `
name: p
visualizer:
  path: pkg_in.py
  extension: html
solutionVisualizer:
  path: pkg_out.py
  extension: html
testcases:
  - name: main
    subgroups:
      - name: deep
        visualizer:
          path: sub_in.py
          extension: html
`;

test('overriding one channel does not clear the other', () => {
  // The subgroup replaces `visualizer` only; `solutionVisualizer` still comes
  // from the package. Resolving the two together would lose it.
  assert.deepStrictEqual(resolve(INDEPENDENT, 'main/deep'), {
    input: true,
    output: true,
  });
});

test('an unknown path falls back to the outermost declaration', () => {
  // A manifest edited since the last build names groups this testcase's path
  // does not match. Degrading to the package answer beats reporting nothing.
  assert.deepStrictEqual(resolve(PACKAGE_ONLY, 'gone/missing'), {
    input: true,
    output: true,
  });
});

test('an undefined path resolves at the package level', () => {
  assert.deepStrictEqual(resolve(PACKAGE_ONLY, undefined), {
    input: true,
    output: true,
  });
});

test('a manifest that is not a mapping does not throw', () => {
  // Caught mid-write, or hand-edited into nonsense.
  assert.deepStrictEqual(resolve('[]', 'main'), { input: false, output: false });
  assert.deepStrictEqual(resolve('', 'main'), { input: false, output: false });
});

test('a cyclic subgroup alias terminates', () => {
  const cyclic: Record<string, unknown> = { name: 'main' };
  cyclic.subgroups = [cyclic];
  const declarations = parseVisualizerDeclarations({
    visualizer: { path: 'v.py' },
    testcases: [cyclic],
  });
  assert.deepStrictEqual(resolveDeclaredVisualizers(declarations, 'main/main/main'), {
    input: true,
    output: true,
  });
});
