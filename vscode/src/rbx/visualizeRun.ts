/**
 * Driving `rbx visualize` -- the one thing the extension asks rbx to *do*.
 *
 * Everywhere else the extension is a pure reader (design D2/D3). This is the
 * documented exception: a solution's output visualization has no eager
 * equivalent, because `rbx build --visualize` only ever visualizes the testset,
 * while a solution's output is produced by `rbx run` and lives per solution
 * under the cache. There is nothing on disk to read, so the artifact has to be
 * asked for.
 *
 * Nothing here imports `vscode`, so `node --test` can hold it to account. The
 * host half -- spawning, progress, opening the result -- is visualize.ts.
 */
import * as path from 'path';

import { Ext, PackageLayout, buildPath, testArtifactPath } from './layout';

/** The command's protocol, as documented in rbx/box/visualization.py. */
export const enum VisualizeExit {
  /** Artifact produced; its absolute path is on stdout. */
  Ok = 0,
  /** Something failed; a message is on stderr. */
  Failure = 1,
  /** This rbx would clear the package's cache, so it refused. */
  CacheSkew = 3,
  /** Ran interactively and wrote no file. Success with nothing to open. */
  Interactive = 42,
}

/** What the caller should do about a finished `rbx visualize`. */
export type VisualizeOutcome =
  | { readonly kind: 'opened'; readonly filePath: string }
  | { readonly kind: 'interactive' }
  | { readonly kind: 'cache-skew' }
  | { readonly kind: 'failed'; readonly message: string };

/**
 * Strip ANSI escapes.
 *
 * rbx restores the cursor on exit, so stdout really ends
 * `<path>\n\x1b[?25h ` even when nothing rendered a spinner. The path line is
 * the machine-readable half of the protocol, so the escape has to come off
 * before anything reads it -- verified against the real bytes, not assumed.
 */
export function stripAnsi(text: string): string {
  // The escape byte is named rather than written literally: a raw control
  // character in source is invisible to review and easy to lose in an edit.
  return text.replace(/\u001b\[[0-9;?]*[A-Za-z]/g, '');
}

/**
 * The artifact path out of a successful run's stdout.
 *
 * Takes the last non-empty line rather than the first: the path is the only
 * thing this command prints to stdout, but a future line of chatter ahead of it
 * should not be mistaken for the answer.
 */
export function parseVisualizationPath(stdout: string): string | undefined {
  const lines = stripAnsi(stdout)
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  return lines.length > 0 ? lines[lines.length - 1] : undefined;
}

/** Turn an exit code and its streams into what the caller should do. */
export function interpretVisualizeExit(
  code: number | null,
  stdout: string,
  stderr: string,
): VisualizeOutcome {
  if (code === VisualizeExit.Interactive) {
    return { kind: 'interactive' };
  }
  if (code === VisualizeExit.CacheSkew) {
    return { kind: 'cache-skew' };
  }
  if (code === VisualizeExit.Ok) {
    const filePath = parseVisualizationPath(stdout);
    if (filePath === undefined) {
      // Exit 0 promises a path. Without one there is nothing to open, and
      // silently doing nothing would read as a broken click.
      return {
        kind: 'failed',
        message: 'rbx visualize reported success but printed no path.',
      };
    }
    return { kind: 'opened', filePath };
  }
  const message = stripAnsi(stderr).trim();
  return {
    kind: 'failed',
    message: message.length > 0 ? message : `rbx visualize exited with ${code}.`,
  };
}

/** Which of the two visualizers to run. */
export type VisualizeKind = 'input' | 'output';

export interface VisualizeRequest {
  readonly kind: VisualizeKind;
  /** The testcase's input. Always required -- it is what selects the visualizer. */
  readonly inputPath: string;
  /** The output to visualize (`output`), or to pass alongside (`input`). */
  readonly outputPath?: string;
  /** An answer to compare the output against. `output` only. */
  readonly answerPath?: string;
  /** Where to write the artifact, WITHOUT an extension. */
  readonly dest?: string;
}

/**
 * Argv for `rbx visualize`.
 *
 * Addressing is by path, so the extension resolves every path itself (it
 * already does, to render the panes) and rbx resolves none. That is what lets
 * one command serve a run artifact, a built answer, or anything else.
 *
 * `--use-stderr` is deliberately never sent: it derives the stderr file by
 * suffix substitution, which is wrong on a communication task, where the
 * solution's stderr is `.sol.err` and `.err` belongs to the interactor. The
 * caller passes the stderr file as `outputPath` instead, which mounts to the
 * same place and cannot guess wrong.
 */
export function visualizeArgs(request: VisualizeRequest): string[] {
  const args = ['visualize', request.kind, '--input', request.inputPath];
  if (request.outputPath !== undefined) {
    args.push('--output', request.outputPath);
  }
  if (request.kind === 'output' && request.answerPath !== undefined) {
    args.push('--answer', request.answerPath);
  }
  if (request.dest !== undefined) {
    args.push('--dest', request.dest);
  }
  return args;
}

/**
 * Where a solution-output visualization should land.
 *
 * Under the **build** directory, deliberately, and not beside the output it
 * visualizes. Left to itself rbx would write it next to the run artifact, i.e.
 * inside `.rbx/runs/<i>/<group>/output_visualization/` -- and the extension
 * watches `**​/.rbx/**` to follow a run, so every visualize click would
 * invalidate the run view and churn the tree for an artifact that says nothing
 * about the run's progress. Nothing watches the build directory except the
 * testset manifest, so writing here costs zero watcher events rather than
 * events that then have to be filtered out.
 *
 * The solution index is in the path because two solutions have different
 * outputs for the same testcase, and would otherwise overwrite each other.
 *
 * Returns a *stem*: the visualizer owns the extension, and the final path comes
 * back on stdout.
 */
export function solutionVisualizationDest(
  pkg: PackageLayout,
  solutionIndex: number,
  group: string,
  stem: string,
): string {
  return path.join(
    buildPath(pkg),
    'visualizations',
    'runs',
    String(solutionIndex),
    group,
    stem,
  );
}

/** The built input for a testcase, which selects which visualizer applies. */
export function testcaseInputPath(
  pkg: PackageLayout,
  group: string,
  stem: string,
): string {
  return testArtifactPath(pkg, group, stem, Ext.Input);
}
