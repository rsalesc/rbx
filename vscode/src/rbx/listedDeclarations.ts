/**
 * Folding rbx's asset listing into the declared-file index.
 *
 * The manifest parse (manifest.ts) reads what each entry *declares* -- a
 * solution's `outcome`, `outcomePerGroup`, `score` -- but sees paths only as
 * written, so a glob (`solutions/good/*.*`) or an `!include`d fragment names no
 * file it can find. rbx's listing (assetListing.ts) is the other half: every
 * file, expanded, and the role rbx gives it. Without merging the two, a
 * globbed solution has no badge, no CodeLens and no Run button anywhere.
 *
 * The rule: the manifest's exact paths stand; a file only rbx lists takes the
 * declaration of the first manifest glob of the same role that matches it --
 * the first, because rbx assigns a file to the first entry that globs it -- or,
 * with none (an include, a field the parse does not read), a declaration
 * built from what rbx said about it.
 *
 * Pure: no `vscode` import.
 */
import * as path from 'path';

import { AssetCategory, ListedProblem } from './assetListing';
import { DeclaredAsset } from './manifest';
import { Role } from './role';

export interface Declaration {
  readonly asset: DeclaredAsset;
  readonly root: string;
}

/** A manifest entry whose path is a glob, as a regex over absolute paths. */
export interface GlobRule {
  readonly root: string;
  readonly asset: DeclaredAsset;
  readonly pattern: RegExp;
}

function roleOf(category: AssetCategory): Role | undefined {
  switch (category) {
    case 'solution':
    case 'checker':
    case 'interactor':
    case 'validator':
    case 'visualizer':
    case 'generator':
    case 'statement':
      return category;
    case 'testplan':
      return 'generator';
    default:
      return undefined;
  }
}

/** `index` plus every file the listings name that it does not. */
export function mergeListed(
  index: ReadonlyMap<string, Declaration>,
  rules: readonly GlobRule[],
  problems: readonly ListedProblem[],
): Map<string, Declaration> {
  const merged = new Map(index);
  for (const problem of problems) {
    for (const listed of problem.assets) {
      const role = roleOf(listed.category);
      if (role === undefined || merged.has(listed.path)) {
        continue;
      }
      const relative = path.relative(problem.root, listed.path);
      const rule = rules.find(
        (each) => each.root === problem.root && each.asset.role === role && each.pattern.test(listed.path),
      );
      const asset: DeclaredAsset =
        rule !== undefined
          ? { ...rule.asset, path: relative }
          : {
              path: relative,
              role,
              ...(role === 'solution' ? { expectation: listed.detail.outcome ?? 'ANY' } : {}),
              ...(listed.category === 'testplan' ? { testplan: true } : {}),
            };
      merged.set(listed.path, { asset, root: problem.root });
    }
  }
  return merged;
}
