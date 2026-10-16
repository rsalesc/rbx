/**
 * The Assets view: contest > problem > asset, as rbx lists them.
 *
 * Not a second Explorer. It shows only what a manifest declares -- no build
 * output, no scratch files -- under the names rbx gives it (`A · cats`, not
 * `problems/cats/`), with what each file is *for* beside it. The listing is
 * `rbx contest assets --json` per contest and `rbx assets --json` per problem
 * outside one (rbx/assetListing.ts); this module only draws it.
 *
 * Read-only: nothing here creates, renames or deletes a file. Rows open what
 * they name, and the inline actions reuse commands that already exist.
 *
 * A listing is cached per root and dropped when one of its `sources` changes,
 * when a file appears or disappears under the root (a glob may now match it),
 * or when the contest variant the dispatcher remembers changes.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { ActiveProblem } from './activeProblem';
import { findContestRoot } from './contestIndex';
import { Dispatcher } from './dispatch';
import { log } from './log';
import {
  AssetListing,
  AssetNode,
  ListedProblem,
  assetListingArgs,
  assetNodes,
  parseAssetListing,
  problemLabel,
} from './rbx/assetListing';
import { resolveRbx, run } from './rbxProcess';
import { RunDataProvider } from './runData';

const VIEW_ID = 'rbx.assets';
const MODE_KEY = 'rbx.assets.mode';
const LISTING_TIMEOUT_MS = 30_000;
const DEBOUNCE_MS = 400;
/** Paths a build or a tool rewrites constantly, and no asset lives under. */
const NOISE = /[\\/](\.rbx|\.box|build|node_modules|\.git)[\\/]/;

type Mode = 'split' | 'flat';

interface Root {
  readonly root: string;
  readonly scope: 'problem' | 'contest';
}

type Result =
  | { readonly kind: 'ok'; readonly listing: AssetListing }
  | { readonly kind: 'error'; readonly message: string };

type Element =
  | { readonly kind: 'root'; readonly root: Root }
  | { readonly kind: 'problem'; readonly problem: ListedProblem; readonly scope: string }
  | { readonly kind: 'message'; readonly id: string; readonly text: string; readonly tooltip?: string; readonly command?: vscode.Command; readonly icon?: string }
  | { readonly kind: 'node'; readonly node: AssetNode };

