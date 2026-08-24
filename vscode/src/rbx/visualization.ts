/**
 * What a visualization is, and which ones the editor shows badly.
 *
 * Away from `vscode` so `node --test` can hold that judgement to account. The
 * document the panel wraps one in is webview/visualizationShell.ts, and the
 * host half -- the panel itself -- is visualizationPanel.ts.
 */
import * as path from 'path';

/** What a visualization panel is showing. */
export interface Visualization {
  /** The package root, which bounds what the webview may load. */
  readonly root: string;
  /** Absolute path to the visualization file. */
  readonly filePath: string;
  /** Tab title, e.g. `main/000 (input)`. */
  readonly label: string;
}

/**
 * Whether this file is one the editor renders badly enough to be worth framing.
 *
 * Only HTML. `Visualizer.extension` is a free string, so a visualization may be
 * an SVG, a PNG or something with no viewer at all -- and of those three, the
 * first two already open in a real preview. Taking them over would trade a
 * native, zoomable, theme-aware viewer for a bare iframe.
 */
export function isFramedVisualization(filePath: string): boolean {
  const extension = path.extname(filePath).toLowerCase();
  return extension === '.html' || extension === '.htm';
}

/** `rbx: main/000 (input)` -- the panel's tab title. */
export function visualizationTitle(visualization: Visualization): string {
  return `rbx: ${visualization.label}`;
}
