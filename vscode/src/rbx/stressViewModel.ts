/**
 * What the Stress view shows, decided ahead of any markup (design S3).
 *
 * The same split as testsetViewModel.ts: everything with an answer -- what a
 * state is called, which chips a finding gets, whether Compare has two things
 * to compare -- is settled here, where `node --test` reaches it, and the
 * renderer only paints. The host brings what needs a disk or a process table
 * (the manifest, whether its rbx is still alive, which outputs a finding has)
 * already resolved, so nothing below touches either.
 */
import * as path from 'path';

import { Hue, hueOfThemeColor } from './hue';
import { outcomeIcon, shortName } from './outcome';
import { StressManifest, StressSpec } from './stress';
import { StressDeclaration } from './stressDeclarations';
import {
  StressLaunch,
  defaultLaunch,
  generatorCallString,
  parseLaunch,
  validateLaunch,
} from './stressSpec';

/**
 * The session's state as the view says it. `stale` is the one the manifest
 * cannot: `running` on disk, with no rbx left to finish it.
 */
export type StressViewState = 'running' | 'done' | 'interrupted' | 'failed' | 'stale';

export interface StressDeclaredRow {
  readonly name: string;
  /** `<generator call> · <finder>`, as written in problem.rbx.yml. */
  readonly summary: string;
}

export interface StressStatus {
  readonly state: StressViewState;
  readonly label: string;
  readonly hue: Hue;
  readonly executed: number;
  readonly skipped: number;
  readonly findings: number;
  readonly findingsLimit?: number;
  /** Seconds, as of the manifest's last write. */
  readonly elapsed: number;
  /** Seconds; the session's budget. */
  readonly timeout?: number;
  /**
   * Epoch ms, only while the session is running and alive: the client ticks
   * the clock from it, so the host needs no timer to keep it moving.
   */
  readonly startedAtMs?: number;
  /** What was run: the declared name, or the flags that said it. */
  readonly spec: string;
  /**
   * Whether Stop can stop it: running, and as a task VS Code knows of. A
   * session started from a plain terminal is live but not ours to end.
   */
  readonly stoppable: boolean;
  /** Running, alive, and not stoppable from here: say where to stop it. */
  readonly external: boolean;
}

export interface StressChip {
  /** The solution's basename, which is what fits in a sidebar. */
  readonly solution: string;
  /** The declared path, for the tooltip. */
  readonly path: string;
  /** Index into the manifest's `solutions`: the stem of its output file. */
  readonly index: number;
  readonly short: string;
  readonly icon: string;
  readonly hue: Hue;
}

export interface StressFindingRow {
  /** The finding's `index`, which every message back to the host names. */
  readonly k: number;
  /** `name args`: what reproduces the input, and what Copy copies. */
  readonly call: string;
  readonly duration?: string;
  readonly chips: readonly StressChip[];
  /** The group it was promoted into this session, when the extension knows. */
  readonly promoted?: string;
  /** Whether at least two outputs (the answer counting as one) are on disk. */
  readonly canCompare: boolean;
}

export interface StressViewModel {
  /** No package to show: the whole view is the empty state. */
  readonly noPackage: boolean;
  /** Whether Run, New, Edit and Stop can do anything; see `dispatchEnabled`. */
  readonly dispatch: boolean;
  readonly declared: readonly StressDeclaredRow[];
  /** Absent before the package's first stress session. */
  readonly status?: StressStatus;
  readonly findings: readonly StressFindingRow[];
  /**
   * The session's `startedAt`, echoed back in every finding message so the
   * host can tell a click on the last session's row from one on this one's.
   */
  readonly session?: string;
}

export const EMPTY_STRESS_MODEL: StressViewModel = {
  noPackage: true,
  dispatch: false,
  declared: [],
  findings: [],
};

export interface StressModelInput {
  readonly declared: readonly StressDeclaration[];
  readonly manifest?: StressManifest;
  /**
   * Whether a `running` manifest still has its rbx: the host's verdict, after
   * `stressLiveness` and the task-list fallback. Ignored for any other state.
   */
  readonly alive: boolean;
  /** Whether a dispatched `rbx stress` task is running for this package. */
  readonly task: boolean;
  /** Findings this session promoted, by index, to the group they went into. */
  readonly promoted?: ReadonlyMap<number, string>;
  /** Findings with at least two outputs to compare, by index. */
  readonly comparable?: ReadonlySet<number>;
  readonly dispatch: boolean;
}

const STATES: Record<StressViewState, { readonly label: string; readonly hue: Hue }> = {
  running: { label: 'Running', hue: 'blue' },
  done: { label: 'Done', hue: 'green' },
  interrupted: { label: 'Interrupted', hue: 'yellow' },
  failed: { label: 'Failed', hue: 'red' },
  // Not "failed": rbx said nothing of the sort, it just stopped saying anything.
  stale: { label: 'Stopped (rbx is gone)', hue: 'orange' },
};

