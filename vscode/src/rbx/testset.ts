/**
 * The testset manifest `rbx build` writes at `build/testset.yml`.
 *
 * Mirrored from the writer described in docs/plans/2026-08-24-vscode-testset-view-design.md
 * (D2). It answers the question the run artifacts cannot: *what is in the
 * testset*, independently of any solution having been run over it -- the
 * generator provenance a build knows in-process, plus the validator verdicts
 * and constraint coverage that used to be computed and thrown away.
 *
 * Two shapes are deliberately not re-modelled here:
 *
 *   - `entries` is the same `GenerationTestcaseEntry` the skeleton embeds, so
 *     `model.parseTestcaseEntry` reads it unchanged. The manifest keeps its
 *     extras in the sibling `tests` list for exactly this reason: a second
 *     parser for the same bytes is a second thing to drift.
 *   - group `vars` are whatever the package declared, arbitrarily nested, and
 *     are carried as raw `Wire` rather than coerced. The view renders them; it
 *     does not compute over them.
 *
 * Tolerant like everything else the extension reads (see wire.ts): unknown keys
 * are ignored, a field of the wrong shape reads as absent, and nothing raises.
 */
import { TestcaseEntry, entryStem, parseTestcaseEntry } from './model';
import { Wire, asArray, asBoolean, asNumber, asRecord, asString, field } from './wire';

export interface TestsetGroup {
  readonly name: string;
  readonly score?: number;
  /** Group names this one depends on, as `TestcaseGroup.deps` declares them. */
  readonly deps: readonly string[];
  /** Subgroup names, in declaration order. */
  readonly subgroups: readonly string[];
  /**
   * The group's effective vars, already merged over the package's by rbx.
   *
   * Merged upstream on purpose: the precedence rules between package, group and
   * subgroup vars live in one place, and it is not this one.
   */
  readonly vars: Readonly<Record<string, Wire>>;
}

/** What the validator said about one testcase. */
export interface TestsetValidation {
  readonly ok: boolean;
  /** The validator that ran, package-relative; absent if the group had none. */
  readonly validator?: string;
  /**
   * The failure, when there is one.
   *
   * A validator that accepted leaves an empty string rather than nothing, and
   * that is normalized away here: a caller asking whether there is anything to
   * show should be able to test the field, not the field and its length.
   */
  readonly message?: string;
}

/**
 * Visualizer output for one testcase, package-relative.
 *
 * The extension does not promise these are images: `Visualizer.extension` is a
 * free string, so what a path can be *shown* as is the panel's problem, and
 * this only says where it landed.
 */
export interface TestsetVisualization {
  readonly input?: string;
  readonly output?: string;
}

/**
 * The per-testcase extras, keyed by (group, index) onto an entry.
 *
 * A parallel list rather than fields on `GenerationTestcaseEntry`, because
 * extending that model would change `skeleton.yml` too, for the benefit of one
 * consumer.
 */
export interface TestsetTest {
  readonly group: string;
  readonly index: number;
  readonly validation?: TestsetValidation;
  readonly visualization?: TestsetVisualization;
  /** Bytes, stamped at dump time so a list never stats thousands of files. */
  readonly inputSize?: number;
  readonly outputSize?: number;
}

/** Whether a variable's declared minimum and maximum were each reached. */
export interface VariableBounds {
  readonly minHit: boolean;
  readonly maxHit: boolean;
}

/** One group's constraint coverage, as the validator reported it. */
export interface GroupBounds {
  readonly group: string;
  readonly validator?: string;
  readonly bounds: Readonly<Record<string, VariableBounds>>;
}

