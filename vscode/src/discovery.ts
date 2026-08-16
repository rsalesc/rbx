/**
 * Finds rbx problem packages in the open workspace.
 *
 * A package is any directory holding a `problem.rbx.yml`. A contest workspace
 * holds several; a single-problem workspace holds one, and the tree flattens
 * that case away.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { PROBLEM_MANIFEST, PackageLayout, packageLayout } from './rbx/layout';

const EXCLUDE = '{**/node_modules/**,**/.git/**,**/.rbx/**,**/build/**}';

export async function discoverPackages(): Promise<PackageLayout[]> {
  const matches = await vscode.workspace.findFiles(`**/${PROBLEM_MANIFEST}`, EXCLUDE);
  const roots = matches.map((uri) => path.dirname(uri.fsPath));
  const unique = Array.from(new Set(roots)).sort();
  return unique.map(packageLayout);
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
