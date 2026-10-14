/**
 * Measurements against the limits they ran under -- the spellings, decided once.
 *
 * Every number here is rbx's: the limits a solution ran under are stamped on the
 * skeleton (`SolutionSkeleton.limits`), the limit a testcase was killed at on its
 * `.eval`. What is decided here is only how a measurement is written and which
 * limit its hover names.
 *
 * Pure, like viewModel.ts, so `node --test` can hold it to account.
 */
import type { Hue } from './hue';
// Types only: this module reaches the webview bundle through viewModel.ts,
// and model.ts imports `path`, which a browser bundle has no way to resolve.
import type { LanguageLimits, Limits } from './model';
import type { SolutionReport } from './report';
import { formatMemory } from './summary';

/** The two outcomes `Outcome.is_slow` names, as they are spelled on the wire. */
const SLOW = new Set(['time-limit-exceeded', 'idleness-limit-exceeded']);

/**
 * Mirrors `Limits.get_expanded_tl`: how long the process may run, ms.
 *
 * Both the solution's limits and a testcase's own (an `.eval`'s
 * `log.metadata.limits`) need it, and rbx caps a TLE's time at this figure
 * rather than at `time`.
 */
export function expandedTimeLimit(limits: Limits | undefined): number | undefined {
  if (limits?.time === undefined) {
    return undefined;
  }
  return limits.isDoubleTL ? limits.time * 2 : limits.time;
}

export function isSlow(outcome: string | undefined): boolean {
  return outcome !== undefined && SLOW.has(outcome);
}

/**
 * The time limits one solution was judged under, in ms.
 *
 * `time` is the limit a verdict is decided at and a measurement is read against;
 * `expanded` is how long the process was allowed to run (twice `time` under
 * `-v4`), past which a measured time is only the moment it was killed.
 */
export interface TimeLimits {
  readonly time: number;
  readonly expanded?: number;
}

/**
 * The time limits a solution ran under, or `undefined` when none was enforced.
 *
 * The skeleton's own record first: it is resolved through the solution's
 * language and profile, and is there from the moment the run starts. The
 * report's `timeLimit` stands in for a skeleton too old to carry it, and says
 * nothing about doubling -- so such a run caps nothing, which is the direction
 * that cannot hide a measurement. Never the package's own `timeLimit`.
 */
export function solutionTimeLimits(
  limits: Limits | undefined,
  report: SolutionReport | undefined,
): TimeLimits | undefined {
  if (limits?.time !== undefined) {
    return { time: limits.time, expanded: expandedTimeLimit(limits) };
  }
  if (report?.timeLimit !== undefined) {
    return { time: Math.round(report.timeLimit * 1000) };
  }
  return undefined;
}

/** A time span's text, hue and hover, before it becomes a `Span`. */
export interface Measured {
  readonly text: string;
  readonly hue: Hue;
  readonly title?: string;
}

/** `Math.trunc`, as `formatTime` does, so a row and the console agree to the ms. */
function ms(seconds: number): number {
  return Math.trunc(seconds * 1000);
}

/**
 * A time, as `rbx run` prints it: `194 ms`, or `>440 ms` for a TLE that ran into
 * the expanded limit (`get_capped_evals_formatted_time`) -- that run was killed,
 * and its raw time is only when. The same rule on every row, testcase or
 * aggregate, because the console applies it to both.
 *
 * The limit itself is left to the header and the hover: on every row it was
 * one more number to read past, and all the rows of a solution share it.
 *
 * `own` is the testcase's recorded limits (an `.eval`'s `log.metadata.limits`),
 * which win over the solution's, the order rbx reads them in. An aggregate has
 * none of its own.
 */
export function measuredTime(
  seconds: number | undefined,
  outcome: string | undefined,
  own: Limits | undefined,
  limits: TimeLimits | undefined,
): Measured | undefined {
  if (seconds === undefined) {
    return undefined;
  }
  const value = ms(seconds);
  const killedAt = expandedTimeLimit(own) ?? limits?.expanded;
  const ile = outcome === 'idleness-limit-exceeded';
  if (killedAt !== undefined && ((isSlow(outcome) && value >= killedAt) || ile)) {
    return {
      text: `>${killedAt} ms`,
      hue: 'dim',
      title: `Killed at ${killedAt} ms; the time it ran for is not a measurement.`,
    };
  }
  if (limits === undefined) {
    return { text: `${value} ms`, hue: 'dim' };
  }
  return {
    text: `${value} ms`,
    hue: 'dim',
    title: `${value} ms of a ${limits.time} ms time limit`,
  };
}

/**
 * A memory measurement, with its limit in the hover.
 *
 * Never hued, like a time: how close to its limit counts as too close is a
 * threshold rbx does not publish, and one invented here would be arbitrary.
 */
export function memoryAgainstLimit(
  bytes: number | undefined,
  limitMiB: number | undefined,
): Measured | undefined {
  const text = formatMemory(bytes);
  if (bytes === undefined || text === undefined) {
    return undefined;
  }
  if (limitMiB === undefined) {
    return { text, hue: 'dim' };
  }
  return {
    text,
    hue: 'dim',
    title: `${text} of a ${formatMemory(limitMiB * 1024 * 1024)} memory limit`,
  };
}

/**
 * One language's line of the header's limits block -- `_print_limits`'s
 * content, in a sidebar's spelling.
 */
export interface LimitLine {
  readonly language: string;
  /** `1000 ms`, or rbx's own `<No time limit>` wording. */
  readonly time: string;
  readonly memory: string;
  /** The limits profile these came from; absent for the package's own. */
  readonly profile?: string;
  readonly doubleTl: boolean;
}

export function limitLines(table: readonly LanguageLimits[]): LimitLine[] {
  return table.map(({ language, limits }) => ({
    language,
    time: limits.time === undefined ? 'no time limit' : `${limits.time} ms`,
    memory:
      limits.memory === undefined
        ? 'no memory limit'
        : (formatMemory(limits.memory * 1024 * 1024) ?? ''),
    profile: limits.profile,
    doubleTl: limits.isDoubleTL,
  }));
}
