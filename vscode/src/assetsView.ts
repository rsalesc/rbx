/**
 * The Assets view, drawn from rbx's asset listing.
 *
 * Neither is a second Explorer. They show only what a manifest declares -- no
 * build output, no scratch files -- under the names rbx gives it (`A · cats`,
 * not `problems/cats/`), with what each file is *for* beside it. The listing
 * is `rbx contest assets --json` per contest and `rbx assets --json` per
 * problem outside one (rbx/assetListing.ts); this module only draws it.
 *
 * One view, two layouts, toggled from its title bar:
 * - **Across problems** (the default): the inverted index -- slot > problem,
 *   where a slot is an asset every problem may have ("en statement", "Main
 *   solution") and each problem is a leaf opening its own file.
 * - **By problem**: contest > problem > asset, split into categories or flat.
 *
 * A statement row opens the source with the statement preview beside it; its
 * inline button opens the source alone.
 *
 * Read-only: nothing here creates, renames or deletes a file. Rows open what
 * they name, and the inline actions reuse commands that already exist.
 *
 * One `AssetListings` store feeds both layouts, so rbx is asked once per root.
 * A listing is dropped when one of its `sources` changes, when a file appears
 * or disappears under the root (a glob may now match it), or when the contest
 * variant the dispatcher remembers changes.
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
  ListedAsset,
  ListedProblem,
  assetListingArgs,
  assetNodes,
  parseAssetListing,
  problemLabel,
  problemSlots,
  slotCatalog,
} from './rbx/assetListing';
import { resolveRbx, run } from './rbxProcess';
import { RunDataProvider } from './runData';
import { StatementPreviewPanel } from './statementPreview';

const ASSETS_VIEW = 'rbx.assets';
const LAYOUT_KEY = 'rbx.assets.layout';
const MODE_KEY = 'rbx.assets.mode';
const SLOTS_KEY = 'rbx.across.slots';
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

// ---------------------------------------------------------------------------
// The shared store.

export class AssetListings implements vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<void>();
  /** Fired when the roots or any listing moved. */
  readonly onDidChange = this.changed.event;

  private roots: Root[] = [];
  private readonly results = new Map<string, Result>();
  private readonly inflight = new Map<string, Promise<void>>();
  private readonly dirty = new Set<string>();
  private reloadTimer?: ReturnType<typeof setTimeout>;

  constructor(
    private readonly data: RunDataProvider,
    private readonly dispatcher: Dispatcher,
  ) {}

  allRoots(): readonly Root[] {
    return this.roots;
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
    const variants = await this.variantRoots();
    void vscode.commands.executeCommand('setContext', 'rbx.assets.hasVariants', variants.length > 0);
    this.changed.fire();
  }

  /** The listing of `root`, asking rbx if it has not been asked yet. */
  async resultFor(root: string): Promise<Result | undefined> {
    if (!this.results.has(root)) {
      await this.load(root);
    }
    return this.results.get(root);
  }

  /** What is on file for `root`, without asking. */
  peek(root: string): Result | undefined {
    return this.results.get(root);
  }

  /** The listed problem declaring `file`, as rbx expanded it (globs included). */
  problemDeclaring(file: string): ListedProblem | undefined {
    for (const result of this.results.values()) {
      if (result.kind !== 'ok') {
        continue;
      }
      const problem = result.listing.problems.find((each) => each.assets.some((asset) => asset.path === file));
      if (problem !== undefined) {
        return problem;
      }
    }
    return undefined;
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

  /** The variant(s) in use, for a view's title. */
  variantDescription(): string | undefined {
    const parts: string[] = [];
    for (const { root, scope } of this.roots) {
      const result = this.results.get(root);
      if (scope === 'contest' && result?.kind === 'ok' && result.listing.contest?.variant !== undefined) {
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
    if (kind === 'change' && !/\.ya?ml$/.test(file)) {
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

  dispose(): void {
    clearTimeout(this.reloadTimer);
    this.changed.dispose();
  }

  private scheduleReload(): void {
    if (this.dirty.size === 0) {
      return;
    }
    clearTimeout(this.reloadTimer);
    this.reloadTimer = setTimeout(() => {
      const roots = [...this.dirty];
      this.dirty.clear();
      for (const root of roots) {
        // The old answer stays on screen until the new one lands, so the tree
        // never flickers empty on save.
        void this.load(root, true);
      }
    }, DEBOUNCE_MS);
  }

  private load(root: string, force = false): Promise<void> {
    const pending = this.inflight.get(root);
    if (pending !== undefined && !force) {
      return pending;
    }
    const spec = this.roots.find((each) => each.root === root);
    if (spec === undefined) {
      return Promise.resolve();
    }
    const work: Promise<void> = this.list(spec).then((result) => {
      if (this.inflight.get(root) === work) {
        this.inflight.delete(root);
      }
      this.results.set(root, result);
      this.changed.fire();
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
}

// ---------------------------------------------------------------------------
// Elements shared by both views.

type Element =
  | { readonly kind: 'root'; readonly root: Root }
  | { readonly kind: 'problem'; readonly problem: ListedProblem; readonly scope: string }
  | {
      readonly kind: 'message';
      readonly id: string;
      readonly text: string;
      readonly tooltip?: string;
      readonly command?: vscode.Command;
      readonly icon?: string;
    }
  | { readonly kind: 'node'; readonly node: AssetNode }
  | { readonly kind: 'slot'; readonly id: string; readonly label: string; readonly description: string; readonly leaves: readonly Element[] }
  | { readonly kind: 'leaf'; readonly id: string; readonly problem: ListedProblem; readonly asset?: ListedAsset };

function messageItem(element: Extract<Element, { kind: 'message' }>): vscode.TreeItem {
  const item = new vscode.TreeItem(element.text, vscode.TreeItemCollapsibleState.None);
  item.id = element.id;
  item.tooltip = element.tooltip ?? element.text;
  item.command = element.command;
  item.iconPath = new vscode.ThemeIcon(element.icon ?? 'info');
  return item;
}

function rootItem(root: Root, result: Result | undefined): vscode.TreeItem {
  const listing = result?.kind === 'ok' ? result.listing : undefined;
  const label =
    root.scope === 'contest' ? (listing?.contest?.title ?? path.basename(root.root)) : path.basename(root.root);
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

/** The message rows standing in for a root rbx could not list. */
function rootTrouble(root: Root, result: Result | undefined): Element[] | undefined {
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
  if (result.listing.scope === 'contest' && result.listing.contest === undefined) {
    return [
      {
        kind: 'message',
        id: `choose:${root.root}`,
        text: 'Choose a contest to list its problems',
        icon: 'versions',
        command: { command: 'rbx.assets.chooseContest', title: 'Choose contest', arguments: [root.root] },
      },
    ];
  }
  return undefined;
}

function nodeItem(node: AssetNode): vscode.TreeItem {
  if (node.kind === 'asset') {
    return fileItem(node.id, node.label, node.description, node.asset);
  }
  const item = new vscode.TreeItem(node.label, vscode.TreeItemCollapsibleState.Collapsed);
  item.id = node.id;
  item.description = node.description;
  item.iconPath = new vscode.ThemeIcon(node.kind === 'category' ? node.icon : 'folder');
  item.contextValue = node.kind === 'category' ? 'rbx.assets.category' : 'rbx.assets.folder';
  return item;
}

function fileItem(id: string, label: string, description: string, asset: ListedAsset): vscode.TreeItem {
  const uri = vscode.Uri.file(asset.path);
  const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
  item.id = id;
  item.resourceUri = uri;
  item.description = description;
  item.tooltip = asset.path;
  item.iconPath = vscode.ThemeIcon.File;
  // A statement is read as much as edited: clicking one opens the source with
  // its preview beside it (which builds it); the inline button opens the
  // source alone.
  item.command =
    asset.category === 'statement'
      ? { command: 'rbx.assets.openStatement', title: 'Open Statement and Preview', arguments: [uri] }
      : { command: 'vscode.open', title: 'Open', arguments: [uri] };
  item.contextValue = `rbx.asset.${asset.category}`;
  return item;
}

// ---------------------------------------------------------------------------
// Assets: contest > problem > asset.

export class AssetsViewProvider implements vscode.TreeDataProvider<Element> {
  private readonly changed = new vscode.EventEmitter<Element | undefined>();
  readonly onDidChangeTreeData = this.changed.event;

  constructor(
    private readonly store: AssetListings,
    private readonly active: ActiveProblem,
    private readonly memento: vscode.Memento,
  ) {}

  get mode(): Mode {
    return this.memento.get<Mode>(MODE_KEY, 'split');
  }

  async setMode(mode: Mode): Promise<void> {
    await this.memento.update(MODE_KEY, mode);
    void vscode.commands.executeCommand('setContext', 'rbx.assets.flat', mode === 'flat');
    this.redraw();
  }

  redraw(): void {
    this.changed.fire(undefined);
  }

  getTreeItem(element: Element): vscode.TreeItem {
    switch (element.kind) {
      case 'root':
        return rootItem(element.root, this.store.peek(element.root.root));
      case 'problem':
        return this.problemItem(element.problem, element.scope);
      case 'message':
        return messageItem(element);
      case 'node':
        return nodeItem(element.node);
      default:
        return new vscode.TreeItem('');
    }
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
      const roots = this.store.allRoots();
      if (roots.length === 1) {
        return this.rootChildren(roots[0]);
      }
      return roots.map((root) => ({ kind: 'root', root }));
    }
    switch (element.kind) {
      case 'root':
        return this.rootChildren(element.root);
      case 'problem':
        return this.problemChildren(element.problem, element.scope);
      case 'node':
        return element.node.kind === 'asset' ? [] : element.node.children.map((node) => ({ kind: 'node', node }));
      default:
        return [];
    }
  }

  private async rootChildren(root: Root): Promise<Element[]> {
    const result = await this.store.resultFor(root.root);
    const trouble = rootTrouble(root, result);
    if (trouble !== undefined || result?.kind !== 'ok') {
      return trouble ?? [];
    }
    const { listing } = result;
    const out: Element[] = [];
    if (listing.contest !== undefined) {
      const nodes = assetNodes(`${root.root}:contest`, listing.contest.assets, listing.contest.root, this.mode);
      out.push(...nodes.map((node): Element => ({ kind: 'node', node })));
    }
    out.push(...listing.problems.map((problem): Element => ({ kind: 'problem', problem, scope: root.root })));
    return out;
  }

  private problemChildren(problem: ListedProblem, scope: string): Element[] {
    if (problem.error !== undefined) {
      return [problemError(problem, scope)];
    }
    return assetNodes(`${scope}:${problem.root}`, problem.assets, problem.root, this.mode).map((node) => ({
      kind: 'node',
      node,
    }));
  }
}

function problemError(problem: ListedProblem, scope: string): Element {
  return {
    kind: 'message',
    id: `${scope}:error:${problem.root}`,
    text: problem.error ?? '',
    icon: 'error',
    command: {
      command: 'vscode.open',
      title: 'Open problem.rbx.yml',
      arguments: [vscode.Uri.file(path.join(problem.root, 'problem.rbx.yml'))],
    },
  };
}

// ---------------------------------------------------------------------------
// Across Problems: slot > problem.

export class AcrossProblemsProvider implements vscode.TreeDataProvider<Element> {
  private readonly changed = new vscode.EventEmitter<Element | undefined>();
  readonly onDidChangeTreeData = this.changed.event;

  constructor(
    private readonly store: AssetListings,
    private readonly memento: vscode.Memento,
  ) {}

  /** The chosen slot keys; `undefined` means every slot found. */
  get chosen(): readonly string[] | undefined {
    return this.memento.get<string[]>(SLOTS_KEY);
  }

  redraw(): void {
    this.changed.fire(undefined);
  }

  /** Every problem across every listed root, in listing order. */
  private async problems(): Promise<{ root: Root; problems: readonly ListedProblem[] }[]> {
    const res = [];
    for (const root of this.store.allRoots()) {
      const result = await this.store.resultFor(root.root);
      res.push({ root, problems: result?.kind === 'ok' ? result.listing.problems : [] });
    }
    return res;
  }

  async chooseSlots(): Promise<void> {
    const all = (await this.problems()).flatMap((each) => each.problems);
    const total = all.length;
    const catalog = slotCatalog(all);
    if (catalog.length === 0) {
      void vscode.window.showInformationMessage('rbx: no assets listed yet.');
      return;
    }
    const chosen = this.chosen;
    const items = catalog.map((entry) => ({
      label: entry.slot.label,
      description: `${entry.count}/${total} problems`,
      picked: chosen === undefined || chosen.includes(entry.slot.key),
      key: entry.slot.key,
    }));
    const picked = await vscode.window.showQuickPick(items, {
      canPickMany: true,
      title: 'Which assets to line up across problems?',
    });
    if (picked === undefined) {
      return;
    }
    await this.memento.update(
      SLOTS_KEY,
      picked.length === items.length ? undefined : picked.map((item) => item.key),
    );
    this.redraw();
  }

  getTreeItem(element: Element): vscode.TreeItem {
    switch (element.kind) {
      case 'root':
        return rootItem(element.root, this.store.peek(element.root.root));
      case 'message':
        return messageItem(element);
      case 'slot': {
        const item = new vscode.TreeItem(element.label, vscode.TreeItemCollapsibleState.Expanded);
        item.id = element.id;
        item.description = element.description;
        item.iconPath = new vscode.ThemeIcon('layers');
        return item;
      }
      case 'leaf':
        return this.leafItem(element);
      default:
        return new vscode.TreeItem('');
    }
  }

  private leafItem(leaf: Extract<Element, { kind: 'leaf' }>): vscode.TreeItem {
    const label = problemLabel(leaf.problem);
    if (leaf.asset === undefined) {
      const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
      item.id = leaf.id;
      item.description = leaf.problem.error !== undefined ? 'failed to load' : 'none';
      item.tooltip = leaf.problem.error ?? `${label} declares no such asset.`;
      item.iconPath = new vscode.ThemeIcon('circle-slash', new vscode.ThemeColor('disabledForeground'));
      return item;
    }
    const relative = path.relative(leaf.problem.root, leaf.asset.path);
    const item = fileItem(leaf.id, label, relative, leaf.asset);
    item.tooltip = leaf.asset.path;
    return item;
  }

  async getChildren(element?: Element): Promise<Element[]> {
    if (element === undefined) {
      const groups = await this.problems();
      if (groups.length === 1) {
        return this.rootChildren(groups[0].root);
      }
      return groups.map(({ root }) => ({ kind: 'root', root }));
    }
    switch (element.kind) {
      case 'root':
        return this.rootChildren(element.root);
      case 'slot':
        return [...element.leaves];
      default:
        return [];
    }
  }

  private async rootChildren(root: Root): Promise<Element[]> {
    const result = await this.store.resultFor(root.root);
    const trouble = rootTrouble(root, result);
    if (trouble !== undefined || result?.kind !== 'ok') {
      return trouble ?? [];
    }
    const problems = result.listing.problems;
    const filled = problems.map((problem) => problemSlots(problem));
    const chosen = this.chosen;
    return slotCatalog(problems)
      .filter((entry) => chosen === undefined || chosen.includes(entry.slot.key))
      .map((entry): Element => {
        const id = `${root.root}:slot:${entry.slot.key}`;
        return {
          kind: 'slot',
          id,
          label: entry.slot.label,
          description: entry.count === problems.length ? '' : `${entry.count}/${problems.length}`,
          leaves: problems.map(
            (problem, index): Element => ({
              kind: 'leaf',
              id: `${id}:${problem.root}`,
              problem,
              asset: filled[index].get(entry.slot.key),
            }),
          ),
        };
      });
  }
}

// ---------------------------------------------------------------------------
// One view, two layouts: across problems (the default) or by problem.

type Layout = 'across' | 'problem';

class LayoutSwitch implements vscode.TreeDataProvider<Element>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<Element | undefined>();
  readonly onDidChangeTreeData = this.changed.event;
  private readonly subscriptions: vscode.Disposable[];

  constructor(
    private readonly byProblem: AssetsViewProvider,
    private readonly across: AcrossProblemsProvider,
    private readonly memento: vscode.Memento,
  ) {
    // Either layout redrawing redraws the view; the inactive one is cheap,
    // since nothing asks it for children.
    this.subscriptions = [
      byProblem.onDidChangeTreeData(() => this.changed.fire(undefined)),
      across.onDidChangeTreeData(() => this.changed.fire(undefined)),
    ];
  }

  get layout(): Layout {
    return this.memento.get<Layout>(LAYOUT_KEY, 'across');
  }

  async setLayout(layout: Layout): Promise<void> {
    await this.memento.update(LAYOUT_KEY, layout);
    this.syncContext();
    this.changed.fire(undefined);
  }

  syncContext(): void {
    void vscode.commands.executeCommand('setContext', 'rbx.assets.across', this.layout === 'across');
  }

  private get current(): vscode.TreeDataProvider<Element> {
    return this.layout === 'across' ? this.across : this.byProblem;
  }

  getTreeItem(element: Element): vscode.TreeItem | Thenable<vscode.TreeItem> {
    return this.current.getTreeItem(element);
  }

  getChildren(element?: Element): vscode.ProviderResult<Element[]> {
    return this.current.getChildren(element);
  }

  dispose(): void {
    this.subscriptions.forEach((each) => each.dispose());
    this.changed.dispose();
  }
}

function uriOf(element: unknown): vscode.Uri | undefined {
  if (element instanceof vscode.Uri) {
    return element;
  }
  const record = element as { node?: AssetNode; asset?: ListedAsset } | undefined;
  if (record?.node?.kind === 'asset') {
    return vscode.Uri.file(record.node.asset.path);
  }
  return record?.asset === undefined ? undefined : vscode.Uri.file(record.asset.path);
}

export function registerAssetsView(
  context: vscode.ExtensionContext,
  data: RunDataProvider,
  active: ActiveProblem,
  dispatcher: Dispatcher,
): void {
  const store = new AssetListings(data, dispatcher);
  const assets = new AssetsViewProvider(store, active, context.workspaceState);
  const across = new AcrossProblemsProvider(store, context.workspaceState);
  const layout = new LayoutSwitch(assets, across, context.workspaceState);
  const assetsView = vscode.window.createTreeView(ASSETS_VIEW, { treeDataProvider: layout, showCollapseAll: true });
  void vscode.commands.executeCommand('setContext', 'rbx.assets.flat', assets.mode === 'flat');
  layout.syncContext();

  const redraw = () => {
    assets.redraw();
    across.redraw();
    assetsView.description = store.variantDescription();
  };

  const watcher = vscode.workspace.createFileSystemWatcher('**/*');
  const on = (kind: 'create' | 'change' | 'delete') => (uri: vscode.Uri) => {
    if (uri.scheme === 'file') {
      store.onFileEvent(uri.fsPath, kind);
    }
  };

  context.subscriptions.push(
    store,
    layout,
    assetsView,
    watcher,
    watcher.onDidCreate(on('create')),
    watcher.onDidChange(on('change')),
    watcher.onDidDelete(on('delete')),
    store.onDidChange(redraw),
    dispatcher.onDidChangeContest((root) => store.onContestChanged(root)),
    data.onDidChange((change) => {
      // A rediscovery (no root) may have added or removed a package.
      if (change.root === undefined) {
        void store.refresh();
      }
    }),
    active.onDidChange(() => assets.redraw()),
    vscode.commands.registerCommand('rbx.assets.refresh', () => store.refresh(true)),
    vscode.commands.registerCommand('rbx.assets.flat', () => assets.setMode('flat')),
    vscode.commands.registerCommand('rbx.assets.split', () => assets.setMode('split')),
    vscode.commands.registerCommand('rbx.across.chooseSlots', () => across.chooseSlots()),
    vscode.commands.registerCommand('rbx.assets.showAcross', () => layout.setLayout('across')),
    vscode.commands.registerCommand('rbx.assets.showByProblem', () => layout.setLayout('problem')),
    vscode.commands.registerCommand('rbx.assets.openStatement', async (uri: unknown) => {
      if (!(uri instanceof vscode.Uri)) {
        return;
      }
      // The source first, so the preview -- which opens beside the active
      // editor -- lands next to it; and never in the column an open preview
      // already holds, or one would cover the other.
      const taken = StatementPreviewPanel.column();
      const active = vscode.window.activeTextEditor?.viewColumn ?? vscode.ViewColumn.One;
      const column =
        taken === undefined || taken !== active
          ? active
          : taken === vscode.ViewColumn.One
            ? vscode.ViewColumn.Two
            : vscode.ViewColumn.One;
      await vscode.commands.executeCommand('vscode.open', uri, { preview: false, viewColumn: column });
      await vscode.commands.executeCommand('rbx.openStatementPreview', uri);
    }),
    vscode.commands.registerCommand('rbx.assets.openSource', (element: unknown) => {
      const uri = uriOf(element);
      return uri === undefined ? undefined : vscode.commands.executeCommand('vscode.open', uri);
    }),
    vscode.commands.registerCommand('rbx.assets.chooseContest', async (arg?: unknown) => {
      let root = typeof arg === 'string' ? arg : undefined;
      if (root === undefined) {
        const roots = await store.variantRoots();
        if (roots.length === 0) {
          void vscode.window.showInformationMessage('rbx: no directory here holds more than one contest.');
          return;
        }
        root =
          roots.length === 1 ? roots[0] : await vscode.window.showQuickPick(roots, { placeHolder: 'Which contest directory?' });
      }
      if (root !== undefined) {
        await dispatcher.chooseContest(root);
      }
    }),
    // Dispatched from rbx's own listing rather than through `rbx.runSolution`,
    // which recognises a solution only by the extension's manifest parse --
    // and that does not expand globs (`solutions/good/*.*`).
    vscode.commands.registerCommand('rbx.assets.run', async (element: unknown) => {
      const uri = uriOf(element);
      const problem = uri === undefined ? undefined : store.problemDeclaring(uri.fsPath);
      if (uri === undefined || problem === undefined) {
        return vscode.commands.executeCommand('rbx.runSolution', uri);
      }
      // rbx reads the file from disk; running a stale save would surprise.
      const open = vscode.workspace.textDocuments.find(
        (document) => document.uri.scheme === 'file' && document.uri.fsPath === uri.fsPath,
      );
      if (open?.isDirty) {
        await open.save();
      }
      await dispatcher.dispatch({
        command: 'run',
        root: problem.root,
        solutions: [path.relative(problem.root, uri.fsPath)],
      });
    }),
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
  void store.refresh();
}
