/**
 * The colors the run view speaks in, as names rather than as `ThemeColor` ids
 * or hex.
 *
 * The view model crosses the webview boundary as JSON, where a `ThemeColor` is
 * meaningless and a hex value would be wrong the moment the user switches
 * theme. A hue is a role -- "this failed", "this is de-emphasized" -- and
 * turning that role into a `--vscode-*` variable is the stylesheet's job, not
 * the model's. Keeping the two apart is what lets the renderer be a pure
 * function of data with no VS Code API in reach.
 */

export type Hue =
  | 'green'
  | 'red'
  | 'yellow'
  | 'blue'
  | 'purple'
  | 'orange'
  | 'neutral'
  | 'dim';

const HUES: Record<string, Hue> = {
  'charts.green': 'green',
  'charts.red': 'red',
  'charts.yellow': 'yellow',
  'charts.blue': 'blue',
  'charts.purple': 'purple',
  'charts.orange': 'orange',
  descriptionForeground: 'dim',
};

/** The hue behind a theme color id recorded in outcome.ts. */
export function hueOfThemeColor(color: string): Hue {
  // `hasOwn` guards the case where the id happens to name something on
  // Object.prototype, which a plain lookup would return instead of 'neutral'.
  return Object.hasOwn(HUES, color) ? HUES[color] : 'neutral';
}

/**
 * The hue of a `[X/Y]` score, mirroring `get_solution_score_style` in
 * `rbx.box.solutions`: a full score is `success`, anything above zero is
 * `warning`, and zero is `error`. The console theme resolves those three to
 * green, yellow and red, which is what this returns so that a score reads the
 * same in the sidebar as it does under `rbx run`.
 *
 * Nothing here divides by `maxScore`, so a zero maximum is not a special case:
 * `score >= maxScore` holds and the score reads as full, exactly as the console
 * decides it. Rows with no scoring at all drop the span before reaching here.
 */
export function hueOfScore(score: number, maxScore: number): Hue {
  if (score >= maxScore) {
    return 'green';
  }
  return score > 0 ? 'yellow' : 'red';
}
