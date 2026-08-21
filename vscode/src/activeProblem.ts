/**
 * Which problem the Run view is showing.
 *
 * The single source of truth for the selection: the dropdown, the quick pick
 * and the auto-switch all go through here, so they cannot disagree about what
 * is on screen.
 */
import * as vscode from 'vscode';

import { indexContests } from './contestIndex';
import { packageLabel } from './discovery';
import { log } from './log';
import { packageLayout } from './rbx/layout';
import { ProblemChoice, problemChoices } from './rbx/problems';
import { RunDataProvider } from './runData';

const SELECTED_KEY = 'rbx.selectedProblem';

export class ActiveProblem {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChange: vscode.Event<void> = this.changed.event;

  private choices: ProblemChoice[] = [];
  private selectedRoot?: string;

  constructor(
    private readonly data: RunDataProvider,
    private readonly memento: vscode.Memento,
  ) {
    // Remembered across windows so reopening a contest lands back on the
    // problem being worked on rather than on whichever one sorts first.
    this.selectedRoot = memento.get<string>(SELECTED_KEY);
  }

  /** Rebuild the list after discovery, keeping the selection if it survived. */
  async refresh(): Promise<void> {
    const roots = (await this.data.discovered()).map((pkg) => pkg.root);
    const identities = await indexContests(roots);
    this.choices = problemChoices(roots, identities, (root) => packageLabel(packageLayout(root)));
    if (!this.knows(this.selectedRoot)) {
      // The selected package went away -- deleted, renamed, or moved out of the
      // glob. Falling back to the first keeps the view showing *something*.
      //
      // Not written back to the memento: a package that vanished because a
      // branch was checked out comes back, and the remembered root should come
      // back with it rather than have been overwritten by the fallback.
      this.selectedRoot = this.choices[0]?.root;
    }
    this.changed.fire();
  }

  problems(): readonly ProblemChoice[] {
    return this.choices;
  }

  selected(): string | undefined {
    return this.selectedRoot;
  }

  /** Show a problem. No-op when it is already showing, or is not a problem. */
  select(root: string): void {
    if (root === this.selectedRoot || !this.knows(root)) {
      return;
    }
    this.selectedRoot = root;
    void this.memento.update(SELECTED_KEY, root);
    log(`Showing ${root}.`);
    this.changed.fire();
  }

  /**
   * Follow a run that just started.
   *
   * rbx writes `skeleton.yml` when a run *begins* (rbx/box/solutions.py:746),
   * so this tracks the problem currently running rather than jumping to one
   * that already finished -- during `rbx contest each run` the view walks the
   * contest in step with it.
   *
   * Unlike `select`, an unknown root is not ignored: a package can be created
   * and run before discovery has seen it, and dropping the switch there would
   * leave the view on the wrong problem until the next rediscovery. Which is
   * why the rediscovery asked for here is the provider's and not just this
   * class's: `discovered()` is memoized (see `RunDataProvider.discovery`), so
   * re-reading it would hand back the very list that is missing the package.
   */
  async follow(root: string): Promise<void> {
    if (!this.knows(root)) {
      await this.data.refresh();
      await this.refresh();
    }
    if (!this.knows(root)) {
      // The workspace glob still does not cover it -- a run outside any open
      // folder, or under one of `discovery.ts`'s exclusions. Saying so beats a
      // view that silently stays put while a different problem runs.
      log(`Not following the run in ${root}: it is not a discovered package.`);
    }
    this.select(root);
  }

  private knows(root: string | undefined): boolean {
    return this.choices.some((choice) => choice.root === root);
  }
}
