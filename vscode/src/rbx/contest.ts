/**
 * What a `contest.rbx.yml` says about the problems under it.
 *
 * Pure, like its neighbours: finding the file is the host's job, and this half
 * only turns parsed YAML into identities. Nothing here throws -- a malformed
 * contest file must cost the packages their letters, never the view.
 */
import * as path from 'path';

import { Wire, asArray, asRecord, asString } from './wire';

export const CONTEST_MANIFEST = 'contest.rbx.yml';
/** Sibling variant files: `contest.<id>.rbx.yml` (rbx's `VARIANT_GLOB`). */
const VARIANT_PREFIX = 'contest.';
const VARIANT_SUFFIX = '.rbx.yml';
/** rbx's `VARIANT_ID_PATTERN` (rbx/box/contest/contest_state.py:6). */
const VARIANT_ID = /^[A-Za-z][A-Za-z0-9_-]*$/;

/**
 * Whether `name` is a contest variant file rbx would actually load.
 *
 * The id between the fixed affixes is checked, not just the affixes: rbx skips
 * a non-matching sibling with a warning (contest_package.py:38-46), and reading
 * one here would be worse than merely redundant. Variants merge first-wins in
 * filename order, so a hand-made `contest.div1.bak.rbx.yml` sorts *before*
 * `contest.div1.rbx.yml` and its stale letters would win.
 */
export function isContestVariantFile(name: string): boolean {
  return (
    name.startsWith(VARIANT_PREFIX) &&
    name.endsWith(VARIANT_SUFFIX) &&
    // The affixes overlap on the canonical name itself, whose id is empty.
    name !== CONTEST_MANIFEST &&
    VARIANT_ID.test(name.slice(VARIANT_PREFIX.length, -VARIANT_SUFFIX.length))
  );
}

/** One problem as its contest declares it. */
export interface ContestProblem {
  readonly shortName: string;
  /**
   * Directory, relative to the contest root. Defaults to the short name.
   *
   * Passed through exactly as written -- resolving and normalizing it is the
   * host's job, so that `./A/`, `A` and `A//B` collapse onto one key there.
   */
  readonly path: string;
  readonly color?: string;
  /** Position among the problems that survived parsing. */
  readonly order: number;
}

export interface ParsedContest {
  /** A dispatcher sentinel: the real contests are sibling `contest.<id>.rbx.yml`. */
  readonly useVariants: boolean;
  readonly problems: readonly ContestProblem[];
}

// Both are handed out to every caller that hits their branch, so both are
// frozen: `readonly` is compile-time only, and one cast-and-push downstream
// would otherwise poison every later parse.
const NO_PROBLEMS: readonly ContestProblem[] = Object.freeze([]);
const EMPTY: ParsedContest = Object.freeze({ useVariants: false, problems: NO_PROBLEMS });
const DISPATCHER: ParsedContest = Object.freeze({ useVariants: true, problems: NO_PROBLEMS });

/** Reads a field as a string, treating the empty string as absent. */
function nonEmptyString(value: Wire): string | undefined {
  return asString(value) || undefined;
}

export function parseContest(raw: Wire): ParsedContest {
  const record = asRecord(raw);
  if (record === undefined) {
    return EMPTY;
  }
  if (record.use_variants === true) {
    // A dispatcher declares nothing else; rbx rejects any other field alongside
    // it (rbx/box/contest/schema.py:242), so anything listed here is ignored
    // rather than trusted.
    return DISPATCHER;
  }
  const problems: ContestProblem[] = [];
  for (const entry of asArray(record.problems)) {
    const fields = asRecord(entry);
    if (fields === undefined) {
      continue;
    }
    const shortName = nonEmptyString(fields.short_name);
    if (shortName === undefined) {
      continue;
    }
    problems.push({
      shortName,
      // rbx defaults an unset path to `./{short_name}/`.
      path: nonEmptyString(fields.path) ?? shortName,
      color: nonEmptyString(fields.color),
      // Counted off the survivors so a skipped entry leaves no hole.
      order: problems.length,
    });
  }
  return { useVariants: false, problems };
}

/** A problem's contest-given identity, keyed by absolute package root. */
export interface ProblemIdentity {
  readonly shortName: string;
  readonly color?: string;
  readonly order: number;
  /**
   * The contest root that named this problem, for grouping.
   *
   * Carried rather than re-derived from the package root: a contest is free to
   * nest its problems (`path: problems/beta`), so the root's parent directory
   * is not the contest, and two contests that both nest under `problems/`
   * would otherwise be indistinguishable in a heading.
   */
  readonly contestRoot: string;
}

/**
 * Resolve each declared problem to the absolute root it names.
 *
 * `path.resolve` normalizes the hand-written spellings a contest file carries
 * -- `./A/`, `A`, `problems/../A` all land on the same key -- so a match is a
 * plain map lookup downstream rather than a path comparison at every use.
 */
export function problemIdentities(
  contestRoot: string,
  contest: ParsedContest,
): Map<string, ProblemIdentity> {
  const identities = new Map<string, ProblemIdentity>();
  for (const problem of contest.problems) {
    const root = path.resolve(contestRoot, problem.path);
    // First declaration of a directory wins, the same rule `indexContests`
    // applies across files -- a half-typed duplicate block must not steal the
    // letter off the problem that is already there.
    if (!identities.has(root)) {
      identities.set(root, {
        shortName: problem.shortName,
        color: problem.color,
        order: problem.order,
        contestRoot,
      });
    }
  }
  return identities;
}
