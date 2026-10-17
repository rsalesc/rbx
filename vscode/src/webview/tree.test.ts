import * as assert from 'assert';
import { test } from 'node:test';

import { TreeController, TreeRow } from './tree';

// The controller's expansion bookkeeping needs no real DOM: a container that
// swallows listeners and a `document` with no focus are enough to drive it.
(globalThis as { document?: unknown }).document = { activeElement: null };

function container(): HTMLElement {
  return {
    addEventListener: () => undefined,
    contains: () => false,
    querySelector: () => null,
    focus: () => undefined,
    scrollTop: 0,
  } as unknown as HTMLElement;
}

const ROWS: TreeRow[] = [
  { id: 'a', depth: 0, expandable: true, defaultExpanded: false },
  { id: 'a/1', parentId: 'a', depth: 1, expandable: false, defaultExpanded: false },
  { id: 'b', depth: 0, expandable: true, defaultExpanded: false },
];

function controller(openByDefault: () => string[]): TreeController<TreeRow> {
  const tree = new TreeController<TreeRow>({
    container: container(),
    visible: () => ROWS,
    rowById: (id) => ROWS.find((row) => row.id === id),
    render: () => undefined,
    invoke: () => undefined,
    click: () => ({ expansion: 'none', invoke: false }),
    save: () => undefined,
    openByDefault,
  });
  tree.seed(ROWS);
  return tree;
}

test('an open-by-default id reads as open without being stored', () => {
  const tree = controller(() => ['a', 'b']);

  assert.deepStrictEqual([...tree.expanded].sort(), ['a', 'b']);
  // Persisted state holds only what the user opened, so the default does not
  // outlive the layout that asked for it.
  assert.deepStrictEqual(tree.snapshot().expanded, []);
});

test('closing an open-by-default id keeps it closed', () => {
  const tree = controller(() => ['a', 'b']);

  tree.toggle('a');

  assert.deepStrictEqual([...tree.expanded], ['b']);
});

test('the defaults vanish when the client stops asking for them', () => {
  let compact = true;
  const tree = controller(() => (compact ? ['a', 'b'] : []));

  compact = false;

  assert.deepStrictEqual([...tree.expanded], []);
});

test('collapse all closes the defaults too, and they stay closed', () => {
  const tree = controller(() => ['a', 'b']);

  tree.collapseAll();

  assert.deepStrictEqual([...tree.expanded], []);
});
