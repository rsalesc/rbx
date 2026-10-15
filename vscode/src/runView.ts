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

import { ActiveProblem } from './activeProblem';
import { log } from './log';
import { chooseSource } from './rbx/adhoc';
import { Latest } from './rbx/latest';
import { RunSource, packageLayout } from './rbx/layout';
import { PackageRunView, RunNode, findingNodes, flattenNodes, nodeId } from './rbx/nodes';
import { asSolutionLabelStyle } from './rbx/solutionLabel';
import { EMPTY_MODEL, buildViewModel } from './rbx/viewModel';
import { dispatchEnabled } from './dispatch';
import { WELCOME_COMMANDS } from './rbx/dispatch';
import { RunDataChange, RunDataProvider } from './runData';

/**
 * What main.ts posts back: a load announcement, a row's primary command, or the
 * problem the dropdown was just set to.
 */
interface ClientMessage {
  readonly type?: string;
  readonly commandId?: string;
  readonly nodeId?: string;
  readonly root?: string;
  readonly source?: string;
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
  /**
   * What the last post said, so the log can report edges instead of ticks.
   *
   * `post` runs on every debounced watcher tick -- many per run -- so logging
   * unconditionally would bury the output channel. Only a change of problem, or
   * of whether that problem has a readable run at all, is news.
   */
  private posted?: { readonly root?: string; readonly readable: boolean };
  /** Overlapping posts resolve out of order; only the newest may land. */
  private readonly posts = new Latest();
  /** The last message the client was sent, serialized, to drop repeats. */
  private lastPosted?: string;
  /**
   * Which run the view shows: the last `rbx run`, or the last `rbx irun`
   * (#907). The toggle sets it, and so does a run starting -- whichever kind
   * of run the setter just started is the one they want to see. Neither ever
   * overwrites the other on disk, so switching loses nothing.
   */
  private source: RunSource = 'run';

