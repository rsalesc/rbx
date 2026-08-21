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

test('climbs past intermediate directories to find the contest', async () => {
  // Several levels, not one: the walk being unbounded is a decided design
  // point (a setter opening `contest/A` leaves the contest file above the
  // workspace root), so a regression clamping it must fail here.
  await withTree(
    { 'contest.rbx.yml': 'problems:\n  - short_name: A\n    path: x/y/A\n' },
    async (root) => {
      const pkg = path.join(root, 'x/y/A');
      const index = await indexContests([pkg]);
      assert.strictEqual(index.get(pkg)?.shortName, 'A');
    },
  );
});

test('gives no identity to a package with no contest above it', async () => {
  // Only as reliable as the absence of a stray contest.rbx.yml somewhere above
  // the temp dir -- inherent to the unbounded walk, and recorded here so a
  // future flake is diagnosable rather than mysterious.
  await withTree({ 'A/problem.rbx.yml': 'name: a\n' }, async (root) => {
    assert.strictEqual((await indexContests([path.join(root, 'A')])).size, 0);
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
      // Sorts first (`b` < `r`) and would win if the id were not validated.
      'contest.div1.bak.rbx.yml': 'problems:\n  - short_name: X\n    path: shared\n',
    },
    async (root) => {
      const index = await indexContests([path.join(root, 'shared')]);
      assert.strictEqual(index.get(path.join(root, 'shared'))?.shortName, 'A');
    },
  );
});

test('scans one contest once for every package under it', async () => {
  // Rescanning is idempotent rather than wrong, so this pins the outcome the
  // `scanned` set protects rather than the saved read: every package under the
  // contest gets its own letter, and a repeated root adds nothing.
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
