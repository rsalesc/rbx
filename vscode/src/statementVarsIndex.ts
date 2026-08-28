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
const TIMEOUT_MS = 10_000;

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
   * This is also what re-arms the logging. `load` -- the only place that logs
   * -- runs once per cache entry, and a failed load caches its `undefined` like
   * any other answer, so a package with no rbx installed writes one line here
   * and stays silent until a manifest change drops the entry again. Nothing
   * about a hint request can make it log.
   */
  invalidate(root: string): void {
    this.index.delete(root);
    this.changed.fire();
  }

  private async load(root: string): Promise<Vars | undefined> {
    const rbx = await resolveRbx(root);
    if (rbx === undefined) {
      log(`No usable rbx for ${root}; statement var hints are off there.`);
      return undefined;
    }

    const result = await run(rbx, ['vars', '--json'], root, TIMEOUT_MS);
    if (result.spawnError !== undefined || result.code !== 0) {
      // A bad package is the common case here -- `rbx vars` exits non-zero on
      // one -- and it is the setter's own half-typed manifest, not a bug to
      // report. The stderr says which, for when it is not.
      log(`rbx vars failed in ${root} (exit ${result.code}): ${result.stderr.trim()}`);
      return undefined;
    }

    const vars = parseVarsPayload(result.stdout);
    if (vars === undefined) {
      log(`Could not read the vars rbx printed for ${root}.`);
      return undefined;
    }
    return vars;
  }

  /**
   * A spawn already in flight is left to finish.
   *
   * `run` hands back no handle to kill, and there is nothing to kill it for:
   * the command writes nothing, and its own timeout bounds it at
   * `TIMEOUT_MS`. Its result resolves into a map nothing reads any more.
   */
  dispose(): void {
    this.index.clear();
    this.changed.dispose();
  }
}
