import * as assert from 'assert';
import { test } from 'node:test';

import { Clock, Coalescer } from './coalescer';

/** A clock that only moves when told to. */
class FakeClock implements Clock {
  private time = 0;
  private timers = new Map<number, { at: number; callback: () => void }>();
  private next = 0;

  now(): number {
    return this.time;
  }

  setTimeout(callback: () => void, ms: number): unknown {
    const id = this.next++;
    this.timers.set(id, { at: this.time + ms, callback });
    return id;
  }

  clearTimeout(handle: unknown): void {
    this.timers.delete(handle as number);
  }

  advance(ms: number): void {
    const until = this.time + ms;
    for (;;) {
      const due = [...this.timers.entries()]
        .filter(([, timer]) => timer.at <= until)
        .sort(([, a], [, b]) => a.at - b.at)[0];
      if (due === undefined) {
        break;
      }
      this.time = due[1].at;
      this.timers.delete(due[0]);
      due[1].callback();
    }
    this.time = until;
  }
}

function setup() {
  const clock = new FakeClock();
  const batches: number[][] = [];
  const coalescer = new Coalescer<number>((batch) => batches.push([...batch]), {
    wait: 200,
    maxWait: 1000,
    clock,
  });
  return { clock, batches, coalescer };
}

test('a burst is flushed once, after the quiet period', () => {
  const { clock, batches, coalescer } = setup();

  coalescer.push(1);
  clock.advance(50);
  coalescer.push(2);
  clock.advance(199);
  assert.deepStrictEqual(batches, []);

  clock.advance(1);
  assert.deepStrictEqual(batches, [[1, 2]]);
});

test('a steady stream is still flushed at least once per ceiling', () => {
  // Events 100ms apart never leave a 200ms gap, so a plain trailing debounce
  // would hold all of them until the stream stopped (#902).
  const { clock, batches, coalescer } = setup();

  for (let i = 0; i < 25; i++) {
    coalescer.push(i);
    clock.advance(100);
  }

  assert.ok(batches.length >= 2, `flushed ${batches.length} time(s)`);
  assert.strictEqual(batches[0].length, 10);
  assert.deepStrictEqual(batches.flat(), [...Array(25).keys()].slice(0, batches.flat().length));
});

test('the ceiling is counted from the first item of each batch', () => {
  const { clock, batches, coalescer } = setup();

  coalescer.push(1);
  clock.advance(300);
  assert.deepStrictEqual(batches, [[1]]);

  // A new batch: the time already spent on the last one does not count.
  coalescer.push(2);
  clock.advance(150);
  coalescer.push(3);
  clock.advance(150);
  assert.deepStrictEqual(batches, [[1]]);
  clock.advance(50);
  assert.deepStrictEqual(batches, [[1], [2, 3]]);
});

test('a disposed coalescer flushes nothing', () => {
  const { clock, batches, coalescer } = setup();

  coalescer.push(1);
  coalescer.dispose();
  clock.advance(5000);

  assert.deepStrictEqual(batches, []);
});
