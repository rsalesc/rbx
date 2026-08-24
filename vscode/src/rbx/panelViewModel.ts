/**
 * What the wide `rbx: Testset` panel *shows* -- decided once, here.
 *
 * The panel is the half of the testset surface that needs width (design D5): a
 * visualization gallery, a constraint-coverage matrix and a stats table. All
 * three are aggregations over `build/testset.yml`, and every one of them is a
 * judgement that can be wrong -- whether a `.dat` visualizer output can be
 * shown as an image, whether a variable was ever driven to its bound, what a
 * group's testcases add up to on disk. Those judgements live in this file so
 * that `node --test` can hold them to account; panelRender.ts downstream is
 * handed strings and hues and paints them.
 *
 * Pure, like viewModel.ts: no `vscode` import, no DOM, and deliberately no
 * knowledge of where the package lives. A gallery cell carries the
 * package-relative path the manifest recorded and an id, and it is the host's
 * job to turn those into a `webview.asWebviewUri` -- which is also what lets a
 * file the manifest names but that is no longer on disk arrive here as "no
 * asset for this id" and render as a placeholder rather than a broken image.
 *
 * Two semantics are load-bearing and are enforced by this module rather than
 * left to the renderer:
 *
 *   - `Testset.validation === undefined` means the build ran `-v0`, so the
 *     coverage data was never computed. That is *not* "validated and nothing
 *     was hit", and an empty matrix would state the second. `Coverage.reported`
 *     carries the distinction and the renderer says it in words.
 *   - `Visualizer.extension` is a free-form string. The manifest promises a
 *     path, never an image, so the extension -> kind mapping below is closed:
 *     anything unrecognized gets an "open in editor" affordance instead of an
 *     `<img>` that would silently draw nothing.
 */
import { Hue } from './hue';
import { formatMemory, formatScore } from './summary';
import {
  Testset,
  TestsetTestcase,
  orderedTestsetGroups,
  testsetGroup,
  testsetTestcases,
} from './testset';
import { Wire } from './wire';

/**
 * How a visualizer output can be shown, given nothing but its file name.
 *
 * `other` is not a failure mode -- a visualizer that emits a `.txt` trace or a
 * `.dot` graph is a perfectly good visualizer, and the panel offers to open it
 * in an editor. What is refused is *guessing*: an unknown extension dropped
 * into an `<img>` renders as a broken-image glyph with no explanation.
 */
export type VisualizationKind = 'image' | 'html' | 'other';

/** The extensions VS Code's webview renders inline without a plugin. */
const IMAGE_EXTENSIONS = new Set(['svg', 'png', 'jpg', 'jpeg', 'gif', 'webp']);
const HTML_EXTENSIONS = new Set(['html', 'htm']);

/**
 * The lowercased final extension of a path, without its dot.
 *
 * A leading-dot basename (`.gitignore`) has no extension rather than an
 * extension of `gitignore`, and a path with no dot at all reads the same way --
 * both end up `other`, which is the safe side of this decision.
 */
function extensionOf(filePath: string): string {
  const base = filePath.split(/[\\/]/).pop() ?? '';
  const dot = base.lastIndexOf('.');
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : '';
}

export function visualizationKind(filePath: string): VisualizationKind {
  const extension = extensionOf(filePath);
  if (IMAGE_EXTENSIONS.has(extension)) {
    return 'image';
  }
  return HTML_EXTENSIONS.has(extension) ? 'html' : 'other';
}

/**
 * Which artifact a visualizer was run over.
 *
 * The manifest carries both channels per testcase, and they are different
 * pictures of the same test -- the input's shape versus the expected answer's.
 * They get their own cells rather than one cell with a toggle, because a
 * gallery is scanned and a toggle is not.
 */
export type VisualizationChannel = 'input' | 'output';

