import * as assert from 'assert';
import { test } from 'node:test';

import { hueOfThemeColor } from './hue';

test('the charts palette outcome.ts records maps onto bare hue names', () => {
  assert.strictEqual(hueOfThemeColor('charts.green'), 'green');
  assert.strictEqual(hueOfThemeColor('charts.red'), 'red');
  assert.strictEqual(hueOfThemeColor('charts.yellow'), 'yellow');
  assert.strictEqual(hueOfThemeColor('charts.blue'), 'blue');
  assert.strictEqual(hueOfThemeColor('charts.purple'), 'purple');
  assert.strictEqual(hueOfThemeColor('charts.orange'), 'orange');
});

test('the de-emphasized foreground is dim, and anything unknown is neutral', () => {
  assert.strictEqual(hueOfThemeColor('descriptionForeground'), 'dim');
  assert.strictEqual(hueOfThemeColor('charts.lines'), 'neutral');
  assert.strictEqual(hueOfThemeColor(''), 'neutral');
  assert.strictEqual(hueOfThemeColor('constructor'), 'neutral');
});
