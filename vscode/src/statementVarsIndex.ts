/**
 * The expanded vars of each problem package, keyed by absolute package root.
 *
 * Asking rbx costs a process spawn, and the answer is consulted on every inlay
 * hint request -- i.e. on every keystroke in a statement file. So it is asked
 * once per package and kept until the manifest that produced it changes.
 *
 * `rbx vars --json` is read-only by construction (rbx/box/cli/commands/
 * vars_cmd.py): it expands `problem.rbx.yml` and touches nothing else, which
 * is what makes it safe to run while the setter is typing.
 */
import * as vscode from 'vscode';

import { log } from './log';
import { Vars } from './rbx/statementVars';
import { parseVarsPayload } from './rbx/varsPayload';
import { resolveRbx, run } from './rbxProcess';

/**
 * How long `rbx vars` may take before we give up on it.
 *
 * Its own constant, between the login-shell probe's 5s and visualize's 120s:
 * the command only parses a YAML file and expands its vars, so anything near
 * this bound is a stuck interpreter rather than slow work.
 */
const VARS_TIMEOUT_MS = 10_000;

export class StatementVarsIndex {
  private readonly changed = new vscode.EventEmitter<void>();
  /** Fired when a package's vars are dropped, so hints can be re-requested. */
  readonly onDidChange: vscode.Event<void> = this.changed.event;

  /**
   * The *promise* per root, not the resolved value.
   *
   * A cold start typically has several hint requests in flight at once (one
   * per visible statement editor), and caching the value would let each of
   * them miss and spawn its own rbx. Caching the promise makes them share the
   * single spawn the first one started.
   *
   * Nothing ever writes a resolved value back into this map, which is what
   * makes `invalidate` during a spawn safe: the stale promise has no way to
   * overwrite the entry a later miss put there. Its result is simply dropped.
   */
  private readonly index = new Map<string, Promise<Vars | undefined>>();

  /** The vars of the package at `root`, or `undefined` if rbx could not say. */
  varsFor(root: string): Promise<Vars | undefined> {
    const cached = this.index.get(root);
    if (cached !== undefined) {
      return cached;
    }
    const pending = this.load(root);
    this.index.set(root, pending);
    return pending;
  }

  /**
   * Drop what is cached for `root` and announce it.
   *
   * This is also what bounds the logging. Asking a root once produces a
   * handful of lines -- `resolveRbx` logs each candidate it rejects, of which
   * there are up to three, and `load` logs whatever went wrong after that --
   * and a failed load caches its `undefined` like any successful answer. So a
   * package with no rbx installed writes that handful once and then stays
   * silent however much the setter types, until a manifest change drops the
   * entry and the next request pays for a fresh look. `resolveRbx` does not
   * cache its own failures; only this cache bounds them.
   */
  invalidate(root: string): void {
    this.index.delete(root);
    this.changed.fire();
  }

  private async load(root: string): Promise<Vars | undefined> {
    // The whole body, because a *rejection* is the one failure mode that is
    // not an absent badge: it would be cached like any other answer, re-thrown
    // into every later hint request for this root, and -- because the promise
    // is cached before it settles -- surface as an unhandledRejection with no
    // handler attached yet. Nothing below is expected to throw today, but D5
    // asks that every failure degrade to no badge, and that has to hold for
    // whatever line is added here next, not only for the ones proved safe now.
    try {
      const rbx = await resolveRbx(root);
      if (rbx === undefined) {
        log(`No usable rbx for ${root}; statement var hints are off there.`);
        return undefined;
      }

      const result = await run(rbx, ['vars', '--json'], root, VARS_TIMEOUT_MS);
      // Split from the exit code below because `run` spells both failures with
      // a null code, and a process that never started wrote no stderr either:
      // the error is the only thing that says what happened.
      if (result.spawnError !== undefined) {
        log(`Could not start rbx in ${root}: ${result.spawnError.message}`);
        return undefined;
      }
      if (result.code !== 0) {
        // A bad package is the common case here -- `rbx vars` exits non-zero
        // on one -- and it is the setter's own half-typed manifest, not a bug
        // to report. A null code that reaches here is the timeout, which `run`
        // reports in the stderr it hands back.
        log(
          `rbx vars failed in ${root} (exit ${result.code ?? 'none'}): ` +
            result.stderr.trim(),
        );
        return undefined;
      }

      const vars = parseVarsPayload(result.stdout);
      if (vars === undefined) {
        log(`Could not read the vars rbx printed for ${root}.`);
        return undefined;
      }
      return vars;
    } catch (error) {
      log(`Asking rbx for the vars of ${root} threw: ${String(error)}`);
      return undefined;
    }
  }

  /**
   * A spawn already in flight is left to finish.
   *
   * `run` hands back no handle to kill, and there is nothing to kill it for:
   * the command writes nothing, and every spawn a load makes -- the probes
   * `resolveRbx` runs as much as `rbx vars` itself -- carries its own timeout,
   * so the whole thing is bounded. Its result resolves into a map nothing
   * reads any more.
   */
  dispose(): void {
    this.index.clear();
    this.changed.dispose();
  }
}
