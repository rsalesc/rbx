/**
 * The Run view, served as a webview.
 *
 * A webview rather than a `TreeView` because a `TreeItem` offers two visual
 * channels -- icon and description -- and the view needs three that must stay
 * independent: what a solution *declared*, what the run *produced*, and whether
 * the two agreed. Still not the Testing API (design D4): that one is shaped
 * around *running* tests, which this extension deliberately never does.
 *
 * This file is the host half and owns only the seam: the HTML shell, the two
 * messages, and the id -> node map that turns a click in the client back into a
 * command argument. What a row shows is viewModel.ts; how it is painted is
 * render.ts.
 */
import * as crypto from 'crypto';
import * as vscode from 'vscode';

import { packageLayout } from './rbx/layout';
import { PackageRunView, RunNode, flattenNodes, nodeId } from './rbx/nodes';
import { asSolutionLabelStyle } from './rbx/solutionLabel';
import { buildViewModel } from './rbx/viewModel';
import { RunDataProvider } from './runData';

/** What main.ts posts back: a load announcement, or a row's primary command. */
interface ClientMessage {
  readonly type?: string;
  readonly commandId?: string;
  readonly nodeId?: string;
}

/** A CSP nonce. Fresh per resolve, from a real random source. */
function makeNonce(): string {
  return crypto.randomBytes(16).toString('base64');
}

export class RunViewProvider implements vscode.WebviewViewProvider {
  static readonly viewType = 'rbx.run';

  /**
   * The rows currently on screen, by id.
   *
   * The client only ever sends ids back, because a `RunNode` carries a whole
   * loaded run and nothing about it would survive `postMessage` usefully. This
   * map is what turns one back into the node the commands expect.
   */
  private nodes = new Map<string, RunNode>();
  private view?: vscode.WebviewView;

  constructor(
    private readonly data: RunDataProvider,
    private readonly extensionUri: vscode.Uri,
  ) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'dist')],
    };
    view.webview.html = this.html(view.webview);

    view.webview.onDidReceiveMessage((message: ClientMessage) => {
      if (message.type === 'ready') {
        void this.post();
        return;
      }
      if (message.type === 'invoke' && message.commandId !== undefined) {
        const node = this.nodeById(message.nodeId ?? '');
        if (node === undefined) {
          // Normal, not an error: a view hidden across a refresh still holds
          // the old model and can name a row that no longer exists.
          return;
        }
        void vscode.commands.executeCommand(message.commandId, node);
      }
    });

    // No `retainContextWhenHidden`: the client persists its own state through
    // `setState` and the host re-posts the whole model on every change, so
    // paying to keep a hidden view alive would buy nothing back.
    const subscriptions = [
      this.data.onDidChange(() => void this.post()),
      // `rbx.solutionLabel` changes nothing on disk, so no reload will bring the
      // new labels in on its own -- the view has to rebuild the model itself.
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration('rbx.solutionLabel')) {
          void this.post();
        }
      }),
    ];
    view.onDidDispose(() => {
      subscriptions.forEach((subscription) => subscription.dispose());
      this.view = undefined;
    });
  }

  /** The node behind a row id, for commands invoked from the context menu. */
  nodeById(id: string): RunNode | undefined {
    return this.nodes.get(id);
  }

  /**
   * Load everything and hand the client a whole new model.
   *
   * The id map is rebuilt in the same pass, from the same `PackageRunView`, so
   * an id the client can see always resolves to the node it was built from.
   */
  private async post(): Promise<void> {
    const packages = await this.data.loadAll();
    // Placeholder: the view now renders one package, but nothing chooses which
    // yet -- the selector lands in a later step and replaces this with the
    // user's choice. Until then the first package discovered stands in, and an
    // empty workspace gets a view with no run, which draws as the empty state.
    const selected: PackageRunView = packages[0] ?? { pkg: packageLayout(''), run: undefined };
    this.nodes = new Map(flattenNodes(selected).map((node) => [nodeId(node), node]));
    // Read per post rather than cached: the setting is window-scoped and the
    // configuration API is the only place its current value lives.
    const style = asSolutionLabelStyle(
      vscode.workspace.getConfiguration('rbx').get('solutionLabel'),
    );
    await this.view?.webview.postMessage({ type: 'state', model: buildViewModel(selected, style) });
  }

  private html(webview: vscode.Webview): string {
    const nonce = makeNonce();
    const asset = (...parts: string[]): vscode.Uri =>
      webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'dist', ...parts));
    // `'unsafe-inline'` on styles only, and it is load-bearing: a `style-src`
    // without it drops every `style` attribute, which is how a row states its
    // indentation and how a histogram bar states its width. Without it the tree
    // renders every depth flush left and every bar at zero width, silently --
    // there is no error, the attribute is simply gone.
    //
    // What it costs is bounded. `script-src` stays nonce-only, so the dangerous
    // half of inline content is still refused; `default-src 'none'` leaves no
    // `img-src` or `connect-src`, so injected CSS has nowhere to send anything;
    // and every value interpolated into this document goes through
    // `escapeHtml`/`escapeAttr` first.
    const csp = [
      `default-src 'none'`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `font-src ${webview.cspSource}`,
      `script-src 'nonce-${nonce}'`,
    ].join('; ');
    // The tree container is part of the static shell rather than something
    // `renderTree` replaces, so focus and scroll survive a re-render --
    // `renderTree` returns only its inner HTML. It is `tabindex="-1"` and not
    // `0`: the rows carry the roving tab stop, and a focusable container would
    // make Tab stop twice on its way into the view.
    return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="${csp};">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="${asset('webview', 'codicon.css')}">
    <link rel="stylesheet" href="${asset('webview', 'style.css')}">
    <title>rbx Run</title>
  </head>
  <body>
    <div id="header"></div>
    <div id="filter-host"></div>
    <div id="tree" role="tree" tabindex="-1"></div>
    <script nonce="${nonce}" src="${asset('webview', 'main.js')}"></script>
  </body>
</html>`;
  }
}
