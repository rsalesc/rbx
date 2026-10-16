/**
 * The focus (rbx/focus.ts) of this window, following the selected problem.
 *
 * Follows `ActiveProblem` rather than the active editor: the selection is what
 * the Run view already shows and what a run already moves, and peeking at a
 * file in another contest should not cost a dozen listings. Packages outside
 * the focus keep everything that is read off disk -- the manifest badges, the
 * run and test views -- and are asked about only when the user acts on them.
 */
import * as vscode from 'vscode';

import { ActiveProblem } from './activeProblem';
import { findContestRoot } from './contestIndex';
import { log } from './log';
import { EMPTY_FOCUS, Focus, focusCandidates, sameFocus } from './rbx/focus';
import { RunDataProvider } from './runData';

export class FocusScope implements vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<void>();
  /** Fired only when the focus holds different packages, never on a move inside it. */
  readonly onDidChange: vscode.Event<void> = this.changed.event;

  private current: Focus = EMPTY_FOCUS;
  private computed?: Promise<void>;
  /** Bumped per recompute, so a slow one cannot land over a newer answer. */
  private generation = 0;
  private readonly disposables: vscode.Disposable[] = [];

  constructor(
    private readonly data: RunDataProvider,
    private readonly active: ActiveProblem,
  ) {
    this.disposables.push(
      this.changed,
      active.onDidChange(() => void this.recompute()),
      // A rediscovery (no root) may have added a problem to the contest.
      data.onDidChange((change) => {
        if (change.root === undefined) {
          void this.recompute();
        }
      }),
    );
  }

  /** The current focus, computed first if nothing has asked yet. */
  async get(): Promise<Focus> {
    if (this.computed === undefined) {
      this.computed = this.recompute();
    }
    await this.computed;
    return this.current;
  }

  dispose(): void {
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
  }

  private recompute(): Promise<void> {
    const generation = ++this.generation;
    const work = this.compute().then((next) => {
      if (generation !== this.generation || sameFocus(next, this.current)) {
        return;
      }
      this.current = next;
      log(
        next.contest !== undefined
          ? `Focused on contest ${next.contest} (${next.problems.length} problem(s)).`
          : `Focused on ${next.problems[0] ?? 'nothing'}.`,
      );
      this.changed.fire();
    });
    this.computed = work;
    return work;
  }

  private async compute(): Promise<Focus> {
    const problems = (await this.data.discovered()).map((pkg) => pkg.root);
    const selected = this.active.selected();
    if (selected === undefined || !problems.includes(selected)) {
      return EMPTY_FOCUS;
    }
    const contest = await findContestRoot(selected);
    if (contest === undefined) {
      return { problems: [selected] };
    }
    const members: string[] = [];
    for (const root of focusCandidates(contest, problems)) {
      // The same upward walk the selected problem took: a nested contest
      // further down claims its own problems.
      if ((await findContestRoot(root)) === contest) {
        members.push(root);
      }
    }
    return { contest, problems: members };
  }
}
