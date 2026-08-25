/**
 * The Tests view, served as a webview beside the Run view.
 *
 * The host half, and it owns only the seam: the HTML shell, the four messages,
 * and the id -> node map that turns a click in the client back into a command
 * argument. What a row shows is testsetViewModel.ts; how it is painted is
 * testsetRender.ts. The arrangement is runView.ts's, deliberately, because the
 * two views sit in one container and a second way of wiring one of them is a
 * second thing to keep in step.
 *
 * Three things are *not* owned here and that is the point of each:
 *
 *   - `ActiveProblem` is passed in, the same instance the Run view holds. Two
 *     views in one container showing two different problems is not a state this
 *     extension should be able to reach.
 *   - The wide panel is opened through a callback. The sidebar knows a row was
 *     asked about; which editor tab answers is the extension's business.
 *   - The manifest's mtime is stat'd here and formatted upstream. Reading the
 *     disk is the host's job and phrasing a time is not.
 */
import * as crypto from 'crypto';
import * as fs from 'fs/promises';
import * as vscode from 'vscode';

import { ActiveProblem } from './activeProblem';
import { log } from './log';
import { packageLayout, testsetPath } from './rbx/layout';
import {
  EMPTY_TESTSET_MODEL,
  TestsetNode,
  buildTestsetViewModel,
  testsetNodeId,
  testsetNodes,
} from './rbx/testsetViewModel';
import { RunDataProvider } from './runData';

/** Which of the panel's surfaces to open, and about what. */
export interface TestsetPanelRequest {
  readonly tab: 'gallery' | 'coverage' | 'stats';
  /** The group the request is about, when a row named one. */
  readonly group?: string;
  /** The row id of a testcase, when the request came from one. */
  readonly testId?: string;
}

/** Where the highlight is, so the panel can follow it. */
export interface TestsetSelection {
  readonly root: string;
  readonly group?: string;
  readonly testId?: string;
}

/**
 * What testsetMain.ts posts back: a load announcement, a row's primary command,
 * the problem the dropdown was set to, a panel request, or the highlight moving.
 */
interface ClientMessage {
  readonly type?: string;
  readonly commandId?: string;
  readonly nodeId?: string;
  readonly root?: string;
  readonly tab?: string;
}

const PANEL_TABS: readonly TestsetPanelRequest['tab'][] = ['gallery', 'coverage', 'stats'];

/** A CSP nonce. Fresh per resolve, from a real random source. */
function makeNonce(): string {
  return crypto.randomBytes(16).toString('base64');
}

/**
 * When the manifest was written, or nothing at all.
 *
 * Nothing at all rather than a guess: the header states the time as a cue about
 * which build is on screen, and a fabricated one would be a claim about a
 * package nobody read.
 */
async function builtAt(root: string): Promise<number | undefined> {
  try {
    return (await fs.stat(testsetPath(packageLayout(root)))).mtimeMs;
  } catch {
    return undefined;
  }
}

export class TestsetViewProvider implements vscode.WebviewViewProvider {
  static readonly viewType = 'rbx.testset';

  /**
   * The rows currently on screen, by id.
   *
   * The client only ever sends ids back, because a node carries a whole parsed
   * manifest and nothing about it would survive `postMessage` usefully. This
   * map is what turns one back into the node the commands expect, and it is
   * rebuilt from the same walk the model was built from.
   */
  private nodes = new Map<string, TestsetNode>();
  private view?: vscode.WebviewView;
  private selectedRow?: string;
  private readonly selectionChanged = new vscode.EventEmitter<TestsetSelection>();
  /** Fires as the highlight moves, so the panel can live-follow the sidebar. */
  readonly onDidChangeSelection: vscode.Event<TestsetSelection> = this.selectionChanged.event;
  /**
   * What the last post said, so the log reports edges instead of ticks.
   *
   * `post` runs on every debounced watcher tick, so logging unconditionally
   * would bury the output channel. Only a change of problem, or of whether that
   * problem has a manifest at all, is news.
   */
  private posted?: { readonly root?: string; readonly built: boolean };

