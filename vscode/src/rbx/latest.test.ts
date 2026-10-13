import * as assert from 'assert';
import { test } from 'node:test';

import { Latest } from './latest';

test('a refresh is current until another one starts', () => {
  const latest = new Latest();
  const first = latest.begin();
  assert.strictEqual(first(), true);

  const second = latest.begin();

  assert.strictEqual(first(), false);
  assert.strictEqual(second(), true);
});

test('the last refresh to start wins, whatever order they finish in', async () => {
  // The bug this guards: a slow load for problem X resolving after a fast one
  // for Y, and painting X while Y is selected.
  const latest = new Latest();
  const shown: string[] = [];
  const refresh = async (name: string, delayMs: number): Promise<void> => {
    const current = latest.begin();
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    if (!current()) {
      return;
    }
    shown.push(name);
  };

  await Promise.all([refresh('slow X', 20), refresh('fast Y', 0)]);

  assert.deepStrictEqual(shown, ['fast Y']);
});
