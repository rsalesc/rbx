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

/**
 * A score as rbx prints it: to the cent, without trailing zeros. Transcribed
 * from `format_score` in `rbx.box.scoring.partial`.
 *
 * Python's `round(x, 2)` and `toFixed(2)` both round the exact binary value of
 * `x`, so they agree everywhere except on an exact tie, which `toFixed` breaks
 * upward and Python breaks to the even cent. A double is exactly halfway
 * between two cents only when its fraction is an odd number of eighths (0.125,
 * 0.375, ...); those are the one case handled by hand.
 */
export function scoreText(score: number): string {
  let fixed = score.toFixed(2);
  if (Number.isInteger(score * 8) && !Number.isInteger(score * 4)) {
    const below = Math.floor(score * 100);
    const cents = below % 2 === 0 ? below : below + 1;
    fixed = (cents / 100).toFixed(2);
  }
  return fixed.replace(/\.?0+$/, '');
}

/** `100`, `50..80`, or `50..` for a range with no ceiling. */
export function scoreRange(range: readonly [number, number]): string {
  const lo = scoreText(range[0]);
  const hi = scoreText(range[1]);
  // Compared as printed: a range whose bounds round to the same cent is one score.
  if (lo === hi) {
    return lo;
  }
  // Naming the ceiling would invent one the setter never wrote.
  return range[1] >= OPEN_ABOVE ? `${lo}..` : `${lo}..${hi}`;
}
