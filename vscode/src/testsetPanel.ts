/**
 * The `rbx: Testset` editor panel -- the wide half of the testset surface.
 *
 * The sidebar is ~300px and does not try to be wide (design D1). Everything
 * that wants width -- a visualization gallery, a coverage matrix, a stats table
 * -- lives here, behind a deliberate open, and live-follows the sidebar's
 * selection the way the testcase panes already do.
 *
 * This file is the host half and owns only the seam: the HTML shell, the CSP
 * nonce, the resolution of package-relative visualization paths into webview
 * URIs, and the two messages the client sends back. What a tab *shows* is
 * panelViewModel.ts; how it is painted is panelRender.ts.
 *
 * Two seams are deliberate here:
 *
 *   - The data source is a structural interface rather than `RunDataProvider`.
 *     The panel needs one method and one event, and typing it that way keeps
 *     this module testable-by-substitution and keeps the provider free to grow
 *     its `testset()` passthrough without this file having to be in the same
 *     change.
 *   - A gallery click *reports an intent* rather than executing a command. The
 *     commands that open a testcase belong to other modules, and a panel that
 *     dispatched them directly would pin their ids in a second place.
 */
import * as crypto from 'crypto';
import * as fs from 'fs/promises';
import * as vscode from 'vscode';

import { PackageLayout, packageLayout, testsetFilePath } from './rbx/layout';
import {
  EMPTY_PANEL_MODEL,
  GalleryCell,
  PanelTab,
  PanelViewModel,
  buildPanelViewModel,
  cellForTestId,
} from './rbx/panelViewModel';
import type { PanelAssets } from './webview/panelRender';
import type { Testset } from './rbx/testset';

/**
 * What the panel needs from the extension's data layer.
 *
 * `RunDataProvider` satisfies this once it grows a `testset(pkg)` passthrough
 * onto `ArtifactStore.testset()`; until then any object with these two members
 * -- including an `ArtifactStore` wrapper -- can be handed in.
 */
export interface TestsetSource {
  /** Fires when the watcher has invalidated something on disk. */
  readonly onDidChange: vscode.Event<void>;
  testset(pkg: PackageLayout): Promise<Testset | undefined>;
}

/** Which tab, and which group, an open asked for. */
export interface TestsetPanelRequest {
  readonly tab?: PanelTab;
  readonly group?: string;
  /** A testcase to reveal in the gallery once the model has landed. */
  readonly testId?: string;
}

/**
 * A click in the gallery, for whoever owns the commands.
 *
 * `kind: 'testcase'` is a click on a cell and means "show me this test";
 * `kind: 'file'` is the explicit affordance on a visualization the panel
 * refuses to guess at, and means "open this exact file". They are different
 * intents over the same cell, which is why one event carries both rather than
 * the router having to infer it.
 */
export interface TestsetOpenRequest {
  readonly kind: 'testcase' | 'file';
  /** The package the panel is showing. */
  readonly root: string;
  readonly group: string;
  readonly stem: string;
  /** Absolute path to the visualization the cell draws. */
  readonly filePath: string;
}

/** A CSP nonce. Fresh per panel, from a real random source. */
function makeNonce(): string {
  return crypto.randomBytes(16).toString('base64');
}

export class TestsetPanel {
  static readonly viewType = 'rbx.testsetPanel';

  /**
   * One panel per package, not one per window.
   *
   * A second panel over the same testset would be two copies of a view with no
   * per-panel state worth keeping apart; a second panel over a *different*
   * package is a contest with two problems open, which is legitimate.
   */
  private static readonly panels = new Map<string, TestsetPanel>();

  private static readonly opened = new vscode.EventEmitter<TestsetOpenRequest>();
  /**
   * Where a gallery click surfaces.
   *
   * Static because the panels are: a subscriber wires this once at activation
   * and does not have to follow panels being opened and closed.
   */
  static readonly onDidRequestOpen: vscode.Event<TestsetOpenRequest> =
    TestsetPanel.opened.event;

