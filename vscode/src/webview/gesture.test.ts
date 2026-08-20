import * as assert from 'assert';
import { test } from 'node:test';

import type { Row } from '../rbx/viewModel';
import { rowClick } from './gesture';

function row(over: Partial<Row> & Pick<Row, 'id'>): Row {
  return {
    depth: 0,
    kind: 'solution',
    gutter: 'none',
    label: over.id,
    labelBold: false,
    meta: [],
    warnings: [],
    mismatch: false,
    expandable: false,
    defaultExpanded: false,
    search: over.id.toLowerCase(),
    section: 'rbx.solution',
    ...over,
  };
}

const solution = row({ id: 'sol', expandable: true, primaryCommand: 'rbx.openSolution' });
const group = row({ id: 'group', kind: 'group', expandable: true, section: 'rbx.group' });
const testcase = row({
  id: 'case',
  kind: 'testcase',
  section: 'rbx.testcase',
  primaryCommand: 'rbx.openInput',
});

test('a single click expands a row that expands', () => {
  assert.deepStrictEqual(rowClick(solution, 1), { toggle: true, open: false });
  assert.deepStrictEqual(rowClick(group, 1), { toggle: true, open: false });
});

test('a single click opens a leaf', () => {
  assert.deepStrictEqual(rowClick(testcase, 1), { toggle: false, open: true });
});

test('a double click on a solution opens it and takes the expansion back', () => {
  assert.deepStrictEqual(rowClick(solution, 2), { toggle: true, open: true });
});

test('a double click on a group only expands, once', () => {
  assert.deepStrictEqual(rowClick(group, 2), { toggle: false, open: false });
});

test('a double click on a leaf does not open it twice', () => {
  assert.deepStrictEqual(rowClick(testcase, 2), { toggle: false, open: false });
});

test('a third click adds nothing to the double click', () => {
  assert.deepStrictEqual(rowClick(solution, 3), { toggle: false, open: false });
  assert.deepStrictEqual(rowClick(testcase, 3), { toggle: false, open: false });
});

test('a click on a row that is gone does nothing', () => {
  assert.deepStrictEqual(rowClick(undefined, 1), { toggle: false, open: false });
});
