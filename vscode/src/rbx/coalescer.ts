/**
 * A trailing debounce with a ceiling.
 *
 * A run drops many files in quick succession, so watcher events are batched.
 * A plain trailing debounce resets on every event, though, and a run that
 * produces one less than `wait` apart -- fast tests -- never lets it fire: the
 * view froze until the run paused or ended, which is the opposite of the live
 * progress the raw artifacts are meant to give (#902). `maxWait` bounds that:
 * however steady the stream, a batch is flushed at least that often.
 */

/** The timer the coalescer runs on, injectable so tests need not sleep. */
export interface Clock {
  now(): number;
  setTimeout(callback: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export const SYSTEM_CLOCK: Clock = {
  now: () => Date.now(),
  setTimeout: (callback, ms) => setTimeout(callback, ms),
  clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export interface CoalescerOptions {
  /** Quiet period that ends a batch. */
  readonly wait?: number;
  /** Longest a batch may stay open, counted from its first item. */
  readonly maxWait?: number;
  readonly clock?: Clock;
}

export class Coalescer<T> {
  private items: T[] = [];
  private opened = 0;
  private timer: unknown;
  private readonly wait: number;
  private readonly maxWait: number;
  private readonly clock: Clock;

  constructor(
    private readonly flushTo: (batch: readonly T[]) => void,
    options: CoalescerOptions = {},
  ) {
    this.wait = options.wait ?? 200;
    this.maxWait = options.maxWait ?? 1000;
    this.clock = options.clock ?? SYSTEM_CLOCK;
  }

  push(item: T): void {
    const now = this.clock.now();
    if (this.items.length === 0) {
      this.opened = now;
    }
    this.items.push(item);
    this.cancel();
    const left = this.maxWait - (now - this.opened);
    const delay = Math.max(0, Math.min(this.wait, left));
    this.timer = this.clock.setTimeout(() => this.flush(), delay);
  }

  /** Hand over whatever is pending now. */
  flush(): void {
    this.cancel();
    if (this.items.length === 0) {
      return;
    }
    const batch = this.items;
    this.items = [];
    this.flushTo(batch);
  }

  dispose(): void {
    this.cancel();
    this.items = [];
  }

  private cancel(): void {
    if (this.timer !== undefined) {
      this.clock.clearTimeout(this.timer);
      this.timer = undefined;
    }
  }
}
