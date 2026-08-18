/**
 * The expectation channel: a badge saying what a row was declared to do, and a
 * colour saying whether it did it.
 *
 * A thin wrapper over `rbx/outcome.ts` and `rbx/expectation.ts`, the way
 * runTree.ts is thin over the same modules -- all the logic worth testing lives
 * there, without a `vscode` import.
 *
 * Decorations rather than the icon because the icon is already spoken for:
 * #664 gave every verdict its own codicon, and that channel must keep reporting
 * what *happened* so the tree and the terminal beside it agree. The badge is
 * plain text (`FileDecoration.badge` cannot hold a codicon), which is why the
 * two marks are different shapes for the same fact -- they are chosen to rhyme:
 * `pass` is a tick in a circle beside a `✓` badge, `close` a cross beside `✗`.
 */
import * as fs from 'fs/promises';
import * as path from 'path';
import * as vscode from 'vscode';

import { PackageLayout, reportPath } from './rbx/layout';
import { Expectation, groupExpectation, solutionExpectation } from './rbx/expectation';
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

/**
 * Has this solution been edited since the run that judged it?
 *
 * The badge is a declaration read from problem.rbx.yml and can never go stale,
 * but the colour is run-derived -- and because solutions are decorated by their
 * real file URI, that colour also rides along on the Explorer entry and the
 * editor tab, where it would go on accusing a file the user has already fixed.
 * So a solution newer than the report keeps its badge and loses its colour: it
 * still says what it promises, and stops claiming anything about what it last
 * did.
 */
async function isStale(pkg: PackageLayout, filePath: string): Promise<boolean> {
  try {
    const [solution, report] = await Promise.all([
      fs.stat(filePath),
      fs.stat(reportPath(pkg)),
    ]);
    return solution.mtimeMs > report.mtimeMs;
  } catch {
    // No report, or no such solution file on this host. Neither is a reason to
    // suppress a colour the report does justify.
    return false;
  }
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
    const resolved =
      uri.scheme === RUN_SCHEME ? await this.forGroup(uri) : await this.forSolution(uri);
    if (resolved === undefined) {
      return undefined;
    }
    const { expectation, stale } = resolved;
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
    const color = stale ? undefined : expectationColor(expectation.status);
    if (color !== undefined) {
      decoration.color = new vscode.ThemeColor(color);
    }
    // Otherwise a mismatched solution paints its `sols/` directory red as well,
    // in a tree where every sibling is also a solution.
    decoration.propagate = false;
    return decoration;
  }

  private async forSolution(
    uri: vscode.Uri,
  ): Promise<{ expectation: Expectation; stale: boolean } | undefined> {
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
      if (run === undefined) {
        continue;
      }
      const expectation = solutionExpectation(run);
      if (expectation === undefined) {
        return undefined;
      }
      return { expectation, stale: await isStale(pkg, uri.fsPath) };
    }
    return undefined;
  }

  private async forGroup(
    uri: vscode.Uri,
  ): Promise<{ expectation: Expectation; stale: boolean } | undefined> {
    const [, index, ...rest] = uri.path.split('/');
    const solutionIndex = Number(index);
    const name = rest.join('/');
    if (!Number.isInteger(solutionIndex) || name === '') {
      return undefined;
    }
    const pkg = this.source.knownPackages().find((candidate) => candidate.root === uri.query);
    if (pkg === undefined) {
      return undefined;
    }
    const run = (await this.source.report(pkg))?.solutions.find(
      (candidate) => candidate.solution.index === solutionIndex,
    );
    const group = run?.groups.find((candidate) => candidate.name === name);
    if (group === undefined) {
      return undefined;
    }
    const expectation = groupExpectation(group);
    // A group row is only ever read inside the Run view, never on a tab that
    // outlives the run, so it has no staleness problem to correct for.
    return expectation === undefined ? undefined : { expectation, stale: false };
  }
}
