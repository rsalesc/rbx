/**
 * How an expected score range is written down.
 *
 * Shared, because the same range reaches the extension along two paths that
 * must not disagree: `problem.rbx.yml` declares it (manifest.ts) before any run
 * exists, and `report.yml` republishes it as `expectedScore` once one has. Both
 * arrive already filled the way `expected_score_range` fills them, so one
 * formatter can draw either.
 *
 * Transcribed from `get_expected_score_repr` in `rbx.box.solutions`, so a range
 * reads in the editor exactly as `rbx run` prints it.
 */

/** rbx's stand-in for "no upper bound". */
const OPEN_ABOVE = 10 ** 9;

/** `100`, `50..80`, or `50..` for a range with no ceiling. */
export function scoreRange(range: readonly [number, number]): string {
  const [lo, hi] = range;
  if (lo === hi) {
    return String(lo);
  }
  // Naming the ceiling would invent one the setter never wrote.
  return hi >= OPEN_ABOVE ? `${lo}..` : `${lo}..${hi}`;
}