export interface Testset {
  /**
   * The version the writer stamped, kept rather than checked.
   *
   * A newer manifest still parses -- every field is optional and unknown keys
   * are ignored -- so refusing one on the version alone would empty the view
   * for no gain. The opposite of `report.parseReport`, which rejects a version
   * it does not know, and for the opposite reason: a testset drawn without a
   * field rbx has since added is incomplete, while a verdict read out of a
   * shape that changed under us is wrong.
   */
  readonly version?: number;
  /** e.g. `BATCH`, `COMMUNICATION`. */
  readonly taskType?: string;
  readonly groups: readonly TestsetGroup[];
  readonly entries: readonly TestcaseEntry[];
  readonly tests: readonly TestsetTest[];
  /**
   * Constraint coverage per group, absent when the build ran `-v0`.
   *
   * Absent and empty mean different things here: absent is "the data was never
   * computed", which the panel says out loud, while an empty list would read as
   * "nothing is covered". Hence `undefined` rather than a defaulted `[]`.
   */
  readonly validation?: readonly GroupBounds[];
}

/** One testcase, with its build-time extras attached. */
export interface TestsetTestcase {
  readonly entry: TestcaseEntry;
  /** The on-disk basename of its artifacts -- see `model.entryStem`. */
  readonly stem: string;
  /** Absent for a manifest whose `tests` list does not cover this entry. */
  readonly test?: TestsetTest;
}

function parseGroup(raw: Wire): TestsetGroup | undefined {
  const name = asString(field(raw, 'name'));
  if (name === undefined) {
    return undefined;
  }
  const deps: string[] = [];
  for (const dep of asArray(field(raw, 'deps'))) {
    const value = asString(dep);
    if (value !== undefined) {
      deps.push(value);
    }
  }
  const subgroups: string[] = [];
  for (const subgroup of asArray(field(raw, 'subgroups'))) {
    const value = asString(subgroup);
    if (value !== undefined) {
      subgroups.push(value);
    }
  }
  return {
    name,
    score: asNumber(field(raw, 'score')),
    deps,
    subgroups,
    vars: asRecord(field(raw, 'vars')) ?? {},
  };
}

function parseValidation(raw: Wire): TestsetValidation | undefined {
  const ok = asBoolean(field(raw, 'ok'));
  if (ok === undefined) {
    return undefined;
  }
  const message = asString(field(raw, 'message'));
  return {
    ok,
    validator: asString(field(raw, 'validator')),
    message: message === '' ? undefined : message,
  };
}

/**
 * The visualizer paths, or nothing when neither channel produced one.
 *
 * A record with both channels absent is dropped rather than kept, so a consumer
 * can ask `visualization !== undefined` instead of testing two fields to find
 * out there is nothing to show.
 */
function parseVisualization(raw: Wire): TestsetVisualization | undefined {
  const input = asString(field(raw, 'input'));
  const output = asString(field(raw, 'output'));
  if (input === undefined && output === undefined) {
    return undefined;
  }
  return { input, output };
}

function parseTest(raw: Wire): TestsetTest | undefined {
  const group = asString(field(raw, 'group'));
  const index = asNumber(field(raw, 'index'));
  if (group === undefined || index === undefined) {
    // Without both there is no entry to attach this to, and the extras are only
    // ever read through that join.
    return undefined;
  }
  return {
    group,
    index,
    validation: parseValidation(field(raw, 'validation')),
    visualization: parseVisualization(field(raw, 'visualization')),
    inputSize: asNumber(field(raw, 'input_size')),
    outputSize: asNumber(field(raw, 'output_size')),
  };
}

/**
 * One variable's `[min_hit, max_hit]` pair.
 *
 * rbx dumps it as a two-element list, which is how `hit_bounds` is shaped in
 * Python. Anything else -- a scalar, a longer list, a list of strings -- is
 * dropped rather than half-read, since a coverage cell drawn from a guess is
 * worse than a missing one.
 */
function parseVariableBounds(raw: Wire): VariableBounds | undefined {
  const pair = asArray(raw);
  const minHit = asBoolean(pair[0]);
  const maxHit = asBoolean(pair[1]);
  if (minHit === undefined || maxHit === undefined) {
    return undefined;
  }
  return { minHit, maxHit };
}

function parseGroupBounds(raw: Wire): GroupBounds | undefined {
  const group = asString(field(raw, 'group'));
  if (group === undefined) {
    return undefined;
  }
  const bounds: Record<string, VariableBounds> = {};
  const rawBounds = asRecord(field(raw, 'bounds')) ?? {};
  for (const [variable, value] of Object.entries(rawBounds)) {
    const parsed = parseVariableBounds(value);
    if (parsed !== undefined) {
      bounds[variable] = parsed;
    }
  }
  return { group, validator: asString(field(raw, 'validator')), bounds };
}