/** A duration in ms, at the precision a sidebar row wants. */
export function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }
  if (ms < 60_000) {
    return `${(ms / 1000).toFixed(1)} s`;
  }
  const seconds = Math.round(ms / 1000);
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`;
}

/**
 * What was run, in the spelling the user would recognise: a declared stress
 * by its name, an ad-hoc one by the flags `rbx stress` was given.
 */
export function specSummary(spec: StressSpec): string {
  if (spec.name !== undefined) {
    return spec.name;
  }
  const parts: string[] = [];
  if (spec.generator !== undefined) {
    parts.push(`-g ${spec.generator}`);
  }
  if (spec.fuzz !== undefined) {
    parts.push(spec.fuzz.length === 0 ? '--fuzz' : spec.fuzz.map((g) => `--fuzz-on ${g}`).join(' '));
  }
  if (spec.finder !== undefined) {
    parts.push(`-f ${spec.finder}`);
  }
  if (spec.slowest) {
    parts.push('--slowest');
  }
  return parts.join(' ');
}

function stateOf(manifest: StressManifest, alive: boolean): StressViewState {
  return manifest.state === 'running' && !alive ? 'stale' : manifest.state;
}

function statusOf(manifest: StressManifest, alive: boolean, task: boolean): StressStatus {
  const state = stateOf(manifest, alive);
  const started = manifest.startedAt === undefined ? NaN : Date.parse(manifest.startedAt);
  return {
    state,
    ...STATES[state],
    executed: manifest.executed,
    skipped: manifest.skipped,
    findings: manifest.findings.length,
    findingsLimit: manifest.spec.findingsLimit,
    elapsed: manifest.elapsed,
    timeout: manifest.spec.timeout,
    startedAtMs: state === 'running' && !Number.isNaN(started) ? started : undefined,
    spec: specSummary(manifest.spec),
    stoppable: state === 'running' && task,
    external: state === 'running' && !task,
  };
}

function findingRows(
  manifest: StressManifest,
  promoted: ReadonlyMap<number, string> | undefined,
  comparable: ReadonlySet<number> | undefined,
): StressFindingRow[] {
  return manifest.findings.map((finding) => ({
    k: finding.index,
    call: generatorCallString(finding.generator),
    duration: finding.duration === undefined ? undefined : formatDuration(finding.duration),
    chips: finding.results.map((result) => {
      // A result naming a solution the list does not have is an rbx bug, but
      // the verdict is still worth showing; the index stands in for the name.
      const declared = manifest.solutions[result.solution] ?? `#${result.solution}`;
      const icon = outcomeIcon(result.outcome);
      return {
        solution: path.posix.basename(declared),
        path: declared,
        index: result.solution,
        short: shortName(result.outcome),
        icon: icon.icon,
        hue: hueOfThemeColor(icon.color),
      };
    }),
    promoted: promoted?.get(finding.index),
    canCompare: comparable?.has(finding.index) ?? false,
  }));
}

export function buildStressViewModel(input: StressModelInput): StressViewModel {
  const manifest = input.manifest;
  return {
    noPackage: false,
    dispatch: input.dispatch,
    declared: input.declared.map((stress) => ({
      name: stress.name,
      summary: `${generatorCallString(stress.generator)} · ${stress.finder}`,
    })),
    status: manifest === undefined ? undefined : statusOf(manifest, input.alive, input.task),
    findings: manifest === undefined ? [] : findingRows(manifest, input.promoted, input.comparable),
    session: manifest?.startedAt,
  };
}

/**
 * What Run on a declared stress launches: the launcher's last launch, if it
 * was this very stress and still holds up, else the stress as declared.
 *
 * `remembered` comes out of `workspaceState`, written by whichever version of
 * the launcher ran last, so it is checked rather than trusted: anything that
 * does not validate against today's declaration is dropped for the default,
 * which can always run.
 */
export function declaredRunLaunch(
  name: string,
  declared: readonly StressDeclaration[],
  remembered: unknown,
): { readonly launch: StressLaunch; readonly declared?: StressDeclaration } {
  const declaration = declared.find((stress) => stress.name === name);
  const fallback = { launch: defaultLaunch({ kind: 'declared', name }), declared: declaration };
  // Rebuilt field by field rather than cast: a shape no launcher this
  // extension shipped would write is no launch at all.
  const candidate = parseLaunch(remembered);
  if (candidate?.source.kind !== 'declared' || candidate.source.name !== name) {
    return fallback;
  }
  return validateLaunch(candidate, declaration) === undefined
    ? { launch: candidate, declared: declaration }
    : fallback;
}
