import * as assert from 'assert';
import { test } from 'node:test';

import {
  visualizationDocument,
  visualizationErrorDocument,
} from './visualizationDocument';

const page = (head = '', body = '<p>hi</p>') =>
  `<!doctype html><html><head>${head}</head><body>${body}</body></html>`;

test('the visualization is handed over as itself', () => {
  // The regression this guards: anything that wraps the document -- an iframe,
  // a shell -- cannot load a webview resource URI at all.
  const html = visualizationDocument(page('<style>body{color:red}</style>'));
  assert.ok(html.includes('<style>body{color:red}</style>'));
  assert.ok(html.includes('<p>hi</p>'));
  assert.ok(!html.includes('<iframe'));
});

test('the gutter reset goes in, inside the layer VS Code styles with', () => {
  const html = visualizationDocument(page());
  // Layered, so it beats `_defaultStyles` and loses to the page's own CSS.
  assert.match(html, /@layer vscode-default \{ body \{ padding: 0; \} \}/);
  assert.ok(html.indexOf('padding: 0') < html.indexOf('</head>'));
});

test('an uppercase HEAD is still found', () => {
  assert.match(visualizationDocument(page().toUpperCase()), /@layer vscode-default/);
});

test('the first head closes the head, not one quoted later in the body', () => {
  const html = visualizationDocument(page('', '<pre></head></pre>'));
  assert.strictEqual(html.match(/@layer vscode-default/g)?.length, 1);
  // Inserted at the real head, not at the one sitting in the page's text.
  assert.ok(html.indexOf('@layer') < html.indexOf('<body>'));
});

test('a document with no head is returned untouched rather than guessed at', () => {
  const fragment = '<p>a visualizer wrote no head</p>';
  assert.strictEqual(visualizationDocument(fragment), fragment);
});

test('an error says what went wrong, escaped', () => {
  const html = visualizationErrorDocument('No file at <build/x.html>');
  assert.ok(!html.includes('<build/x.html>'));
  assert.match(html, /&lt;build\/x\.html&gt;/);
});