export class AssetsViewProvider implements vscode.TreeDataProvider<Element>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<Element | undefined>();
  readonly onDidChangeTreeData = this.changed.event;

  private roots: Root[] = [];
  private readonly results = new Map<string, Result>();
  private readonly inflight = new Map<string, Promise<void>>();
  private refreshTimer?: ReturnType<typeof setTimeout>;
  private readonly dirty = new Set<string>();

  constructor(
    private readonly data: RunDataProvider,
    private readonly active: ActiveProblem,
    private readonly dispatcher: Dispatcher,
    private readonly memento: vscode.Memento,
  ) {}

  get mode(): Mode {
    return this.memento.get<Mode>(MODE_KEY, 'split');
  }

  async setMode(mode: Mode): Promise<void> {
    await this.memento.update(MODE_KEY, mode);
    void vscode.commands.executeCommand('setContext', 'rbx.assets.flat', mode === 'flat');
    this.changed.fire(undefined);
  }

  /** Re-discover the roots; with `hard`, also drop every cached listing. */
  async refresh(hard = false): Promise<void> {
    const problems = (await this.data.discovered()).map((pkg) => pkg.root);
    const roots: Root[] = [];
    const contests = new Set<string>();
    for (const root of problems) {
      const contest = await findContestRoot(root);
      if (contest === undefined) {
        roots.push({ root, scope: 'problem' });
      } else if (!contests.has(contest)) {
        contests.add(contest);
        roots.push({ root: contest, scope: 'contest' });
      }
    }
    this.roots = roots;
    if (hard) {
      this.results.clear();
    }
    await this.syncVariantContext();
    this.changed.fire(undefined);
  }

  /** The contest roots that hold more than one contest. */
  async variantRoots(): Promise<string[]> {
    const res: string[] = [];
    for (const { root, scope } of this.roots) {
      if (scope === 'contest' && (await this.dispatcher.contestChoices(root)).length > 1) {
        res.push(root);
      }
    }
    return res;
  }

  private async syncVariantContext(): Promise<void> {
    const roots = await this.variantRoots();
    void vscode.commands.executeCommand('setContext', 'rbx.assets.hasVariants', roots.length > 0);
  }

  /** The variant label shown in the view's title. */
  variantDescription(): string | undefined {
    const parts: string[] = [];
    for (const { root, scope } of this.roots) {
      if (scope !== 'contest') {
        continue;
      }
      const result = this.results.get(root);
      if (result?.kind === 'ok' && result.listing.contest?.variant !== undefined) {
        parts.push(result.listing.contest.variant);
      }
    }
    return parts.length === 0 ? undefined : parts.join(', ');
  }

  /** A file changed on disk: drop the listings it may have moved. */
  onFileEvent(file: string, kind: 'create' | 'change' | 'delete'): void {
    if (NOISE.test(file)) {
      return;
    }
    const isYaml = /\.ya?ml$/.test(file);
    if (kind === 'change' && !isYaml) {
      return;
    }
    for (const { root } of this.roots) {
      const result = this.results.get(root);
      const named = result?.kind === 'ok' && result.listing.sources.includes(file);
      const inside = file.startsWith(root + path.sep);
      if (named || (inside && (kind !== 'change' || result?.kind === 'error'))) {
        this.dirty.add(root);
      }
    }
    this.scheduleReload();
  }

  onContestChanged(contestRoot: string): void {
    this.dirty.add(contestRoot);
    this.scheduleReload();
  }

  private scheduleReload(): void {
    if (this.dirty.size === 0) {
      return;
    }
    clearTimeout(this.refreshTimer);
    this.refreshTimer = setTimeout(() => {
      const roots = [...this.dirty];
      this.dirty.clear();
      for (const root of roots) {
        // Kept on screen until the new answer lands, so the tree never flickers
        // empty on save.
        void this.load(root, true);
      }
    }, DEBOUNCE_MS);
  }

  dispose(): void {
    clearTimeout(this.refreshTimer);
    this.changed.dispose();
  }

  // -------------------------------------------------------------------------

  private load(root: string, force = false): Promise<void> {
    const pending = this.inflight.get(root);
    if (pending !== undefined && !force) {
      return pending;
    }
    const spec = this.roots.find((each) => each.root === root);
    if (spec === undefined) {
      return Promise.resolve();
    }
    const work = this.list(spec).then((result) => {
      if (this.inflight.get(root) === work) {
        this.inflight.delete(root);
      }
      this.results.set(root, result);
      this.changed.fire(undefined);
    });
    this.inflight.set(root, work);
    return work;
  }

  private async list(spec: Root): Promise<Result> {
    const rbx = await resolveRbx(spec.root);
    if (rbx === undefined) {
      return { kind: 'error', message: 'Could not find the rbx executable. Set `rbx.executable`.' };
    }
    const remembered = spec.scope === 'contest' ? this.dispatcher.rememberedVariant(spec.root) : undefined;
    const args = assetListingArgs(spec.scope, remembered === '' ? undefined : remembered);
    const result = await run(rbx, args, spec.root, LISTING_TIMEOUT_MS);
    if (result.spawnError !== undefined || result.code !== 0) {
      log(`rbx ${args.join(' ')} failed in ${spec.root} (exit ${result.code ?? 'none'}): ${result.stderr.trim()}`);
      if (/No such command/.test(result.stderr + result.stdout)) {
        return { kind: 'error', message: 'This rbx is too old to list assets; update it.' };
      }
      const last = (result.stderr.trim() || result.stdout.trim()).split('\n').pop() ?? '';
      return { kind: 'error', message: last || `rbx exited with ${result.code ?? 'no code'}.` };
    }
    const listing = parseAssetListing(result.stdout);
    if (listing === undefined) {
      return { kind: 'error', message: 'Could not read the asset listing rbx printed; update rbx or the extension.' };
    }
    return { kind: 'ok', listing };
  }

  // -------------------------------------------------------------------------

  getTreeItem(element: Element): vscode.TreeItem {
    switch (element.kind) {
      case 'root':
        return this.rootItem(element.root);
      case 'problem':
        return this.problemItem(element.problem, element.scope);
      case 'message': {
        const item = new vscode.TreeItem(element.text, vscode.TreeItemCollapsibleState.None);
        item.id = element.id;
        item.tooltip = element.tooltip ?? element.text;
        item.command = element.command;
        item.iconPath = new vscode.ThemeIcon(element.icon ?? 'info');
        return item;
      }
      case 'node':
        return nodeItem(element.node);
    }
  }

  private rootItem(root: Root): vscode.TreeItem {
    const result = this.results.get(root.root);
    const listing = result?.kind === 'ok' ? result.listing : undefined;
    const label =
      root.scope === 'contest'
        ? (listing?.contest?.title ?? path.basename(root.root))
        : path.basename(root.root);
    const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.Expanded);
    item.id = `root:${root.root}`;
    item.tooltip = root.root;
    if (root.scope === 'contest') {
      item.iconPath = new vscode.ThemeIcon('trophy');
      item.contextValue = 'rbx.assets.contest';
      const variant = listing?.contest?.variant;
      item.description = variant ?? (listing?.contest === undefined ? undefined : 'default contest');
    } else {
      item.iconPath = new vscode.ThemeIcon('package');
    }
    return item;
  }

  private problemItem(problem: ListedProblem, scope: string): vscode.TreeItem {
    const isActive = this.active.selected() === problem.root;
    const item = new vscode.TreeItem(
      problemLabel(problem),
      isActive ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.Collapsed,
    );
    // The id carries the active flag so VS Code re-applies the expansion state
    // when the active problem moves; otherwise it keeps whatever it remembered.
    item.id = `${scope}:problem:${problem.root}${isActive ? ':active' : ''}`;
    item.description = [problem.title, isActive ? '● active' : undefined]
      .filter((part) => part !== undefined)
      .join(' · ');
    item.tooltip = new vscode.MarkdownString(
      [`**${problemLabel(problem)}**`, problem.title, `\`${problem.root}\``, problem.error]
        .filter((part) => part !== undefined)
        .join('\n\n'),
    );
    item.iconPath = new vscode.ThemeIcon(
      problem.error !== undefined ? 'error' : 'symbol-namespace',
      problem.error !== undefined ? new vscode.ThemeColor('errorForeground') : undefined,
    );
    item.contextValue = 'rbx.assets.problem';
    return item;
  }

  async getChildren(element?: Element): Promise<Element[]> {
    if (element === undefined) {
      if (this.roots.length === 0) {
        return [];
      }
      if (this.roots.length === 1) {
        return this.rootChildren(this.roots[0]);
      }
      return this.roots.map((root) => ({ kind: 'root', root }));
    }
    switch (element.kind) {
      case 'root':
        return this.rootChildren(element.root);
      case 'problem':
        return this.problemChildren(element.problem, element.scope);
      case 'node':
        return element.node.kind === 'asset'
          ? []
          : element.node.children.map((node) => ({ kind: 'node', node }));
      default:
        return [];
    }
  }

  private async rootChildren(root: Root): Promise<Element[]> {
    if (!this.results.has(root.root)) {
      await this.load(root.root);
      void this.syncTitle();
    }
    const result = this.results.get(root.root);
    if (result === undefined) {
      return [];
    }
    if (result.kind === 'error') {
      return [
        {
          kind: 'message',
          id: `error:${root.root}`,
          text: result.message,
          icon: 'warning',
          command: { command: 'rbx.showLog', title: 'Show log' },
        },
      ];
    }
    const { listing } = result;
    if (listing.scope === 'problem') {
      const problem = listing.problems[0];
      // Outside a contest the problem node itself is the root's only child;
      // show it anyway, so the letter-less name and its error still read.
      return problem === undefined ? [] : [{ kind: 'problem', problem, scope: root.root }];
    }
    const out: Element[] = [];
    if (listing.contest === undefined) {
      out.push({
        kind: 'message',
        id: `choose:${root.root}`,
        text: 'Choose a contest to list its problems',
        icon: 'versions',
        command: { command: 'rbx.assets.chooseContest', title: 'Choose contest', arguments: [root.root] },
      });
      return out;
    }
    const contestNodes = assetNodes(`${root.root}:contest`, listing.contest.assets, listing.contest.root, this.mode);
    out.push(...contestNodes.map((node): Element => ({ kind: 'node', node })));
    out.push(...listing.problems.map((problem): Element => ({ kind: 'problem', problem, scope: root.root })));
    return out;
  }

  private problemChildren(problem: ListedProblem, scope: string): Element[] {
    if (problem.error !== undefined) {
      return [
        {
          kind: 'message',
          id: `${scope}:error:${problem.root}`,
          text: problem.error,
          icon: 'error',
          command: {
            command: 'vscode.open',
            title: 'Open problem.rbx.yml',
            arguments: [vscode.Uri.file(path.join(problem.root, 'problem.rbx.yml'))],
          },
        },
      ];
    }
    return assetNodes(`${scope}:${problem.root}`, problem.assets, problem.root, this.mode).map((node) => ({
      kind: 'node',
      node,
    }));
  }

  private titleListener?: () => void;

  onTitleChange(listener: () => void): void {
    this.titleListener = listener;
  }

  private async syncTitle(): Promise<void> {
    this.titleListener?.();
  }
}

