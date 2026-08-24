/**
 * What each row of the Tests view *shows* -- decided once, here.
 *
 * The Run view answers "what happened when this was run". This one answers the
 * question that comes before it: *what is even in the testset*. The facts are
 * different -- where a test came from, how big it is, whether the validator
 * accepted it, whether a visualizer drew it -- but the discipline is the one
 * viewModel.ts established, and it is the reason both files exist: a row's
 * meaning is decided in a module `node --test` can hold to account, and the
 * renderer downstream is handed strings, hues and booleans to paint.
 *
 * Two things live here that the Run view keeps in nodes.ts. The node types and
 * the walk that produces them are in this file rather than beside their run
 * counterparts because the id scheme is the same decision as the row: an id is
 * what a click, a selection and a context menu all travel as, and splitting the
 * two halves of that scheme across two modules is how they start to disagree.
 *
 * Pure by design: no `vscode` import and no DOM.
 */
import { Hue } from './hue';
import { PackageLayout } from './layout';
import { TestcaseEntry } from './model';
import { formatMemory, formatScore } from './summary';
import {
  Testset,
  TestsetTest,
  TestsetTestcase,
  orderedTestsetGroups,
  testcasesForGroup,
  testsetGroup,
} from './testset';

/**
 * What a meta span *is*, so the stylesheet can drop them in priority order.
 *
 * The same mechanism as the Run view's `SpanRole`, with this view's three
 * channels: how many tests a group holds, what it is worth, and how big one
 * test's input is. See the ladder at the foot of style.css for the order.
 */
export type TestsetSpanRole = 'count' | 'score' | 'size';

export interface TestsetSpan {
  readonly text: string;
  readonly hue?: Hue;
  readonly role?: TestsetSpanRole;
}

/**
 * A mark at the right-hand end of a row.
 *
 * Two of them, and they are not the same kind of fact: a visualization is
 * something the row *has*, a failed validation is something wrong with it. They
 * share a column because both are answered by glancing rather than by reading,
 * and neither has anything to say on most rows.
 */
export type TestsetFlagKind = 'visualization' | 'invalid';

export interface TestsetFlag {
  readonly kind: TestsetFlagKind;
  readonly hue: Hue;
  /** The hover, which is where a failed validator's own sentence goes. */
  readonly title: string;
}

/**
 * One line of provenance: where this testcase came from.
 *
 * Deliberately the same shape, the same three spellings and the same two
 * commands as the Run view's `CardOrigin`. `rbx.openGeneratorScript` and
 * `rbx.openCopiedFrom` already do exactly this job, and a testcase's origin is
 * the same fact whether it is reached through a run or through a build.
 */
export interface TestsetOrigin {
  readonly text: string;
  readonly open?: 'rbx.openGeneratorScript' | 'rbx.openCopiedFrom';
  readonly title: string;
}

/** A labelled figure on the card -- a size, and nothing that moves. */
export interface TestsetValue {
  readonly label: string;
  readonly text: string;
}

/**
 * What the validator said, in the one place there is room to say it.
 *
 * Absent when the group had no validator at all, which is different from having
 * passed one: the row's flag column stays empty in both cases, and the card is
 * where that difference is spelled out.
 */
export interface TestsetValidationCard {
  readonly ok: boolean;
  readonly hue: Hue;
  /** `Validated` / `Rejected by the validator`. */
  readonly text: string;
  readonly validator?: string;
  /** The validator's own sentence, only ever on a failure. */
  readonly message?: string;
}

/**
 * What the card under the tree says about the selected testcase.
 *
 * The row above it carries the stem, the size and the two flags, so the card
 * carries what a 22px row cannot: where the test came from, the validator's
 * own words, and the sizes of both artifacts.
 */