  constructor(
    private readonly data: RunDataProvider,
    private readonly active: ActiveProblem,
    private readonly extensionUri: vscode.Uri,
    private readonly onOpenPanel: (request: TestsetPanelRequest) => void,
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
      if (message.type === 'select' && message.root !== undefined) {
        // No `post` here: `ActiveProblem` fires its change event, which is
        // already subscribed below. Posting as well would draw the view twice.
        this.active.select(message.root);
        return;
      }
      if (message.type === 'selection') {
        this.remember(message.nodeId);
        return;
      }
      if (message.type === 'panel') {
        this.requestPanel(this.asTab(message.tab), message.nodeId);
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

    // No `retainContextWhenHidden`, for the reason runView.ts gives: the client
    // persists its own state and the host re-posts the whole model on every
    // change, so paying to keep a hidden view alive would buy nothing back.
    const subscriptions = [
      this.data.onDidChange(() => void this.post()),
      // Both, and they are different events: `data` changes what the selected
      // problem's testset says, `active` changes which problem that is.
      this.active.onDidChange(() => void this.post()),
    ];
    view.onDidDispose(() => {
      subscriptions.forEach((subscription) => subscription.dispose());
      this.view = undefined;
    });
  }

  /** The node behind a row id, for commands invoked from the context menu. */
  nodeById(id: string): TestsetNode | undefined {
    return this.nodes.get(id);
  }

  /** Where the highlight is, for a panel opening without a row to ask. */
  selection(): TestsetSelection | undefined {
    const root = this.active.selected();
    return root === undefined ? undefined : this.selectionOf(root, this.selectedRow);
  }

  /**
   * Open the wide surface. The one path, whether the ask came from the client,
   * a context menu or the palette.
   */
  requestPanel(tab: TestsetPanelRequest['tab'], nodeId?: string): void {
    const node = nodeId === undefined ? undefined : this.nodeById(nodeId);
    this.onOpenPanel({
      tab,
      group: node?.group,
      testId: node?.kind === 'testsetTestcase' ? nodeId : undefined,
    });
  }

  private asTab(tab: string | undefined): TestsetPanelRequest['tab'] {
    // A tab the client asked for and this host does not know is a message from
    // a newer bundle than the one that shipped; the gallery is the surface the
    // view exists to reach, so it is the fallback rather than a dropped ask.
    return PANEL_TABS.find((candidate) => candidate === tab) ?? 'gallery';
  }

  private selectionOf(root: string, nodeId: string | undefined): TestsetSelection {
    const node = nodeId === undefined ? undefined : this.nodeById(nodeId);
    return {
      root,
      group: node?.group,
      testId: node?.kind === 'testsetTestcase' ? nodeId : undefined,
    };
  }

  private remember(nodeId: string | undefined): void {
    if (nodeId === this.selectedRow) {
      return;
    }
    this.selectedRow = nodeId;
    const root = this.active.selected();
    if (root !== undefined) {
      this.selectionChanged.fire(this.selectionOf(root, nodeId));
    }
  }

  /**
   * Load the selected problem's manifest and hand the client a whole new model.
   *
   * One problem, not every discovered one: a contest of thirty problems costs
   * one package's manifest per tick rather than thirty. The id map is rebuilt in
   * the same pass, from the same testset, so an id the client can see always
   * resolves to the node it was built from.
   */
  private async post(): Promise<void> {
    const selected = this.active.selected();
    const pkg = selected === undefined ? undefined : packageLayout(selected);
    const testset = pkg === undefined ? undefined : await this.data.testset(pkg);
    this.nodes = new Map(
      testsetNodes(pkg ?? packageLayout(''), testset).map((node) => [testsetNodeId(node), node]),
    );
    const built = testset !== undefined;
    const posted = this.posted;
    if (posted === undefined || posted.root !== selected || posted.built !== built) {
      // Nothing said for an undefined selection: discovery already logged that
      // it found no package, and repeating it here adds no fact.
      if (selected !== undefined) {
        log(
          built
            ? `Loaded the testset in ${selected}.`
            : `No testset for ${selected} -- run \`rbx build\` in that directory.`,
        );
      }
      this.posted = { root: selected, built };
    }
    await this.view?.webview.postMessage({
      type: 'state',
      model:
        testset === undefined || selected === undefined
          ? EMPTY_TESTSET_MODEL
          : buildTestsetViewModel(testset, {
              builtAt: await builtAt(selected),
              // So a channel the build did not draw can still offer to draw it
              // now, where a visualizer is declared for it.
              visualizers: await this.data.visualizers(packageLayout(selected)),
            }),
      problems: this.active.problems(),
      selected,
    });
  }

  private html(webview: vscode.Webview): string {
    const nonce = makeNonce();
    const asset = (...parts: string[]): vscode.Uri =>
      webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'dist', ...parts));
    // `'unsafe-inline'` on styles only, and it is load-bearing: without it every
    // `style` attribute is dropped, which is how a row states its indentation --
    // silently, with no error. See the longer note in runView.ts for what that
    // costs and why it is bounded.
    const csp = [
      `default-src 'none'`,
      `style-src ${webview.cspSource} 'unsafe-inline'`,
      `font-src ${webview.cspSource}`,
      `script-src 'nonce-${nonce}'`,
    ].join('; ');
    // The same shell as the Run view, minus the findings panel: the tree
    // container is static so focus and scroll survive a re-render, and it is
    // `tabindex="-1"` because the rows carry the roving tab stop.
    return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="${csp};">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="${asset('webview', 'codicon.css')}">
    <link rel="stylesheet" href="${asset('webview', 'style.css')}">
    <title>rbx Tests</title>
  </head>
  <body>
    <div id="selector-host"></div>
    <div id="header"></div>
    <div id="filter-host"></div>
    <div id="tree" role="tree" tabindex="-1"></div>
    <!-- The testcase card: where the test came from, what the validator said,
         and how big it is. Empty, and hidden, for any selection that is not a
         testcase. -->
    <div id="card"></div>
    <script nonce="${nonce}" src="${asset('webview', 'testsetMain.js')}"></script>
  </body>
</html>`;
  }
}