export function parseTestset(raw: Wire): Testset | undefined {
  const root = asRecord(raw);
  if (root === undefined) {
    return undefined;
  }

  const groups: TestsetGroup[] = [];
  for (const rawGroup of asArray(root.groups)) {
    const group = parseGroup(rawGroup);
    if (group !== undefined) {
      groups.push(group);
    }
  }

  const entries: TestcaseEntry[] = [];
  for (const rawEntry of asArray(root.entries)) {
    const entry = parseTestcaseEntry(rawEntry);
    if (entry !== undefined) {
      entries.push(entry);
    }
  }

  const tests: TestsetTest[] = [];
  for (const rawTest of asArray(root.tests)) {
    const test = parseTest(rawTest);
    if (test !== undefined) {
      tests.push(test);
    }
  }

  return {
    version: asNumber(root.version),
    taskType: asString(root.task_type),
    groups,
    entries,
    tests,
    validation: parseValidationReport(root),
  };
}

/**
 * The coverage report, distinguishing "not computed" from "computed as empty".
 *
 * The key being absent is what `-v0` looks like, and it is the one case that
 * must not collapse into an empty list -- see `Testset.validation`.
 */
function parseValidationReport(root: Record<string, Wire>): GroupBounds[] | undefined {
  if (!Array.isArray(root.validation)) {
    return undefined;
  }
  const report: GroupBounds[] = [];
  for (const raw of root.validation) {
    const bounds = parseGroupBounds(raw);
    if (bounds !== undefined) {
      report.push(bounds);
    }
  }
  return report;
}

/**
 * Entries paired with their extras, in the order the manifest lists them.
 *
 * The join lives here and not in `parseTestset` because the two halves fail
 * independently: `entries` is a verbatim copy of a shape the extension has read
 * for a year, `tests` is new and written by a possibly older or newer rbx. A
 * parser that folded them together would have to invent a record for a `tests`
 * row naming an entry that is not there -- whereas leaving the manifest a
 * faithful mirror of the file lets every consumer say what it wants to do about
 * the mismatch, and lets the parser's tests be about the file alone.
 */
export function testsetTestcases(testset: Testset): TestsetTestcase[] {
  const byKey = new Map<string, TestsetTest>();
  for (const test of testset.tests) {
    byKey.set(testKey(test.group, test.index), test);
  }
  return testset.entries.map((entry) => ({
    entry,
    stem: entryStem(entry),
    test: byKey.get(testKey(entry.group, entry.index)),
  }));
}

function testKey(group: string, index: number): string {
  return `${group} ${index}`;
}

/** The joined testcases of one group, in declaration order. */
export function testcasesForGroup(testset: Testset, group: string): TestsetTestcase[] {
  return testsetTestcases(testset).filter((testcase) => testcase.entry.group === group);
}

/**
 * Group names in manifest order, followed by any group only the entries mention.
 *
 * A subset build (`rbx build --groups main`) merges into the manifest rather
 * than truncating it, so `groups` and `entries` can legitimately disagree about
 * which groups exist; neither is treated as authoritative over the other.
 */
export function orderedTestsetGroups(testset: Testset): string[] {
  const names = testset.groups.map((group) => group.name);
  const seen = new Set(names);
  for (const entry of testset.entries) {
    if (!seen.has(entry.group)) {
      seen.add(entry.group);
      names.push(entry.group);
    }
  }
  return names;
}

/** One group's declaration, when the manifest carries it. */
export function testsetGroup(testset: Testset, group: string): TestsetGroup | undefined {
  return testset.groups.find((candidate) => candidate.name === group);
}

/** One group's constraint coverage, or undefined if the build did not report it. */
export function boundsForGroup(
  testset: Testset,
  group: string,
): GroupBounds | undefined {
  return testset.validation?.find((bounds) => bounds.group === group);
}
