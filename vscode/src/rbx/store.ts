/**
 * Reads a package's run artifacts off disk into the model the tree renders.
 *
 * Everything here is best-effort: a missing skeleton means "no run yet" (an
 * empty view, not an error), and a missing `.eval` means that testcase is still
 * pending -- which is exactly what an in-progress run looks like, and is why the
 * extension gets live progress without any streaming protocol.
 *
 * And incremental (#902): the watcher says *which* artifact moved, and the
 * store does the least that accounts for it -- one `.eval` landing re-reads
 * that one file and patches that one testcase, rather than re-reading the run.
 */
import * as fs from 'fs/promises';
import { parse as parseYaml } from 'yaml';

import { EvalKey, RefreshPlan, evalKeyId } from './artifactEvents';
import { ReadResult, ReadStats, YamlFileCache } from './fileReader';
import {
  Ext,
  PackageLayout,
  RunSource,
  compilationLogPath,
  manifestPath,
  reportPath,
  runArtifactPath,
  skeletonPath,
  solutionSourcePath,
  stressManifestPath,
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
import { GroupReport, RunEnd, RunReport, SolutionReport, parseReport } from './report';
import { StressManifest, parseStressManifest } from './stress';
import { Testset, parseTestset } from './testset';

/** One (solution, testcase) pair, with wherever its artifacts live. */
export interface TestcaseRun {
  readonly entry: TestcaseEntry;
  readonly stem: string;
  /** Absent while the run has not produced this evaluation yet. */
  readonly evaluation?: Evaluation;
  /**
   * Why the `.eval` could not be read, when it exists but the read failed.
   *
   * Kept apart from a missing evaluation on purpose: the two used to be one
   * `undefined`, so an `EMFILE` on a large run drew a testcase that *had* a
   * verdict as pending (#902).
   */
  readonly readError?: string;
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
  /** The transcript (`.pio`), written under `rbx -cp` or `--merge-stderr`. */
  readonly interactionPath: string;
  /** Whether this run was asked to write `interactionPath` at all. */
  readonly capturesInteraction: boolean;
  /** The interactor's stderr (`.int.err`) -- communication tasks only. */
  readonly interactorStderrPath: string;
  /** The interactor's run log (`.int.log`) -- communication tasks only. */
  readonly interactorLogPath: string;
  /** The checker's full stderr, kept under `--keep-checker-stderr`. */
  readonly checkerStderrPath: string;
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
  /**
   * How the run ended, once rbx has said so -- see `RunEnd`. Absent while it
   * is in flight, which is also what a run by an older rbx always looks like.
   */
  readonly ended?: RunEnd;
}

/** Reads one YAML artifact; the store's `YamlFileCache`, behind a seam. */
type Reader = (filePath: string) => Promise<ReadResult>;

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
  skeleton: Skeleton,
  solutionIndex: number,
  entry: TestcaseEntry,
  read: Reader,
  source: RunSource = 'run',
): Promise<TestcaseRun> {
  const stem = entryStem(entry);
  const group = entry.group;
  const artifact = (name: string, ext: Ext): string =>
    runArtifactPath(pkg, solutionIndex, group, name, ext, source);
  const evalPath = artifact(stem, Ext.Eval);
  const result = await read(evalPath);
  const evaluation = result.kind === 'ok' ? parseEvaluation(result.value) : undefined;

  return {
    entry,
    stem,
    evaluation,
    // Spread rather than set: almost every testcase has no read error, and an
    // explicit `readError: undefined` on each would make them unequal to the
    // same testcase written without it.
    ...(result.kind === 'error' ? { readError: result.message } : {}),
    inputPath: testArtifactPath(pkg, group, stem, Ext.Input, source),
    answerPath: testArtifactPath(pkg, group, stem, Ext.Output, source),
    outputPath: artifact(stem, Ext.Output),
    stderrPaths: [artifact(stem, Ext.Stderr), artifact(`${stem}.sol`, Ext.Stderr)],
    logPath: artifact(stem, Ext.Log),
    interactionPath: artifact(stem, Ext.Interaction),
    capturesInteraction: skeleton.capturesInteraction ?? false,
    interactorStderrPath: artifact(`${stem}.int`, Ext.Stderr),
    interactorLogPath: artifact(`${stem}.int`, Ext.Log),
    checkerStderrPath: artifact(`${stem}.checker`, Ext.Stderr),
  };
}