  constructor(
    private readonly data: RunDataProvider,
    private readonly active: ActiveProblem,
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
        // A fresh client holds no model, so nothing it was sent still counts.
        this.lastPosted = undefined;
        void this.post();
        return;
      }
      if (message.type === 'source' && (message.source === 'run' || message.source === 'irun')) {
        this.source = message.source;
        void this.post();
        return;
      }
      if (message.type === 'select' && message.root !== undefined) {
        // No `post` here: `ActiveProblem` fires its change event, which is
        // already subscribed below. Posting as well would draw the view twice.
        this.active.select(message.root);
        return;
      }
      if (message.type === 'command' && WELCOME_COMMANDS.includes(message.commandId ?? '')) {
        // An empty-state button (#906): no row, so no node to resolve.
        void vscode.commands.executeCommand(message.commandId as string);
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
      this.data.onDidChange((change) => {
        // Followed whichever package started it: the skeleton watcher in
        // extension.ts moves the selection there on its own.
        const started = change.plan?.started;
        if (started !== undefined) {
          this.source = started;
        }
        if (started !== undefined || this.concerns(change)) {
          void this.post();
        }
      }),
      // Both, and they are different events: `data` changes what the selected
      // problem's run says, `active` changes which problem that is.
      this.active.onDidChange(() => void this.post()),
      // `rbx.solutionLabel` changes nothing on disk, so no reload will bring the
      // new labels in on its own -- the view has to rebuild the model itself.
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (
          event.affectsConfiguration('rbx.solutionLabel') ||
          event.affectsConfiguration('rbx.dispatch.enabled')
        ) {
          void this.post();
        }
      }),
    ];
    view.onDidDispose(() => {
      subscriptions.forEach((subscription) => subscription.dispose());
      this.view = undefined;
    });
  }

  /**
   * Whether a data change can move what this view shows.
   *
   * It shows one package's run and visualizer declarations, so a change to
   * another package, or to a testset, is none of its business -- and during a
   * contest-wide build those are most of the ticks.
   */
  private concerns(change: RunDataChange): boolean {
    if (change.root !== undefined && change.root !== this.active.selected()) {
      return false;
    }
    return (
      change.plan === undefined ||
      change.plan.run !== 'keep' ||
      change.plan.manifest ||
      change.plan.irun
    );
  }

  /** The node behind a row id, for commands invoked from the context menu. */
  nodeById(id: string): RunNode | undefined {
    return this.nodes.get(id);
  }

  /**
   * Load the selected problem's run and hand the client a whole new model.
   *
   * One problem, not every discovered one: only the selected package is read
   * from disk, so a contest of thirty problems costs one package's artifacts
   * per tick rather than thirty.
   *
   * The id map is rebuilt in the same pass, from the same `PackageRunView`, so
   * an id the client can see always resolves to the node it was built from.
   *
   * The dropdown's contents ride along with the model rather than on a message
   * of their own: they are answers to the same question -- what is the view
   * showing -- and posting them separately would let the client draw a
   * selection the model does not match.
   */
  private async post(): Promise<void> {
    const selected = this.active.selected();
    // Undefined and not an empty layout: no package was discovered, so there is
    // nothing to load and the client draws its empty state.
    const pkg = selected === undefined ? undefined : packageLayout(selected);
    const current = this.posts.begin();
    // Read on every post, whichever source is showing: whether one exists at
    // all is what decides if the toggle is drawn. One testcase per solution,
    // so it is a handful of files, and the store caches it between ticks.
    const adhoc = pkg === undefined ? undefined : await this.data.report(pkg, 'irun');
    const { source, choice } = chooseSource(this.source, adhoc);
    const view: PackageRunView | undefined =
      pkg === undefined
        ? undefined
        : source === 'irun'
          ? { pkg, run: adhoc, flat: true }
          : { pkg, run: await this.data.report(pkg) };
    // Read alongside the run rather than cached here: the store invalidates
    // both on the same watcher tick, so the buttons cannot describe a manifest
    // the rest of the card does not.
    const visualizers =
      pkg === undefined ? undefined : await this.data.visualizers(pkg);
    // Every await is above this line and every side effect below it: a post
    // that a newer one overtook must not touch the node map or the client.
    if (!current()) {
      return;
    }
    // Both walks, because both produce rows the client can click: the tree's,
    // and the compilation findings' -- including the warning lines under them,
    // each of which resolves to the position it opens the source at.
    const nodes: RunNode[] =
      view === undefined ? [] : [...flattenNodes(view), ...findingNodes(view)];
    this.nodes = new Map(nodes.map((node) => [nodeId(node), node]));
    const readable = view?.run !== undefined;
    const posted = this.posted;
    if (posted === undefined || posted.root !== selected || posted.readable !== readable) {
      // Nothing said for an undefined selection: discovery already logged that
      // it found no package, and repeating it here adds no fact.
      if (selected !== undefined) {
        log(
          readable
            ? `Loaded the run in ${selected}.`
            : `No readable run for ${selected} -- run \`rbx run\` in that directory.`,
        );
      }
      this.posted = { root: selected, readable };
    }
    // Read per post rather than cached: the setting is window-scoped and the
    // configuration API is the only place its current value lives.
    const style = asSolutionLabelStyle(
      vscode.workspace.getConfiguration('rbx').get('solutionLabel'),
    );
    const message = {
      type: 'state',
      // Shows the empty state's Run/Build buttons; see style.css.
      dispatch: dispatchEnabled(),
      model:
        view === undefined ? EMPTY_MODEL : buildViewModel(view, style, visualizers),
      problems: this.active.problems(),
      selected,
      source: choice,
    };
    // A tick whose events moved nothing visible -- a report rewritten with the
    // same aggregates, an `.eval` rewritten whole -- builds the model it built
    // last time. Posting it again would cost the client a full re-render for
    // nothing, so it is dropped here.
    const serialized = JSON.stringify(message);
    if (serialized === this.lastPosted || this.view === undefined) {
      return;
    }
    this.lastPosted = serialized;
    await this.view.webview.postMessage(message);
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
    <div id="selector-host"></div>
    <div id="header"></div>
    <div id="filter-host"></div>
    <div id="tree" role="tree" tabindex="-1"></div>
    <!-- The testcase card. Below the tree and above the findings panel, so the
         two things that describe *something else* -- the selected testcase, and
         the compile phase -- stack at the foot of the view in the order they
         are consulted. It carries only what the selected row cannot: the
         checker's own sentence, and where the test came from. Empty, and
         hidden, for any selection that is not a testcase. -->
    <div id="card"></div>
    <!-- The findings panel is a flex sibling of the tree rather than a second
         view in the container: only a webview can give the header a badge
         coloured by severity, which is the whole point of it. It stays empty,
         and hidden, whenever the compile phase had nothing to report. -->
    <div id="findings"></div>
    <script nonce="${nonce}" src="${asset('webview', 'main.js')}"></script>
  </body>
</html>`;
  }
}
