import * as assert from 'assert';
import { test } from 'node:test';

import { EditQueue } from './editQueue';

/** A queue whose calls stay pending until the test releases them. */
function harness(options: { failEdits?: boolean } = {}) {
  const calls: string[] = [];
  const pending: (() => void)[] = [];
  const updatingAtSettle: boolean[] = [];
  const errors: unknown[] = [];
  const wait = (label: string) =>
    new Promise<void>((resolve, reject) => {
      calls.push(label);
      pending.push(() => (options.failEdits && label.startsWith('edit') ? reject(new Error(label)) : resolve()));
    });
  const queue: EditQueue<number> = new EditQueue<number>({
    runEdit: (ms) => wait(`edit ${ms}`),
    refresh: () => wait('refresh'),
    settled: () => {
      updatingAtSettle.push(queue.updating);
    },
    onError: (e) => errors.push(e),
  });
  const release = async () => {
    pending.shift()?.();
    // Let the queue observe the settled call and start the next one.
    await new Promise((r) => setImmediate(r));
  };
  return { queue, calls, release, updatingAtSettle, errors };
}

test('a burst of edits runs the first and then only the latest', async () => {
  const { queue, calls, release } = harness();
  for (const ms of [1100, 1200, 1300, 1400, 1500]) queue.edit(ms);
  assert.deepStrictEqual(calls, ['edit 1100']);
  assert.strictEqual(queue.updating, true);

  await release();
  assert.deepStrictEqual(calls, ['edit 1100', 'edit 1500']);
  await release();
  await queue.idle();
  assert.strictEqual(queue.updating, false);
});

test('a refresh that overtakes an edit never leaves the queue updating', async () => {
  // The bug this module exists for: an edit in flight, a refresh asked for
  // meanwhile (the panel became visible), and the UI stuck disabled forever.
  const { queue, calls, release } = harness();
  queue.edit(1100);
  queue.refresh();
  queue.edit(1200);
  await release(); // edit 1100
  assert.deepStrictEqual(calls, ['edit 1100', 'edit 1200']); // the edit goes first
  await release(); // edit 1200
  assert.deepStrictEqual(calls, ['edit 1100', 'edit 1200', 'refresh']);
  assert.strictEqual(queue.updating, false); // a refresh is not an edit
  await release();
  await queue.idle();
  assert.strictEqual(queue.updating, false);
});

test('refreshes coalesce', async () => {
  const { queue, calls, release } = harness();
  queue.refresh();
  queue.refresh();
  queue.refresh();
  await release();
  await release();
  await queue.idle();
  assert.deepStrictEqual(calls, ['refresh', 'refresh']);
});

test('a failing edit still settles, reports, and lets the next one run', async () => {
  const { queue, calls, release, errors, updatingAtSettle } = harness({ failEdits: true });
  queue.edit(1100);
  queue.edit(1200);
  await release();
  await release();
  await queue.idle();
  assert.deepStrictEqual(calls, ['edit 1100', 'edit 1200']);
  assert.strictEqual(errors.length, 2);
  // Still updating after the first (1200 waits), idle after the last.
  assert.deepStrictEqual(updatingAtSettle, [true, false]);
  assert.strictEqual(queue.updating, false);
});