async function loadSolutionRun(
  pkg: PackageLayout,
  skeleton: Skeleton,
  solution: SolutionEntry,
  report: SolutionReport | undefined,
  read: Reader,
  source: RunSource = 'run',
): Promise<SolutionRun> {
  const groupReports = new Map(
    (report?.groups ?? []).map((group) => [group.name, group]),
  );
  const groups = await Promise.all(
    orderedGroups(skeleton).map(async (name): Promise<GroupRun> => {
      // Still one `Promise.all` over the whole group, but every read in it
      // queues on the cache's limiter, so at most a bounded number are open.
      const testcases = await Promise.all(
        entriesForGroup(skeleton, name).map((entry) =>
          loadTestcaseRun(pkg, skeleton, solution.index, entry, read, source),
        ),
      );
      return { name, testcases, report: groupReports.get(name) };
    }),
  );
  return { solution, groups, report };
}

/** What one store did on one load or patch, for the reload log line. */
export interface StoreTrace {
  readonly root: string;
  /** Why: `load`, `reload`, or what a patch re-read. */
  readonly reason: string;
  readonly stats: ReadStats;
  readonly ms: number;
}

export interface ArtifactStoreOptions {
  readonly files?: YamlFileCache;
  /** Called after every load and patch; the extension logs it. */
  readonly trace?: (trace: StoreTrace) => void;
}

function diffStats(after: ReadStats, before: ReadStats): ReadStats {
  return {
    reads: after.reads - before.reads,
    hits: after.hits - before.hits,
    missing: after.missing - before.missing,
    errors: after.errors - before.errors,
  };
}

function reportsByIndex(report: RunReport | undefined): Map<number, SolutionReport> {
  return new Map((report?.solutions ?? []).map((solution) => [solution.index, solution]));
}

/**
 * Loads and caches one package's run, testset and visualizer declarations.
 *
 * The three are cached apart and dropped apart (`apply`): a testset landing
 * says nothing about the run, and an `.eval` landing says nothing about the
 * testset. They used to be dropped together on every watcher tick.
 */
export class ArtifactStore {
  private cached?: Promise<PackageRun | undefined>;
  private cachedSkeleton?: Promise<Skeleton | undefined>;
  private cachedTestset?: Promise<Testset | undefined>;
  private cachedVisualizers?: Promise<VisualizerDeclarations | undefined>;
  private cachedStress?: Promise<StressManifest | undefined>;
  /** The last `rbx irun`, cached apart from the run: neither moves the other. */
  private cachedIrun?: Promise<PackageRun | undefined>;
  private readonly files: YamlFileCache;
  private readonly trace?: (trace: StoreTrace) => void;

  constructor(
    readonly pkg: PackageLayout,
    options: ArtifactStoreOptions = {},
  ) {
    this.files = options.files ?? new YamlFileCache();
    this.trace = options.trace;
  }

  /**
   * Drop everything; the next read of each starts from disk.
   *
   * Except the per-file cache, which is safe to keep: every entry in it is
   * checked against the file's `(mtime, size)` before it is reused. That is
   * what makes a rediscovery -- which invalidates every package -- cost a stat
   * per `.eval` rather than a read and a parse.
   */
  invalidate(): void {
    this.cached = undefined;
    this.cachedSkeleton = undefined;
    this.cachedTestset = undefined;
    this.cachedVisualizers = undefined;
    this.cachedStress = undefined;
    this.cachedIrun = undefined;
  }

