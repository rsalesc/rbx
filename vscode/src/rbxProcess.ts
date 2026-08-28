/**
 * Spawning `rbx`, and finding the `rbx` to spawn.
 *
 * The extension is a pure reader everywhere else (design D2/D3). Spawning rbx
 * at all is a deliberate exception, narrowed to read-only, idempotent work the
 * user explicitly asked for. It does not drive the build -- there is still no
 * Build button, and `rbx build` / `rbx run` stay in the terminal.
 *
 * The doctrine reversal is safe in a way the original rationale did not know:
 * rbx cache directories take a *shared* session lock and support any number of
 * concurrent processes, and a cache is only ever emptied under an *exclusive*
 * lock that waits for (or refuses) live holders. So this cannot corrupt a run
 * in flight. The one hazard left -- a version-skewed rbx clearing the cache and
 * forcing a surprise rebuild -- rbx itself refuses, with exit code 3.
 *
 * Everything decidable without `vscode` lives in rbx/executable.ts, which
 * `node --test` covers.
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

/** How long the login-shell probe may take before we give up on it. */
const PROBE_TIMEOUT_MS = 5_000;

export interface SpawnResult {
  readonly code: number | null;
  readonly stdout: string;
  readonly stderr: string;
  /** Set when the process could not be started at all (typically ENOENT). */
  readonly spawnError?: NodeJS.ErrnoException;
}

export function run(
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

export async function resolveRbx(root: string): Promise<string | undefined> {
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
