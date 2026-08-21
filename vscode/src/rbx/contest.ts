/**
 * What a `contest.rbx.yml` says about the problems under it.
 *
 * Pure, like its neighbours: finding the file is the host's job, and this half
 * only turns parsed YAML into identities. Nothing here throws -- a malformed
 * contest file must cost the packages their letters, never the view.
 */
import { Wire, asArray, asRecord, asString } from './wire';

/** One problem as its contest declares it. */
export interface ContestProblem {
  readonly shortName: string;
  /** Directory, relative to the contest root. Defaults to the short name. */
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

const EMPTY: ParsedContest = { useVariants: false, problems: [] };

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
    // it (rbx/box/contest/schema.py:242).
    return { useVariants: true, problems: [] };
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