  /**
   * Bring the cache in step with a batch of watcher events.
   *
   * A patch is chained onto the run already cached rather than replacing it,
   * so a caller asking mid-patch gets the patched run, and two patches in a
   * row apply in the order their events arrived. Nothing loaded yet means
   * nothing to patch: the next `load` reads the run as it is on disk.
   */
  apply(plan: RefreshPlan): void {
    if (plan.testset) {
      this.cachedTestset = undefined;
    }
    if (plan.manifest) {
      this.cachedVisualizers = undefined;
    }
    if (plan.stress) {
      this.cachedStress = undefined;
    }
    if (plan.irun) {
      this.cachedIrun = undefined;
    }
    if (plan.run === 'reload') {
      this.dropRun();
      return;
    }
    if (plan.run === 'keep' || this.cached === undefined) {
      return;
    }
    const previous = this.cached;
    this.cached = previous
      .catch(() => undefined)
      .then((run) => (run === undefined ? this.read('reload') : this.patch(run, plan)));
  }

  /**
   * The run on disk for `source`: the last `rbx run`, or the last `rbx irun`.
   *
   * The ad-hoc run is always read whole, never patched -- it is one testcase
   * per solution -- so its cache is a single promise dropped by any event
   * about it.
   */
  load(source: RunSource = 'run'): Promise<PackageRun | undefined> {
    if (source === 'irun') {
      if (this.cachedIrun === undefined) {
        this.cachedIrun = this.readIrun();
      }
      return this.cachedIrun;
    }
    if (this.cached === undefined) {
      this.cached = this.read('load');
    }
    return this.cached;
  }

  /**
   * The compile findings of the run on disk, reading no `.eval` to get them.
   *
   * The Problems panel covers every package in the workspace, and all it needs
   * is the skeleton. Going through `load` made it read every evaluation of
   * every package in a contest just to list a few warnings.
   */
  async findings(): Promise<readonly CompilationFinding[]> {
    const skeleton = await this.skeleton();
    return skeleton === undefined ? [] : this.findingsOf(skeleton);
  }

  /**
   * The testset the last `rbx build` published, or undefined if there is none.
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
   * Read from the manifest rather than from the build's testset manifest, so an
   * edit that adds a visualizer shows up without a rebuild; the manifest
   * watcher sends a `manifest` event for exactly that.
   */
  visualizers(): Promise<VisualizerDeclarations | undefined> {
    if (this.cachedVisualizers === undefined) {
      this.cachedVisualizers = readYamlFile(manifestPath(this.pkg)).then((raw) =>
        raw === undefined ? undefined : parseVisualizerDeclarations(raw),
      );
    }
    return this.cachedVisualizers;
  }

  /**
   * The latest stress session, or undefined if there is none readable.
   *
   * Cached apart from the run, like the testset: a stress test rewrites its
   * manifest whenever a finding lands, and none of that may cost the run view
   * a re-read. Only the manifest is read -- a finding's files are opened on
   * demand, from the paths layout.ts builds.
   */
  stress(): Promise<StressManifest | undefined> {
    if (this.cachedStress === undefined) {
      this.cachedStress = readYamlFile(stressManifestPath(this.pkg)).then(parseStressManifest);
    }
    return this.cachedStress;
  }

  private dropRun(): void {
    this.cached = undefined;
    this.cachedSkeleton = undefined;
    // A new run wiped `runs/`, so nothing cached for the old one can be reused,
    // and keeping it would only hold the memory.
    this.files.clear();
  }

  private skeleton(): Promise<Skeleton | undefined> {
    if (this.cachedSkeleton === undefined) {
      this.cachedSkeleton = readYamlFile(skeletonPath(this.pkg)).then(parseSkeleton);
    }
    return this.cachedSkeleton;
  }

  private findingsOf(skeleton: Skeleton, source: RunSource = 'run'): CompilationFinding[] {
    return skeleton.compilation.map(
      (entry): CompilationFinding => ({
        entry,
        logPath: compilationLogPath(this.pkg, entry.log, source),
        sourcePath: solutionSourcePath(this.pkg, entry.path),
      }),
    );
  }

  private async readReport(source: RunSource = 'run'): Promise<RunReport | undefined> {
    // Not through the file cache: it is one file, rewritten whole, and the
    // event that brought us here is the news that it changed.
    return parseReport(await readYamlFile(reportPath(this.pkg, source)));
  }

