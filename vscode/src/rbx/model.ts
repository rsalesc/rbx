/**
 * TypeScript mirrors of the rbx models the extension reads, plus their parsers.
 *
 * Mirrored from:
 *   - rbx.box.solutions.SolutionReportSkeleton (+ SolutionSkeleton, GroupSkeleton)
 *   - rbx.box.generation_schema.GenerationTestcaseEntry
 *   - rbx.grading.steps.Evaluation (+ CheckerResult, TestcaseIO, TestcaseLog)
 *
 * Only the fields the UI actually uses are mirrored. Everything else is dropped
 * on purpose -- see wire.ts for why parsing is tolerant.
 */
import * as path from 'path';

import { Wire, asArray, asNumber, asRecord, asString, field } from './wire';

/** rbx.box.generation_schema.GenerationTestcaseEntry, as embedded in the skeleton. */
export interface TestcaseEntry {
  readonly group: string;
  readonly index: number;
  readonly subgroup?: string;
  /** Absolute path recorded at generation time; may not exist on this host. */
  readonly inputPath?: string;
  readonly outputPath?: string;
  /** Provenance, for the build tree (M2) and for tooltips today. */
  readonly generatorName?: string;
  readonly generatorArgs?: string;
  readonly copiedFrom?: string;
}

export interface SolutionEntry {
  readonly path: string;
  /** Expected outcome declared in problem.rbx.yml, e.g. `ACCEPTED`. */
  readonly expectedOutcome?: string;
  /** Index into `Skeleton.solutions`; also the directory name under .rbx/runs. */
  readonly index: number;
}

export interface GroupEntry {
  readonly name: string;
  readonly score?: number;
}

export interface Skeleton {
  readonly solutions: readonly SolutionEntry[];
  readonly entries: readonly TestcaseEntry[];
  readonly groups: readonly GroupEntry[];
}

export interface Evaluation {
  readonly outcome?: string;
  /** Checker message; absent for verdicts the checker never saw, e.g. TLE. */
  readonly message?: string;
  /** Seconds, as rbx records them. */
  readonly time?: number;
  /** Bytes. */
  readonly memory?: number;
  /**
   * The verdict this testcase would have got without the time limit.
   *
   * Set only on a *soft* TLE: under `-v4` rbx judges at 2x the limit, so a run
   * that crosses 1x is reported TLE while the checker still gets to see the
   * output. A hard TLE -- one that never finished -- leaves this absent, and
   * that difference is the whole meaning of the field.
   *
   * Reading it is safe; deciding whether it is worth *showing* is not. See
   * `GroupReport.unexpectedNoTleVerdicts`.
   */
  readonly noTleOutcome?: string;
}

/**
 * Resolve the on-disk stem of a testcase's artifacts.
 *
 * Mirrors `SolutionReportSkeleton.get_entry_stem()`: the stem comes from the
 * basename of the generated input path, *not* from the testcase index. A
 * subgroup-generated test is `1-gen-000`, not `000`.
 *
 * Getting this wrong silently shows another testcase's output -- it was a real
 * rbx bug once (#418 / #429) -- so the zero-padded index is only ever used as a
 * fallback for old packages that predate the named stems.
 */
export function entryStem(entry: TestcaseEntry): string {
  if (entry.inputPath !== undefined) {
    const base = path.basename(entry.inputPath);
    const dot = base.lastIndexOf('.');
    return dot > 0 ? base.slice(0, dot) : base;
  }
  return String(entry.index).padStart(3, '0');
}

function parseTestcaseEntry(raw: Wire): TestcaseEntry | undefined {
  const group = asString(field(raw, 'group_entry', 'group'));
  const index = asNumber(field(raw, 'group_entry', 'index'));
  if (group === undefined || index === undefined) {
    return undefined;
  }
  return {
    group,
    index,
    subgroup: asString(field(raw, 'subgroup_entry', 'group')),
    inputPath: asString(field(raw, 'metadata', 'copied_to', 'inputPath')),
    outputPath: asString(field(raw, 'metadata', 'copied_to', 'outputPath')),
    generatorName: asString(field(raw, 'metadata', 'generator_call', 'name')),
    generatorArgs: asString(field(raw, 'metadata', 'generator_call', 'args')),
    copiedFrom: asString(field(raw, 'metadata', 'copied_from', 'inputPath')),
  };
}

export function parseSkeleton(raw: Wire): Skeleton | undefined {
  const root = asRecord(raw);
  if (root === undefined) {
    return undefined;
  }

  const solutions: SolutionEntry[] = [];
  asArray(root.solutions).forEach((rawSolution, index) => {
    const solutionPath = asString(field(rawSolution, 'path'));
    if (solutionPath === undefined) {
      return;
    }
    solutions.push({
      path: solutionPath,
      expectedOutcome: asString(field(rawSolution, 'outcome')),
      index,
    });
  });

  const entries: TestcaseEntry[] = [];
  for (const rawEntry of asArray(root.entries)) {
    const entry = parseTestcaseEntry(rawEntry);
    if (entry !== undefined) {
      entries.push(entry);
    }
  }

  const groups: GroupEntry[] = [];
  for (const rawGroup of asArray(root.groups)) {
    const name = asString(field(rawGroup, 'name'));
    if (name !== undefined) {
      groups.push({ name, score: asNumber(field(rawGroup, 'score')) });
    }
  }

  return { solutions, entries, groups };
}

export function parseEvaluation(raw: Wire): Evaluation | undefined {
  if (asRecord(raw) === undefined) {
    return undefined;
  }
  return {
    outcome: asString(field(raw, 'result', 'outcome')),
    message: asString(field(raw, 'result', 'message')),
    time: asNumber(field(raw, 'log', 'time')),
    memory: asNumber(field(raw, 'log', 'memory')),
    noTleOutcome: asString(field(raw, 'result', 'no_tle_outcome')),
  };
}

/** Entries belonging to one group, in declaration order. */
export function entriesForGroup(skeleton: Skeleton, group: string): TestcaseEntry[] {
  return skeleton.entries.filter((entry) => entry.group === group);
}

/** Group names in the order the skeleton declares them, ignoring empty groups. */
export function orderedGroups(skeleton: Skeleton): string[] {
  const named = skeleton.groups.map((group) => group.name);
  const seen = new Set(named);
  for (const entry of skeleton.entries) {
    if (!seen.has(entry.group)) {
      seen.add(entry.group);
      named.push(entry.group);
    }
  }
  return named.filter((group) => entriesForGroup(skeleton, group).length > 0);
}
