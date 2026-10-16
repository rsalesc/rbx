/**
 * Which files are statement sources, and which package builds each.
 *
 * rbx says, through `rbx statements ls --json` in every problem of the focus
 * (focus.ts) and `rbx contest statements ls --json` in its contest
 * (rbx/statementListing.ts). The manifest parse (declared.ts) answers for every
 * other package, and for one rbx could not -- an rbx too old to have the
 * command, or a manifest mid-edit -- so a statement's button never waits on a
 * process, and never depends on one existing.
 *
 * Each answer is cached per root, and dropped when a YAML file it was read from
 * changes -- `sources`, which names the contest and every `!include`d fragment,
 * neither of which a problem's own manifest gives any sign of. That is what
 * makes `rbx lang add pt` at a contest root, which edits only the contest's
 * list, reach every problem's preview button.
 *
 * The fallback has its own gap, closed in `registerStatementSources`: a file
 * created under a `{lang}` template is a new statement although no manifest
 * changed.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { DeclaredIndex } from './declared';
import { FocusScope } from './focus';
import { log } from './log';
import { DispatchScope } from './rbx/dispatch';
import {
  StatementListing,
  StatementSource,
  listingArgs,
  mergeStatementSources,
  parseStatementListing,
} from './rbx/statementListing';
import { resolveRbx, run } from './rbxProcess';

/**
 * How long one listing may take. It only loads YAML, so anything near this is
 * a stuck interpreter; generous anyway, because a cold `uv run` can be slow.
 */
const LISTING_TIMEOUT_MS = 20_000;

/** At most this many listings at once: a contest opens a dozen packages together. */
const MAX_CONCURRENT_LISTINGS = 4;

/** Collapses the burst of answers a refresh produces into one change event. */
const PUBLISH_DELAY_MS = 100;

/** Re-reading the manifests after a burst of statement files appears (`rbx lang add`). */
const REINDEX_DELAY_MS = 300;

const YAML_GLOB = '**/*.{yml,yaml}';

interface Root {
  readonly root: string;
  readonly scope: DispatchScope;
  /** The contest above a problem, whose files decide its languages. */
  readonly contest?: string;
}

