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
  assert.deepStrictEqual(rowClick(solution, 1), { expansion: 'toggle', invoke: false });
  assert.deepStrictEqual(rowClick(group, 1), { expansion: 'toggle', invoke: false });
});

test('a single click opens a leaf', () => {
  assert.deepStrictEqual(rowClick(testcase, 1), { expansion: 'none', invoke: true });
});

test('a double click on a solution opens it and leaves the row expanded', () => {
  // Not a second toggle: the first click may have collapsed the row, and a
  // gesture that opens a file should not shut the thing it opened from.
  assert.deepStrictEqual(rowClick(solution, 2), { expansion: 'expand', invoke: true });
});

test('a double click on a group only expands, once', () => {
  assert.deepStrictEqual(rowClick(group, 2), { expansion: 'none', invoke: false });
});

test('a double click on a leaf does not open it twice', () => {
  assert.deepStrictEqual(rowClick(testcase, 2), { expansion: 'none', invoke: false });
});

test('a third click adds nothing to the double click', () => {
  assert.deepStrictEqual(rowClick(solution, 3), { expansion: 'none', invoke: false });
  assert.deepStrictEqual(rowClick(testcase, 3), { expansion: 'none', invoke: false });
});

test('a click on a row that is gone does nothing', () => {
  assert.deepStrictEqual(rowClick(undefined, 1), { expansion: 'none', invoke: false });
});
