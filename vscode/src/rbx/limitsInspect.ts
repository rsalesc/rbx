/**
 * What `rbx time-inspect` prints about a limits profile (`.limits/<name>.yml`).
 *
 * Like report.ts, this mirrors field names and nothing else: every check below
 * -- whether a limit is under what an accepted solution needs, whether a slow
 * solution would now pass -- was decided by `rbx.box.timing_edit`, the module
 * `rbx time --edit` routes through. The time-profile editor only draws it.
 */

/** The only inspect version this extension understands. */
export const SUPPORTED_INSPECT_VERSION = 1;

export type SolutionStatus = 'ok' | 'thin' | 'fails' | 'passes' | 'unverified' | 'unchecked';

export interface TimingBound {
  readonly value: number;
  readonly solution?: string | null;
}

export interface GroupReport {
  readonly languages: string[];
  readonly timeLimit: number;
  readonly origin: 'estimated' | 'multiplier' | 'defaulted';
  readonly solutionCount?: number;
  readonly fastest?: number;
  readonly slowest?: number;
  readonly relativeToLanguage?: string;
  readonly multiplier?: number;
  readonly increment?: number;
  readonly isLeftover?: boolean;
  readonly estimatedTimeLimit?: number;
}

export interface GroupCheck {
  readonly time_limit: number;
  readonly estimated: number | null;
  readonly min_ms: number | null;
  readonly min_solution: string | null;
  readonly max_ms: number | null;
  readonly max_solution: string | null;
  readonly slowest_ms: number | null;
  readonly violating: TimingBound[];
  readonly confirmed: string[];
  readonly unverified: string[];
  readonly ok: boolean;
  readonly belowMin: boolean;
  readonly breaksUpper: boolean;
  readonly rejectsOwnSolutions: boolean;
}

export interface SolutionCheck {
  readonly path: string;
  readonly language: string;
  /** `LOWER` for an accepted solution, `UPPER` for one expected too slow. */
  readonly role: string;
  readonly time: number | null;
  readonly survived_at: number | null;
  readonly min_ms: number | null;
  readonly max_ms: number | null;
  readonly ratio: number | null;
  readonly status: SolutionStatus;
  /** What problem.rbx.yml declares for it: an `ExpectedOutcome` member name. */
  readonly expectedOutcome?: string | null;
}

/**
 * A solution the last run judged and the estimate did not measure, read off
 * `.rbx/runs/report.yml` -- typically what `rbx time --run-all` adds.
 */
export interface RunSolution {
  readonly path: string;
  readonly language: string | null;
  readonly expectedOutcome: string;
  /** An `Outcome` value (`wrong-answer`, ...); null when nothing was judged. */
  readonly outcome: string | null;
  readonly matchesExpectation: boolean;
  readonly complete: boolean;
  /** ms. */
  readonly maxTime: number | null;
  /** The limit it ran under, in ms. */
  readonly timeLimit: number | null;
}

export interface LastRun {
  /** The limits profiles the run resolved its limits from. */
  readonly profiles: string[];
  readonly finished: boolean;
  readonly endedAt?: string | null;
}

export interface Row {
  /** `base`, or the group's index as a string: what `--set`/`--revert` take. */
  readonly key: string;
  readonly report: GroupReport | null;
  readonly timeLimit: number | null;
  readonly editable: boolean;
  readonly check: GroupCheck | null;
  readonly solutions: SolutionCheck[];
  readonly runSolutions?: RunSolution[];
}

export interface Multipliers {
  readonly acToTimeLimit?: number;
  readonly fastestToTimeLimit?: number;
  readonly timeLimitToTle?: number;
  readonly timeResolution?: number;
}

export interface EffectiveLimits {
  readonly timeLimit: number;
  readonly memoryLimit: number;
  readonly outputLimit: number;
  readonly languages: { language: string; timeLimit: number; memoryLimit: number }[];
  readonly package: { timeLimit: number; memoryLimit: number; outputLimit: number };
}

export interface InspectResult {
  readonly version: number;
  readonly profile: string;
  readonly path: string;
  readonly errors: string[];
  /** Present only when an edit was asked for: the whole edited profile. */
  readonly yaml?: string;
  readonly inheritFromPackage?: boolean;
  readonly timeLimit?: number | null;
  readonly memoryLimit?: number | null;
  readonly outputLimit?: number | null;
  readonly formula?: string | null;
  readonly multipliers?: Multipliers | null;
  readonly editable?: boolean;
  readonly hasSolutions?: boolean;
  readonly rows?: Row[];
  readonly effective?: EffectiveLimits;
  readonly lastRun?: LastRun | null;
  /** The checksum bucket that moved since the estimate, or null. */
  readonly stale?: 'solutions' | 'interactor' | 'tests' | null;
}

export type ParseOutcome =
  | { readonly ok: true; readonly result: InspectResult }
  | { readonly ok: false; readonly error: string };

/** Parse rbx's stdout: the last line holding a JSON object. */
export function parseInspect(stdout: string): ParseOutcome {
  const line = stdout
    .split('\n')
    .map((l) => l.trim())
    .reverse()
    .find((l) => l.startsWith('{'));
  if (line === undefined) {
    return { ok: false, error: 'rbx printed no inspection result.' };
  }
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch (e) {
    return { ok: false, error: `Unreadable inspection result: ${String(e)}` };
  }
  if (typeof value !== 'object' || value === null) {
    return { ok: false, error: 'The inspection result is not an object.' };
  }
  const result = value as InspectResult;
  if (result.version !== SUPPORTED_INSPECT_VERSION) {
    return {
      ok: false,
      error: `This rbx speaks time-inspect v${String(result.version)}; the extension reads v${SUPPORTED_INSPECT_VERSION}. Update one of them.`,
    };
  }
  return { ok: true, result };
}

/** `.../<root>/.limits/<name>.yml` -> its problem root and profile name. */
export function profileLocation(
  fsPath: string,
): { readonly root: string; readonly profile: string } | undefined {
  const match = /^(.*)[\\/]\.limits[\\/]([^\\/]+)\.ya?ml$/.exec(fsPath);
  if (match === null) {
    return undefined;
  }
  return { root: match[1], profile: match[2] };
}

/** An edit the webview can ask for, as `rbx time-inspect` flags. */
export type ProfileEdit =
  | { readonly kind: 'set'; readonly row: string; readonly ms: number }
  | { readonly kind: 'revert'; readonly row: string }
  | { readonly kind: 'memory'; readonly mb: number }
  | { readonly kind: 'inherit'; readonly value: boolean };

export function inspectArgs(profile: string, edit?: ProfileEdit): string[] {
  const args = ['time-inspect', '-p', profile, '--stdin'];
  if (edit === undefined) {
    return args;
  }
  switch (edit.kind) {
    case 'set':
      return [...args, '--set', `${edit.row}=${Math.round(edit.ms)}`];
    case 'revert':
      return [...args, '--revert', edit.row];
    case 'memory':
      return [...args, '--memory', String(Math.round(edit.mb))];
    case 'inherit':
      return [...args, edit.value ? '--inherit' : '--no-inherit'];
  }
}

/** The step the ± buttons move a limit by. */
export function limitStep(result: InspectResult): number {
  return result.multipliers?.timeResolution ?? 100;
}
