/**
 * Measurements against the limits they ran under -- the spellings, decided once.
 *
 * Every number here is rbx's: the limits a solution ran under are stamped on the
 * skeleton (`SolutionSkeleton.limits`), the limit a testcase was killed at on its
 * `.eval`, and the share of a limit that counts as tight on the report. What is
 * decided here is only how a measurement and its limit are written side by side.
 *
 * Pure, like viewModel.ts, so `node --test` can hold it to account.
 */
import type { Hue } from './hue';
// Types only: this module reaches the webview bundle through viewModel.ts,
// and model.ts imports `path`, which a browser bundle has no way to resolve.
import type { Evaluation, LanguageLimits, Limits } from './model';
import type { SolutionReport } from './report';
import { formatMemory, formatTime } from './summary';

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
 * Whether a measurement sits at or past rbx's tight-margin line, but inside the
 * limit. Inside, because past it the verdict chip is already saying so; and no
 * line at all without the published ratio -- see `RunReport.tightTimeMarginRatio`.
 */
function tight(value: number, limit: number, ratio: number | undefined): boolean {
  return ratio !== undefined && limit > 0 && value >= limit * ratio && value < limit;
}

/** `0.93×TL`: two places, which is the resolution `rbx time` tunes at. */
function share(value: number, limit: number, unit: string): string {
  return `${(value / limit).toFixed(2)}×${unit}`;
}

/**
 * One testcase's time, against the limit it ran under.
 *
 * `412 / 1000 ms`, or rbx's own `>2000 ms` for a TLE that ran into the expanded
 * limit (`get_capped_evals_formatted_time`): that run was killed, and its raw
 * time is only when. The cap prefers the testcase's own recorded limits, which
 * is the order rbx reads them in.
 */
export function testcaseTime(
  evaluation: Evaluation | undefined,
  limits: TimeLimits | undefined,
  ratio: number | undefined,
): Measured | undefined {
  const seconds = evaluation?.time;
  if (seconds === undefined) {
    return undefined;
  }
  const value = ms(seconds);
  const killedAt = expandedTimeLimit(evaluation?.limits) ?? limits?.expanded;
  const slow = isSlow(evaluation?.outcome);
  const ile = evaluation?.outcome === 'idleness-limit-exceeded';
  if (killedAt !== undefined && ((slow && value >= killedAt) || ile)) {
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
    text: `${value} / ${limits.time} ms`,
    hue: tight(value, limits.time, ratio) ? 'yellow' : 'dim',
    title: `${value} ms of a ${limits.time} ms time limit (${share(value, limits.time, 'TL')})`,
  };
}

/**
 * A group's or a solution's max time, as a share of the limit: `0.93×TL`.
 *
 * A share and not a pair, because every row under one solution has the same
 * denominator and the header already names it; the share is what is left to
 * compare from row to row. A slow aggregate that reached the expanded limit
 * reads `>2.00×TL` for the reason a testcase reads `>2000 ms`.
 */
export function aggregateTime(
  maxTime: number | undefined,
  outcome: string | undefined,
  limits: TimeLimits | undefined,
  ratio: number | undefined,
): Measured | undefined {
  if (maxTime === undefined) {
    return undefined;
  }
  if (limits === undefined || limits.time <= 0) {
    return { text: formatTime(maxTime) ?? '', hue: 'dim' };
  }
  const value = ms(maxTime);
  const killedAt = limits.expanded;
  if (killedAt !== undefined && isSlow(outcome) && value >= killedAt) {
    return {
      text: `>${share(killedAt, limits.time, 'TL')}`,
      hue: 'dim',
      title: `Killed at ${killedAt} ms, against a ${limits.time} ms time limit`,
    };
  }
  return {
    text: share(value, limits.time, 'TL'),
    hue: tight(value, limits.time, ratio) ? 'yellow' : 'dim',
    title: `Max time ${value} ms of a ${limits.time} ms time limit`,
  };
}

/**
 * A memory measurement, hued against the memory limit.
 *
 * The text stays the measurement alone -- memory is the first span a narrow row
 * drops, and a pair would only get it dropped sooner -- and the limit goes in
 * the hover. Drawn tight at the same share as time: the one threshold rbx
 * publishes, rather than a second one invented here.
 */
export function memoryAgainstLimit(
  bytes: number | undefined,
  limitMiB: number | undefined,
  ratio: number | undefined,
): Measured | undefined {
  const text = formatMemory(bytes);
  if (bytes === undefined || text === undefined) {
    return undefined;
  }
  if (limitMiB === undefined) {
    return { text, hue: 'dim' };
  }
  const limit = limitMiB * 1024 * 1024;
  return {
    text,
    hue: tight(bytes, limit, ratio) ? 'yellow' : 'dim',
    title: `${text} of a ${formatMemory(limit)} memory limit (${share(bytes, limit, 'ML')})`,
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
