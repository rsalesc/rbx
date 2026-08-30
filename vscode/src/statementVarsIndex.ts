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
 *
 * A *filtered* reference is not in that map -- what `\VAR{N.max | sci}` shows
 * is whatever the pipeline makes of the value, and evaluating Jinja is rbx's
 * job. So this also holds the second cache: expressions, rendered by `rbx vars
 * --render --target text`, which builds no statement and holds to the same
 * read-only bargain. It is keyed per expression rather than per package because
 * a statement only pays for the filters it actually uses. See
 * docs/plans/2026-08-29-statement-filter-targets-design.md (D3, D5).
 */
import * as vscode from 'vscode';

import { log } from './log';
import { Vars } from './rbx/statementVars';
import { parseVarsPayload } from './rbx/varsPayload';
import { resolveRbx, run } from './rbxProcess';

/**
 * How long `rbx vars` may take before we give up on it, rendering or not.
 *
 * Its own constant, between the login-shell probe's 5s and visualize's 120s:
 * the command parses a YAML file, expands its vars and -- under `--render` --
 * evaluates a handful of Jinja expressions against them, so anything near this
 * bound is a stuck interpreter rather than slow work. The same bound covers
 * both because the rendering is the cheap half of what `--render` does; the
 * package load it shares with `--json` is the rest.
 */
const VARS_TIMEOUT_MS = 10_000;

/** Shared because it is only ever read: nothing rendered, and nothing will be. */
const EMPTY: ReadonlyMap<string, string> = new Map();

/**
 * What is known about the filtered expressions of one package root.
 *
 * Two maps rather than one because they answer two different questions, and
 * the provider needs them at two different times: `text` is read synchronously
 * while hints are being built, and cannot be a map of promises; `asked` is what
 * makes a second request for an expression free, and has to cover the ones
 * still in flight as well as the ones that settled.
 */