  private model: PanelViewModel = EMPTY_PANEL_MODEL;
  private readonly subscriptions: vscode.Disposable[] = [];
  /** Set while an open asked for a testcase the model has not been built for yet. */
  private pendingReveal?: string;

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private readonly source: TestsetSource,
    private readonly pkg: PackageLayout,
    private readonly extensionUri: vscode.Uri,
    private request: TestsetPanelRequest,
  ) {
    panel.webview.html = this.html(panel.webview);
    this.subscriptions.push(
      panel.webview.onDidReceiveMessage((message: { type?: string; id?: string }) => {
        if (message.type === 'ready') {
          void this.post();
          return;
        }
        if (message.id !== undefined) {
          this.report(message.type === 'openFile' ? 'file' : 'testcase', message.id);
        }
      }),
      // The panel follows the same debounced watcher the Run view does, so a
      // rebuild redraws the gallery without the reader asking.
      source.onDidChange(() => void this.post()),
    );
    panel.onDidDispose(() => {
      this.subscriptions.forEach((subscription) => subscription.dispose());
      TestsetPanel.panels.delete(pkg.root);
    });
  }

  /**
   * Open the panel over `root`, or reveal the one already open over it.
   *
   * `context` is taken rather than a bare `Uri` so the caller passes what it
   * already holds at activation, and so a future disposable registered by the
   * panel has somewhere to go.
   */
  static show(
    context: vscode.ExtensionContext,
    source: TestsetSource,
    root: string,
    request: TestsetPanelRequest = {},
  ): void {
    const existing = TestsetPanel.panels.get(root);
    if (existing !== undefined) {
      existing.request = request;
      existing.panel.reveal(existing.panel.viewColumn, true);
      void existing.post();
      return;
    }
    const pkg = packageLayout(root);
    const panel = vscode.window.createWebviewPanel(
      TestsetPanel.viewType,
      'rbx: Testset',
      { viewColumn: vscode.ViewColumn.Active, preserveFocus: true },
      {
        enableScripts: true,
        // Exactly two roots: the package's build directory, where every
        // visualization the manifest can name lives, and the extension's own
        // bundle. Nothing wider -- the panel renders files a generator wrote,
        // and the workspace root would put every file in the repository one
        // crafted manifest path away from being served into a webview.
        localResourceRoots: [
          vscode.Uri.joinPath(vscode.Uri.file(root), 'build'),
          vscode.Uri.joinPath(context.extensionUri, 'dist'),
        ],
        // No `retainContextWhenHidden`: the client persists tab, group and
        // scroll through `setState`, and the host re-posts the whole model on
        // `ready`, so keeping a hidden panel's DOM alive -- images and all --
        // would buy nothing back.
      },
    );
    TestsetPanel.panels.set(
      root,
      new TestsetPanel(panel, source, pkg, context.extensionUri, request),
    );
  }

  /**
   * Live-follow: scroll the gallery to the testcase the sidebar just selected.
   *
   * A no-op when no panel is open, which is the common case -- the sidebar
   * announces its selection unconditionally rather than having to know whether
   * anyone is listening.
   */
  static reveal(testId: string): void {
    for (const panel of TestsetPanel.panels.values()) {
      void panel.revealTest(testId);
    }
  }

  /** The manifest changed on disk. */
  static refresh(): void {
    for (const panel of TestsetPanel.panels.values()) {
      void panel.post();
    }
  }

  private async revealTest(testId: string): Promise<void> {
    const cell = cellForTestId(this.model.gallery, testId);
    if (cell === undefined) {
      // The model may simply not have landed yet -- remember the ask and let
      // the next post carry it, rather than dropping a follow silently.
      this.pendingReveal = testId;
      return;
    }
    await this.panel.webview.postMessage({ type: 'reveal', cellId: cell.id });
  }

  private cellById(id: string): GalleryCell | undefined {
    return this.model.gallery.cells.find((cell) => cell.id === id);
  }

  private report(kind: TestsetOpenRequest['kind'], id: string): void {
    const cell = this.cellById(id);
    if (cell === undefined) {
      // Normal, not an error: a panel hidden across a rebuild still holds the
      // old model and can name a cell that no longer exists.
      return;
    }
    TestsetPanel.opened.fire({
      kind,
      root: this.pkg.root,
      group: cell.group,
      stem: cell.stem,
      filePath: testsetFilePath(this.pkg, cell.path),
    });
  }

  /**
   * Load the manifest and hand the client a whole new model, assets included.
   *
   * One message with both, because a cell drawn against a stale asset map is a
   * broken image: the two are only ever correct together.
   */
  private async post(): Promise<void> {
    this.model = buildPanelViewModel(this.pkg.root, await this.source.testset(this.pkg));
    const assets = await this.resolveAssets(this.model);
    const request = this.request;
    // Consumed: a tab or group the *open* asked for must not be re-imposed on
    // the reader by the next watcher tick.
    this.request = {};
    await this.panel.webview.postMessage({
      type: 'state',
      model: this.model,
      assets,
      tab: request.tab,
      group: request.group,
    });
    const reveal = request.testId ?? this.pendingReveal;
    if (reveal !== undefined) {
      this.pendingReveal = undefined;
      await this.revealTest(reveal);
    }
  }

  /**
   * Webview URIs for the visualizations that are actually on disk.
   *
   * The existence check is what turns "the manifest names a file that was
   * cleaned away" into a placeholder instead of a broken-image glyph. It costs
   * one `access` per cell, issued in parallel and only when the model changes
   * -- cheap next to decoding the images themselves, and the only alternative
   * is the renderer guessing.
   */
  private async resolveAssets(model: PanelViewModel): Promise<PanelAssets> {
    const assets: Record<string, string> = {};
    await Promise.all(
      model.gallery.cells.map(async (cell) => {
        const absolute = testsetFilePath(this.pkg, cell.path);
        try {
          await fs.access(absolute);
        } catch {
          return;
        }
        assets[cell.id] = this.panel.webview
          .asWebviewUri(vscode.Uri.file(absolute))
          .toString();
      }),
    );
    return assets;
  }

  private html(webview: vscode.Webview): string {
    const nonce = makeNonce();
    const asset = (...parts: string[]): vscode.Uri =>
      webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'dist', ...parts));
    // Same shape as the Run view's, plus the two directives a gallery needs:
    // `img-src` for the visualizations, and `frame-src` for the `.html` ones,
    // both restricted to `webview.cspSource` -- which resolves only what
    // `localResourceRoots` allows, so the CSP and the roots above are one
    // decision expressed twice.
    //
    // `'unsafe-inline'` stays on styles only and is load-bearing for the same
    // reason it is there: `style` attributes are how a cell states its size.
    // `script-src` remains nonce-only and there is no `connect-src`, so nothing
    // a generated visualization contains has anywhere to send anything.
    const csp = [
      `default-src 'none'`,
      `img-src ${webview.cspSource} data:`,
      `frame-src ${webview.cspSource}`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `font-src ${webview.cspSource}`,
      `script-src 'nonce-${nonce}'`,
    ].join('; ');
    // The scrolling container is part of the static shell rather than something
    // the renderer replaces, so the scroll position survives a re-render --
    // `renderPanel` returns only its inner HTML.
    return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="${csp};">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="${asset('webview', 'codicon.css')}">
    <link rel="stylesheet" href="${asset('webview', 'panelStyle.css')}">
    <title>rbx Testset</title>
  </head>
  <body>
    <div id="panel"></div>
    <script nonce="${nonce}" src="${asset('webview', 'panelMain.js')}"></script>
  </body>
</html>`;
  }
}
