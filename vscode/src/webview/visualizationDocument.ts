/**
 * The document a visualization panel shows.
 *
 * There is no shell and no `<iframe>` here, and that is the whole design. A
 * webview resource URI *cannot* be framed: the service worker that serves those
 * URIs resolves which webview is asking from the `?id=` on the requesting
 * client's URL (`getWebviewIdForClient`), and a frame navigated cross-origin to
 * a resource URI has neither that parameter nor -- being a navigation rather
 * than a subresource fetch -- a client at all. The request 404s and the frame
 * comes up blank. This is why the testset gallery renders SVG cells (an `<img>`
 * is a subresource, issued by the webview document itself) and never renders
 * its HTML ones.
 *
 * VS Code hits the same wall internally and works around it the same way this
 * module does -- see its `pre/index.html`:
 *
 *   // We should just be able to use srcdoc, but I wasn't
 *   // seeing the service worker applying properly.
 *   // Fake load an empty on the correct origin and then write real html
 *   // into it to get around this.
 *
 * So the visualization becomes the panel's own document, handed to VS Code as
 * `webview.html`. It is written into a frame already loaded at the right origin
 * with the right `?id=`, which is the one path that works.
 */

/**
 * The visualization's own HTML, with VS Code's default gutter neutralised.
 *
 * Webview content is styled by an injected `_defaultStyles` sheet that sets
 * `body { padding: 0 20px }`, which would inset a visualization that never
 * asked to be inset. The reset goes into `@layer vscode-default`, the same
 * cascade layer that rule lives in, so it wins there (later in the layer) while
 * still losing to *any* unlayered rule the visualization writes -- a page that
 * sets its own body padding keeps it. That is the property a blunt override
 * would not have.
 *
 * Injected before `</head>`; a document without one is returned untouched
 * rather than guessed at. Layer order makes the insertion point irrelevant, so
 * this needs no more surgery than that.
 */
export function visualizationDocument(html: string): string {
  const reset = '<style>@layer vscode-default { body { padding: 0; } }</style>';
  // The *first* `</head>`: a later one is inside the body -- text in a `<pre>`,
  // a string in a script -- and inserting there would put a style tag in the
  // body of someone's document.
  const head = html.toLowerCase().indexOf('</head>');
  if (head === -1) {
    return html;
  }
  return html.slice(0, head) + reset + html.slice(head);
}

/** A visualization that could not be read, said out loud instead of shown blank. */
export function visualizationErrorDocument(message: string): string {
  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <style>
      body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size); }
      code { color: var(--vscode-textPreformat-foreground); }
    </style>
  </head>
  <body>
    <p>${escapeText(message)}</p>
  </body>
</html>`;
}

function escapeText(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
