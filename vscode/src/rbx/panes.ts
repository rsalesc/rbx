/**
 * What the testcase panes show, and how they recognise their own tabs.
 *
 * The decisions live here, away from `vscode`, so `node --test` can hold them
 * to account: which artifact a channel names, and -- the load-bearing one --
 * whether a tab already on screen is one of ours.
 *
 * That last question is what keeps the user's arrangement. `setEditorLayout`
 * rearranges the *whole* editor area, so calling it on every open would undo a
 * dragged pane on every arrow key. Instead the opener looks for its own tabs
 * first and reuses the groups it finds them in; the layout is only ever a seed
 * for the case where there are none. See
 * `docs/plans/2026-08-21-vscode-testcase-detail-design.md`.
 */
import { TestcaseRun } from './store';

/** What the second pane is showing. `out` is the diff, mirroring `rbx ui`. */
export type Channel = 'out' | 'err' | 'log';

export const CHANNELS: readonly Channel[] = ['out', 'err', 'log'];

/**
 * Which of the two panes a tab belongs to.
 *
 * `undefined` for a tab that is not the extension's at all, which is almost
 * every tab in a real window.
 */
export type PaneKind = 'input' | 'channel';

/**
 * The display names artifacts are opened under.
 *
 * These are the last segment of an `rbx:` URI's *path*, which is what
 * `artifactFs` turns into a tab title -- so they are both what the user reads
 * and how a tab is recognised later. Keeping the two jobs on one string is
 * deliberate: a tab titled `stderr.err` that we failed to recognise would be a
 * pane we opened and then abandoned.
 */
export const LABELS = {
  input: 'input.in',
  output: 'output.out',
  answer: 'answer.out',
  stderr: 'stderr.err',
  log: 'run.log',
} as const;

const CHANNEL_LABELS: readonly string[] = [
  LABELS.output,
  LABELS.answer,
  LABELS.stderr,
  LABELS.log,
];

/**
 * Which pane a display path names, if any.
 *
 * Matched on the last segment rather than the whole path: the rest of it is
 * `<solution>/<group>/<stem>`, which changes with every testcase, and a pane is
 * still the same pane when it moves to the next one.
 */
export function paneKindOf(displayPath: string): PaneKind | undefined {
  const name = displayPath.split('/').filter((part) => part !== '').pop();
  if (name === undefined) {
    return undefined;
  }
  if (name === LABELS.input) {
    return 'input';
  }
  return CHANNEL_LABELS.includes(name) ? 'channel' : undefined;
}

/**
 * `sols/wa.cpp/main/1-gen-000` -- the display prefix a testcase's tabs share.
 *
 * The last segment is appended per artifact and becomes the tab title; this
 * part is what tells two open testcases apart in the tab's tooltip.
 */
export function labelPrefix(solutionPath: string, group: string, stem: string): string {
  return `${solutionPath}/${group}/${stem}`;
}

/** One file a pane can be asked to show. */
export interface Artifact {
  /** Candidates, most likely first -- `stderrPaths` has two spellings. */
  readonly paths: readonly string[];
  /** The last segment of the display path, and so the tab's title. */
  readonly label: string;
  /** What to say when none of `paths` is on disk. */
  readonly missing: string;
}

/** The diff a channel of `out` shows: the solution's output against the answer. */
export interface DiffArtifact {
  readonly left: Artifact;
  readonly right: Artifact;
}

export function inputArtifact(testcase: TestcaseRun): Artifact {
  return {
    paths: [testcase.inputPath],
    label: LABELS.input,
    missing: 'No input on disk for this testcase. Run `rbx build` first.',
  };
}

export function outputArtifact(testcase: TestcaseRun): Artifact {
  return {
    paths: [testcase.outputPath],
    label: LABELS.output,
    missing: 'This solution produced no output for this testcase.',
  };
}

export function answerArtifact(testcase: TestcaseRun): Artifact {
  return {
    paths: [testcase.answerPath],
    label: LABELS.answer,
    missing: 'No expected answer on disk for this testcase.',
  };
}

/**
 * What the channel pane shows: a diff for `out`, a single file otherwise.
 *
 * `out` is the diff rather than the output alone because that is what `rbx ui`'s
 * output box is in two-sided mode -- the output beside what it should have been.
 * It also leaves one concept, a channel, where the alternative was a cycle plus
 * a loose "and also the answer" button.
 */
export function channelArtifact(
  channel: Channel,
  testcase: TestcaseRun,
): Artifact | DiffArtifact {
  switch (channel) {
    case 'out':
      return { left: outputArtifact(testcase), right: answerArtifact(testcase) };
    case 'err':
      return {
        paths: testcase.stderrPaths,
        label: LABELS.stderr,
        missing: 'This solution wrote nothing to stderr for this testcase.',
      };
    case 'log':
      return {
        paths: [testcase.logPath],
        label: LABELS.log,
        missing: 'rbx recorded no log for this testcase.',
      };
  }
}

export function isDiff(artifact: Artifact | DiffArtifact): artifact is DiffArtifact {
  return (artifact as DiffArtifact).left !== undefined;
}

/**
 * How the two panes are arranged the *first* time they are opened.
 *
 * A seed and nothing more: once the panes exist, the opener finds them and this
 * is never consulted again, so a user who drags them keeps the arrangement for
 * good. `beside` gives the input its own column; `below` stacks them the way
 * `rbx ui` does.
 */
export type TestcaseLayout = 'beside' | 'below';

export const DEFAULT_TESTCASE_LAYOUT: TestcaseLayout = 'beside';

export function asTestcaseLayout(value: unknown): TestcaseLayout {
  return value === 'below' ? 'below' : DEFAULT_TESTCASE_LAYOUT;
}

/**
 * The built-in command that seeds `layout`.
 *
 * These rather than a raw `vscode.setEditorLayout` payload: the layout API
 * takes an `orientation` whose two values are easy to get backwards and
 * impossible to unit-test, while `...TwoColumns` and `...TwoRows` say in their
 * names exactly what they produce and are the same commands the Layout menu
 * runs.
 */
export function layoutCommand(layout: TestcaseLayout): string {
  return layout === 'below'
    ? 'workbench.action.editorLayoutTwoRows'
    : 'workbench.action.editorLayoutTwoColumns';
}
