/**
 * Finding the `rbx` to run, per package.
 *
 * The extension host's `PATH` is **not** the integrated terminal's. It is
 * inherited from whatever launched VS Code: start it with `code .` and it is
 * the user's shell `PATH`; start it from Dock, Finder or Spotlight on macOS and
 * it is a minimal `/usr/bin:/bin:/usr/sbin:/sbin` with no `~/.local/bin` -- which
 * is exactly where `uv tool install` and `pipx` put rbx, and exactly what
 * docs/intro/installation.md recommends. So a bare `spawn('rbx')` works or fails
 * depending on how the editor was opened, which is the worst kind of bug report.
 *
 * (The Python extension's virtualenv activation does not help: it injects
 * environment into *terminal* creation and has no effect on `child_process`.)
 *
 * Resolution is cached per **package root**, and resolved with `cwd` set to that
 * root, so direnv, mise or a project-local `.venv` each give their own package
 * the rbx it expects. A session-global cache would pin whichever package was
 * visualized first and be wrong for every other one.
 *
 * Nothing here imports `vscode`; the settings value is passed in.
 */

/** How one candidate was arrived at, for logging when it turns out to be wrong. */
export type RbxSource = 'setting' | 'path' | 'login-shell';

export interface RbxCandidate {
  readonly command: string;
  readonly source: RbxSource;
}

/**
 * The candidates to try, in order, for a package.
 *
 * The setting wins outright -- someone who set it has already been let down by
 * the automatic answer. `PATH` comes next because it costs nothing and is right
 * whenever the editor was launched from a shell. The login shell is last
 * because it spawns a shell, which is worth ~200ms and is only needed when the
 * cheap answer missed.
 *
 * This is an ordering of *candidates*, not a commitment: the caller validates
 * each and falls through, so a stale binary on `PATH` does not shadow the right
 * one further down.
 */
export function rbxCandidates(configured: string | undefined): RbxCandidate[] {
  const candidates: RbxCandidate[] = [];
  const trimmed = configured?.trim();
  if (trimmed !== undefined && trimmed.length > 0) {
    candidates.push({ command: trimmed, source: 'setting' });
  }
  candidates.push({ command: 'rbx', source: 'path' });
  candidates.push({ command: 'rbx', source: 'login-shell' });
  return candidates;
}

/**
 * The command a login shell runs to report where `rbx` is.
 *
 * `-l` so profile files are read (that is the whole point), `-i` because many
 * setups put their `PATH` edits in the interactive rc rather than the profile,
 * and `command -v` because it is POSIX and does not depend on `which` existing.
 */
export function loginShellProbe(shell: string): {
  command: string;
  args: string[];
} {
  return { command: shell, args: ['-lic', 'command -v rbx'] };
}

/**
 * The absolute path a login-shell probe reported, if it reported one.
 *
 * An interactive login shell prints whatever the user's rc prints -- banners,
 * version managers announcing themselves -- so the answer is the last line that
 * looks like a path, not the whole output.
 */
export function parseLoginShellPath(stdout: string): string | undefined {
  const lines = stdout
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('/'));
  return lines.length > 0 ? lines[lines.length - 1] : undefined;
}