  private traced<T>(reason: string, work: () => Promise<T>): Promise<T> {
    const before = { ...this.files.stats };
    const started = Date.now();
    return work().then((result) => {
      this.trace?.({
        root: this.pkg.root,
        reason,
        stats: diffStats(this.files.stats, before),
        ms: Date.now() - started,
      });
      return result;
    });
  }

  private read(reason: string): Promise<PackageRun | undefined> {
    return this.traced(reason, async () => {
      // A fresh read of the skeleton too: whatever brought us here may be the
      // news that it changed.
      this.cachedSkeleton = undefined;
      const skeleton = await this.skeleton();
      if (skeleton === undefined) {
        return undefined;
      }
      // The report is matched to solutions by index, not by position: mid-run
      // it holds only the solutions that have finished, in the order they did.
      const report = await this.readReport();
      const reports = reportsByIndex(report);
      const read: Reader = (filePath) => this.files.read(filePath);
      const solutions = await Promise.all(
        skeleton.solutions.map((solution) =>
          loadSolutionRun(this.pkg, skeleton, solution, reports.get(solution.index), read),
        ),
      );
      return this.assemble(skeleton, solutions, report?.ended);
    });
  }

  /**
   * The last `rbx irun`, read whole.
   *
   * Every `.eval` is forgotten before it is read: `irun` replaces `.irun` as a
   * directory on every invocation, and the same path can come back with a
   * different verdict and, at the file system's mtime grain, the same stat.
   */
  private readIrun(): Promise<PackageRun | undefined> {
    return this.traced('ad-hoc run', async () => {
      const skeleton = parseSkeleton(await readYamlFile(skeletonPath(this.pkg, 'irun')));
      if (skeleton === undefined) {
        return undefined;
      }
      const report = await this.readReport('irun');
      const reports = reportsByIndex(report);
      const read: Reader = (filePath) => {
        this.files.forget(filePath);
        return this.files.read(filePath);
      };
      const solutions = await Promise.all(
        skeleton.solutions.map((solution) =>
          loadSolutionRun(this.pkg, skeleton, solution, reports.get(solution.index), read, 'irun'),
        ),
      );
      return this.assemble(skeleton, solutions, report?.ended, 'irun');
    });
  }

  private assemble(
    skeleton: Skeleton,
    solutions: readonly SolutionRun[],
    ended: RunEnd | undefined,
    source: RunSource = 'run',
  ): PackageRun {
    const findings = this.findingsOf(skeleton, source);
    return ended === undefined
      ? { skeleton, solutions, findings }
      : { skeleton, solutions, findings, ended };
  }

  /**
   * The run with `plan`'s report and evaluations re-read, and nothing else.
   *
   * Structurally shared: a solution, group or testcase no event named is the
   * very object it was before, so a patch costs the files it names and the
   * spine above them -- not the run.
   */
  private patch(run: PackageRun, plan: RefreshPlan): Promise<PackageRun> {
    const what = [
      plan.report ? 'report' : undefined,
      plan.evals.length > 0 ? `${plan.evals.length} evaluation(s)` : undefined,
    ].filter((part) => part !== undefined);
    return this.traced(what.join(' + '), async () => {
      const report = plan.report ? await this.readReport() : undefined;
      const reports = plan.report ? reportsByIndex(report) : undefined;
      const fresh = await this.readEvaluations(run, plan.evals);

      const solutions = run.solutions.map((solution): SolutionRun => {
        const index = solution.solution.index;
        const solutionReport = reports === undefined ? solution.report : reports.get(index);
        const touched = fresh.get(index);
        if (touched === undefined && solutionReport === solution.report) {
          return solution;
        }
        const groupReports = new Map(
          (solutionReport?.groups ?? []).map((group) => [group.name, group]),
        );
        const groups = solution.groups.map((group): GroupRun => {
          const groupReport =
            reports === undefined ? group.report : groupReports.get(group.name);
          const testcases = touched?.get(group.name);
          if (testcases === undefined && groupReport === group.report) {
            return group;
          }
          return {
            name: group.name,
            testcases:
              testcases === undefined
                ? group.testcases
                : group.testcases.map((testcase) => testcases.get(testcase.stem) ?? testcase),
            report: groupReport,
          };
        });
        return { solution: solution.solution, groups, report: solutionReport };
      });
      return this.assemble(run.skeleton, solutions, plan.report ? report?.ended : run.ended);
    });
  }