export interface GalleryCell {
  /** Stable across rebuilds; the only thing the client ever sends back. */
  readonly id: string;
  readonly group: string;
  readonly stem: string;
  readonly channel: VisualizationChannel;
  /**
   * What the channel is *called* on screen: `input` or `answer`.
   *
   * Named here rather than in the renderer because it is a meaning decision,
   * and because `output` is the wrong word for a reader: the solution
   * visualizer draws the reference *answer*, which is what the testcase panes
   * already call it (`answer.out`). Two vocabularies for one file is how a
   * reader ends up believing there are two files.
   */
  readonly channelName: string;
  /** Package-relative, exactly as the manifest recorded it. */
  readonly path: string;
  readonly kind: VisualizationKind;
  /** What the cell is captioned with under the picture. */
  readonly label: string;
  /** The extension, shown on an `other` cell so the offer is not a mystery. */
  readonly extension: string;
}

export interface Gallery {
  readonly cells: readonly GalleryCell[];
  /** Testcases in the whole testset that produced no visualization at all. */
  readonly withoutVisualization: number;
}

/** One (variable, group) cell of the coverage matrix. */
export interface CoverageCell {
  readonly minHit: boolean;
  readonly maxHit: boolean;
  /**
   * Green when both bounds were reached, yellow for one, red for neither.
   *
   * The same vocabulary the run view spends on verdicts, for the same reason:
   * a setter scanning the matrix is looking for the cells that are not green.
   */
  readonly hue: Hue;
  /** The group's declared value for this variable, when it declares one. */
  readonly value?: string;
}

export interface CoverageRow {
  readonly variable: string;
  /** One entry per group in `Coverage.groups`; absent where nothing was reported. */
  readonly cells: readonly (CoverageCell | undefined)[];
}

export interface Coverage {
  /**
   * False when the build ran `-v0` and the data does not exist.
   *
   * Distinct from `rows.length === 0`, which is a validated testset that
   * declared no bounded variables. The renderer says the two differently.
   */
  readonly reported: boolean;
  /** Group names across the top, in manifest order. */
  readonly groups: readonly string[];
  /** The validator each column's group ran, when the report names one. */
  readonly validators: readonly (string | undefined)[];
  readonly rows: readonly CoverageRow[];
  /**
   * Variables that reached neither bound in any group -- the roll-up above the
   * table, and the finding a setter is actually looking for.
   */
  readonly neverHit: readonly string[];
}

export interface SubgroupStat {
  readonly name: string;
  readonly count: number;
}

export interface GroupStats {
  readonly group: string;
  readonly count: number;
  /** `[40/100]` -- the group's share of the testset's total score. */
  readonly score?: string;
  readonly deps: readonly string[];
  readonly subgroups: readonly SubgroupStat[];
  /** Already formatted; absent when no testcase in the group carries a size. */
  readonly maxInput?: string;
  readonly totalInput?: string;
  readonly maxOutput?: string;
}

export interface Stats {
  readonly groups: readonly GroupStats[];
  readonly count: number;
  readonly totalInput?: string;
  readonly maxInput?: string;
  readonly maxOutput?: string;
  /**
   * Testcases in groups rbx treats as samples.
   *
   * Counted by name rather than by a flag, because the manifest carries none:
   * `samples` is the group `rbx` generates and packages as the statement's
   * examples. A package that does not use that name reports zero, which is
   * honest -- the panel never claims a sample count it cannot source.
   */
  readonly samples: number;
}

export type PanelTab = 'gallery' | 'coverage' | 'stats';

export interface PanelViewModel {
  /** Absolute package root, for the panel title and for routing an open. */
  readonly root: string;
  readonly taskType?: string;
  /** Every group, for the group picker; `undefined` there means "all groups". */
  readonly groups: readonly string[];
  readonly gallery: Gallery;
  readonly coverage: Coverage;
  readonly stats: Stats;
  /** No manifest on disk, or one describing nothing. */
  readonly empty: boolean;
}

/** What the client holds and the host seeds: which tab, and which group. */
export interface PanelUiState {
  readonly tab: PanelTab;
  /** Undefined shows every group at once. */
  readonly group?: string;
  /**
   * Which visualization channel the gallery shows. Undefined shows both.
   *
   * A package declaring both an input and a solution visualizer produces two
   * cells per testcase, and interleaved they are hard to read as two series
   * however well each is labelled. The filter is what lets the gallery be
   * scanned as one series at a time.
   */
  readonly channel?: VisualizationChannel;
}

