/**
 * Reads the assets a package *declares*, straight out of `problem.rbx.yml`.
 *
 * Everything else the extension shows comes from `.rbx/runs`, which exists only
 * after `rbx run`. The Explorer cannot wait for that: a solution promises
 * something the moment it is written down, and the badge saying so has to be
 * there when you open the folder for the first time. So this is the one module
 * that reads the manifest rather than an artifact.
 *
 * Two consequences follow, and both are deliberate:
 *
 *   - Expectations arrive as the setter *spelled* them (`ac/tle`, `fail`,
 *     `Accepted`), not as the enum names the skeleton publishes, so they must
 *     be resolved here. `normalizeExpectation` mirrors `AutoEnum.from_str`.
 *   - Nothing here is validated. rbx owns that, and a manifest this cannot make
 *     sense of must degrade to fewer badges, never to an error -- the file is
 *     edited by hand and is therefore *usually* half-written when we read it.
 */
import { Role, moreSpecific } from './role';
import { Wire, asArray, asNumber, asRecord, asString, field } from './wire';

/**
 * One entry of a solution's `outcomePerGroup`, resolved the same way `outcome`
 * is.
 *
 * A list rather than a record because the order is the one the setter wrote,
 * and that is the order it is read back in: `outcomePerGroup` is a stack of
 * overrides, `'*'` usually first, and re-sorting it would make a banner read
 * differently from the file it describes.
 */
export interface PerGroupExpectation {
  /** A top-level group name, or the wildcard `*`. */
  readonly group: string;
  readonly expectation: string;
}

/** One file `problem.rbx.yml` names, and what it named it as. */
export interface DeclaredAsset {
  /** As written in the manifest: relative to the package root. */
  readonly path: string;
  readonly role: Role;
  /**
   * For solutions: the declared `outcome`, resolved to an `ExpectedOutcome`
   * member name (`ACCEPTED_OR_TLE`). A spelling this extension cannot resolve
   * is passed through untouched so `expectationDisplay` can fall back to
   * showing it raw.
   */
  readonly expectation?: string;
  /**
   * For solutions: the declared `outcomePerGroup`, in declaration order, and
   * absent rather than empty when nothing was declared.
   *
   * This is a *second* layer of expectations, not a refinement of the first:
   * rbx keeps matching `outcome` against the whole testset while checking each
   * entry here against one group's tests alone, and a solution fails if either
   * layer does. So both have to be shown, and neither can stand in for the
   * other.
   */
  readonly perGroup?: readonly PerGroupExpectation[];
  /**
   * For solutions: the declared `score`, as the filled-in `[lo, hi]` range
   * `expected_score_range` produces -- an exact score becomes `[n, n]`, and an
   * omitted bound becomes 0 or 10^9.
   *
   * Filled here rather than kept as the setter wrote it so that one formatter
   * can draw a range whichever side it arrived from: the run report publishes
   * `expectedScore` already filled in exactly this way.
   */
  readonly score?: readonly [number, number];
}

/**
 * `AutoEnum._normalize`: lowercase, then drop the characters rbx treats as
 * noise. Note `/` and `+` survive, which is why `ac/tle` and `ac+tle` are
 * listed below as separate aliases rather than folded into one.
 */
function normalize(value: string): string {
  return value.toLowerCase().replace(/[ \-_.:;,]/g, '');
}

/**
 * `ExpectedOutcome`'s aliases, transcribed from rbx/box/schema.py as of
 * 2026-08-19. The member name itself is always accepted too -- `AutoEnum`
 * registers `_normalize(e.name)` before any alias -- which is what lets
 * `outcome: accepted-or-tle` resolve without being spelled out here.
 */
