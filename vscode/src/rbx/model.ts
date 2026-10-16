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

import { Wire, asArray, asBoolean, asNumber, asRecord, asString, field } from './wire';

/** rbx.box.generation_schema.GenerationTestcaseEntry, as embedded in the skeleton. */
export interface TestcaseEntry {
  readonly group: string;
  readonly index: number;
  readonly subgroup?: string;
  /** Absolute path recorded at generation time; may not exist on this host. */
  readonly inputPath?: string;
  readonly outputPath?: string;
  /** Provenance, shown on the testcase card -- see `viewModel.TestcaseCard`. */
  readonly generatorName?: string;
  readonly generatorArgs?: string;
  readonly copiedFrom?: string;
  /**
   * The generator script line this testcase was generated from.
   *
   * `GenerationInput.generator_script` is a `GeneratorScriptEntry`, which is a
   * real `path` and `line` rather than a name -- so unlike `generatorName`,
   * which names a generator declared in `problem.rbx.yml` and would have to be
   * resolved through the manifest, this one can be opened directly.
   */
  readonly generatorScript?: string;
  readonly generatorScriptLine?: number;
}

/**
 * rbx.grading.limits.Limits: what one solution, or one language, is judged under.
 *
 * Units as rbx keeps them, which are not the units of `Evaluation`: time in
 * milliseconds, memory in MiB (rbx multiplies by 1024 twice before comparing),
 * output in KiB. Converting is the view model's business, at the one place a
 * limit is set beside a measurement.
 */
export interface Limits {
  /**
   * The *enforced* time limit, ms. Absent when none is enforced -- a sanitized
   * run nulls it -- and the view then has nothing to measure a time against.
   */
  readonly time?: number;
  /** The declared time limit, ms, kept even when `time` is nulled. */
  readonly configuredTime?: number;
  /** MiB. */
  readonly memory?: number;
  /** KiB. */
  readonly output?: number;
  /**
   * Whether this run judges at double the time limit (`-v4`, the default).
   *
   * The verdict is still decided at 1x -- a run between 1x and 2x is a *soft*
   * TLE -- and only the process is allowed to run on to 2x. So `time` stays the
   * limit a measurement is read against, and this says how far past it a
   * measurement can go before the run is killed and the time stops meaning
   * anything.
   */
  readonly isDoubleTL: boolean;
  /** The limits profile these came from (`rbx time`); absent for the package's own. */
  readonly profile?: string;
}

/** One row of the skeleton's per-language limits table. */
export interface LanguageLimits {
  readonly language: string;
  readonly limits: Limits;
}

export function parseLimits(raw: Wire): Limits | undefined {
  if (asRecord(raw) === undefined) {
    return undefined;
  }
  return {
    time: asNumber(field(raw, 'time')),
    configuredTime: asNumber(field(raw, 'configuredTime')),
    memory: asNumber(field(raw, 'memory')),
    output: asNumber(field(raw, 'output')),
    isDoubleTL: asBoolean(field(raw, 'isDoubleTL')) ?? false,
    profile: asString(field(raw, 'profile')),
  };
}

export interface SolutionEntry {
  readonly path: string;
  /** Expected outcome declared in problem.rbx.yml, e.g. `ACCEPTED`. */
  readonly expectedOutcome?: string;
  /** Index into `Skeleton.solutions`; also the directory name under .rbx/runs. */
  readonly index: number;
  /**
   * The limits this solution is judged under, already resolved through its
   * language and any `--profile` by rbx (`SolutionSkeleton.limits`).
   *
   * Absent on a skeleton written by an rbx that predates the field. Resolving it
   * here instead would need rbx's language table, which is exactly the lookup
   * rbx stamps this field to spare its readers.
   */
  readonly limits?: Limits;
}

export interface GroupEntry {
  readonly name: string;
  readonly score?: number;
}

/** One warning the compiler emitted, as rbx parsed it. */
export interface CompilationWarning {
  /**
   * The file the compiler named, package-relative.
   *
   * Not assumed to be the solution's own path: rbx keeps any first-party file
   * that warned, and a diagnostic has to land on the file the compiler was
   * talking about rather than on the file that was being compiled.
   */
  readonly file: string;
  readonly line: number;
  readonly flag?: string;
  readonly msg: string;
}

