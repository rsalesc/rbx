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
}

export interface SolutionReport {
  readonly path: string;
  readonly index: number;
  readonly expectedOutcome?: string;
  readonly outcome?: string;
  readonly status: string;
  readonly matchesExpectation: boolean;
  readonly score: number;
  readonly maxScore: number;
  readonly maxTime?: number;
  readonly maxMemory?: number;
  readonly failedGroups: readonly string[];
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
  };
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
