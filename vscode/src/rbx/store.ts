/**
 * Reads a package's run artifacts off disk into the model the tree renders.
 *
 * Everything here is best-effort: a missing skeleton means "no run yet" (an
 * empty view, not an error), and a missing `.eval` means that testcase is still
 * pending -- which is exactly what an in-progress run looks like, and is why the
 * extension gets live progress without any streaming protocol.
 */
import * as fs from 'fs/promises';
import { parse as parseYaml } from 'yaml';

import {
  Ext,
  PackageLayout,
  compilationLogPath,
  manifestPath,
  reportPath,
  runArtifactPath,
  skeletonPath,
  solutionSourcePath,
  testArtifactPath,
  testsetPath,
} from './layout';
import {
  VisualizerDeclarations,
  parseVisualizerDeclarations,
} from './declaredVisualizers';
import {
  CompilationEntry,
  Evaluation,
  Skeleton,
  SolutionEntry,
  TestcaseEntry,
  entriesForGroup,
  entryStem,
  orderedGroups,
  parseEvaluation,
  parseSkeleton,
} from './model';
import { GroupReport, SolutionReport, parseReport } from './report';
import { Testset, parseTestset } from './testset';

/** One (solution, testcase) pair, with wherever its artifacts live. */
export interface TestcaseRun {
  readonly entry: TestcaseEntry;
  readonly stem: string;
  /** Absent while the run has not produced this evaluation yet. */
  readonly evaluation?: Evaluation;
  readonly inputPath: string;
  readonly answerPath: string;
  readonly outputPath: string;
  /**
   * Candidate stderr paths, most likely first. A batch run writes `<stem>.err`;
   * a communication task writes the solution's stderr to `<stem>.sol.err`
   * instead, and there is nothing in the evaluation that says which kind of task
   * produced it -- so both are offered and the opener takes whichever exists.
   */
  readonly stderrPaths: readonly string[];
  /**
   * The run log -- what rbx recorded about executing this testcase.
   *
   * The third channel of the testcase panes, alongside the output diff and
   * stderr, mirroring `rbx ui`'s `3`. A single path rather than candidates like
   * `stderrPaths`: the log is written by the grading step itself, so its name
   * does not depend on the task type.
   */
  readonly logPath: string;
  readonly interactionPath: string;
}

export interface GroupRun {
  readonly name: string;
  readonly testcases: readonly TestcaseRun[];
  /**
   * rbx's aggregates for this group. Absent until the solution finishes, since
   * that is when rbx publishes them -- so absence means "still running", and
   * the tree shows progress instead of a verdict.
   */
  readonly report?: GroupReport;
}

export interface SolutionRun {
  readonly solution: SolutionEntry;
  readonly groups: readonly GroupRun[];
  readonly report?: SolutionReport;
}

/**
 * One solution's compilation record, with its files resolved on this host.
 *
 * Kept apart from `SolutionRun` because the two do not line up: a solution that
 * failed to compile has a finding and no run at all, and a solution that merely
 * warned has both.
 */
export interface CompilationFinding {
  readonly entry: CompilationEntry;
  /** Absolute path to the stored compiler output. */
  readonly logPath: string;
  /** Absolute path to the solution's source. */
  readonly sourcePath: string;
}

export interface PackageRun {
  readonly skeleton: Skeleton;
  readonly solutions: readonly SolutionRun[];
  readonly findings: readonly CompilationFinding[];
}

/**
 * Parse a YAML file, or `undefined` for anything that is not readable YAML.
 *
 * Exported for the manifest reader, which needs the same tolerance for a
 * different reason: run artifacts are caught half-written by the watcher,
 * `problem.rbx.yml` is caught half-typed by the user.
 */
export async function readYamlFile(filePath: string): Promise<unknown> {
  let text: string;
  try {
    text = await fs.readFile(filePath, 'utf8');
  } catch {
    // Missing, unreadable, or a dangling symlink -- all mean "not there yet".
    return undefined;
  }
  try {
    return parseYaml(text);
  } catch {
    // A half-written file caught mid-run. The watcher will call us again.
    return undefined;
  }
}