/**
 * What the compile phase had to say about one solution.
 *
 * rbx.box.compilation_findings.SolutionCompilation. A `FAILED` record is the
 * *only* trace of a solution that did not compile: it is filtered out of
 * `solutions` and `compiled_solutions` before the skeleton is written, so
 * without this it would simply be missing from the view.
 */
export interface CompilationEntry {
  readonly path: string;
  /** The declaration, carried here because a failed solution has no SolutionEntry. */
  readonly expectedOutcome?: string;
  readonly status: 'WARNINGS' | 'FAILED';
  /** Relative to the runs dir, e.g. `compilation/0.log`. */
  readonly log: string;
  readonly warnings: readonly CompilationWarning[];
  /** A one-line cause, when there is one: `'g++' was not found`. */
  readonly reason?: string;
}

export interface Skeleton {
  readonly solutions: readonly SolutionEntry[];
  readonly entries: readonly TestcaseEntry[];
  readonly groups: readonly GroupEntry[];
  /**
   * Empty for a run whose solutions all compiled cleanly -- and for any run by
   * an rbx too old to write the field, which reads the same way on purpose.
   */
  readonly compilation: readonly CompilationEntry[];
  /**
   * Whether the run was sanitized (`rbx run -s`), which drops the problem's
   * time limit for the environment default. Every time in the view is then a
   * measurement against a limit the package never declared.
   */
  readonly sanitized: boolean;
  /**
   * Whether rbx narrowed the run to the ACCEPTED solutions on its own, which
   * it does for a sanitized run that named no solutions. The view then shows a
   * subset of the package's solutions with nothing saying why the rest are
   * missing.
   */
  readonly onlyAccepted: boolean;
  /**
   * Whether the run kept the interaction transcript (`rbx -cp`), or folded the
   * solution's stderr into one (`--merge-stderr`). Either one writes the `.pio`
   * the `io` channel shows; with neither, a missing transcript is expected and
   * the channel says how to get one.
   */
  readonly capturesInteraction?: boolean;
  /**
   * The per-language limits table `rbx run` prints before it starts, in the
   * order rbx keeps it. Empty on a skeleton too old to carry it.
   */
  readonly limits: readonly LanguageLimits[];
  /** `VerificationLevel`, as its number; absent on a skeleton too old to say. */
  readonly verification?: number;
  /**
   * How the run's testcases were validated, and which ones failed it.
   *
   * Absent on a skeleton too old to say, and on runs that do not say (`rbx
   * time`), which read like a run whose every testcase passed.
   */
  readonly validation?: RunValidation;
}

/** One (testcase, validator) rejection a run went ahead past. */
export interface InvalidTestcase {
  readonly group: string;
  readonly index: number;
  /** The validator that rejected it, package-relative. */
  readonly validator: string;
  readonly message?: string;
}