export const EMPTY_PANEL_MODEL: PanelViewModel = {
  root: '',
  groups: [],
  gallery: { cells: [], withoutVisualization: 0 },
  coverage: { reported: false, groups: [], validators: [], rows: [], neverHit: [] },
  stats: { groups: [], count: 0, samples: 0 },
  empty: true,
};

/** The group rbx generates from the statement's examples. */
const SAMPLES_GROUP = 'samples';

/**
 * The id a gallery cell -- and the sidebar's live-follow -- speaks in.
 *
 * `group::stem` rather than an index: indices renumber when a generator script
 * gains a line, whereas the stem is what the artifacts on disk are named, so a
 * selection survives a rebuild that only added tests.
 */
export function testcaseId(group: string, stem: string): string {
  return `${group}::${stem}`;
}

export function buildPanelViewModel(root: string, testset?: Testset): PanelViewModel {
  if (testset === undefined) {
    return { ...EMPTY_PANEL_MODEL, root };
  }
  const testcases = testsetTestcases(testset);
  const groups = orderedTestsetGroups(testset);
  return {
    root,
    taskType: testset.taskType,
    groups,
    gallery: buildGallery(testcases),
    coverage: buildCoverage(testset),
    stats: buildStats(testset, testcases, groups),
    empty: testcases.length === 0 && groups.length === 0,
  };
}

function buildGallery(testcases: readonly TestsetTestcase[]): Gallery {
  const cells: GalleryCell[] = [];
  let withoutVisualization = 0;
  for (const testcase of testcases) {
    const visualization = testcase.test?.visualization;
    if (visualization === undefined) {
      withoutVisualization += 1;
      continue;
    }
    const group = testcase.entry.group;
    for (const channel of ['input', 'output'] as const) {
      const filePath = visualization[channel];
      if (filePath === undefined) {
        continue;
      }
      cells.push({
        // The channel is part of the id: one testcase can contribute two cells
        // and the client addresses each of them separately.
        id: `${testcaseId(group, testcase.stem)}::${channel}`,
        group,
        stem: testcase.stem,
        channel,
        channelName: channel === 'input' ? 'input' : 'answer',
        path: filePath,
        kind: visualizationKind(filePath),
        label: testcase.stem,
        extension: extensionOf(filePath),
      });
    }
  }
  return { cells, withoutVisualization };
}

/**
 * The cell a `testId` from the sidebar names, tolerantly.
 *
 * Exact first, then the input channel of a testcase id, then any cell whose id
 * is a tail of the one asked for -- the sidebar composes its row ids from the
 * package root and this panel does not, and a live-follow that silently does
 * nothing is worse than one that lands on the right testcase's first picture.
 */
export function cellForTestId(
  gallery: Gallery,
  testId: string,
): GalleryCell | undefined {
  return (
    gallery.cells.find((cell) => cell.id === testId) ??
    gallery.cells.find((cell) => cell.id === `${testId}::input`) ??
    gallery.cells.find((cell) => testId.endsWith(cell.id)) ??
    gallery.cells.find((cell) => testId.endsWith(testcaseId(cell.group, cell.stem)))
  );
}

/**
 * A declared var, as one line of a table cell.
 *
 * Group vars are arbitrary YAML (see `TestsetGroup.vars`), so anything that is
 * not a scalar is shown as its JSON rather than as `[object Object]`. The panel
 * displays these; it never computes over them.
 */
function formatVar(value: Wire): string | undefined {
  if (value === undefined || value === null) {
    return undefined;
  }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    // Cyclic, which YAML anchors can produce. Nothing useful to show.
    return undefined;
  }
}

function hueOfBounds(minHit: boolean, maxHit: boolean): Hue {
  if (minHit && maxHit) {
    return 'green';
  }
  return minHit || maxHit ? 'yellow' : 'red';
}