async function loadTestcaseRun(
  pkg: PackageLayout,
  solutionIndex: number,
  entry: TestcaseEntry,
): Promise<TestcaseRun> {
  const stem = entryStem(entry);
  const group = entry.group;
  const evalPath = runArtifactPath(pkg, solutionIndex, group, stem, Ext.Eval);
  const evaluation = parseEvaluation(await readYamlFile(evalPath));

  return {
    entry,
    stem,
    evaluation,
    inputPath: testArtifactPath(pkg, group, stem, Ext.Input),
    answerPath: testArtifactPath(pkg, group, stem, Ext.Output),
    outputPath: runArtifactPath(pkg, solutionIndex, group, stem, Ext.Output),
    stderrPaths: [
      runArtifactPath(pkg, solutionIndex, group, stem, Ext.Stderr),
      runArtifactPath(pkg, solutionIndex, group, `${stem}.sol`, Ext.Stderr),
    ],
    logPath: runArtifactPath(pkg, solutionIndex, group, stem, Ext.Log),
    interactionPath: runArtifactPath(pkg, solutionIndex, group, stem, Ext.Interaction),
  };
}

async function loadSolutionRun(
  pkg: PackageLayout,
  skeleton: Skeleton,
  solution: SolutionEntry,
  report: SolutionReport | undefined,
): Promise<SolutionRun> {
  const groupReports = new Map(
    (report?.groups ?? []).map((group) => [group.name, group]),
  );
  const groups = await Promise.all(
    orderedGroups(skeleton).map(async (name): Promise<GroupRun> => {
      const testcases = await Promise.all(
        entriesForGroup(skeleton, name).map((entry) =>
          loadTestcaseRun(pkg, solution.index, entry),
        ),
      );
      return { name, testcases, report: groupReports.get(name) };
    }),
  );
  return { solution, groups, report };
}

/**
 * Loads and caches one package's run report.
 *
 * The cache is invalidated wholesale by `invalidate()` rather than per file:
 * a run is a few hundred small YAML files at most, and rereading them all is
 * cheaper than tracking which of them a filesystem event referred to.
 */
export class ArtifactStore {
  private cached?: Promise<PackageRun | undefined>;
  private cachedTestset?: Promise<Testset | undefined>;
  private cachedVisualizers?: Promise<VisualizerDeclarations | undefined>;

  constructor(private readonly pkg: PackageLayout) {}

  invalidate(): void {
    this.cached = undefined;
    this.cachedTestset = undefined;
    this.cachedVisualizers = undefined;
  }

  load(): Promise<PackageRun | undefined> {
    if (this.cached === undefined) {
      this.cached = this.read();
    }
    return this.cached;
  }

  /**
   * The testset the last `rbx build` published, or undefined if there is none.
   *
   * Cached beside the run rather than in a store of its own: the two describe
   * the same package and are invalidated by the same watcher tick, so keeping
   * them together is what stops the Run and Tests views ever disagreeing about
   * which package is being shown.
   *
   * A missing manifest is not an error -- it is what a package that has never
   * been built looks like, and the view renders it as empty.
   */
  testset(): Promise<Testset | undefined> {
    if (this.cachedTestset === undefined) {
      this.cachedTestset = readYamlFile(testsetPath(this.pkg)).then(parseTestset);
    }
    return this.cachedTestset;
  }

  /**
   * What `problem.rbx.yml` declares about visualizers.
   *
   * Cached beside the testset, and invalidated by the same watcher tick, for
   * the same reason: the Run and Tests views must never disagree about which
   * buttons a testcase gets. The manifest watcher already invalidates the
   * store, so an edit that adds a visualizer shows up without a rebuild --
   * which is the whole reason this is read from the manifest rather than from
   * the build's testset manifest.
   */
  visualizers(): Promise<VisualizerDeclarations | undefined> {
    if (this.cachedVisualizers === undefined) {
      this.cachedVisualizers = readYamlFile(manifestPath(this.pkg)).then((raw) =>
        raw === undefined ? undefined : parseVisualizerDeclarations(raw),
      );
    }
    return this.cachedVisualizers;
  }

  private async read(): Promise<PackageRun | undefined> {
    const skeleton = parseSkeleton(await readYamlFile(skeletonPath(this.pkg)));
    if (skeleton === undefined) {
      return undefined;
    }
    // The report is matched to solutions by index, not by position: mid-run it
    // holds only the solutions that have finished, in the order they finished.
    const report = parseReport(await readYamlFile(reportPath(this.pkg)));
    const reports = new Map(
      (report?.solutions ?? []).map((solution) => [solution.index, solution]),
    );
    const solutions = await Promise.all(
      skeleton.solutions.map((solution) =>
        loadSolutionRun(this.pkg, skeleton, solution, reports.get(solution.index)),
      ),
    );
    const findings = skeleton.compilation.map(
      (entry): CompilationFinding => ({
        entry,
        logPath: compilationLogPath(this.pkg, entry.log),
        sourcePath: solutionSourcePath(this.pkg, entry.path),
      }),
    );
    return { skeleton, solutions, findings };
  }
}
