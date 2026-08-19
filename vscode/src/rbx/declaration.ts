/**
 * What the editor says a solution is declared to do.
 *
 * The Explorer badge (decoration.ts) has two characters and a colour; this is
 * the same declaration spelled out for the two channels that reach you while
 * the solution itself is open -- a CodeLens on its own line above line one, and
 * the language status item, which stays put while you scroll.
 *
 * Both layers rbx checks are shown, because neither can stand in for the other:
 * `outcome` is matched against the whole testset while each `outcomePerGroup`
 * entry is matched against one group's tests alone, and a solution fails if
 * either misses.
 *
 * Nothing here imports `vscode`; solutionLens.ts and solutionStatus.ts are the
 * glue that hands this to the editor.
 */
import { expectationDisplay, expectationSpelling } from './expectation';
import { DeclaredAsset, PerGroupExpectation } from './manifest';

export interface SolutionDeclaration {
  /**
   * A codicon id, without the `$(...)` wrapper.
   *
   * The editor draws in the UI font, where the glyphs `rbx run` prints are not
   * all guaranteed to exist -- `⧖` (U+29D6) in particular. A codicon always
   * does, so the glyph is translated rather than passed through, and the
   * translation is one-way: `iconOf` maps each glyph to the codicon that means
   * the same thing.
   */
  readonly icon: string;
  /** The pooled `outcome`, as the manifest spells it: `accepted-or-tle`. */
  readonly pooled: string;
  /** Each `outcomePerGroup` override, in the order it was written. */
  readonly overrides: readonly string[];
  /** The same declaration in the labels the run view and the terminal use. */
  readonly tooltip: string;
}

/**
 * `outcomePerGroup`'s wildcard, in words.
 *
 * `'*'` is not a group name, and printing it as one would read as a group
 * called `*`. It means "every group, individually" -- a different claim from
 * the pooled `outcome` beside it, and the line is only readable if the
 * difference survives.
 */
const WILDCARD = 'each group';

/** `ANY`, which rbx defaults an omitted `outcome` to, said as what it is. */
const NOTHING_DECLARED = 'no outcome declared';

const SEPARATOR = ' · ';

/**
 * The gap before the right-hand slot.
 *
 * A CodeLens title is one run of text with no box to right-align inside, so
 * spaces are what is available. They are enough to read the two halves as two
 * halves.
 */
const GAP = '     ';

/**
 * `ExpectedOutcome.icon()`'s glyphs, as the codicons that mean the same thing.
 *
 * Four glyphs, four codicons, and the mapping is exhaustive by construction:
 * anything else falls back to the one that claims the least.
 */
const ICON: Record<string, string> = {
  '✓': 'pass',
  '⧖': 'watch',
  '✗': 'error',
  '?': 'question',
};

function iconOf(glyph: string): string {
  return Object.hasOwn(ICON, glyph) ? ICON[glyph] : 'question';
}

function groupPhrase(entry: PerGroupExpectation): string {
  const group = entry.group === '*' ? WILDCARD : entry.group;
  return `${group}: ${expectationSpelling(entry.expectation)}`;
}

/**
 * What `asset` declares, or `undefined` for anything with nothing to declare.
 *
 * That is every non-solution -- a generator promises nothing, so a line saying
 * what it promises would say nothing -- and a solution whose expectation is
 * missing entirely, which `parseManifest` already prevents by defaulting to
 * `ANY` but which is still handled: this reads a hand-edited file.
 */
export function declarationFor(asset: DeclaredAsset): SolutionDeclaration | undefined {
  if (asset.role !== 'solution' || asset.expectation === undefined) {
    return undefined;
  }
  const display = expectationDisplay(asset.expectation);
  if (display === undefined) {
    return undefined;
  }
  return {
    icon: iconOf(display.glyph),
    pooled:
      asset.expectation === 'ANY' ? NOTHING_DECLARED : expectationSpelling(asset.expectation),
    overrides: (asset.perGroup ?? []).map(groupPhrase),
    tooltip: tooltipFor(asset, display.label),
  };
}

/**
 * The hover, which repeats the declaration in the *other* spelling.
 *
 * The lens is written the way the manifest is; the hover the way a verdict is
 * (`AC or TLE`), so hovering answers "what will this be compared against?"
 * rather than restating the line it is attached to.
 */
function tooltipFor(asset: DeclaredAsset, label: string): string {
  const head =
    label === 'ANY' ? 'rbx solution — no outcome declared' : `rbx solution — expected ${label}`;
  const lines = (asset.perGroup ?? []).map((entry) => {
    const group = entry.group === '*' ? WILDCARD : entry.group;
    return `${group}: ${expectationDisplay(entry.expectation)?.label ?? entry.expectation}`;
  });
  return [head, ...lines].join('\n');
}

/**
 * The CodeLens title: the whole declaration, on the line above line one.
 *
 * `run` is the last run's half of the line -- verdict, worst time, points, and
 * whether the declaration was missed. It ships unset: laying the space out is
 * cheap, and filling it carries questions this channel does not have to answer
 * (which run, how stale is too stale, and what it says when there has never
 * been one). Until then the title is the declaration alone, which is a
 * finished sentence on its own.
 */
export function lensTitle(declaration: SolutionDeclaration, run?: string): string {
  const declared = `$(${declaration.icon}) ${[declaration.pooled, ...declaration.overrides].join(SEPARATOR)}`;
  return run === undefined || run === '' ? declared : `${declared}${GAP}${run}`;
}

/**
 * The status item's one line, which is the pooled outcome only.
 *
 * The status bar is crowded and shared with every other extension, so the
 * per-group layer moves to `statusDetail`, which the user sees on hover or when
 * the item is pinned open.
 */
export function statusText(declaration: SolutionDeclaration): string {
  return `$(${declaration.icon}) ${declaration.pooled}`;
}

/** The overrides, or `undefined` when the solution declares none. */
export function statusDetail(declaration: SolutionDeclaration): string | undefined {
  return declaration.overrides.length === 0
    ? undefined
    : declaration.overrides.join(SEPARATOR);
}
