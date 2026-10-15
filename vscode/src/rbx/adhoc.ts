/**
 * The Run view's choice between the last `rbx run` and the last `rbx irun`.
 *
 * Pure, so the label and the choice are tested rather than trusted; the host
 * (runView.ts) holds the state and the webview (render.ts) draws it.
 */
import type { RunSource } from './layout';
import type { TestcaseEntry } from './model';
import type { PackageRun } from './store';

/** What the source toggle draws, or undefined when there is nothing to choose. */
export interface SourceChoice {
  /** The source the view is showing. */
  readonly selected: RunSource;
  /** What the ad-hoc run ran, for the toggle's tooltip. */
  readonly adhoc: string;
}

/**
 * Say what an ad-hoc run ran, the way the setter asked for it.
 *
 * `rbx irun` records it in the one entry of its skeleton: a generator call
 * (`-g`), a testset entry (`-t`, which keeps the entry's own group and index),
 * or neither -- input typed at the prompt, which rbx files under the synthetic
 * `interactive` group.
 */
export function describeAdhoc(entry: TestcaseEntry | undefined): string {
  if (entry === undefined) {
    return 'ad-hoc run';
  }
  // The group first: a testset entry made by a generator carries its call too,
  // and `-t samples/1` is what the setter typed.
  if (entry.group !== 'interactive') {
    return `${entry.group}/${entry.index}`;
  }
  if (entry.generatorName !== undefined) {
    const args = entry.generatorArgs?.trim() ?? '';
    return args === '' ? entry.generatorName : `${entry.generatorName} ${args}`;
  }
  return 'typed input';
}

/**
 * The source to show, and whether to offer the toggle at all.
 *
 * An ad-hoc run that is not on disk cannot be shown, so asking for one falls
 * back to the main run -- and with nothing to switch to, no toggle is drawn.
 */
export function chooseSource(
  wanted: RunSource,
  adhoc: PackageRun | undefined,
): { readonly source: RunSource; readonly choice?: SourceChoice } {
  if (adhoc === undefined) {
    return { source: 'run' };
  }
  return {
    source: wanted,
    choice: { selected: wanted, adhoc: describeAdhoc(adhoc.skeleton.entries[0]) },
  };
}
