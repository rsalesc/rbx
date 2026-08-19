/**
 * What the Explorer draws for one declared asset.
 *
 * Kept apart from the provider that hands it to VS Code for the same reason
 * `viewModel.ts` is kept apart from the webview: deciding what a badge says is
 * a pure function of the manifest and is worth testing, while
 * `FileDecorationProvider` is glue that is not.
 *
 * A `FileDecoration` offers a badge of at most two characters, one colour that
 * tints both the badge and the file name, and a tooltip. There is no third
 * channel here -- no background, no second line -- which is what the badge
 * alphabet in expectation.ts exists to work around.
 */
import { expectationDisplay } from './expectation';
import { Hue } from './hue';
import { DeclaredAsset } from './manifest';
import { roleBadge, roleLabel } from './role';

export interface BadgeDecoration {
  /** At most two characters. VS Code silently truncates anything longer. */
  readonly badge: string;
  /** A contributed `ThemeColor` id; see `contributes.colors` in package.json. */
  readonly colorId: string;
  readonly tooltip: string;
}

/**
 * Hues, as contributed colour ids.
 *
 * Contributed rather than `charts.*` directly so a colour theme can restyle
 * them, but defaulting *to* `charts.*` so that one that does not still agrees
 * with the run view -- which reaches the same hues through the webview's
 * `--vscode-charts-*` variables.
 *
 * The Explorer is the only channel that carries a hue at all: a CodeLens takes
 * the theme's own `editorCodeLens.foreground` and a language status item has
 * severity rather than colour, so neither of the editor channels can borrow
 * this table even though they say the same thing.
 */
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

/**
 * How `asset` is badged, or `undefined` for one there is nothing to say about.
 *
 * The only such case today is a solution whose expectation resolves to nothing
 * at all, which `parseManifest` already prevents by defaulting to `ANY`. It is
 * still handled rather than asserted away: this reads a hand-edited file.
 */
export function decorationFor(asset: DeclaredAsset): BadgeDecoration | undefined {
  if (asset.role === 'solution') {
    const display = expectationDisplay(asset.expectation);
    if (display === undefined) {
      return undefined;
    }
    return {
      badge: display.badge,
      colorId: COLOR[display.hue],
      tooltip:
        display.label === 'ANY'
          ? 'rbx solution — no outcome declared'
          : `rbx solution — expected ${display.label}`,
    };
  }
  return {
    badge: roleBadge(asset.role),
    // One neutral colour for every role. A role carries no judgement, so it
    // must not borrow a hue that means one.
    colorId: COLOR.dim,
    tooltip: `rbx ${roleLabel(asset.role)}`,
  };
}
