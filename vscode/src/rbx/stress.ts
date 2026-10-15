/**
 * The stress session rbx publishes at `.rbx/runs/.stress/stress.yml` (#908).
 *
 * The same contract as the run report (report.ts): rbx decides, the extension
 * reads. `rbx stress` used to keep its session in memory and print it, and the
 * only way to show one in the editor would have been to parse that output --
 * which design D2/D3 rules out, and which would lose the session on a window
 * reload besides. So `rbx.box.stress_manifest` writes it down instead, and this
 * mirrors its field names (see docs/plans/2026-10-15-vscode-stress-design.md).
 *
 * The file is rewritten atomically -- when a finding lands, and at most once a
 * second for the counters -- so a read never sees half of it. What can still
 * happen is an rbx and an extension that disagree on the version, which is
 * what the gate below is for.
 */
import { Wire, asArray, asBoolean, asNumber, asRecord, asString, field } from './wire';

/** The only stress manifest version this extension understands. */
export const STRESS_SUPPORTED_VERSION = 1;

/**
 * Where the session is.
 *
 * `interrupted` (Ctrl-C) and `failed` (an exception) are written by a `finally`
 * on rbx's way out, so a session that ended always says so. A `running` one
 * with no rbx task alive is the one case the file cannot describe -- rbx was
 * killed outright -- and telling it apart is the caller's job, from the tasks
 * it can see.
 */
export type StressState = 'running' | 'done' | 'interrupted' | 'failed';

const STATES: readonly StressState[] = ['running', 'done', 'interrupted', 'failed'];

/** What the session was asked to do. */
export interface StressSpec {
  /** The declared stress, when one was run by name. */
  readonly name?: string;
  /** The generator expression, unexpanded; absent when fuzzing. */
  readonly generator?: string;
  readonly finder?: string;
  /**
   * The testgroups fuzzed: absent for no fuzzing, `[]` for every group. rbx
   * writes `null` and `[]` apart on purpose, and so are they read apart.
   */
  readonly fuzz?: readonly string[];
  readonly slowest: boolean;
  /** Seconds. */
  readonly timeout?: number;
  readonly findingsLimit?: number;
  /** The effective time limit, ms, before any double TL; absent when unlimited. */
  readonly timelimit?: number;
  readonly doubleTL: boolean;
}

/** How one solution fared on a finding. */
export interface StressResult {
  /** Index into `StressManifest.solutions`; also the artifact file stem. */
  readonly solution: number;
  /**
   * The worst outcome across every finder call on this solution, as an rbx
   * `Outcome` value (`wrong-answer`) -- the same vocabulary a `.eval` uses, so
   * outcome.ts draws it without a second table.
   */
  readonly outcome: string;
  /** Seconds. */
  readonly time?: number;
  /** Bytes. */
  readonly memory?: number;
}

export interface StressFinding {
  /** From 1; also the directory name under `findings/`. */
  readonly index: number;
  /** The expanded call, with its seed: re-running it reproduces the input. */
  readonly generator: { readonly name: string; readonly args?: string };
  /** Milliseconds. */
  readonly duration?: number;
  /**
   * One per solution the finder evaluated. The reference solution may have
   * artifacts in the finding and still no entry here, when the finder only
   * needed its answer.
   */
  readonly results: readonly StressResult[];
}

export interface StressManifest {
  readonly state: StressState;
  readonly spec: StressSpec;
  /** ISO 8601, with its offset. */
  readonly startedAt?: string;
  /** Seconds. */
  readonly elapsed: number;
  readonly executed: number;
  readonly skipped: number;
  /** The solutions involved, in order; `StressResult.solution` indexes this. */
  readonly solutions: readonly string[];
  readonly findings: readonly StressFinding[];
}

function strings(raw: Wire): string[] {
  return asArray(raw)
    .map((value) => asString(value))
    .filter((value): value is string => value !== undefined);
}

function parseSpec(raw: Wire): StressSpec {
  const fuzz = field(raw, 'fuzz');
  return {
    name: asString(field(raw, 'name')),
    generator: asString(field(raw, 'generator')),
    finder: asString(field(raw, 'finder')),
    fuzz: Array.isArray(fuzz) ? strings(fuzz) : undefined,
    slowest: asBoolean(field(raw, 'slowest')) ?? false,
    timeout: asNumber(field(raw, 'timeout')),
    findingsLimit: asNumber(field(raw, 'findingsLimit')),
    timelimit: asNumber(field(raw, 'timelimit')),
    doubleTL: asBoolean(field(raw, 'doubleTL')) ?? false,
  };
}

function parseResult(raw: Wire): StressResult | undefined {
  // Both required: a result without its solution cannot be put on a row, and
  // one without its outcome would be drawn as pending in a session that may
  // well be over.
  const solution = asNumber(field(raw, 'solution'));
  const outcome = asString(field(raw, 'outcome'));
  if (solution === undefined || outcome === undefined) {
    return undefined;
  }
  return {
    solution,
    outcome,
    time: asNumber(field(raw, 'time')),
    memory: asNumber(field(raw, 'memory')),
  };
}

function parseFinding(raw: Wire): StressFinding | undefined {
  // The index names the directory the finding's files are in, and the call is
  // what Copy and Promote hand on: a finding missing either is no use to
  // anything that would show it.
  const index = asNumber(field(raw, 'index'));
  const name = asString(field(raw, 'generator', 'name'));
  if (index === undefined || name === undefined) {
    return undefined;
  }
  const results: StressResult[] = [];
  for (const rawResult of asArray(field(raw, 'results'))) {
    const result = parseResult(rawResult);
    if (result !== undefined) {
      results.push(result);
    }
  }
  return {
    index,
    generator: { name, args: asString(field(raw, 'generator', 'args')) },
    duration: asNumber(field(raw, 'duration')),
    results,
  };
}

/**
 * Parse a stress manifest, or return `undefined` when there is nothing usable.
 *
 * A version this extension does not know is ignored rather than read
 * optimistically, as with the run report; so is a state it does not know,
 * since the state is what decides whether the view says a session is still
 * going -- and guessing wrong there either hides a live session or shows a
 * finished one as stuck.
 */
export function parseStressManifest(raw: Wire): StressManifest | undefined {
  if (asRecord(raw) === undefined) {
    return undefined;
  }
  if (asNumber(field(raw, 'version')) !== STRESS_SUPPORTED_VERSION) {
    return undefined;
  }
  const state = asString(field(raw, 'state'));
  if (state === undefined || !(STATES as readonly string[]).includes(state)) {
    return undefined;
  }
  const findings: StressFinding[] = [];
  for (const rawFinding of asArray(field(raw, 'findings'))) {
    const finding = parseFinding(rawFinding);
    if (finding !== undefined) {
      findings.push(finding);
    }
  }
  return {
    state: state as StressState,
    spec: parseSpec(field(raw, 'spec')),
    startedAt: asString(field(raw, 'startedAt')),
    elapsed: asNumber(field(raw, 'elapsed')) ?? 0,
    executed: asNumber(field(raw, 'executed')) ?? 0,
    skipped: asNumber(field(raw, 'skipped')) ?? 0,
    solutions: strings(field(raw, 'solutions')),
    findings,
  };
}
