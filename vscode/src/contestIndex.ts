/**
 * Contest identities for the discovered packages.
 *
 * Walks up from each package root to the nearest `contest.rbx.yml`, mirroring
 * `find_contest_root` (rbx/box/contest/contest_package.py:103). Nothing new is
 * asked of rbx: the file is already on disk, and reading it is what lets the
 * selector call a package `A` instead of naming its directory.
 */
import * as fs from 'fs/promises';
import * as path from 'path';

import {
  CONTEST_MANIFEST,
  ProblemIdentity,
  contestVariantId,
  isContestVariantFile,
  parseContest,
  problemIdentities,
} from './rbx/contest';
import { readYamlFile } from './rbx/store';

/**
 * The nearest ancestor of `from` holding a contest.rbx.yml, or undefined.
 *
 * Deliberately unbounded by the workspace folder: opening `contest/A` directly
 * is common, and that puts the contest file above the workspace root -- exactly
 * the case that would lose its letters if the walk stopped there.
 */
async function findContestRoot(from: string): Promise<string | undefined> {
  let walker = from;
  for (;;) {
    try {
      // `isFile`, not mere existence: rbx checks `is_file()` too
      // (contest_package.py:111), and a *directory* named contest.rbx.yml
      // would otherwise stop the walk and shadow the real contest above it.
      if ((await fs.stat(path.join(walker, CONTEST_MANIFEST))).isFile()) {
        return walker;
      }
    } catch {
      // Not here; keep walking.
    }
    const parent = path.dirname(walker);
    if (parent === walker) {
      return undefined;
    }
    walker = parent;
  }
}

/**
 * Every contest file in a root: the canonical one plus its variants.
 *
 * A `use_variants: true` canonical declares no problems of its own, so the
 * letters live only in the siblings. Reading all of them and letting the first
 * file to name a root win means the extension never has to resolve which
 * variant is *selected* -- a question only `RBX_CONTEST` can answer, and one
 * whose answer is almost always the same letters anyway.
 */
async function contestFiles(root: string): Promise<string[]> {
  const files = [path.join(root, CONTEST_MANIFEST)];
  let entries: string[];
  try {
    entries = await fs.readdir(root);
  } catch {
    return files;
  }
  for (const entry of entries.sort()) {
    if (isContestVariantFile(entry)) {
      files.push(path.join(root, entry));
    }
  }
  return files;
}

/** Identities for every root that a contest names, keyed by absolute root. */
export async function indexContests(
  roots: readonly string[],
): Promise<Map<string, ProblemIdentity>> {
  const index = new Map<string, ProblemIdentity>();
  const scanned = new Set<string>();
  for (const root of roots) {
    const contestRoot = await findContestRoot(root);
    if (contestRoot === undefined || scanned.has(contestRoot)) {
      continue;
    }
    scanned.add(contestRoot);
    for (const file of await contestFiles(contestRoot)) {
      const contest = parseContest(await readYamlFile(file));
      // The id comes from the filename rather than the parsed contest: a
      // variant file does not name itself, and `contestFiles` has just sorted
      // these by that very name.
      const identities = problemIdentities(
        contestRoot,
        contest,
        contestVariantId(path.basename(file)),
      );
      for (const [key, identity] of identities) {
        // First file to name a root wins; canonical is read first.
        if (!index.has(key)) {
          index.set(key, identity);
        }
      }
    }
  }
  return index;
}
