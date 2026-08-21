/**
 * The only file-touching tests in the suite, because this is the only host-side
 * module that never imports `vscode`: the walk-up, the variant glob and the
 * merge order are reachable from `node --test` with nothing but a temp dir.
 */
import * as assert from 'assert';
import * as fs from 'fs/promises';
import { test } from 'node:test';
import * as os from 'os';
import * as path from 'path';

import { indexContests } from './contestIndex';

/** Builds a tree of `relative path -> file contents`, and always removes it. */
async function withTree(
  files: Record<string, string>,
  body: (root: string) => Promise<void>,
): Promise<void> {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'rbx-contest-'));
  try {
    for (const [name, contents] of Object.entries(files)) {
      const file = path.join(root, name);
      await fs.mkdir(path.dirname(file), { recursive: true });
      await fs.writeFile(file, contents);
    }
    await body(root);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
}

test('finds the contest above a nested package root', async () => {
  await withTree({ 'contest.rbx.yml': 'problems:\n  - short_name: A\n' }, async (root) => {
    const index = await indexContests([path.join(root, 'A')]);
    assert.strictEqual(index.get(path.join(root, 'A'))?.shortName, 'A');
  });
});

test('lets the first variant name a root the later ones also name', async () => {
  // The canonical dispatcher declares nothing, so the letters live only in the
  // siblings -- and the extension picks one without resolving `RBX_CONTEST`.
  await withTree(
    {
      'contest.rbx.yml': 'use_variants: true\n',
      'contest.div1.rbx.yml': 'problems:\n  - short_name: A\n    path: shared\n',
      'contest.div2.rbx.yml': 'problems:\n  - short_name: Z\n    path: shared\n',
    },
    async (root) => {
      const index = await indexContests([path.join(root, 'shared')]);
      assert.strictEqual(index.get(path.join(root, 'shared'))?.shortName, 'A');
    },
  );
});

test('scans one contest once for every package under it', async () => {
  // Rescanning is idempotent rather than wrong, so this pins the outcome the
  // `scanned` set and the canonical-vs-variant filename filter protect: every
  // package under the contest gets its own letter, and none gets a second one.
  await withTree(
    { 'contest.rbx.yml': 'problems:\n  - short_name: A\n  - short_name: B\n' },
    async (root) => {
      const roots = [path.join(root, 'A'), path.join(root, 'B'), path.join(root, 'A')];
      const index = await indexContests(roots);
      assert.deepStrictEqual(
        [...index].map(([key, identity]) => [path.relative(root, key), identity.shortName]),
        [
          ['A', 'A'],
          ['B', 'B'],
        ],
      );
    },
  );
});
