/**
 * What the banner above line one of a solution says.
 *
 * The Explorer badge (decoration.ts) has two characters and a colour to say
 * what a solution is declared to do; a line of its own has room to say it in
 * words, and it is in your eyeline exactly when you are editing the file the
 * declaration is about. So this is the same fact drawn in the channel that can
 * afford the whole of it -- the pooled `outcome` *and* every `outcomePerGroup`
 * override, which the badge has no room for at all.
 *
 * Badge and colour come from the same tables the Explorer reads, so the two can
 * never disagree about the same file. Everything a `TextEditorDecorationType`
 * needs beyond that is assembled in solutionBanner.ts; nothing here imports
 * `vscode`.
 */
import { colorIdOf } from './color';
import { expectationDisplay, expectationSpelling } from './expectation';
import { DeclaredAsset, PerGroupExpectation } from './manifest';

/**
 * How much of the editor the declaration is allowed to take.
 *
 * VS Code has no banner API. A line of its own is a `before` attachment forced
 * onto one with `display: block`, which is a CSS trick on a narrow, partly
 * sanitised surface rather than a documented feature -- so `inline` keeps the
 * same text as a chip at the start of line one, which is certain to render but
 * shifts the first line of code sideways. `off` is for anyone who wants neither.
 */
export type BannerMode = 'banner' | 'inline' | 'off';

export const DEFAULT_BANNER_MODE: BannerMode = 'banner';

/** The configured mode, or the default for anything unrecognized. */
export function asBannerMode(value: unknown): BannerMode {
  return value === 'banner' || value === 'inline' || value === 'off'
    ? value
    : DEFAULT_BANNER_MODE;
}

export interface SolutionBanner {
  /** The Explorer's badge, unchanged: the first thing the line says. */
  readonly badge: string;
  /**
   * The declaration in words: the pooled `outcome`, then each
   * `outcomePerGroup` override in the order it was written.
   */
  readonly declaration: string;
  /** A contributed `ThemeColor` id; see `contributes.colors` in package.json. */
  readonly colorId: string;
  readonly tooltip: string;
}

/**
 * `outcomePerGroup`'s wildcard, in words.
 *
 * `'*'` is not a group name, and printing it as one would read as a group
 * called `*`. It means "every group, individually" -- which is a different
 * claim from the pooled `outcome` sitting next to it on the same line, and the
 * line is only readable if the difference survives.
 */
const WILDCARD = 'each group';

/** `ANY`, which rbx defaults an omitted `outcome` to, said as what it is. */
const NOTHING_DECLARED = 'no outcome declared';

const SEPARATOR = ' · ';

/**
 * The gap before the right-hand slot.
 *
 * A `contentText` attachment is one run of text, so the slot cannot be pushed
 * to the far edge of the editor the way a real toolbar would: there is no
 * second box to right-align inside. Spaces are what is left, and they are
 * enough to read the two halves as two halves.
 */
const GAP = '     ';

function groupPhrase(entry: PerGroupExpectation): string {
  const group = entry.group === '*' ? WILDCARD : entry.group;
  return `${group}: ${expectationSpelling(entry.expectation)}`;
}

/**
 * The banner for `asset`, or `undefined` for anything that has no declaration
 * to show.
 *
 * That is every non-solution -- a generator promises nothing, so a line saying
 * what it promises would say nothing -- and a solution whose expectation is
 * missing entirely, which `parseManifest` already prevents by defaulting to
 * `ANY` but which is still handled: this reads a hand-edited file.
 */
export function bannerFor(asset: DeclaredAsset): SolutionBanner | undefined {
  if (asset.role !== 'solution') {
    return undefined;
  }
  const display = expectationDisplay(asset.expectation);
  if (display === undefined || asset.expectation === undefined) {
    return undefined;
  }
  const pooled =
    asset.expectation === 'ANY' ? NOTHING_DECLARED : expectationSpelling(asset.expectation);
  const overrides = (asset.perGroup ?? []).map(groupPhrase);
  return {
    badge: display.badge,
    declaration: [pooled, ...overrides].join(SEPARATOR),
    colorId: colorIdOf(display.hue),
    tooltip: tooltipFor(asset, display.label),
  };
}

/**
 * The hover, which repeats the line in the labels the run view uses.
 *
 * Deliberately the *other* spelling: the line is written the way the manifest
 * is, and the hover the way a verdict is (`AC or TLE`), so hovering answers
 * "what will this be compared against?" rather than restating the file.
 */
function tooltipFor(asset: DeclaredAsset, label: string): string {
  const head = label === 'ANY' ? 'rbx solution — no outcome declared' : `rbx solution — expected ${label}`;
  const lines = (asset.perGroup ?? []).map((entry) => {
    const group = entry.group === '*' ? WILDCARD : entry.group;
    return `${group}: ${expectationDisplay(entry.expectation)?.label ?? entry.expectation}`;
  });
  return [head, ...lines].join('\n');
}

/**
 * The banner as one line of text.
 *
 * `run` is the last run's half of the line -- verdict, worst time, points, and
 * whether the declaration was missed. It ships unset: laying the space out is
 * cheap and filling it carries questions this channel does not have to answer
 * (which run, how stale is too stale, and what it says when there has never
 * been one). Until then the line is the declaration alone, which is a finished
 * sentence on its own.
 */
export function bannerLine(banner: SolutionBanner, run?: string): string {
  const declared = `${banner.badge}  ${banner.declaration}`;
  return run === undefined || run === '' ? declared : `${declared}${GAP}${run}`;
}