function nodeItem(node: AssetNode): vscode.TreeItem {
  if (node.kind === 'asset') {
    const uri = vscode.Uri.file(node.asset.path);
    const item = new vscode.TreeItem(node.label, vscode.TreeItemCollapsibleState.None);
    item.id = node.id;
    item.resourceUri = uri;
    item.description = node.description;
    item.tooltip = node.asset.path;
    item.iconPath = vscode.ThemeIcon.File;
    item.command = { command: 'vscode.open', title: 'Open', arguments: [uri] };
    item.contextValue = `rbx.asset.${node.asset.category}`;
    return item;
  }
  const item = new vscode.TreeItem(node.label, vscode.TreeItemCollapsibleState.Collapsed);
  item.id = node.id;
  item.description = node.description;
  item.iconPath = new vscode.ThemeIcon(node.kind === 'category' ? node.icon : 'folder');
  item.contextValue = node.kind === 'category' ? 'rbx.assets.category' : 'rbx.assets.folder';
  return item;
}

function uriOf(element: unknown): vscode.Uri | undefined {
  if (element instanceof vscode.Uri) {
    return element;
  }
  const node = (element as { node?: AssetNode } | undefined)?.node;
  return node?.kind === 'asset' ? vscode.Uri.file(node.asset.path) : undefined;
}

