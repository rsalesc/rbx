/**
 * Finds rbx problem packages in the open workspace.
 *
 * A package is any directory holding a `problem.rbx.yml`. A contest workspace
 * holds several; a single-problem workspace holds one. Which of them the Run
 * view shows is not decided here but in `activeProblem.ts`.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { PROBLEM_MANIFEST, PackageLayout, packageLayout } from './rbx/layout';

// `**/build/**` is a guess, not a rule: the build directory is named by the
// preset (see rbx/environment.ts) and may be called something else. It is only
// here to keep the scan cheap -- rbx never writes a `problem.rbx.yml` into a
// build directory, so nothing is lost when the guess misses.
const EXCLUDE = '{**/node_modules/**,**/.git/**,**/.rbx/**,**/build/**}';

export async function discoverPackages(): Promise<PackageLayout[]> {
  const matches = await vscode.workspace.findFiles(`**/${PROBLEM_MANIFEST}`, EXCLUDE);
  const roots = matches.map((uri) => path.dirname(uri.fsPath));
  const unique = Array.from(new Set(roots)).sort();
  // Wrapped rather than passed by reference: `packageLayout` takes an optional
  // second argument, and `Array.map` would hand it the index.
  return unique.map((root) => packageLayout(root));
}

/** Label for a package node: its directory name, or its path when ambiguous. */
export function packageLabel(pkg: PackageLayout): string {
  const folder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(pkg.root));
  if (folder === undefined) {
    return path.basename(pkg.root);
  }
  const relative = path.relative(folder.uri.fsPath, pkg.root);
  return relative === '' ? path.basename(pkg.root) : relative;
}