  /** The named evaluations, re-read, as solution -> group -> stem -> testcase. */
  private async readEvaluations(
    run: PackageRun,
    keys: readonly EvalKey[],
  ): Promise<Map<number, Map<string, Map<string, TestcaseRun>>>> {
    const byId = new Map<string, TestcaseEntry>();
    for (const key of keys) {
      const entry = run.solutions
        .find((solution) => solution.solution.index === key.solution)
        ?.groups.find((group) => group.name === key.group)
        ?.testcases.find((testcase) => testcase.stem === key.stem)?.entry;
      // An event for a testcase this run does not have is one from the run
      // before it, caught on its way out; the skeleton event that follows it
      // reloads the run anyway.
      if (entry !== undefined) {
        byId.set(evalKeyId(key), entry);
      }
    }
    const read: Reader = (filePath) => {
      // The event is the news that this file changed, so a cached parse of it
      // is stale by definition -- even one whose stat happens to match.
      this.files.forget(filePath);
      return this.files.read(filePath);
    };
    const loaded = await Promise.all(
      keys
        .filter((key) => byId.has(evalKeyId(key)))
        .map(async (key) => ({
          key,
          testcase: await loadTestcaseRun(
            this.pkg,
            run.skeleton,
            key.solution,
            byId.get(evalKeyId(key)) as TestcaseEntry,
            read,
          ),
        })),
    );
    const out = new Map<number, Map<string, Map<string, TestcaseRun>>>();
    for (const { key, testcase } of loaded) {
      const groups = out.get(key.solution) ?? new Map<string, Map<string, TestcaseRun>>();
      out.set(key.solution, groups);
      const stems = groups.get(key.group) ?? new Map<string, TestcaseRun>();
      groups.set(key.group, stems);
      stems.set(key.stem, testcase);
    }
    return out;
  }
}

function sameLayout(a: PackageLayout, b: PackageLayout): boolean {
  return a.root === b.root && a.buildDir === b.buildDir;
}

/**
 * One `ArtifactStore` per package, kept only while its layout is current.
 *
 * Keyed by root for lookup, but a store is reused only when the *whole* layout
 * still matches. A store captures its layout when it is built, and every path
 * it reads hangs off it -- so when a preset renames the build directory, a
 * store found by root alone keeps reading `<root>/<old buildDir>/testset.yml`
 * and resolving testcase inputs under a directory that is no longer written
 * (#901). Comparing the layout makes the next caller holding the new one get a
 * fresh store instead.
 */
export class ArtifactStores {
  private readonly stores = new Map<string, ArtifactStore>();

  constructor(
    private readonly create: (pkg: PackageLayout) => ArtifactStore = (pkg) =>
      new ArtifactStore(pkg),
  ) {}

  /** Bring one package's store in step with a batch of events, if it has one. */
  apply(root: string, plan: RefreshPlan): void {
    this.stores.get(root)?.apply(plan);
  }

  /** The store for `pkg`, replacing one built for an older layout of it. */
  for(pkg: PackageLayout): ArtifactStore {
    const existing = this.stores.get(pkg.root);
    if (existing !== undefined && sameLayout(existing.pkg, pkg)) {
      return existing;
    }
    const store = this.create(pkg);
    this.stores.set(pkg.root, store);
    return store;
  }

  /** Drop one package's cached artifacts, if it has a store at all. */
  invalidate(root: string): void {
    this.stores.get(root)?.invalidate();
  }

  /**
   * After discovery: forget packages that are gone or whose layout moved, and
   * drop every cached artifact of the rest.
   */
  retain(packages: readonly PackageLayout[]): void {
    const current = new Map(packages.map((pkg) => [pkg.root, pkg]));
    for (const [root, store] of this.stores) {
      const pkg = current.get(root);
      if (pkg === undefined || !sameLayout(store.pkg, pkg)) {
        this.stores.delete(root);
      } else {
        store.invalidate();
      }
    }
  }
}