export interface TestsetCard {
  /** `main/1-gen-000`, so the card says which row it is describing. */
  readonly title: string;
  readonly origins: readonly TestsetOrigin[];
  readonly values: readonly TestsetValue[];
  readonly validation?: TestsetValidationCard;
  /**
   * The visualizer's output, package-relative, when the build produced one.
   *
   * A path and not a rendered image: this view is 300px wide and the panel is
   * where a picture is worth opening. The card offers the jump.
   */
  readonly visualization?: string;
  /**
   * The answer visualization, when a `solutionVisualizer` drew one.
   *
   * The card used to carry the input channel alone, on the grounds that
   * solution-output visualizers belong to the Run view. That conflated two
   * different files: the Run view's business is a *solution's* output, while
   * this one is the reference answer the build itself produced, sitting in the
   * same testset the card describes. Offering one and silently dropping the
   * other left the panel showing two pictures the card could only reach one of.
   */
  readonly answerVisualization?: string;
}

export interface TestsetRow {
  readonly id: string;
  readonly parentId?: string;
  readonly depth: number;
  readonly kind: 'group' | 'testcase';
  readonly label: string;
  /** The whole of what a shortened label stands for; absent when there is none. */
  readonly labelTitle?: string;
  readonly meta: readonly TestsetSpan[];
  readonly flags: readonly TestsetFlag[];
  readonly expandable: boolean;
  readonly defaultExpanded: boolean;
  /**
   * What the card under the tree shows while this row is selected.
   *
   * Only testcase rows carry one, and it rides on the row for the reason the
   * Run view's does: the card describes *the selection*, which is the client's
   * fact, so shipping it with the model lets the card be drawn the instant the
   * highlight moves.
   */
  readonly card?: TestsetCard;
  /** Lowercased haystack for the filter box. */
  readonly search: string;
  /** The `webviewSection` a context menu keys on. */
  readonly section: string;
  readonly primaryCommand?: string;
}

/**
 * The strip above the tree: how much there is, and when it was built.
 *
 * `built` is a cue and never a claim. The manifest is whatever the last build
 * wrote, and deciding whether it is *stale* would mean modelling which of the
 * package's inputs feed which group -- which is wrong in both directions (see
 * design D2). So the header states the time and says nothing about it.
 */
export interface TestsetHeader {
  /** `built 3m ago`, or absent when the host could not stat the manifest. */
  readonly built?: string;
  /** `40 tests · 3 groups`. */
  readonly summary: string;
}

export interface TestsetViewModel {
  readonly rows: readonly TestsetRow[];
  /** No manifest at all -- the package has never been built. */
  readonly empty: boolean;
  /** Absent exactly when `empty`: there is nothing to summarize. */
  readonly header?: TestsetHeader;
}

/**
 * The model of a view with no package behind it at all.
 *
 * Shared by the client's starting state and the host's answer for an empty
 * workspace, so the two cannot drift -- the same arrangement as `EMPTY_MODEL`.
 */
export const EMPTY_TESTSET_MODEL: TestsetViewModel = { rows: [], empty: true };

/** One group's row, and the thing a group-level command acts on. */
export interface TestsetGroupNode {
  readonly kind: 'testsetGroup';
  readonly pkg: PackageLayout;
  readonly group: string;
}

/** One built testcase: its entry, and whatever extras the manifest carried. */
export interface TestsetTestcaseNode {
  readonly kind: 'testsetTestcase';
  readonly pkg: PackageLayout;
  readonly group: string;
  readonly stem: string;
  readonly entry: TestcaseEntry;
  /**
   * Absent when the manifest's `tests` list does not cover this entry -- an
   * older rbx, or a subset build that merged an entry in without its extras.
   */
  readonly test?: TestsetTest;
}

export type TestsetNode = TestsetGroupNode | TestsetTestcaseNode;

/**
 * The stable row id, and the key for selection, expansion and every message.
 *
 * Not rooted at the package the way `nodeId` is. It does not need to be: the
 * host rebuilds its id map from the package it is posting, so an id kept across
 * a problem switch resolves against the new package or not at all -- and
 * `main` meaning *this* package's `main` is the only reading available.
 */
export function testsetNodeId(node: TestsetNode): string {
  return node.kind === 'testsetGroup' ? node.group : `${node.group}::${node.stem}`;
}

