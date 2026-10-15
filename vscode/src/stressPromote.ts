/**
 * Promote on a stress finding (#908): `rbx.stress.promote`.
 *
 * A finding is promoted like any other test (promoter.ts), as `finding:K`.
 * What this adds is the stress session around it: the finding must still be
 * the latest session's -- `--session` makes rbx refuse one a newer session
 * has replaced, and this says so sooner -- and once the promotion is written
 * the finding's row is badged with the group it went to.
 *
 * Not while the session runs: `--slowest` may still renumber its findings.
 * The view shows Promote disabled then; this refuses too, for a click that
 * raced the state change.
 */
import * as vscode from 'vscode';

import { log } from './log';
import { Promoter } from './promoter';
import { findingGone } from './stressCommands';
import type { PromoteArgs, StressViewProvider } from './stressView';

function asPromoteArgs(raw: unknown): PromoteArgs | undefined {
  if (typeof raw !== 'object' || raw === null) {
    return undefined;
  }
  const { root, finding, session } = raw as Record<string, unknown>;
  if (typeof root !== 'string' || typeof finding !== 'number') {
    return undefined;
  }
  return { root, finding, ...(typeof session === 'string' ? { session } : {}) };
}

export class StressPromoter {
  constructor(
    private readonly stress: StressViewProvider,
    private readonly promoter: Promoter,
  ) {}

  /** `rbx.stress.promote`. */
  async promote(raw: unknown): Promise<void> {
    const args = asPromoteArgs(raw);
    if (args === undefined) {
      log(`rbx.stress.promote called with unexpected arguments: ${JSON.stringify(raw)}`);
      return;
    }
    const { root } = args;
    const manifest = await this.stress.sessionFor(root, args.session);
    const finding = manifest?.findings.find((each) => each.index === args.finding);
    if (manifest === undefined || finding === undefined) {
      findingGone(args.finding);
      return;
    }
    const k = finding.index;
    if (this.stress.isRunning(root, manifest)) {
      void vscode.window.showInformationMessage(
        `rbx: wait for the stress to finish before promoting finding #${k} -- ` +
          'its findings may still change while it runs.',
      );
      return;
    }
    const startedAt = manifest.startedAt;
    await this.promoter.promote({
      root,
      sources: [`finding:${k}`],
      label: `finding #${k}`,
      ...(startedAt === undefined ? {} : { session: startedAt }),
      stillThere: () => this.stillThere(root, k, startedAt),
      onPromoted: (group) => this.stress.markPromoted(root, startedAt, k, group),
    });
  }

  /**
   * Whether finding `k` of the session that started at `startedAt` is still
   * the latest session's -- or false, having said so. Checked again after the
   * pickers and the input boxes, which wait on the user for as long as they
   * like.
   */
  private async stillThere(root: string, k: number, startedAt: string | undefined): Promise<boolean> {
    const manifest = await this.stress.sessionFor(root, startedAt);
    if (manifest === undefined || !manifest.findings.some((each) => each.index === k)) {
      findingGone(k);
      return false;
    }
    return true;
  }
}
