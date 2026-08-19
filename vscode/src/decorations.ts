/**
 * The mismatch channel: red label text and an `✗` badge on rows where the run
 * disagreed with what the package declared.
 *
 * A `FileDecoration` is the only way to colour a `TreeItem`'s label, which is
 * why this exists at all -- `TreeItem` itself offers an icon, a description and
 * a tooltip, none of which can tint the row.
 *
 * Every row it decorates is addressed by a synthetic `rbx-run:` URI, including
 * solutions, which do have a real file behind them. That is deliberate:
 * decorations are global per URI, so decorating `sols/wa.cpp` itself would put
 * the mark on that file in the Explorer and on its editor tab as well. The
 * Explorer is a separate question with its own scoping and staleness problems
 * (see the channel inventory issue), and pulling the URI into a private scheme
 * keeps this change inside the view it was designed for.
 *
 * Nothing here decides anything: `matchesExpectation` was computed by
 * `rbx.box.run_report`.
 */
import * as vscode from 'vscode';

import { groupExpectation, solutionExpectation } from './rbx/expectation';
import { PackageLayout } from './rbx/layout';
import { MISMATCH_BADGE, expectationColor, expectedShortName } from './rbx/outcome';
import { PackageRun } from './rbx/store';

/** Scheme for run rows, none of which are files as far as decorations go. */
export const RUN_SCHEME = 'rbx-run';

/**
 * A URI standing for one solution row, or one group row beneath it.
 *
 * The package root goes in the query rather than the path: it is an absolute
 * path itself, and concatenating it would make the group name unrecoverable.
 * It still has to be somewhere, or two packages in one workspace would collide
 * on the same solution index.
 */
export function runUri(
  pkg: PackageLayout,
  solutionIndex: number,
  group?: string,
): vscode.Uri {
  return vscode.Uri.from({
    scheme: RUN_SCHEME,
    path: group === undefined ? `/${solutionIndex}` : `/${solutionIndex}/${group}`,
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
    // rediscovered, and a decoration goes stale under exactly those
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
    if (uri.scheme !== RUN_SCHEME) {
      return undefined;
    }
    const resolved = await this.resolve(uri);
    // Only a miss is drawn. A row that did what it promised gets no decoration
    // at all, which is what makes the decorated rows findable by eye.
    if (resolved === undefined || resolved.status !== 'missed') {
      return undefined;
    }
    const decoration = new vscode.FileDecoration(
      MISMATCH_BADGE,
      `Did not match its expected outcome (${expectedShortName(resolved.declared)})`,
      new vscode.ThemeColor(expectationColor('missed') ?? 'charts.red'),
    );
    // Rows are not files, but a group row is a child of a solution row and
    // would otherwise tint its parent for a miss the parent may not have.
    decoration.propagate = false;
    return decoration;
  }

  private async resolve(
    uri: vscode.Uri,
  ): Promise<{ declared: string; status: string } | undefined> {
    const [, index, ...rest] = uri.path.split('/');
    const solutionIndex = Number(index);
    if (!Number.isInteger(solutionIndex)) {
      return undefined;
    }
    const pkg = this.source.knownPackages().find((known) => known.root === uri.query);
    if (pkg === undefined) {
      return undefined;
    }
    const run = (await this.source.report(pkg))?.solutions.find(
      (candidate) => candidate.solution.index === solutionIndex,
    );
    if (run === undefined) {
      return undefined;
    }
    const name = rest.join('/');
    if (name === '') {
      return solutionExpectation(run);
    }
    const group = run.groups.find((candidate) => candidate.name === name);
    return group === undefined ? undefined : groupExpectation(group);
  }
}