/**
 * The testset in display order: every group, with the tests under it.
 *
 * The one walk both the rows and the nodes are built from, so an id the client
 * can see always resolves to the node the row was built from. Groups come from
 * `orderedTestsetGroups`, which merges the two lists the manifest can disagree
 * on. A build writes them together and they should agree, but the manifest is
 * two independently-parsed halves (`groups` is new, `entries` is dumped
 * verbatim), so either can degrade without the other; neither is treated as
 * authoritative over the other.
 */
function testsetWalk(testset: Testset): { group: string; testcases: TestsetTestcase[] }[] {
  return orderedTestsetGroups(testset).map((group) => ({
    group,
    testcases: testcasesForGroup(testset, group),
  }));
}

/** Every row of one package's testset, in display order, parents before children. */
export function testsetNodes(
  pkg: PackageLayout,
  testset: Testset | undefined,
): TestsetNode[] {
  if (testset === undefined) {
    return [];
  }
  const nodes: TestsetNode[] = [];
  for (const { group, testcases } of testsetWalk(testset)) {
    nodes.push({ kind: 'testsetGroup', pkg, group });
    for (const testcase of testcases) {
      nodes.push({
        kind: 'testsetTestcase',
        pkg,
        group,
        stem: testcase.stem,
        entry: testcase.entry,
        test: testcase.test,
      });
    }
  }
  return nodes;
}

function span(
  text: string | undefined,
  hue: Hue,
  role: TestsetSpanRole,
): TestsetSpan | undefined {
  return text === undefined || text === '' ? undefined : { text, hue, role };
}

function spans(candidates: readonly (TestsetSpan | undefined)[]): TestsetSpan[] {
  return candidates.filter((candidate): candidate is TestsetSpan => candidate !== undefined);
}

/**
 * The mark a failed validation draws, wherever it is drawn.
 *
 * One helper for both levels so a group and the testcase inside it cannot end
 * up saying different things about the same failure.
 */
function invalidFlag(title: string): TestsetFlag {
  return { kind: 'invalid', hue: 'red', title };
}

/** `main` -> its share of the testset's points, or nothing to say. */
function scoreSpan(score: number | undefined, total: number): TestsetSpan | undefined {
  if (score === undefined || score === 0 || total === 0) {
    return undefined;
  }
  // `formatScore` and its brackets, against the testset's own total: a bare
  // `100` beside a count is two numbers with nothing to tell them apart, and
  // what a reader wants from a group's score is its *share*. Dim rather than
  // hued by `hueOfScore` -- that function ranks an achieved score against its
  // maximum, and nothing here has been achieved yet.
  return { text: formatScore(score, total), hue: 'dim', role: 'score' };
}

/**
 * The whole testset's declared points, as the denominator of every group's.
 *
 * Zero when no group declares a score, which is the common case on an ICPC-style
 * problem -- and is what drops the span from every row rather than drawing
 * `[0/0]` down the view.
 */
function totalScore(testset: Testset): number {
  return testset.groups.reduce((sum, group) => sum + (group.score ?? 0), 0);
}

/**
 * `search` for one row: what the user is likely to type at it.
 *
 * The field list is `TestExplorerScreen`'s -- see `_search_text` in
 * `rbx/box/ui/screens/test_list_search.py`: the test's name, its generator
 * call, its generator script and where it was copied from. Two surfaces onto
 * the same testset should not disagree about what typing `gen` finds.
 *
 * Built here rather than in the renderer for the reason the Run view's is: the
 * renderer is handed a haystack, and a second one assembled at paint time is a
 * second thing to drift.
 */
function haystack(parts: readonly (string | undefined)[]): string {
  const words = parts
    .filter((part): part is string => part !== undefined && part !== '')
    .map((part) => part.toLowerCase());
  return [...new Set(words)].join(' ');
}

/** The generator call as rbx spells it, name and arguments together. */
function generatorCall(entry: TestcaseEntry): string | undefined {
  if (entry.generatorName === undefined || entry.generatorName === '') {
    return undefined;
  }
  const args = entry.generatorArgs ?? '';
  return args === '' ? entry.generatorName : `${entry.generatorName} ${args}`;
}