function buildCoverage(testset: Testset): Coverage {
  const report = testset.validation;
  if (report === undefined) {
    return { reported: false, groups: [], validators: [], rows: [], neverHit: [] };
  }
  // Columns follow the report rather than the manifest's group list: a `-v0`
  // group in an otherwise validated build has no column to draw, and an empty
  // column reads exactly like a group that hit nothing.
  const columns = report.map((bounds) => bounds.group);
  // Variables in first-seen order across the report, so the rows of a matrix
  // and the order the validator declares its constraints stay in step.
  const variables: string[] = [];
  for (const bounds of report) {
    for (const variable of Object.keys(bounds.bounds)) {
      if (!variables.includes(variable)) {
        variables.push(variable);
      }
    }
  }
  const rows: CoverageRow[] = variables.map((variable) => ({
    variable,
    cells: report.map((bounds) => {
      const hit = bounds.bounds[variable];
      if (hit === undefined) {
        return undefined;
      }
      return {
        minHit: hit.minHit,
        maxHit: hit.maxHit,
        hue: hueOfBounds(hit.minHit, hit.maxHit),
        value: formatVar(testsetGroup(testset, bounds.group)?.vars[variable]),
      };
    }),
  }));
  const neverHit = rows
    .filter((row) =>
      row.cells.every((cell) => cell === undefined || (!cell.minHit && !cell.maxHit)),
    )
    .map((row) => row.variable);
  return {
    reported: true,
    groups: columns,
    validators: report.map((bounds) => bounds.validator),
    rows,
    neverHit,
  };
}

/** The largest of a list of sizes, or undefined when none was stamped. */
function maxSize(sizes: readonly number[]): number | undefined {
  return sizes.length === 0 ? undefined : Math.max(...sizes);
}

function sumSize(sizes: readonly number[]): number | undefined {
  return sizes.length === 0 ? undefined : sizes.reduce((total, size) => total + size, 0);
}

function buildStats(
  testset: Testset,
  testcases: readonly TestsetTestcase[],
  groups: readonly string[],
): Stats {
  // Scores are shown as a share of the testset's total, which is the number a
  // setter checks: 40 means nothing until you know whether the package adds up
  // to 100. A testset that scores nothing leaves the column empty rather than
  // printing `[0/0]` on every row.
  const totalScore = testset.groups.reduce((total, group) => total + (group.score ?? 0), 0);
  const perGroup: GroupStats[] = groups.map((name) => {
    const own = testcases.filter((testcase) => testcase.entry.group === name);
    const declared = testsetGroup(testset, name);
    const inputs = sizes(own, 'inputSize');
    const outputs = sizes(own, 'outputSize');
    return {
      group: name,
      count: own.length,
      score:
        declared?.score === undefined || totalScore === 0
          ? undefined
          : formatScore(declared.score, totalScore),
      deps: declared?.deps ?? [],
      subgroups: subgroupStats(own, declared?.subgroups ?? []),
      maxInput: formatMemory(maxSize(inputs)),
      totalInput: formatMemory(sumSize(inputs)),
      maxOutput: formatMemory(maxSize(outputs)),
    };
  });
  const allInputs = sizes(testcases, 'inputSize');
  const allOutputs = sizes(testcases, 'outputSize');
  return {
    groups: perGroup,
    count: testcases.length,
    totalInput: formatMemory(sumSize(allInputs)),
    maxInput: formatMemory(maxSize(allInputs)),
    maxOutput: formatMemory(maxSize(allOutputs)),
    samples: testcases.filter((testcase) => testcase.entry.group === SAMPLES_GROUP).length,
  };
}

function sizes(
  testcases: readonly TestsetTestcase[],
  channel: 'inputSize' | 'outputSize',
): number[] {
  const found: number[] = [];
  for (const testcase of testcases) {
    const size = testcase.test?.[channel];
    if (size !== undefined) {
      found.push(size);
    }
  }
  return found;
}

/**
 * The subgroup breakdown, declared subgroups first.
 *
 * Entries carry the subgroup they came from, and a manifest merged from a
 * subset build can hold a subgroup the group declaration no longer lists -- so
 * both sources contribute, and the declared order wins where they agree.
 */
function subgroupStats(
  testcases: readonly TestsetTestcase[],
  declared: readonly string[],
): SubgroupStat[] {
  const counts = new Map<string, number>();
  for (const name of declared) {
    counts.set(name, 0);
  }
  for (const testcase of testcases) {
    const name = testcase.entry.subgroup;
    if (name !== undefined && name !== '') {
      counts.set(name, (counts.get(name) ?? 0) + 1);
    }
  }
  return [...counts.entries()].map(([name, count]) => ({ name, count }));
}