const ALIASES: Record<string, readonly string[]> = {
  ANY: ['any'],
  ACCEPTED: ['accepted', 'ac', 'correct'],
  ACCEPTED_OR_TLE: [
    'accepted or time limit exceeded',
    'accepted or tle',
    'ac or tle',
    'ac/tle',
    'ac+tle',
  ],
  WRONG_ANSWER: ['wrong answer', 'wa'],
  INCORRECT: ['fail', 'incorrect'],
  RUNTIME_ERROR: ['runtime error', 'rte', 're'],
  TIME_LIMIT_EXCEEDED: ['time limit exceeded', 'timeout', 'tle', 'tl'],
  MEMORY_LIMIT_EXCEEDED: ['memory limit exceeded', 'mle', 'ml'],
  OUTPUT_LIMIT_EXCEEDED: ['output limit exceeded', 'ole', 'ol'],
  TLE_OR_RTE: ['tle or rte', 'tle/rte', 'tle+rte', 'tle or re', 'tle+re'],
  JUDGE_FAILED: ['judge failed', 'jf'],
  COMPILATION_ERROR: ['compilation error', 'ce'],
};

const BY_SPELLING = new Map<string, string>();
for (const [member, aliases] of Object.entries(ALIASES)) {
  BY_SPELLING.set(normalize(member), member);
  for (const alias of aliases) {
    BY_SPELLING.set(normalize(alias), member);
  }
}

/**
 * The `ExpectedOutcome` member a manifest spelling means.
 *
 * An unresolvable spelling comes back unchanged rather than as `undefined`:
 * that covers both a member from a newer rbx and a typo, and in either case the
 * setter did declare *something*. Rendering it as "nothing declared" would
 * quietly disagree with `rbx run`, which refuses to run the package at all.
 */
export function normalizeExpectation(spelled: string): string {
  return BY_SPELLING.get(normalize(spelled)) ?? spelled;
}

/** Collects one declaration, keeping the most specific role per path. */
class Collector {
  private readonly byPath = new Map<string, DeclaredAsset>();

  add(
    rawPath: Wire,
    role: Role,
    expectation?: string,
    perGroup?: readonly PerGroupExpectation[],
    score?: readonly [number, number],
  ): void {
    const declared = asString(rawPath);
    if (declared === undefined || declared === '') {
      return;
    }
    const existing = this.byPath.get(declared);
    if (existing === undefined) {
      this.byPath.set(declared, { path: declared, role, expectation, perGroup, score });
      return;
    }
    const winner = moreSpecific(existing.role, role);
    this.byPath.set(declared, {
      path: declared,
      role: winner,
      // A solution's expectations survive a second, less specific claim on the
      // same file: they are the only fields either claim carries any data in.
      expectation: existing.expectation ?? expectation,
      perGroup: existing.perGroup ?? perGroup,
      score: existing.score ?? score,
    });
  }

  /** A `CodeItem`-shaped value, which is `{path: ...}` wherever rbx uses one. */
  addItem(item: Wire, role: Role): void {
    this.add(field(item, 'path'), role);
  }

  assets(): DeclaredAsset[] {
    return [...this.byPath.values()];
  }
}

/**
 * rbx's stand-in for an unbounded upper score (`expected_score_range`).
 *
 * Not a real ceiling, and never drawn as one: `scoreRange` in score.ts prints
 * `50..` rather than inventing a maximum the setter never wrote.
 */
const OPEN_ABOVE = 10 ** 9;

/**
 * One solution's declared `score`, filled the way `expected_score_range` fills
 * it, or `undefined` when nothing usable was declared.
 *
 * `score: 100` is the exact-score spelling and `score: [lo, hi]` the range one,
 * with either bound nullable. Anything else -- a word, a three-element list, a
 * half-typed value -- reads as no declaration at all rather than as a wrong
 * one.
 */
function expectedScore(raw: Wire): readonly [number, number] | undefined {
  const exact = asNumber(raw);
  if (exact !== undefined) {
    return [exact, exact];
  }
  if (!Array.isArray(raw) || raw.length !== 2) {
    return undefined;
  }
  const [lo, hi] = raw.map(asNumber);
  if (lo === undefined && hi === undefined) {
    return undefined;
  }
  return [lo ?? 0, hi ?? OPEN_ABOVE];
}

/**
 * One solution's `outcomePerGroup`, or `undefined` when it declares none.
 *
 * Every entry is read independently, so a group whose value is still being
 * typed -- `main:` with nothing after it -- costs that entry and leaves the
 * rest of the declaration readable. That matters more here than elsewhere: a
 * mapping is half-written for as long as it takes to type the next line.
 */
