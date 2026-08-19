import * as assert from 'assert';
import { test } from 'node:test';

import { hueOfScore, hueOfThemeColor } from './hue';

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

test('a score is hued the three ways get_solution_score_style hues it', () => {
  assert.strictEqual(hueOfScore(100, 100), 'green');
  assert.strictEqual(hueOfScore(70, 100), 'yellow');
  assert.strictEqual(hueOfScore(0, 100), 'red');
});

test('a score at neither end of its range is partial, however small', () => {
  // The console draws the line at "> 0", not at some fraction of the maximum:
  // one point out of a hundred is a partial score and not a zero.
  assert.strictEqual(hueOfScore(1, 100), 'yellow');
  assert.strictEqual(hueOfScore(99, 100), 'yellow');
  // And `>=`, like the console, so an overshoot still reads as full.
  assert.strictEqual(hueOfScore(120, 100), 'green');
  assert.strictEqual(hueOfScore(0, 0), 'green');
});
