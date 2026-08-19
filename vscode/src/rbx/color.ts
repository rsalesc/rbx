/**
 * Hues as contributed colour ids, shared by every channel that draws a
 * declaration in the editor chrome.
 *
 * One table, deliberately: the Explorer badge, the editor tab and the banner
 * above line one all say the same thing about the same file, and they are only
 * guaranteed not to disagree if they read the colour from the same place.
 *
 * Contributed ids rather than `charts.*` directly so a colour theme can restyle
 * them, but defaulting *to* `charts.*` (see `contributes.colors` in
 * package.json) so that a theme which does not still agrees with the run view --
 * which reaches the same hues through the webview's `--vscode-charts-*`
 * variables.
 */
import { Hue } from './hue';

const COLOR: Record<Hue, string> = {
  green: 'rbx.expectedAccepted',
  red: 'rbx.expectedIncorrect',
  yellow: 'rbx.expectedSlow',
  blue: 'rbx.expectedError',
  purple: 'rbx.expectedOther',
  orange: 'rbx.expectedOther',
  neutral: 'rbx.expectedAny',
  dim: 'rbx.declaredRole',
};

/** The contributed colour id for `hue`. */
export function colorIdOf(hue: Hue): string {
  return COLOR[hue];
}