export class StatementSources implements vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<void>();
  /** Fired whenever the set of statement sources may have moved. */
  readonly onDidChange: vscode.Event<void> = this.changed.event;

  private roots: Root[] = [];
  /** One promise per root, settled or in flight; `undefined` means rbx could not say. */
  private readonly listings = new Map<string, Promise<StatementListing | undefined>>();
  /** The settled answers, readable without awaiting. */
  private readonly settled = new Map<string, StatementListing | undefined>();
  private merged = new Map<string, StatementSource>();
  private publishTimer?: ReturnType<typeof setTimeout>;

  private running = 0;
  private readonly waiting: (() => void)[] = [];

  constructor(
    private readonly focus: FocusScope,
    private readonly declared: DeclaredIndex,
  ) {}

  /** What `file` is as a statement source, or `undefined` if it is none. */
  sourceFor(file: string): StatementSource | undefined {
    return this.merged.get(file);
  }

  /** Every known statement source, for the editor button's `when`. */
  paths(): string[] {
    return [...this.merged.keys()];
  }

  /** Re-read which packages are in focus, and ask rbx about any not yet asked. */
  async refresh(): Promise<void> {
    const { contest, problems } = await this.focus.get();
    const roots: Root[] = problems.map((root) => ({ root, scope: 'problem', contest }));
    if (contest !== undefined) {
      roots.push({ root: contest, scope: 'contest' });
    }
    this.roots = roots;

    const current = new Set(roots.map(({ root }) => root));
    for (const root of [...this.listings.keys()]) {
      if (!current.has(root)) {
        this.drop(root);
      }
    }
    // The fallback first, so nothing waits on a process to get its button.
    this.schedulePublish();
    for (const root of roots) {
      void this.listingFor(root);
    }
  }

  /**
   * A YAML file was created, changed or deleted: drop every answer it may
   * have changed, and ask again.
   *
   * An answer names its own sources. A root rbx could not answer for names
   * none, so for it -- and for any root, when a file appears or disappears,
   * which no answer can have named yet (a new contest variant) -- a YAML file
   * directly in the root or in its contest's root counts. Never one further
   * down: that is where `.rbx/` is, which every build rewrites.
   */
  onYamlEvent(file: string, kind: 'create' | 'change' | 'delete'): void {
    const dir = path.dirname(file);
    for (const root of this.roots) {
      const listing = this.settled.get(root.root);
      const named = listing?.sources.includes(file) ?? false;
      const near = dir === root.root || dir === root.contest;
      const unanswered = this.settled.has(root.root) && listing === undefined;
      if (named || (near && (kind !== 'change' || unanswered))) {
        this.drop(root.root);
        void this.listingFor(root);
      }
    }
  }

  dispose(): void {
    clearTimeout(this.publishTimer);
    this.changed.dispose();
  }

  private drop(root: string): void {
    this.listings.delete(root);
    this.settled.delete(root);
  }

  private listingFor(root: Root): Promise<StatementListing | undefined> {
    const cached = this.listings.get(root.root);
    if (cached !== undefined) {
      return cached;
    }
    const pending = this.limited(() => this.load(root)).then((listing) => {
      // Only if this is still the promise on file: a drop during the spawn
      // means the answer describes YAML that has since moved on.
      if (this.listings.get(root.root) === pending) {
        this.settled.set(root.root, listing);
        this.schedulePublish();
      }
      return listing;
    });
    this.listings.set(root.root, pending);
    return pending;
  }

  private async limited<T>(work: () => Promise<T>): Promise<T> {
    while (this.running >= MAX_CONCURRENT_LISTINGS) {
      await new Promise<void>((resolve) => this.waiting.push(resolve));
    }
    this.running++;
    try {
      return await work();
    } finally {
      this.running--;
      this.waiting.shift()?.();
    }
  }

  /** Never rejects: every failure is an `undefined`, i.e. "use the fallback". */
  private async load({ root, scope }: Root): Promise<StatementListing | undefined> {
    try {
      const rbx = await resolveRbx(root);
      if (rbx === undefined) {
        return undefined;
      }
      const args = listingArgs(scope);
      const result = await run(rbx, args, root, LISTING_TIMEOUT_MS);
      if (result.spawnError !== undefined || result.code !== 0) {
        log(
          `rbx ${args.join(' ')} failed in ${root} (exit ${result.code ?? 'none'}); ` +
            `using the manifest's statements there. ${result.stderr.trim()}`,
        );
        return undefined;
      }
      const listing = parseStatementListing(result.stdout);
      if (listing === undefined) {
        log(`Could not read the statements rbx listed for ${root}.`);
      }
      return listing;
    } catch (error) {
      log(`Listing the statements of ${root} threw: ${String(error)}`);
      return undefined;
    }
  }

  private schedulePublish(): void {
    clearTimeout(this.publishTimer);
    this.publishTimer = setTimeout(() => this.publish(), PUBLISH_DELAY_MS);
  }

  private publish(): void {
    const listings: StatementListing[] = [];
    for (const { root } of this.roots) {
      const listing = this.settled.get(root);
      if (listing !== undefined) {
        listings.push(listing);
      }
    }
    this.merged = mergeStatementSources(listings, this.declared.statementDeclarations());
    this.changed.fire();
  }
}

/**
 * The index, wired to what moves it: the manifest index (packages appearing,
 * the fallback changing) and two watchers -- YAML files for rbx's answers, and
 * files created or deleted under a `{lang}` template for the fallback's.
 */
export function registerStatementSources(
  context: vscode.ExtensionContext,
  focus: FocusScope,
  declared: DeclaredIndex,
): StatementSources {
  const sources = new StatementSources(focus, declared);
  void sources.refresh();

  const yaml = vscode.workspace.createFileSystemWatcher(YAML_GLOB);
  const onYaml = (kind: 'create' | 'change' | 'delete') => (uri: vscode.Uri) => {
    if (uri.scheme === 'file') {
      sources.onYamlEvent(uri.fsPath, kind);
    }
  };

  // `**/*`, because a template may name any extension; the test per event is
  // a handful of regexes, cheap next to the build churn it is filtering.
  const files = vscode.workspace.createFileSystemWatcher('**/*', false, true, false);
  let reindex: ReturnType<typeof setTimeout> | undefined;
  const onFile = (uri: vscode.Uri) => {
    if (uri.scheme !== 'file' || !declared.matchesLangTemplate(uri.fsPath)) {
      return;
    }
    clearTimeout(reindex);
    reindex = setTimeout(() => void declared.refresh(), REINDEX_DELAY_MS);
  };

  context.subscriptions.push(
    sources,
    yaml,
    files,
    { dispose: () => clearTimeout(reindex) },
    yaml.onDidCreate(onYaml('create')),
    yaml.onDidChange(onYaml('change')),
    yaml.onDidDelete(onYaml('delete')),
    files.onDidCreate(onFile),
    files.onDidDelete(onFile),
    // A package appearing or disappearing, or the fallback moving.
    declared.onDidChange(() => void sources.refresh()),
    focus.onDidChange(() => void sources.refresh()),
  );
  return sources;
}
