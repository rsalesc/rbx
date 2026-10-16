import * as assert from 'assert';
import { test } from 'node:test';

import { Limiter } from './limiter';

function deferred(): { promise: Promise<void>; resolve: () => void; reject: (e: Error) => void } {
  let resolve!: () => void;
  let reject!: (e: Error) => void;
  const promise = new Promise<void>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const tick = () => new Promise<void>((resolve) => setImmediate(resolve));

test('never runs more than max at once, and starts the rest in order', async () => {
  const limiter = new Limiter(2);
  const gates = [deferred(), deferred(), deferred(), deferred()];
  const started: number[] = [];
  const all = gates.map((gate, i) =>
    limiter.run(async () => {
      started.push(i);
      await gate.promise;
    }),
  );

  await tick();
  assert.deepStrictEqual(started, [0, 1]);
  gates[1].resolve();
  await tick();
  assert.deepStrictEqual(started, [0, 1, 2]);
  gates[0].resolve();
  gates[2].resolve();
  gates[3].resolve();
  await Promise.all(all);
  assert.deepStrictEqual(started, [0, 1, 2, 3]);
});

test('a rejected piece of work frees its slot and passes the rejection on', async () => {
  const limiter = new Limiter(1);
  const failing = deferred();
  const first = limiter.run(() => failing.promise);
  let secondRan = false;
  const second = limiter.run(async () => {
    secondRan = true;
  });

  failing.reject(new Error('boom'));
  await assert.rejects(first, /boom/);
  await second;
  assert.ok(secondRan);
});