function perGroupExpectations(raw: Wire): readonly PerGroupExpectation[] | undefined {
  const record = asRecord(raw);
  if (record === undefined) {
    return undefined;
  }
  const entries: PerGroupExpectation[] = [];
  for (const [group, spelled] of Object.entries(record)) {
    const value = asString(spelled);
    if (group === '' || value === undefined) {
      continue;
    }
    entries.push({ group, expectation: normalizeExpectation(value) });
  }
  return entries.length === 0 ? undefined : entries;
}

/**
 * Walk a testcase group and its subgroups.
 *
 * Groups nest, and a validator or generator script declared three levels down
 * is as much a validator as the package-level one. Recursion depth is bounded
 * by rbx's own schema (a group holds subgroups, which hold none), but the guard
 * is kept anyway: this parses a hand-edited file, and a YAML alias cycle would
 * otherwise hang the extension host rather than produce one missing badge.
 */
function collectGroup(collector: Collector, group: Wire, depth: number): void {
  if (depth > 4) {
    return;
  }
  collector.addItem(field(group, 'validator'), 'validator');
  collector.addItem(field(group, 'visualizer'), 'visualizer');
  collector.addItem(field(group, 'generatorScript'), 'generator');
  for (const subgroup of asArray(field(group, 'subgroups'))) {
    collectGroup(collector, subgroup, depth + 1);
  }
}

/** Statements, tutorials and documents all share `BaseStatement`. */
function collectStatements(collector: Collector, list: Wire): void {
  for (const statement of asArray(list)) {
    // `file` is the v2 spelling; `path` was v1's, and packages that predate the
    // rename are still on disk.
    collector.add(field(statement, 'file'), 'statement');
    collector.add(field(statement, 'path'), 'statement');
  }
}

/**
 * What the package calls itself, or `undefined` if it does not say.
 *
 * The selector pairs this with the contest letter, because a letter alone does
 * not say which problem it is. The *declared* name rather than the directory:
 * rbx defaults a problem's path to its short name, so a contest laid out the
 * default way has every package sitting in a directory called `A`, `B`, `C`,
 * and a basename would render the useless `A - A`.
 */
export function parseProblemName(raw: Wire): string | undefined {
  const root = asRecord(raw);
  if (root === undefined) {
    return undefined;
  }
  const name = asString(root.name);
  // An empty `name:` is a name the setter has not written yet, not a name that
  // happens to be blank -- the manifest is usually half-typed when we read it.
  return name === '' ? undefined : name;
}

/**
 * Every asset `problem.rbx.yml` declares, in no particular order.
 *
 * Returns an empty list rather than throwing for anything it cannot read,
 * including a manifest that is not a mapping at all.
 */
export function parseManifest(raw: Wire): DeclaredAsset[] {
  const root = asRecord(raw);
  if (root === undefined) {
    return [];
  }
  const collector = new Collector();

  for (const solution of asArray(root.solutions)) {
    const spelled = asString(field(solution, 'outcome'));
    collector.add(
      field(solution, 'path'),
      'solution',
      // An entry with no `outcome:` is not undeclared -- rbx defaults it to
      // ANY -- so it gets ANY's badge rather than no badge at all. The two
      // states look different on purpose: `?` says "runs, nothing promised",
      // and a bare file name says "rbx has never heard of this file".
      spelled === undefined ? 'ANY' : normalizeExpectation(spelled),
      perGroupExpectations(field(solution, 'outcomePerGroup')),
      expectedScore(field(solution, 'score')),
    );
  }

  collector.addItem(root.checker, 'checker');
  collector.addItem(field(root.checker, 'fallback_to'), 'checker');
  collector.addItem(root.interactor, 'interactor');
  collector.addItem(root.validator, 'validator');
  collector.addItem(root.visualizer, 'visualizer');
  collector.addItem(root.generatorScript, 'generator');
  for (const generator of asArray(root.generators)) {
    collector.addItem(generator, 'generator');
  }
  for (const group of asArray(root.testcases)) {
    collectGroup(collector, group, 0);
  }
  collectStatements(collector, root.statements);
  collectStatements(collector, root.tutorials);

  return collector.assets();
}