/** The generator script as a `path:line`, which is what makes it openable. */
function generatorScript(entry: TestcaseEntry): string | undefined {
  if (entry.generatorScript === undefined || entry.generatorScript === '') {
    return undefined;
  }
  const line = entry.generatorScriptLine;
  return line === undefined ? entry.generatorScript : `${entry.generatorScript}:${line}`;
}

/**
 * Where a testcase came from, in the order rbx's own metadata markup prints it.
 *
 * `get_generation_metadata_markup` prints copied-from, then the generator call,
 * then the generator script, and a test can have more than one of them. Keeping
 * that sequence is what makes this card and `rbx ui` read as one tool.
 */
function cardOrigins(entry: TestcaseEntry): TestsetOrigin[] {
  const origins: TestsetOrigin[] = [];
  if (entry.copiedFrom !== undefined && entry.copiedFrom !== '') {
    origins.push({
      text: entry.copiedFrom,
      open: 'rbx.openCopiedFrom',
      title: `Copied from ${entry.copiedFrom}`,
    });
  }
  const call = generatorCall(entry);
  if (call !== undefined) {
    // Text, not a link: a call names a generator declared in `problem.rbx.yml`
    // and would have to be resolved through the manifest to become a path.
    origins.push({ text: call, title: `Generated by ${call}` });
  }
  const script = generatorScript(entry);
  if (script !== undefined) {
    origins.push({
      text: script,
      open: 'rbx.openGeneratorScript',
      title: `Generated from ${script}`,
    });
  }
  return origins;
}

function validationCard(test: TestsetTest | undefined): TestsetValidationCard | undefined {
  const validation = test?.validation;
  if (validation === undefined) {
    return undefined;
  }
  return {
    ok: validation.ok,
    hue: validation.ok ? 'green' : 'red',
    text: validation.ok ? 'Validated' : 'Rejected by the validator',
    validator: validation.validator,
    // Only ever on a failure: a validator that accepted has nothing to say, and
    // `parseValidation` has already folded an empty message into nothing.
    message: validation.ok ? undefined : validation.message,
  };
}

function cardValues(test: TestsetTest | undefined): TestsetValue[] {
  // The same B / KiB / MiB `rbx run` prints for memory. Sizes are stamped into
  // the manifest at dump time (design D2), so nothing here stats a file.
  const values: TestsetValue[] = [];
  const input = formatMemory(test?.inputSize);
  if (input !== undefined) {
    values.push({ label: 'Input', text: input });
  }
  const output = formatMemory(test?.outputSize);
  if (output !== undefined) {
    values.push({ label: 'Answer', text: output });
  }
  return values;
}

function testcaseCard(group: string, testcase: TestsetTestcase): TestsetCard {
  return {
    title: `${group}/${testcase.stem}`,
    origins: cardOrigins(testcase.entry),
    values: cardValues(testcase.test),
    validation: validationCard(testcase.test),
    visualization: testcase.test?.visualization?.input,
    answerVisualization: testcase.test?.visualization?.output,
  };
}

function testcaseRow(group: string, testcase: TestsetTestcase): TestsetRow {
  const test = testcase.test;
  const failed = test?.validation?.ok === false;
  // Either channel counts: the mark says a picture exists, and which one it
  // is belongs to the card, not to a one-glyph flag.
  const visualized =
    test?.visualization?.input !== undefined || test?.visualization?.output !== undefined;
  return {
    id: `${group}::${testcase.stem}`,
    parentId: group,
    depth: 1,
    kind: 'testcase',
    label: testcase.stem,
    meta: spans([span(formatMemory(test?.inputSize), 'dim', 'size')]),
    flags: [
      ...(visualized
        ? [{ kind: 'visualization' as const, hue: 'blue' as const, title: 'Has a visualization' }]
        : []),
      ...(failed
        ? [invalidFlag(test?.validation?.message ?? 'The validator rejected this test.')]
        : []),
    ],
    expandable: false,
    defaultExpanded: false,
    card: testcaseCard(group, testcase),
    search: haystack([
      `${group}/${testcase.stem}`,
      testcase.stem,
      generatorCall(testcase.entry),
      generatorScript(testcase.entry),
      testcase.entry.copiedFrom,
      // Tokens for the two things the flags say, so a filter can find them: the
      // marks are scannable, but only on the rows already on screen.
      failed ? 'invalid' : undefined,
      visualized ? 'visualization' : undefined,
    ]),
    section: 'rbx.testsetTestcase',
    // Two panes, `input.in` beside `answer.out`. A built testcase has no run,
    // so there is no channel to choose and nothing sticky to remember.
    primaryCommand: 'rbx.openBuiltTestcase',
  };
}

