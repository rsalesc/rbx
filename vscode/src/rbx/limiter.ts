/**
 * At most `max` pieces of async work at once; the rest wait their turn, in
 * order.
 *
 * A slot is released however the work ends, rejection included: a limiter
 * that leaked a slot per failure would, under exactly the load that makes work
 * fail, wedge everything queued behind it.
 */
export class Limiter {
  private running = 0;
  private readonly waiting: (() => void)[] = [];

  constructor(private readonly max: number) {}

  async run<T>(work: () => Promise<T>): Promise<T> {
    while (this.running >= this.max) {
      await new Promise<void>((resolve) => this.waiting.push(resolve));
    }
    this.running++;
    try {
      return await work();
    } finally {
      this.running--;
      this.waiting.shift()?.();
    }
  }
}