interface RootRenders {
  /**
   * Every expression this root has been asked about, settled or in flight,
   * mapped to the text it rendered to -- or to `undefined` for one rbx left out
   * of its answer.
   *
   * **Failures are cached exactly like successes**, and that is the point of
   * this map. A setter halfway through typing `\VAR{N.max | sc` has written a
   * syntactically fine expression that renders to nothing, and it stays on
   * screen for as long as it takes to type the rest: without a memory of having
   * asked, every keystroke would spawn a process to be told the same thing
   * again.
   */
  readonly asked: Map<string, Promise<string | undefined>>;
  /**
   * The subset that came back with text, readable without awaiting anything.
   *
   * Written only where a batch settles, so it cannot drift from `asked`.
   */
  readonly text: Map<string, string>;
}

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

  /**
   * What each root's filtered expressions render to.
   *
   * Kept in this class rather than a sibling one because it is the same cache
   * with a finer key: both halves are the expansion of one `problem.rbx.yml`,
   * both are dropped by the same manifest change, and a sibling would need the
   * same root, the same invalidation call and the same change event wired
   * through `extension.ts` a second time to say nothing new.
   */
  private readonly renders = new Map<string, RootRenders>();

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
   * The rendered text known for `root` right now, keyed by expression.
   *
   * Synchronous and never waits: it is what a hint request can draw without
   * paying for a spawn. An expression missing from it is unasked, still in
   * flight, or one rbx declined to render, and all three mean the same thing to
   * a caller -- no badge. Which of the three it is decides only whether a batch
   * is worth starting, and `renderedFor` answers that itself.
   */
  renderedNow(root: string): ReadonlyMap<string, string> {
    return this.renders.get(root)?.text ?? EMPTY;
  }

  /**
   * What `expressions` render to in the package at `root`.
   *
   * Answered from cache wherever possible; whatever is left over goes to rbx in
   * a single spawn, however many expressions that is. Expressions rbx did not
   * render are absent from the result, exactly as they are absent from its own
   * answer.
   *
   * Never rejects: `render` catches every way the spawn can fail and answers
   * with an empty map, and the bookkeeping around it cannot throw. That matters
   * because a caller leaves this promise unawaited, to keep the rest of its
   * hints from waiting on a process.
   */
  async renderedFor(root: string, expressions: string[]): Promise<Map<string, string>> {
    const entry = this.rootRenders(root);

    const missing = expressions.filter((expression) => !entry.asked.has(expression));
    if (missing.length > 0) {
      // Written into the entry this call captured, never into whatever
      // `this.renders` holds by then. That is what makes an `invalidate` during
      // a spawn safe: it detaches this object from the map, and the answer
      // lands in something nobody reads any more rather than resurrecting vars
      // the manifest has moved on from.
      const batch = this.render(root, missing).then((rendered) => {
        for (const [expression, text] of rendered) {
          entry.text.set(expression, text);
        }
        return rendered;
      });
      // Each expression gets its own promise off the one batch, so a later
      // request naming some of these and some new ones shares this spawn for
      // the overlap instead of asking again.
      for (const expression of missing) {
        entry.asked.set(
          expression,
          batch.then((rendered) => rendered.get(expression)),
        );
      }
    }

    const settled = await Promise.all(
      expressions.map(async (expression) => {
        const text = await entry.asked.get(expression);
        return [expression, text] as const;
      }),
    );
    const result = new Map<string, string>();
    for (const [expression, text] of settled) {
      if (text !== undefined) {
        result.set(expression, text);
      }
    }
    return result;
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
    // The renders go with the vars: a changed `vars` block changes what
    // `N.max | sci` renders to just as surely as what `N.max` expands to, and
    // keeping the expressions would badge the old bound under the new manifest.
    this.renders.delete(root);
    this.changed.fire();
  }

  private rootRenders(root: string): RootRenders {
    const existing = this.renders.get(root);
    if (existing !== undefined) {
      return existing;
    }
    const created: RootRenders = { asked: new Map(), text: new Map() };
    this.renders.set(root, created);
    return created;
  }

  /**
   * Ask rbx to render `expressions`, in one spawn.
   *
   * Same failure posture as `load`, and the same reason for the whole body
   * being wrapped: an expression rbx could not answer for is simply absent from
   * the map, and so is every expression when the process itself failed. The
   * caller cannot tell the two apart, and does not need to -- both draw no
   * badge, and both are remembered so the next keystroke does not ask again.
   */
  private async render(
    root: string,
    expressions: string[],
  ): Promise<ReadonlyMap<string, string>> {
    try {
      const rbx = await resolveRbx(root);
      if (rbx === undefined) {
        log(`No usable rbx for ${root}; filtered statement var hints are off there.`);
        return EMPTY;
      }

      const result = await run(
        rbx,
        ['vars', '--render', '--target', 'text'],
        root,
        VARS_TIMEOUT_MS,
        // One per line, which is how the command reads them; `run` closes the
        // pipe after this write, which is the EOF it reads up to. The trailing
        // newline is only tidiness -- the command splits lines and drops the
        // blank one it produces.
        `${expressions.join('\n')}\n`,
      );
      if (result.spawnError !== undefined) {
        log(`Could not start rbx in ${root}: ${result.spawnError.message}`);
        return EMPTY;
      }
      if (result.code !== 0) {
        // Reserved for "the package could not be read at all": an expression
        // that merely fails to render leaves the exit code 0 and drops out of
        // the map, and rbx names it on stderr.
        log(
          `rbx vars --render failed in ${root} (exit ${result.code ?? 'none'}): ` +
            result.stderr.trim(),
        );
        return EMPTY;
      }

      // The same flat map of strings `--json` prints, so the same reader: the
      // keys are expressions rather than names, which nothing in there cares
      // about.
      const rendered = parseVarsPayload(result.stdout);
      if (rendered === undefined) {
        log(`Could not read the renders rbx printed for ${root}.`);
        return EMPTY;
      }
      return new Map(Object.entries(rendered));
    } catch (error) {
      log(`Asking rbx to render expressions for ${root} threw: ${String(error)}`);
      return EMPTY;
    }
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
    this.renders.clear();
    this.changed.dispose();
  }
}
