import * as assert from 'assert';
import { test } from 'node:test';

import { isFramedVisualization, visualizationTitle } from './visualization';

test('HTML is taken over, and the case of the extension does not matter', () => {
  assert.ok(isFramedVisualization('/w/a/build/tests/main/visualization/000.html'));
  assert.ok(isFramedVisualization('/w/a/build/tests/main/visualization/000.HTML'));
  assert.ok(isFramedVisualization('/w/a/build/tests/main/visualization/000.htm'));
});

test('what the editor already previews is left to the editor', () => {
  // The regression this guards: taking these over would replace a zoomable,
  // theme-aware preview for a plain webview.
  for (const name of ['000.svg', '000.png', '000.jpg', '000.gif', '000.txt', '000']) {
    assert.ok(
      !isFramedVisualization(`/w/a/build/tests/main/visualization/${name}`),
      `${name} should be left to the editor`,
    );
  }
});

test('a dot in a directory name is not an extension', () => {
  assert.ok(!isFramedVisualization('/w/a.html/build/tests/main/visualization/000'));
});

test('the tab says which testcase and channel it is', () => {
  assert.strictEqual(
    visualizationTitle({ root: '/w/a', filePath: '/w/a/x.html', label: 'main/000 (input)' }),
    'rbx: main/000 (input)',
  );
});