export interface RunValidation {
  /**
   * `warn`: the run went ahead past invalid testcases (`--on-invalid=warn`).
   * `fail`: it would have stopped at one, so none were. `off`: not validated.
   */
  readonly mode: 'fail' | 'warn' | 'off';
  readonly invalid: readonly InvalidTestcase[];
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
  /**
   * Whether this run tripped a sanitizer.
   *
   * Unlike `noTleOutcome`, this needs no answer from rbx to be worth showing:
   * it is a fact about this run alone rather than a verdict to be weighed
   * against an expectation, so the row can carry it directly. It is also the
   * only thing that says *which* stderr is worth opening.
   */
  readonly sanitizerWarnings?: boolean;
  /**
   * Whether an interactor judged this testcase, i.e. it is a communication
   * task. Read off `interactor_timing`, which rbx records for every run that
   * had an interactor -- so this decides which channels the card offers.
   */
  readonly communication?: boolean;
  /** Interactor CPU seconds, when measured. */
  readonly interactorTime?: number;
  /** Checker CPU seconds, when measured. */
  readonly checkerTime?: number;
  /** The solution's wall-clock seconds, beside the CPU `time` above. */
  readonly wallTime?: number;
  /**
   * The limits this testcase actually ran under (`log.metadata.limits`).
   *
   * What rbx's own `get_capped_evals_formatted_time` reads first when it caps a
   * TLE's time, so the cap a row draws is the one this run was killed at.
   */
  readonly limits?: Limits;
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

/**
 * One `GenerationTestcaseEntry`, wherever rbx embedded it.
 *
 * Exported because `build/testset.yml` dumps the very same entries verbatim
 * (design D2): the manifest keeps its extras in sibling keys precisely so this
 * parser is reused rather than written a second time and left to drift.
 */
export function parseTestcaseEntry(raw: Wire): TestcaseEntry | undefined {
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
    generatorScript: asString(field(raw, 'metadata', 'generator_script', 'path')),
    generatorScriptLine: asNumber(field(raw, 'metadata', 'generator_script', 'line')),
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
      limits: parseLimits(field(rawSolution, 'limits')),
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

  return {
    solutions,
    entries,
    groups,
    compilation: parseCompilation(root),
    // snake_case on the wire: `skeleton.yml` is a dump of the Pydantic model.
    sanitized: asBoolean(root.sanitized) ?? false,
    onlyAccepted: asBoolean(root.only_accepted) ?? false,
    capturesInteraction:
      (asBoolean(root.capture_pipes) ?? false) || (asBoolean(root.merge_stderr) ?? false),
    limits: parseLanguageLimits(root.limits),
    verification: asNumber(root.verification),
    validation: parseValidation(root.validation),
  };
}

function parseValidation(raw: Wire): RunValidation | undefined {
  const mode = asString(field(raw, 'mode'));
  if (mode !== 'fail' && mode !== 'warn' && mode !== 'off') {
    return undefined;
  }
  const invalid: InvalidTestcase[] = [];
  for (const rawInvalid of asArray(field(raw, 'invalid'))) {
    const group = asString(field(rawInvalid, 'group'));
    const index = asNumber(field(rawInvalid, 'index'));
    const validator = asString(field(rawInvalid, 'validator'));
    if (group === undefined || index === undefined || validator === undefined) {
      continue;
    }
    const message = asString(field(rawInvalid, 'message'));
    invalid.push({ group, index, validator, ...(message === undefined ? {} : { message }) });
  }
  return { mode, invalid };
}

function parseLanguageLimits(raw: Wire): LanguageLimits[] {
  const table = asRecord(raw);
  if (table === undefined) {
    return [];
  }
  const rows: LanguageLimits[] = [];
  for (const [language, rawLimits] of Object.entries(table)) {
    const limits = parseLimits(rawLimits);
    if (limits !== undefined) {
      rows.push({ language, limits });
    }
  }
  return rows;
}

function parseWarning(raw: Wire): CompilationWarning | undefined {
  const file = asString(field(raw, 'file'));
  const line = asNumber(field(raw, 'line'));
  const msg = asString(field(raw, 'msg'));
  if (file === undefined || line === undefined || msg === undefined) {
    return undefined;
  }
  return { file, line, flag: asString(field(raw, 'flag')), msg };
}

/**
 * The compilation records, dropping anything that does not carry the three
 * fields a row cannot be drawn without: who, how badly, and where the compiler
 * output went.
 */
function parseCompilation(root: Record<string, Wire>): CompilationEntry[] {
  const entries: CompilationEntry[] = [];
  for (const raw of asArray(root.compilation)) {
    const entryPath = asString(field(raw, 'path'));
    const status = asString(field(raw, 'status'));
    const log = asString(field(raw, 'log'));
    if (
      entryPath === undefined ||
      log === undefined ||
      (status !== 'WARNINGS' && status !== 'FAILED')
    ) {
      continue;
    }
    const warnings: CompilationWarning[] = [];
    for (const rawWarning of asArray(field(raw, 'warnings'))) {
      const warning = parseWarning(rawWarning);
      if (warning !== undefined) {
        warnings.push(warning);
      }
    }
    entries.push({
      path: entryPath,
      expectedOutcome: asString(field(raw, 'outcome')),
      status,
      log,
      warnings,
      reason: asString(field(raw, 'reason')),
    });
  }
  return entries;
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
    sanitizerWarnings: asBoolean(field(raw, 'result', 'sanitizer_warnings')),
    communication: asRecord(field(raw, 'result', 'interactor_timing')) !== undefined,
    interactorTime: asNumber(field(raw, 'result', 'interactor_timing', 'time')),
    checkerTime: asNumber(field(raw, 'result', 'checker_timing', 'time')),
    wallTime: asNumber(field(raw, 'log', 'wall_time')),
    limits: parseLimits(field(raw, 'log', 'metadata', 'limits')),
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
