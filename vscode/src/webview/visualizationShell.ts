/**
 * The document a single visualization is shown inside.
 *
 * A shell rather than a renderer: it has no model, no client script and nothing
 * to update. All it does is frame one file at full size -- the testset gallery's
 * `.html` cell (panelRender.ts), alone and without the `sandbox=""` a thumbnail
 * grid wants.
 *
 * It lives here, beside the other HTML this extension emits, so it can share
 * `escapeAttr` and so `node --test` can hold its policy to account without
 * standing up a webview. The panel that hosts it is visualizationPanel.ts.
 */
import { escapeAttr } from './render';

/**
 * Frame `source` -- a webview URI for the visualization -- under `cspSource`.
 *
 * `default-src 'none'` with a single `frame-src` is the entire policy, and the
 * shell earns it by doing nothing: it loads nothing, runs nothing and talks to
 * nobody, so there is no `script-src` here at all and no nonce to mint.
 *
 * What the *framed* document may do is not governed by this policy -- it is a
 * separate document, and an interactive visualization is allowed to be
 * interactive. What does bound it is the webview's `localResourceRoots`, which
 * is what `cspSource` resolves against, so the frame can only ever reach files
 * under the package's build directory.
 */
export function visualizationShell(
  source: string,
  cspSource: string,
  title: string,
): string {
  const csp = [
    `default-src 'none'`,
    `frame-src ${cspSource}`,
    `style-src 'unsafe-inline'`,
  ].join('; ');
  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <meta http-equiv="Content-Security-Policy" content="${csp};">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${escapeAttr(title)}</title>
    <style>
      html, body { margin: 0; padding: 0; height: 100%; overflow: hidden; }
      /* White, not the editor background: a generated page is written against a
         browser's default canvas, and a dark one behind transparent SVG or
         unstyled text renders it unreadable. */
      iframe { display: block; border: 0; width: 100%; height: 100%; background: #fff; }
    </style>
  </head>
  <body>
    <iframe src="${escapeAttr(source)}" title="${escapeAttr(title)}"></iframe>
  </body>
</html>`;
}
