import * as assert from 'assert';
import { test } from 'node:test';

import { visualizationShell } from './visualizationShell';

test('the shell frames the source it is given', () => {
  const html = visualizationShell('https://res/000.html?rbx=1', 'https://res', 'rbx: x');
  assert.match(html, /<iframe src="https:\/\/res\/000\.html\?rbx=1"/);
});

test('the policy denies everything but framing the webview source', () => {
  const html = visualizationShell('https://res/000.html', 'https://res', 'rbx: x');
  const csp = /content="([^"]*)"/.exec(html)?.[1];
  if (csp === undefined) {
    assert.fail('the shell carries no Content-Security-Policy meta tag');
  }
  assert.ok(csp.includes(`default-src 'none'`));
  assert.ok(csp.includes('frame-src https://res'));
  // The shell runs nothing of its own, so it grants itself nothing to run with
  // -- no `script-src`, and no `connect-src` for anything to phone home over.
  assert.ok(!csp.includes('script-src'));
  assert.ok(!csp.includes('connect-src'));
});

test('a title is escaped rather than interpolated raw', () => {
  // The label is built from a group and a stem, which come off disk.
  const html = visualizationShell('https://res/x.html', 'https://res', '<script>&"');
  assert.ok(!html.includes('<script>'));
  assert.match(html, /&lt;script&gt;&amp;&quot;/);
});
