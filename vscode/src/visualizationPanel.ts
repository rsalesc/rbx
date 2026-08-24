/**
 * The single-visualization editor panel.
 *
 * A visualizer's output is whatever the generator wrote. An SVG or a PNG the
 * editor already shows well, and this file does not touch them. An HTML page it
 * does not: handed to `vscode.open` it opens as *source*, and the reader is left
 * to find the affordance that renders it -- if the extension that provides one
 * is even installed.
 *
 * So HTML, and only HTML, is shown here instead -- as the panel's *own*
 * document. Not framed: a webview resource URI cannot be the `src` of an
 * `<iframe>` at all, for the reason webview/visualizationDocument.ts sets out.
 * That is a limitation of the resource protocol rather than of this panel, and
 * it is the same one that leaves the testset gallery's HTML cells blank.
 *
 * The panel stays deliberately dumb: no client script of its own, no messages,
 * no model. Its one action -- open this in a real browser -- is an editor-title
 * button rather than markup, so it is a native affordance and costs the
 * visualization no vertical space.
 */
import * as fs from 'fs/promises';
import * as vscode from 'vscode';

import {
  Visualization,
  isFramedVisualization,
  visualizationTitle,
} from './rbx/visualization';
import {
  visualizationDocument,
  visualizationErrorDocument,
} from './webview/visualizationDocument';

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

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private visualization: Visualization,
  ) {
    void this.render();
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
      // Re-read rather than merely reveal: an open is the reader asking to see
      // the file as it is *now*, and it may have been rebuilt since. Reading it
      // again is also all the cache-busting this needs -- the document *is* the
      // file's bytes, so a rebuilt visualization is a different document.
      void existing.render();
      existing.panel.reveal(existing.panel.viewColumn);
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      VisualizationPanel.viewType,
      visualizationTitle(visualization),
      vscode.ViewColumn.Active,
      {
        // The visualization *is* this document, so these are its own scripts --
        // an interactive one would otherwise load dead. It is code a generator
        // in this package already ran locally during the build, at the same
        // trust level as the rest of the package.
        enableScripts: true,
        // One root, the same one the testset panel uses: the package's build
        // directory, where everything a visualizer writes lands. It bounds what
        // the document may pull in; the workspace root would put every file in
        // the repository one crafted path away from being served into a webview.
        localResourceRoots: [
          vscode.Uri.joinPath(vscode.Uri.file(visualization.root), 'build'),
        ],
        // A visualization can be an expensive page -- a canvas replay, a big DOM
        // -- and there is no host-side model to rebuild it from, so hiding the
        // tab must not throw it away.
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

  private async render(): Promise<void> {
    const { filePath } = this.visualization;
    let html: string;
    try {
      html = visualizationDocument(await fs.readFile(filePath, 'utf8'));
    } catch (error) {
      // A blank panel is the one outcome worth ruling out: it is what this bug
      // looked like, and it tells the reader nothing about what went wrong.
      const reason = error instanceof Error ? error.message : String(error);
      html = visualizationErrorDocument(`Could not read ${filePath}: ${reason}`);
    }
    this.panel.webview.html = html;
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
  // this file" prompt is a better answer than a blank panel.
  await vscode.commands.executeCommand(
    'vscode.open',
    vscode.Uri.file(visualization.filePath),
  );
}

/**
 * Hand the visualization to the OS -- which for an `.html` file is the default
 * browser, with its devtools, its zoom and its own fonts.
 *
 * The panel is a convenience, not a replacement: a visualization heavy enough to
 * want profiling wants a real browser, and this is the door to it.
 */
export async function openVisualizationExternally(filePath?: string): Promise<void> {
  const target = filePath ?? VisualizationPanel.activeFile();
  if (target === undefined) {
    vscode.window.showInformationMessage('No rbx visualization is open.');
    return;
  }
  await vscode.env.openExternal(vscode.Uri.file(target));
}
