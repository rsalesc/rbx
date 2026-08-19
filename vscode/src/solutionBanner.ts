/**
 * Draws a solution's declaration on a line of its own, above line one.
 *
 * The Explorer badge is two characters seen out of the corner of your eye; this
 * is the same declaration spelled out, in the one place that is impossible to
 * miss while you are editing the very file the declaration is about -- which is
 * exactly when it matters. What it *says* is decided in `rbx/banner.ts`; this
 * module is only how VS Code is persuaded to show it.
 *
 * ## There is no banner API
 *
 * The line is a `before` attachment on a whole-line `TextEditorDecorationType`,
 * pushed onto its own line with `display: block` injected through
 * `textDecoration`. That is a CSS trick, not a documented feature:
 * `DecorationRenderOptions` offers no `display`, and the only reason it works
 * is how VS Code turns the attachment into CSS.
 *
 * Read off `workbench.desktop.main.js` (VS Code 1.10x,
 * `getCSSTextForModelDecorationContentClassName`), three things about that
 * surface are load-bearing here:
 *
 *   - `before` with a `contentText` becomes a real `::before` rule on a
 *     generated class -- *not* the injected-text path, which is reserved for
 *     `beforeInjectedText` and is not reachable from the extension API.
 *   - `textDecoration` is interpolated into `text-decoration:{0};` with no
 *     sanitising, which is what lets `none; display: block;` through. Only the
 *     properties in that function's list are emitted at all, so anything else
 *     has to ride along in this one string.
 *   - **Never set the `width` or `height` fields.** Either one makes VS Code
 *     append `display:inline-block;` *after* the payload, which wins on order
 *     and quietly turns the banner back into a chip. Width belongs inside
 *     `BLOCK_STYLE` instead.
 *
 * The honest alternative -- `createWebviewTextEditorInset` -- is still proposed
 * API and cannot ship in a published extension. So the trick is the default,
 * and `rbx.solutionBanner: inline` is the fallback if a VS Code version ever
 * sanitises it away, or if the editor's fixed line box turns out to clip the
 * block rather than make room for it: the same text as a chip at the start of
 * line one, which is certain to render but shifts the first line of code
 * sideways.
 */
import * as vscode from 'vscode';

import { DeclaredIndex } from './declared';
import { BannerMode, asBannerMode, bannerFor, bannerLine } from './rbx/banner';

const SETTING = 'rbx.solutionBanner';

/** The background behind the whole line, contributed in package.json. */
const BACKGROUND = 'rbx.solutionBannerBackground';

/**
 * The style injected through `textDecoration`, which is the only channel a
 * decoration attachment has for CSS it has no dedicated field for.
 *
 * `none;` first so that the property this is nominally setting is closed off
 * before anything else is appended -- everything after it is the payload.
 * `white-space: pre` keeps the gap before the right-hand slot from collapsing,
 * and `display: block` is the whole trick: it takes the attachment out of the
 * text flow of line one and gives it a line.
 */
const BLOCK_STYLE =
  'none; display: block; white-space: pre; width: max-content; ' +
  'padding: 0 0.6em; border-radius: 3px;';

/** The same chip, left in the text flow of line one. */
const INLINE_STYLE = 'none; white-space: pre; padding: 0 0.6em; border-radius: 3px;';

export class SolutionBannerDecorator {
  /**
   * One decoration type for every banner.
   *
   * The text and the colour differ per file, but both are per-*range* render
   * options, so a second type would buy nothing and cost a `dispose` each. The
   * type is created once and reused for every editor.
   */
  private readonly type = vscode.window.createTextEditorDecorationType({
    isWholeLine: true,
    // The banner describes the file, not the text at that position: it must not
    // grow to swallow whatever is typed at the start of line one.
    rangeBehavior: vscode.DecorationRangeBehavior.ClosedClosed,
  });

  constructor(private readonly declared: DeclaredIndex) {}

  /** Redraw every visible editor. */
  refresh(): void {
    for (const editor of vscode.window.visibleTextEditors) {
      this.apply(editor);
    }
  }

  private apply(editor: vscode.TextEditor): void {
    editor.setDecorations(this.type, this.decorationsFor(editor));
  }

  private decorationsFor(editor: vscode.TextEditor): vscode.DecorationOptions[] {
    const mode = configuredMode();
    if (mode === 'off') {
      return [];
    }
    const asset = this.declared.assetFor(editor.document.uri);
    if (asset === undefined) {
      return [];
    }
    const banner = bannerFor(asset);
    if (banner === undefined) {
      return [];
    }
    return [
      {
        // Line one only, and collapsed: `isWholeLine` already covers the line,
        // and an empty range keeps the decoration off any selection the user
        // makes there.
        range: new vscode.Range(0, 0, 0, 0),
        hoverMessage: banner.tooltip,
        renderOptions: {
          before: {
            // One line, always: VS Code keeps only the first line of a
            // `contentText` (`match(/^.*$/m)`), so a banner that wrapped would
            // lose its tail silently rather than wrap.
            contentText: bannerLine(banner),
            color: new vscode.ThemeColor(banner.colorId),
            backgroundColor: new vscode.ThemeColor(BACKGROUND),
            margin: mode === 'inline' ? '0 0.6em 0 0' : '0',
            textDecoration: mode === 'inline' ? INLINE_STYLE : BLOCK_STYLE,
          },
        },
      },
    ];
  }

  dispose(): void {
    this.type.dispose();
  }
}

function configuredMode(): BannerMode {
  return asBannerMode(vscode.workspace.getConfiguration().get<string>(SETTING));
}

export function registerSolutionBanner(
  context: vscode.ExtensionContext,
  declared: DeclaredIndex,
): SolutionBannerDecorator {
  const decorator = new SolutionBannerDecorator(declared);
  context.subscriptions.push(
    decorator,
    // A decoration lives on an editor, not on a document, so an editor that
    // becomes visible after the last refresh has none until it is redrawn.
    vscode.window.onDidChangeVisibleTextEditors(() => decorator.refresh()),
    declared.onDidChange(() => decorator.refresh()),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(SETTING)) {
        decorator.refresh();
      }
    }),
  );
  return decorator;
}
