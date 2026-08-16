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
  runArtifactPath,
  skeletonPath,
  testArtifactPath,
} from './layout';
import {
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
  readonly interactionPath: string;
}

export interface GroupRun {
  readonly name: string;
  /** Points the group is worth, from the skeleton; 0 under binary scoring. */
  readonly score: number;
  readonly testcases: readonly TestcaseRun[];
}

export interface SolutionRun {
  readonly solution: SolutionEntry;
  readonly groups: readonly GroupRun[];
}

export interface RunReport {
  readonly skeleton: Skeleton;
  readonly solutions: readonly SolutionRun[];
}

async function readYamlFile(filePath: string): Promise<unknown> {
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
    interactionPath: runArtifactPath(pkg, solutionIndex, group, stem, Ext.Interaction),
  };
}

async function loadSolutionRun(
  pkg: PackageLayout,
  skeleton: Skeleton,
  solution: SolutionEntry,
): Promise<SolutionRun> {
  const scores = new Map(skeleton.groups.map((group) => [group.name, group.score ?? 0]));
  const groups = await Promise.all(
    orderedGroups(skeleton).map(async (name): Promise<GroupRun> => {
      const testcases = await Promise.all(
        entriesForGroup(skeleton, name).map((entry) =>
          loadTestcaseRun(pkg, solution.index, entry),
        ),
      );
      return { name, score: scores.get(name) ?? 0, testcases };
    }),
  );
  return { solution, groups };
}

/**
 * Loads and caches one package's run report.
 *
 * The cache is invalidated wholesale by `invalidate()` rather than per file:
 * a run is a few hundred small YAML files at most, and rereading them all is
 * cheaper than tracking which of them a filesystem event referred to.
 */
export class ArtifactStore {
  private cached?: Promise<RunReport | undefined>;

  constructor(private readonly pkg: PackageLayout) {}

  invalidate(): void {
    this.cached = undefined;
  }

  load(): Promise<RunReport | undefined> {
    if (this.cached === undefined) {
      this.cached = this.read();
    }
    return this.cached;
  }

  private async read(): Promise<RunReport | undefined> {
    const skeleton = parseSkeleton(await readYamlFile(skeletonPath(this.pkg)));
    if (skeleton === undefined) {
      return undefined;
    }
    const solutions = await Promise.all(
      skeleton.solutions.map((solution) => loadSolutionRun(this.pkg, skeleton, solution)),
    );
    return { skeleton, solutions };
  }
}
