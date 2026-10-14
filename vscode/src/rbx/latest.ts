/**
 * Which of several overlapping async refreshes is still the one that counts.
 *
 * The views, the Testset panel and the Problems panel each refresh on every
 * watcher tick and every selection change, and a refresh awaits disk reads
 * before it touches anything. Several are routinely in flight at once, and they
 * resolve in whatever order their reads finish -- so without a guard the *last
 * to finish* wins rather than the *last to start*. A slow reload of problem X
 * resolving after the user picked Y painted X under Y's selection, and an older
 * run snapshot could land over a newer one (#901).
 *
 * Usage: take a ticket when the refresh starts, do every `await` first, then
 * return early if the ticket is no longer current, before any side effect.
 */
export class Latest {
  private generation = 0;

  /** Start a refresh; the returned check is true until another one starts. */
  begin(): () => boolean {
    const mine = ++this.generation;
    return () => mine === this.generation;
  }
}
