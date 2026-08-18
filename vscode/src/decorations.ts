/**
 * The expectation channel: a badge and a hue saying what a row was declared to
 * do.
 *
 * A thin wrapper over `rbx/outcome.ts` and `rbx/expectation.ts`, the way
 * runTree.ts is thin over the same modules -- all the logic worth testing lives
 * there, without a `vscode` import.
 *
 * Decorations rather than the icon because the icon is already spoken for:
 * #664 gave every verdict its own codicon, and that channel keeps reporting
 * what *happened*. Note what this file therefore does not carry: whether the
 * declaration held. That is the icon's business, which grows a mark in its
 * corner on a miss -- so a mismatch shows in the Run view, where there is an
 * icon, and not on an Explorer entry or an editor tab, where there is not.
 *
 * Everything here is read from problem.rbx.yml by way of the skeleton, so none
 * of it is a claim about the last run and none of it goes stale when the
 * solution is edited.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { groupExpectation, solutionExpectation } from './rbx/expectation';
import { PackageLayout } from './rbx/layout';
import { expectationBadge, expectationColor, expectationTooltip } from './rbx/outcome';
import { PackageRun } from './rbx/store';

/** Scheme for rows that are not files, i.e. groups. */
export const RUN_SCHEME = 'rbx-run';

/**
 * A URI standing for one group under one solution.
 *
 * Groups have no file of their own, and a decoration provider is addressed by
 * URI, so they get a synthetic one. The package root goes in the query rather
 * than the path: it is an absolute path itself, and concatenating it would make
 * the group name unrecoverable on a root containing a digit-only segment. It
 * still has to be *somewhere*, or two packages declaring the same group name
 * under the same solution index would collide.
 */
export function groupUri(
  pkg: PackageLayout,
  solutionIndex: number,
  group: string,
): vscode.Uri {
  return vscode.Uri.from({
    scheme: RUN_SCHEME,
    path: `/${solutionIndex}/${group}`,
    query: pkg.root,
  });
}

/** What the provider needs from the tree, kept narrow so it cannot reach further. */
export interface RunSource {
  knownPackages(): readonly PackageLayout[];
  report(pkg: PackageLayout): Promise<PackageRun | undefined>;
  readonly onDidChangeTreeData: vscode.Event<unknown>;
}

export class ExpectationDecorationProvider implements vscode.FileDecorationProvider {
  private readonly changed = new vscode.EventEmitter<undefined>();
  readonly onDidChangeFileDecorations = this.changed.event;

  private readonly disposable: vscode.Disposable;

  constructor(private readonly source: RunSource) {
    // The tree already fires whenever artifacts land or packages are
    // rediscovered, and a decoration is stale under exactly the same
    // conditions -- so it rides that event rather than watching the disk twice.
    this.disposable = source.onDidChangeTreeData(() => this.changed.fire(undefined));
  }

  dispose(): void {
    this.disposable.dispose();
    this.changed.dispose();
  }

  async provideFileDecoration(
    uri: vscode.Uri,
  ): Promise<vscode.FileDecoration | undefined> {
    const expectation =
      uri.scheme === RUN_SCHEME ? await this.forGroup(uri) : await this.forSolution(uri);
    if (expectation === undefined) {
      return undefined;
    }
    const badge = expectationBadge(expectation.declared);
    if (badge === undefined) {
      // `ANY`, or a declaration from an rbx newer than this extension. Both
      // mean there is nothing honest to draw.
      return undefined;
    }
    const decoration = new vscode.FileDecoration(
      badge,
      expectationTooltip(
        expectation.declared,
        expectation.outcome,
        expectation.status,
        expectation.failedGroups,
      ),
    );
    const color = expectationColor(expectation.declared);
    if (color !== undefined) {
      decoration.color = new vscode.ThemeColor(color);
    }
    // Otherwise a decorated solution paints its `sols/` directory too, in a
    // tree where every sibling is also a solution.
    decoration.propagate = false;
    return decoration;
  }

  private async forSolution(uri: vscode.Uri) {
    if (uri.scheme !== 'file') {
      return undefined;
    }
    for (const pkg of this.source.knownPackages()) {
      const relative = path.relative(pkg.root, uri.fsPath);
      if (relative.startsWith('..') || path.isAbsolute(relative)) {
        continue;
      }
      const run = (await this.source.report(pkg))?.solutions.find(
        (candidate) => candidate.solution.path === relative,
      );
      if (run !== undefined) {
        return solutionExpectation(run);
      }
    }
    return undefined;
  }

  private async forGroup(uri: vscode.Uri) {
    const [, index, ...rest] = uri.path.split('/');
    const solutionIndex = Number(index);
    const name = rest.join('/');
    if (!Number.isInteger(solutionIndex) || name === '') {
      return undefined;
    }
    const pkg = this.source
      .knownPackages()
      .find((candidate) => candidate.root === uri.query);
    if (pkg === undefined) {
      return undefined;
    }
    const run = (await this.source.report(pkg))?.solutions.find(
      (candidate) => candidate.solution.index === solutionIndex,
    );
    const group = run?.groups.find((candidate) => candidate.name === name);
    return group === undefined ? undefined : groupExpectation(group);
  }
}
