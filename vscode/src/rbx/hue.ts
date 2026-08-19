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