function groupRow(
  group: string,
  testset: Testset,
  total: number,
  count: number,
  invalid: number,
): TestsetRow {
  const declared = testsetGroup(testset, group);
  return {
    id: group,
    depth: 0,
    kind: 'group',
    label: group,
    // Ordered by how long each survives a narrowing sidebar, longest-lived
    // first, so hiding always removes a *suffix* of the line -- which is what
    // keeps the separators correct without the stylesheet knowing which spans
    // are left. See the container queries in style.css.
    meta: spans([
      scoreSpan(declared?.score, total),
      span(count === 1 ? '1 test' : `${count} tests`, 'dim', 'count'),
    ]),
    flags:
      invalid === 0
        ? []
        : [
            invalidFlag(
              invalid === 1
                ? '1 test in this group was rejected by the validator.'
                : `${invalid} tests in this group were rejected by the validator.`,
            ),
          ],
    expandable: true,
    // Open by default, like the Run view's groups: the breakdown is the reason
    // to look at the view at all, and a testset opens to a list of group names
    // otherwise.
    defaultExpanded: true,
    search: haystack([group, invalid === 0 ? undefined : 'invalid']),
    section: 'rbx.testsetGroup',
  };
}

/**
 * `built 3m ago` -- coarse on purpose.
 *
 * Rounded down to the unit, and never more precise than a minute past the first
 * one: this is a cue about which build the view is showing, not a clock, and a
 * ticking second count would suggest the view knows something it does not.
 */
function relativeTime(builtAt: number, now: number): string {
  const seconds = Math.max(0, Math.round((now - builtAt) / 1000));
  if (seconds < 60) {
    return 'built just now';
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `built ${minutes}m ago`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return `built ${hours}h ago`;
  }
  return `built ${Math.floor(hours / 24)}d ago`;
}

function summary(groups: number, tests: number): string {
  const testWord = tests === 1 ? '1 test' : `${tests} tests`;
  const groupWord = groups === 1 ? '1 group' : `${groups} groups`;
  return `${testWord} · ${groupWord}`;
}

export interface TestsetViewOptions {
  /** The manifest's mtime in epoch milliseconds, when the host could stat it. */
  readonly builtAt?: number;
  /** Injected so the header is a pure function of its inputs under test. */
  readonly now?: number;
}

export function buildTestsetViewModel(
  testset: Testset | undefined,
  options: TestsetViewOptions = {},
): TestsetViewModel {
  if (testset === undefined) {
    return EMPTY_TESTSET_MODEL;
  }
  const total = totalScore(testset);
  const walk = testsetWalk(testset);
  const rows: TestsetRow[] = [];
  let tests = 0;
  for (const { group, testcases } of walk) {
    rows.push(
      groupRow(
        group,
        testset,
        total,
        testcases.length,
        testcases.filter((testcase) => testcase.test?.validation?.ok === false).length,
      ),
    );
    for (const testcase of testcases) {
      tests += 1;
      rows.push(testcaseRow(group, testcase));
    }
  }
  return {
    rows,
    // A manifest listing no tests is still a manifest: the package was built,
    // and saying "never built" would send the reader to run a build that has
    // already run. `empty` is reserved for there being no manifest at all.
    empty: false,
    header: {
      built: options.builtAt === undefined
        ? undefined
        : relativeTime(options.builtAt, options.now ?? Date.now()),
      summary: summary(walk.length, tests),
    },
  };
}
