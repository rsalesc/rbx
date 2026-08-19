/**
 * The run report rbx publishes at `.rbx/runs/report.yml`.
 *
 * This is the whole reason the extension no longer decides anything about a
 * run. Every aggregate below -- the worst verdict, whether a solution met its
 * declared expectation, the points a group earned -- was computed by
 * `rbx.box.run_report` from the report `rbx run` was already building. Deriving
 * any of it here again is how the two implementations drifted in the first
 * place (see docs/plans/2026-08-16-run-report-artifact-design.md).
 *
 * Mirroring the *field names* is fine and deliberate: a renamed field fails
 * loudly and locally. Mirroring the *decisions* was not.
 */
import { Wire, asArray, asBoolean, asNumber, asString, field } from './wire';

/** The only report version this extension understands. */
export const SUPPORTED_VERSION = 1;

export interface GroupReport {
  readonly name: string;
  /** Worst verdict in the group; absent when none of it has been evaluated. */
  readonly outcome?: string;
  /** Set only when the solution declares an `outcomePerGroup` covering it. */
  readonly expectedOutcome?: string;
  readonly matchesExpectation: boolean;
  readonly score: number;
  readonly maxScore: number;
  /** Seconds. */
  readonly maxTime?: number;
  /** Bytes. */
  readonly maxMemory?: number;
  /** This group alone only timed out within double TL. */
  readonly runUnderDoubleTl: boolean;
  /** This group alone finished within double TL, but with these verdicts. */
  readonly doubleTlVerdicts: readonly string[];
}

export interface SolutionReport {
  readonly path: string;
  readonly index: number;
  readonly expectedOutcome?: string;
  readonly outcome?: string;
  readonly status: string;
  readonly matchesExpectation: boolean;
  /**
   * Whether the *pooled* `outcome` layer held on its own.
   *
   * `matchesExpectation` is the aggregate of two independent layers, and the
   * aggregate alone cannot say which of them to blame: `sols/mislabeled.cpp`
   * declares `incorrect` and *is* incorrect, and is caught only by its
   * `outcomePerGroup`. Absent on a report written by an rbx that predates the
   * field -- see `pooledMissed` in viewModel.ts for what stands in then.
   */
  readonly pooledMatchesExpectation?: boolean;
  readonly score: number;
  readonly maxScore: number;
  readonly maxTime?: number;
  readonly maxMemory?: number;
  readonly failedGroups: readonly string[];
  /** The `[min, max]` score range declared, when one was. */
  readonly expectedScore?: readonly [number, number];
  /**
   * A solution declared slow that only timed out *within* double TL.
   *
   * The one field here that describes a run which passed: `status` is `OK` and
   * `matchesExpectation` is true, so every other channel in the view draws this
   * solution clean. rbx decides it -- the console prints the same fact as a
   * WARNING -- and the extension only renders it.
   */
  readonly runUnderDoubleTl: boolean;
  /**
   * What a solution declared slow would have got without the time limit.
   *
   * Independent of `runUnderDoubleTl`, not an alternative to it: both are
   * unions over the pooled layer and every group, so two groups can each raise
   * one. Empty on an rbx that predates the field, which is indistinguishable
   * from a run with nothing to say -- and that is the safe direction.
   */
  readonly doubleTlVerdicts: readonly string[];
  readonly groups: readonly GroupReport[];
}

export interface RunReport {
  readonly solutions: readonly SolutionReport[];
}

function parseGroup(raw: Wire): GroupReport | undefined {
  const name = asString(field(raw, 'name'));
  if (name === undefined) {
    return undefined;
  }
  return {
    name,
    outcome: asString(field(raw, 'outcome')),
    expectedOutcome: asString(field(raw, 'expectedOutcome')),
    matchesExpectation: asBoolean(field(raw, 'matchesExpectation')) ?? true,
    score: asNumber(field(raw, 'score')) ?? 0,
    maxScore: asNumber(field(raw, 'maxScore')) ?? 0,
    maxTime: asNumber(field(raw, 'maxTime')),
    maxMemory: asNumber(field(raw, 'maxMemory')),
    runUnderDoubleTl: asBoolean(field(raw, 'runUnderDoubleTl')) ?? false,
    doubleTlVerdicts: parseOutcomes(field(raw, 'doubleTlVerdicts')),
  };
}

/**
 * The verdict names in a `doubleTlVerdicts` list, dropping anything unusable.
 *
 * Absent on a report written by an rbx that predates the field, which reads as
 * an empty list -- the same as a run with nothing to warn about. Under-warning
 * against an old report is the safe direction; inventing a warning is not.
 */
function parseOutcomes(raw: Wire): string[] {
  return asArray(raw)
    .map((value) => asString(value))
    .filter((value): value is string => value !== undefined);
}

/**
 * `[min, max]`, or `undefined` for anything that is not exactly that.
 *
 * Both ends are required: a half-parsed range would be rendered as a bound the
 * package never declared, which is worse than rendering no bound at all.
 */
function parseScoreRange(raw: Wire): readonly [number, number] | undefined {
  const values = asArray(raw)
    .map((value) => asNumber(value))
    .filter((value): value is number => value !== undefined);
  return values.length === 2 ? [values[0], values[1]] : undefined;
}

function parseSolution(raw: Wire): SolutionReport | undefined {
  const path = asString(field(raw, 'path'));
  const index = asNumber(field(raw, 'index'));
  if (path === undefined || index === undefined) {
    return undefined;
  }
  const groups: GroupReport[] = [];
  for (const rawGroup of asArray(field(raw, 'groups'))) {
    const group = parseGroup(rawGroup);
    if (group !== undefined) {
      groups.push(group);
    }
  }
  return {
    path,
    index,
    expectedOutcome: asString(field(raw, 'expectedOutcome')),
    outcome: asString(field(raw, 'outcome')),
    status: asString(field(raw, 'status')) ?? 'OK',
    matchesExpectation: asBoolean(field(raw, 'matchesExpectation')) ?? true,
    score: asNumber(field(raw, 'score')) ?? 0,
    maxScore: asNumber(field(raw, 'maxScore')) ?? 0,
    maxTime: asNumber(field(raw, 'maxTime')),
    maxMemory: asNumber(field(raw, 'maxMemory')),
    failedGroups: asArray(field(raw, 'failedGroups'))
      .map((name) => asString(name))
      .filter((name): name is string => name !== undefined),
    pooledMatchesExpectation: asBoolean(field(raw, 'pooledMatchesExpectation')),
    expectedScore: parseScoreRange(field(raw, 'expectedScore')),
    runUnderDoubleTl: asBoolean(field(raw, 'runUnderDoubleTl')) ?? false,
    doubleTlVerdicts: parseOutcomes(field(raw, 'doubleTlVerdicts')),
    groups,
  };
}

/**
 * Parse a report, or return `undefined` when there is nothing usable.
 *
 * A version this extension does not know is ignored rather than read
 * optimistically: rendering a run without aggregates is recoverable, rendering
 * the wrong verdict is not. The same goes for a missing or half-written file,
 * which is simply what a run in flight looks like.
 */
export function parseReport(raw: Wire): RunReport | undefined {
  const version = asNumber(field(raw, 'version'));
  if (version !== SUPPORTED_VERSION) {
    return undefined;
  }
  const solutions: SolutionReport[] = [];
  for (const rawSolution of asArray(field(raw, 'solutions'))) {
    const solution = parseSolution(rawSolution);
    if (solution !== undefined) {
      solutions.push(solution);
    }
  }
  return { solutions };
}
