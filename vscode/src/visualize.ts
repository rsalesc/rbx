/**
 * Running `rbx visualize` from the editor.
 *
 * This is a read-only, idempotent, per-testcase artifact the user explicitly
 * asked for. It does not drive the build -- there is still no Build button, and
 * `rbx build` / `rbx run` stay in the terminal. Spawning rbx at all, and finding
 * the rbx to spawn, live in rbxProcess.ts.
 *
 * Everything decidable without `vscode` lives in rbx/visualizeRun.ts, which
 * `node --test` covers.
 */
import * as vscode from 'vscode';

import { log } from './log';
import { resolveRbx, run } from './rbxProcess';
import {
  VisualizeOutcome,
  VisualizeRequest,
  interpretVisualizeExit,
  visualizeArgs,
} from './rbx/visualizeRun';
import { openVisualization } from './visualizationPanel';

/** How long a visualizer may run before we stop waiting for it. */
const VISUALIZE_TIMEOUT_MS = 120_000;

/**
 * One in-flight visualization per package.
 *
 * Arrowing down a list with the key held would otherwise fan out into a queue
 * of sandboxed compilations, each of which the user has already moved past.
 */
const inFlight = new Set<string>();

function reportFailure(message: string): void {
  log(`rbx visualize failed: ${message}`);
  // A compile failure is many lines and does not fit a toast, so the toast is
  // an entry point to the channel rather than the message itself.
  void vscode.window
    .showErrorMessage('rbx could not build this visualization.', 'Show Output')
    .then((choice) => {
      if (choice === 'Show Output') {
        void vscode.commands.executeCommand('workbench.action.output.toggleOutput');
      }
    });
}

/**
 * Run a visualizer for one testcase and show what it produced.
 *
 * `label` is what the resulting panel is titled -- e.g. `main/000 (output)`.
 */
export async function runVisualizer(
  context: vscode.ExtensionContext,
  root: string,
  request: VisualizeRequest,
  label: string,
): Promise<void> {
  if (inFlight.has(root)) {
    return;
  }

  const command = await resolveRbx(root);
  if (command === undefined) {
    void vscode.window.showErrorMessage(
      'Could not find rbx. Set "rbx.executable" to its full path, or open VS Code from a terminal.',
    );
    return;
  }

  inFlight.add(root);
  try {
    const outcome = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: `Visualizing ${label}…` },
      async (): Promise<VisualizeOutcome> => {
        const args = visualizeArgs(request);
        log(`${command} ${args.join(' ')}`);
        const result = await run(command, args, root, VISUALIZE_TIMEOUT_MS);
        if (result.spawnError !== undefined) {
          return { kind: 'failed', message: String(result.spawnError.message) };
        }
        return interpretVisualizeExit(result.code, result.stdout, result.stderr);
      },
    );

    switch (outcome.kind) {
      case 'opened':
        await openVisualization(context, {
          root,
          filePath: outcome.filePath,
          label,
        });
        return;
      case 'interactive':
        // The visualizer said it interacted with the user and wrote no file.
        // That is a success with nothing to show.
        log(`Visualizer for ${label} ran interactively and produced no file.`);
        return;
      case 'cache-skew':
        // Deliberately not the generic failure toast: nothing is broken, and
        // the fix is specific.
        void vscode.window.showErrorMessage(
          'This package was built by a different version of rbx. ' +
            'Run "rbx build" in a terminal, or point "rbx.executable" at the matching rbx.',
        );
        return;
      case 'failed':
        reportFailure(outcome.message);
        return;
    }
  } finally {
    inFlight.delete(root);
  }
}