export function registerAssetsView(
  context: vscode.ExtensionContext,
  data: RunDataProvider,
  active: ActiveProblem,
  dispatcher: Dispatcher,
): AssetsViewProvider {
  const provider = new AssetsViewProvider(data, active, dispatcher, context.workspaceState);
  const view = vscode.window.createTreeView(VIEW_ID, { treeDataProvider: provider, showCollapseAll: true });
  const syncDescription = () => {
    view.description = provider.variantDescription();
  };
  provider.onTitleChange(syncDescription);
  void vscode.commands.executeCommand('setContext', 'rbx.assets.flat', provider.mode === 'flat');

  const watcher = vscode.workspace.createFileSystemWatcher('**/*');
  const on = (kind: 'create' | 'change' | 'delete') => (uri: vscode.Uri) => {
    if (uri.scheme === 'file') {
      provider.onFileEvent(uri.fsPath, kind);
    }
  };

  context.subscriptions.push(
    provider,
    view,
    watcher,
    watcher.onDidCreate(on('create')),
    watcher.onDidChange(on('change')),
    watcher.onDidDelete(on('delete')),
    provider.onDidChangeTreeData(syncDescription),
    dispatcher.onDidChangeContest((root) => provider.onContestChanged(root)),
    data.onDidChange((change) => {
      // A rediscovery (no root) may have added or removed a package.
      if (change.root === undefined) {
        void provider.refresh();
      }
    }),
    active.onDidChange(() => void provider.refresh()),
    vscode.commands.registerCommand('rbx.assets.refresh', () => provider.refresh(true)),
    vscode.commands.registerCommand('rbx.assets.flat', () => provider.setMode('flat')),
    vscode.commands.registerCommand('rbx.assets.split', () => provider.setMode('split')),
    vscode.commands.registerCommand('rbx.assets.chooseContest', async (arg?: unknown) => {
      let root = typeof arg === 'string' ? arg : undefined;
      if (root === undefined) {
        const roots = await provider.variantRoots();
        if (roots.length === 0) {
          void vscode.window.showInformationMessage('rbx: no directory here holds more than one contest.');
          return;
        }
        root =
          roots.length === 1
            ? roots[0]
            : (await vscode.window.showQuickPick(roots, { placeHolder: 'Which contest directory?' }));
      }
      if (root !== undefined) {
        await dispatcher.chooseContest(root);
      }
    }),
    vscode.commands.registerCommand('rbx.assets.preview', (element: unknown) =>
      vscode.commands.executeCommand('rbx.openStatementPreview', uriOf(element)),
    ),
    vscode.commands.registerCommand('rbx.assets.run', (element: unknown) =>
      vscode.commands.executeCommand('rbx.runSolution', uriOf(element)),
    ),
    vscode.commands.registerCommand('rbx.assets.openToSide', (element: unknown) => {
      const uri = uriOf(element);
      return uri === undefined
        ? undefined
        : vscode.commands.executeCommand('vscode.open', uri, { viewColumn: vscode.ViewColumn.Beside });
    }),
    vscode.commands.registerCommand('rbx.assets.reveal', (element: unknown) => {
      const uri = uriOf(element);
      return uri === undefined ? undefined : vscode.commands.executeCommand('revealInExplorer', uri);
    }),
    vscode.commands.registerCommand('rbx.assets.copyPath', async (element: unknown) => {
      const uri = uriOf(element);
      if (uri !== undefined) {
        await vscode.env.clipboard.writeText(uri.fsPath);
      }
    }),
  );
  void provider.refresh();
  return provider;
}
