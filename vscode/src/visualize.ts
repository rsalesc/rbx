/**
 * Running `rbx visualize` from the editor.
 *
 * The extension is a pure reader everywhere else (design D2/D3). This is the
 * one deliberate exception, narrowed to: a read-only, idempotent, per-testcase
 * artifact the user explicitly asked for. It does not drive the build -- there
 * is still no Build button, and `rbx build` / `rbx run` stay in the terminal.
 *
 * The doctrine reversal is safe in a way the original rationale did not know:
 * rbx cache directories take a *shared* session lock and support any number of
 * concurrent processes, and a cache is only ever emptied under an *exclusive*
 * lock that waits for (or refuses) live holders. So this cannot corrupt a run
 * in flight. The one hazard left -- a version-skewed rbx clearing the cache and
 * forcing a surprise rebuild -- rbx itself refuses, with exit code 3.
 *
 * Everything decidable without `vscode` lives in rbx/visualizeRun.ts and
 * rbx/executable.ts, which `node --test` covers.
 */
import { spawn } from 'child_process';
import * as os from 'os';
import * as vscode from 'vscode';

import { log } from './log';
import {
  RbxCandidate,
  loginShellProbe,
  parseLoginShellPath,
  rbxCandidates,
} from './rbx/executable';
import {
  VisualizeOutcome,
  VisualizeRequest,
  interpretVisualizeExit,
  visualizeArgs,
} from './rbx/visualizeRun';
import { openVisualization } from './visualizationPanel';

/** How long a visualizer may run before we stop waiting for it. */
const VISUALIZE_TIMEOUT_MS = 120_000;

/** How long the login-shell probe may take before we give up on it. */
const PROBE_TIMEOUT_MS = 5_000;

interface SpawnResult {
  readonly code: number | null;
  readonly stdout: string;
  readonly stderr: string;
  /** Set when the process could not be started at all (typically ENOENT). */
  readonly spawnError?: NodeJS.ErrnoException;
}

function run(
  command: string,
  args: string[],
  cwd: string,
  timeoutMs: number,
): Promise<SpawnResult> {
  return new Promise((resolve) => {
    const child = spawn(command, args, { cwd, shell: false });
    let stdout = '';
    let stderr = '';
    let settled = false;

    const finish = (result: SpawnResult) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };

    const timer = setTimeout(() => {
      child.kill();
      finish({
        code: null,
        stdout,
        stderr: `${stderr}\nTimed out after ${timeoutMs}ms.`,
      });
    }, timeoutMs);

    child.stdout?.on('data', (chunk) => {
      stdout += String(chunk);
    });
    child.stderr?.on('data', (chunk) => {
      stderr += String(chunk);
    });
    child.on('error', (error) => {
      finish({ code: null, stdout, stderr, spawnError: error });
    });
    child.on('close', (code) => {
      finish({ code, stdout, stderr });
    });
  });
}

/**
 * The resolved `rbx` for a package root.
 *
 * Cached per root rather than per session, and never populated with a candidate
 * that has not answered: a stale binary on `PATH` must fall through to the
 * login shell rather than being locked in for the rest of the session.
 */
const resolved = new Map<string, string>();

export function resetRbxExecutables(): void {
  resolved.clear();
}

/** Whether this candidate is an rbx that actually runs. */
async function validate(command: string, root: string): Promise<boolean> {
  const result = await run(command, ['--version'], root, PROBE_TIMEOUT_MS);
  return result.spawnError === undefined && result.code === 0;
}

async function resolveCandidate(
  candidate: RbxCandidate,
  root: string,
): Promise<string | undefined> {
  if (candidate.source !== 'login-shell') {
    return (await validate(candidate.command, root)) ? candidate.command : undefined;
  }

  // Resolved in the package root so direnv/mise/a project `.venv` answer for
  // *this* package.
  const shell = process.env.SHELL ?? '/bin/sh';
  if (os.platform() === 'win32') {
    // No login-shell equivalent worth guessing at; the setting is the answer.
    return undefined;
  }
  const probe = loginShellProbe(shell);
  const result = await run(probe.command, probe.args, root, PROBE_TIMEOUT_MS);
  const found = parseLoginShellPath(result.stdout);
  if (found === undefined) {
    return undefined;
  }
  return (await validate(found, root)) ? found : undefined;
}

async function resolveRbx(root: string): Promise<string | undefined> {
  const cached = resolved.get(root);
  if (cached !== undefined) {
    return cached;
  }

  const configured = vscode.workspace
    .getConfiguration('rbx', vscode.Uri.file(root))
    .get<string>('executable');

  for (const candidate of rbxCandidates(configured)) {
    const command = await resolveCandidate(candidate, root);
    if (command !== undefined) {
      log(`Resolved rbx for ${root} via ${candidate.source}: ${command}`);
      resolved.set(root, command);
      return command;
    }
    log(`rbx not usable for ${root} via ${candidate.source}.`);
  }
  return undefined;
}

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
