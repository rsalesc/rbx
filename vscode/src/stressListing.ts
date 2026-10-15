/**
 * What rbx says a package declares for stress testing, asked headless.
 *
 * problem.rbx.yml may declare solutions by glob (`sols/wa-*.*`), and only rbx
 * knows which files that names -- so the launcher's pickers come from
 * `rbx stress --list --json`, which is read-only by construction (like
 * `rbx vars --json`, see rbxProcess.ts for what makes that safe to spawn).
 *
 * Asked lazily and cached per package. A cached answer is dropped when
 * problem.rbx.yml changes, or when a file is created or deleted in the package
 * -- a glob's expansion depends on exactly that -- and asked again only when
 * someone next wants it. Until it lands, or when rbx cannot answer, the caller
 * falls back to the YAML (`withoutGlobs`) and says why.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { log } from './log';
import { CACHE_DIR, packageLayout } from './rbx/layout';
import { lastJson } from './rbx/promote';
import {
  StressDeclarations,
  listingFailure,
  parseStressListing,
} from './rbx/stressDeclarations';
import { resolveRbx, run } from './rbxProcess';
import type { RunDataChange } from './runData';

/** A package load and a glob walk; anything near this is a stuck interpreter. */
const LISTING_TIMEOUT_MS = 20_000;

/** Files land in bursts (a checkout, a build); one re-ask per burst. */
const DEBOUNCE_MS = 500;

/** rbx's answer for one package: the declarations, or why there are none. */
export type ListingAnswer =
  | { readonly declarations: StressDeclarations }
  | { readonly error: string };

/** What was printed on `stdout`, read as a listing. Multi-line JSON included. */
function readListing(stdout: string): StressDeclarations | undefined {
  const last = parseStressListing(lastJson(stdout));
  if (last !== undefined) {
    return last;
  }
  try {
    return parseStressListing(JSON.parse(stdout) as unknown);
  } catch {
    return undefined;
  }
}

async function ask(root: string): Promise<ListingAnswer> {
  try {
    const rbx = await resolveRbx(root);
    if (rbx === undefined) {
      return { error: 'no usable rbx was found' };
    }
    const result = await run(rbx, ['stress', '--list', '--json'], root, LISTING_TIMEOUT_MS);
    if (result.spawnError !== undefined) {
      return { error: result.spawnError.message };
    }
    if (result.code !== 0) {
      return { error: listingFailure(result.stderr) };
    }
    const declarations = readListing(result.stdout);
    return declarations === undefined
      ? { error: 'rbx printed something other than a listing' }
      : { declarations };
  } catch (error) {
    // Every failure is a fallback, never a rejection cached for the next asker.
    return { error: String(error) };
  }
}

export class StressListing implements vscode.Disposable {
  private readonly answers = new Map<string, ListingAnswer>();
  private readonly pending = new Map<string, Promise<void>>();
  /** Bumped on every invalidation, so an answer to a stale question is dropped. */
  private readonly generation = new Map<string, number>();
  private readonly watchers = new Map<string, vscode.Disposable>();
  private readonly timers = new Map<string, ReturnType<typeof setTimeout>>();
  private readonly changed = new vscode.EventEmitter<string>();
  private readonly subscriptions: vscode.Disposable[] = [];

  /** Fires with a package root whose answer landed or was dropped. */
  readonly onDidChange = this.changed.event;

  constructor(onDataChange: vscode.Event<RunDataChange>) {
    this.subscriptions.push(
      this.changed,
      onDataChange((change) => {
        if (change.plan?.manifest !== true) {
          return;
        }
        const roots =
          change.root === undefined ? [...this.answers.keys(), ...this.pending.keys()] : [change.root];
        roots.forEach((root) => this.invalidate(root));
      }),
    );
  }

  /** rbx's answer for `root` if it has one; asks for it otherwise. */
  peek(root: string): ListingAnswer | undefined {
    const key = path.resolve(root);
    const answer = this.answers.get(key);
    if (answer === undefined && !this.pending.has(key)) {
      this.start(key);
    }
    return answer;
  }

  private start(key: string): void {
    this.watch(key);
    const generation = this.generation.get(key) ?? 0;
    const pending = ask(key).then((answer) => {
      if ((this.generation.get(key) ?? 0) !== generation) {
        return; // Invalidated while asking; the next peek asks again.
      }
      this.pending.delete(key);
      this.answers.set(key, answer);
      if ('error' in answer) {
        log(`rbx stress --list failed in ${key}: ${answer.error}`);
      }
      this.changed.fire(key);
    });
    this.pending.set(key, pending);
  }

  private invalidate(root: string): void {
    const key = path.resolve(root);
    if (!this.answers.has(key) && !this.pending.has(key)) {
      return;
    }
    this.generation.set(key, (this.generation.get(key) ?? 0) + 1);
    this.answers.delete(key);
    this.pending.delete(key);
    this.changed.fire(key);
  }

  /**
   * Re-ask when files come or go in the package: a glob's expansion is the set
   * of files that exist. Edits are ignored (they expand nothing new), and so
   * is everything under rbx's own cache and build directories, which churn
   * through every run.
   */
  private watch(key: string): void {
    if (this.watchers.has(key)) {
      return;
    }
    const ignored = [CACHE_DIR, packageLayout(key).buildDir].map((dir) => path.join(key, dir) + path.sep);
    const watcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(vscode.Uri.file(key), '**/*'),
      false,
      true,
      false,
    );
    const onFile = (uri: vscode.Uri) => {
      if (ignored.some((dir) => uri.fsPath.startsWith(dir))) {
        return;
      }
      clearTimeout(this.timers.get(key));
      this.timers.set(
        key,
        setTimeout(() => {
          this.timers.delete(key);
          this.invalidate(key);
        }, DEBOUNCE_MS),
      );
    };
    this.watchers.set(
      key,
      vscode.Disposable.from(watcher, watcher.onDidCreate(onFile), watcher.onDidDelete(onFile)),
    );
  }

  dispose(): void {
    this.timers.forEach((timer) => clearTimeout(timer));
    this.watchers.forEach((watcher) => watcher.dispose());
    this.subscriptions.forEach((subscription) => subscription.dispose());
  }
}
