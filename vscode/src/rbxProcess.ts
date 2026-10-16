/**
 * Spawning `rbx`, and finding the `rbx` to spawn.
 *
 * The extension is a reader everywhere else (design D2/D3). Spawning rbx at
 * all is a deliberate exception, narrowed to read-only, idempotent work the
 * user explicitly asked for. It does not drive the build: `rbx build` / `rbx
 * run` always run in a visible terminal -- typed by the user, or dispatched
 * there as a VS Code task by dispatch.ts (D3 as amended by #906) -- and never
 * through `run` here.
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
  helpOffersOnInvalid,
  loginShellProbe,
  parseLoginShellPath,
  probeIsDefinite,
  probeKey,
  rbxCandidates,
} from './rbx/executable';
import { Limiter } from './rbx/limiter';

/** How long the login-shell probe may take before we give up on it. */
const PROBE_TIMEOUT_MS = 5_000;

/**
 * At most this many `run` processes alive at once, across the whole extension.
 *
 * Each is a Python interpreter importing rbx. Every caller is meant to ask
 * about a handful of packages, but a caller that loops over every discovered
 * one -- in a workspace with thousands -- once started them all together,
 * exhausted the file descriptors and put the machine's load average in the
 * hundreds. This is the backstop for the next such loop, not the fix for it.
 */
const MAX_CONCURRENT_SPAWNS = 10;

/** How long a binary that failed `--version` stays failed before it is asked again. */
const FAILED_CHECK_TTL_MS = 30_000;

const spawns = new Limiter(MAX_CONCURRENT_SPAWNS);

export interface SpawnResult {
  readonly code: number | null;
  readonly stdout: string;
  readonly stderr: string;
  /** Set when the process could not be started at all (typically ENOENT). */
  readonly spawnError?: NodeJS.ErrnoException;
}

/**
 * Run `command` and collect what it printed, waiting for a free slot first.
 *
 * The timeout starts when the process does, not while it waits: a queue behind
 * a busy contest must not make a healthy rbx look stuck.
 *
 * `stdin` is optional and, when omitted, the child's stdin is left exactly as
 * it was before this parameter existed: a pipe nobody writes to and nobody
 * closes. Only a caller that passes text changes anything, which is what leaves
 * every other caller -- `rbx visualize`, `rbx vars --json`, and the `--version`
 * and login-shell probes below -- running as it did.
 */
export function run(
  command: string,
  args: string[],
  cwd: string,
  timeoutMs: number,
  stdin?: string,
): Promise<SpawnResult> {
  return spawns.run(() => spawnAndCollect(command, args, cwd, timeoutMs, stdin));
}

function spawnAndCollect(
  command: string,
  args: string[],
  cwd: string,
  timeoutMs: number,
  stdin?: string,
): Promise<SpawnResult> {
  return new Promise((resolve) => {
    const child = spawn(command, args, { cwd, shell: false });

    if (stdin !== undefined) {
      // Swallowed, not reported: a child that exits without draining its input
      // leaves this write to fail with EPIPE, and an unhandled `error` on the
      // stream would throw out of the event loop. Whatever went wrong shows up
      // as the exit code and stderr below, which is what the caller reads.
      child.stdin?.on('error', () => undefined);
      child.stdin?.end(stdin);
    }

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

/**
 * Resolutions in flight, per root, so features asking about one root at the
 * same moment share its probes instead of each starting their own.
 */
const resolving = new Map<string, Promise<string | undefined>>();

interface Check {
  readonly answer: Promise<boolean>;
  /** When the binary failed, so the failure can expire; unset while pending or once it passed. */
  failedAt?: number;
}

/** Per binary (see `probeKey`): whether it answers `--version`. */
const checks = new Map<string, Check>();

export function resetRbxExecutables(): void {
  resolved.clear();
  resolving.clear();
  checks.clear();
  onInvalidSupport.clear();
}

/** Per executable: whether its `rbx run` takes `--on-invalid`. */
const onInvalidSupport = new Map<string, Promise<boolean>>();

/**
 * Whether this rbx can be asked to run past invalid testcases.
 *
 * Probed once per executable and remembered, failures included: a probe that
 * failed answers `false`, so the run goes out exactly as it did before the
 * flag existed rather than not at all.
 */
export function supportsOnInvalid(executable: string, cwd: string): Promise<boolean> {
  let answer = onInvalidSupport.get(executable);
  if (answer === undefined) {
    answer = run(executable, ['run', '--help'], cwd, PROBE_TIMEOUT_MS).then((result) => {
      const supported = result.code === 0 && helpOffersOnInvalid(result.stdout);
      log(`rbx at ${executable} ${supported ? 'takes' : 'does not take'} --on-invalid.`);
      return supported;
    });
    onInvalidSupport.set(executable, answer);
  }
  return answer;
}

/**
 * Whether this candidate is an rbx that actually runs.
 *
 * Asked once per binary rather than once per root, and the failures are
 * remembered too, for a while: a stale `rbx.executable` would otherwise cost a
 * failed spawn for every package before each one fell through to `PATH`. A
 * timeout is not remembered at all (`probeIsDefinite`).
 */
function validate(command: string, root: string): Promise<boolean> {
  const key = probeKey(command, root);
  const cached = checks.get(key);
  if (
    cached !== undefined &&
    (cached.failedAt === undefined || Date.now() - cached.failedAt < FAILED_CHECK_TTL_MS)
  ) {
    return cached.answer;
  }
  const check: Check = {
    answer: run(command, ['--version'], root, PROBE_TIMEOUT_MS).then((result) => {
      const usable = result.spawnError === undefined && result.code === 0;
      if (checks.get(key) === check) {
        if (!probeIsDefinite(result)) {
          checks.delete(key);
        } else if (!usable) {
          check.failedAt = Date.now();
        }
      }
      return usable;
    }),
  };
  checks.set(key, check);
  return check.answer;
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

export function resolveRbx(root: string): Promise<string | undefined> {
  const cached = resolved.get(root);
  if (cached !== undefined) {
    return Promise.resolve(cached);
  }
  let pending = resolving.get(root);
  if (pending === undefined) {
    pending = resolveUncached(root).finally(() => resolving.delete(root));
    resolving.set(root, pending);
  }
  return pending;
}

async function resolveUncached(root: string): Promise<string | undefined> {
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
