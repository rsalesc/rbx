/**
 * The single-visualization editor panel.
 *
 * A visualizer's output is whatever the generator wrote. An SVG or a PNG the
 * editor already shows well, and this file does not touch them. An HTML page it
 * does not: handed to `vscode.open` it opens as *source*, and the reader is left
 * to find the affordance that renders it -- if the extension that provides one
 * is even installed.
 *
 * So HTML, and only HTML, is framed here instead, in a webview whose iframe
 * points at the file through `asWebviewUri`. That is the same seam the testset
 * gallery already relies on -- `frame-src ${webview.cspSource}` over
 * `localResourceRoots` limited to the package's build directory -- and this file
 * is that one gallery cell, alone, at full size.
 *
 * The panel is deliberately dumb: no client script, no messages, no model. Its
 * one action -- open this in a real browser -- is an editor-title button rather
 * than markup, so it is a native affordance, needs no `script-src`, and costs
 * the visualization no vertical space.
 *
 * The parts worth testing live away from `vscode`: which files to frame in
 * rbx/visualization.ts, and the document itself -- CSP included -- in
 * webview/visualizationShell.ts.
 */
import * as vscode from 'vscode';

import {
  Visualization,
  isFramedVisualization,
  visualizationTitle,
} from './rbx/visualization';
import { visualizationShell } from './webview/visualizationShell';

export { Visualization } from './rbx/visualization';

export class VisualizationPanel {
  /**
   * Also the `activeWebviewPanelId` the editor-title button tests for, so the
   * button appears over this panel and nowhere else. Changing it means changing
   * the two `when` clauses in package.json.
   */
  static readonly viewType = 'rbx.visualization';

  /**
   * One panel per file, not one per window.
   *
   * Two visualizations open side by side is a real thing to want -- an input
   * next to the answer it produced -- and the same one open twice is not.
   */
  private static readonly panels = new Map<string, VisualizationPanel>();

  /**
   * The panel the editor-title button acts on.
   *
   * `activeWebviewPanelId` tells VS Code *whether* to draw the button, but the
   * command it invokes is given no argument, so which panel it belongs to has to
   * be tracked here for the command to have a subject at all.
   */
  private static focused?: VisualizationPanel;

  /**
   * Bumped per render and hung off the iframe's query.
   *
   * The webview resource URI for a rebuilt visualization is byte-identical to
   * the one before it, so without this an explicit re-open would redraw the
   * cached page -- exactly the case the panel exists to serve: run
   * `rbx build --visualize`, look again.
   */
  private static generation = 0;

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private visualization: Visualization,
  ) {
    this.render();
    panel.onDidChangeViewState(() => {
      if (panel.active) {
        VisualizationPanel.focused = this;
      } else if (VisualizationPanel.focused === this) {
        VisualizationPanel.focused = undefined;
      }
    });
    panel.onDidDispose(() => {
      VisualizationPanel.panels.delete(this.visualization.filePath);
      if (VisualizationPanel.focused === this) {
        VisualizationPanel.focused = undefined;
      }
    });
    VisualizationPanel.focused = this;
  }

  /** Open a panel over this visualization, or reveal and reload the one there. */
  static show(context: vscode.ExtensionContext, visualization: Visualization): void {
    const existing = VisualizationPanel.panels.get(visualization.filePath);
    if (existing !== undefined) {
      existing.visualization = visualization;
      existing.panel.title = visualizationTitle(visualization);
      // Re-render rather than merely reveal: an open is the reader asking to see
      // the file as it is *now*, and it may have been rebuilt since.
      existing.render();
      existing.panel.reveal(existing.panel.viewColumn);
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      VisualizationPanel.viewType,
      visualizationTitle(visualization),
      vscode.ViewColumn.Active,
      {
        // The shell itself has no script and its CSP grants it none. This is
        // for the *framed* document: the sandbox VS Code puts on a webview
        // omits `allow-scripts` when this is off, and sandbox flags are
        // inherited by nested frames -- so without it an interactive
        // visualization would load with its own JavaScript dead. The testset
        // gallery frames HTML on the same terms.
        enableScripts: true,
        // One root, the same one the testset panel uses: the package's build
        // directory, where everything a visualizer writes lands. The workspace
        // root would put every file in the repository one crafted path away from
        // being served into a webview.
        localResourceRoots: [
          vscode.Uri.joinPath(vscode.Uri.file(visualization.root), 'build'),
        ],
        // A visualization can be an expensive page -- a canvas replay, a big DOM
        // -- and unlike the gallery there is no host-side model to rebuild it
        // from, so hiding the tab must not throw it away.
        retainContextWhenHidden: true,
      },
    );
    VisualizationPanel.panels.set(
      visualization.filePath,
      new VisualizationPanel(panel, visualization),
    );
    context.subscriptions.push(panel);
  }

  /** The file the focused panel is showing, for the external-browser command. */
  static activeFile(): string | undefined {
    return VisualizationPanel.focused?.visualization.filePath;
  }

  private render(): void {
    VisualizationPanel.generation += 1;
    const source = this.panel.webview
      .asWebviewUri(vscode.Uri.file(this.visualization.filePath))
      .with({ query: `rbx=${VisualizationPanel.generation}` })
      .toString();
    this.panel.webview.html = visualizationShell(
      source,
      this.panel.webview.cspSource,
      visualizationTitle(this.visualization),
    );
  }
}

/**
 * Show a visualization, however it is best shown.
 *
 * The one entry point both call sites use -- the Tests view's channel commands
 * and a click on the gallery's file affordance -- so "how is a visualization
 * displayed" stays a single decision.
 */
export async function openVisualization(
  context: vscode.ExtensionContext,
  visualization: Visualization,
): Promise<void> {
  if (isFramedVisualization(visualization.filePath)) {
    VisualizationPanel.show(context, visualization);
    return;
  }
  // Anything else: let the editor decide. It has a viewer for the image formats
  // a visualizer realistically emits, and where it has none, its "no editor for
  // this file" prompt is a better answer than a blank iframe.
  await vscode.commands.executeCommand(
    'vscode.open',
    vscode.Uri.file(visualization.filePath),
  );
}

/**
 * Hand the visualization to the OS -- which for an `.html` file is the default
 * browser, with its devtools, its zoom and its own fonts.
 *
 * The framed panel is a convenience, not a replacement: a visualization heavy
 * enough to want profiling wants a real browser, and this is the door to it.
 */
export async function openVisualizationExternally(filePath?: string): Promise<void> {
  const target = filePath ?? VisualizationPanel.activeFile();
  if (target === undefined) {
    vscode.window.showInformationMessage('No rbx visualization is open.');
    return;
  }
  await vscode.env.openExternal(vscode.Uri.file(target));
}
