/**
 * What the stress launcher offers, read straight out of `problem.rbx.yml`.
 *
 * The launcher's pickers -- declared stresses, generator names, solutions,
 * testgroups to fuzz -- are all about what the package *declares*, and so is
 * this, for the same reason manifest.ts reads the manifest rather than an
 * artifact: a package never built or stressed still has all of them.
 *
 * Read tolerantly, like everything else from that file: it is edited by hand,
 * and a half-typed entry costs that entry, never the rest. Field names follow
 * rbx/box/schema.py (`Package.stresses`, `.generators`, `.solutions`,
 * `.testcases`).
 */
import { normalizeExpectation } from './manifest';
import { GeneratorCall } from './stress';
import { Wire, asArray, asString, field } from './wire';

export interface StressDeclaration {
  readonly name: string;
  /** The generator's name, and its args as written. */
  readonly generator: GeneratorCall;
  /** The finder expression, as written. */
  readonly finder: string;
}

export interface DeclaredSolution {
  /** Relative to the package root, as written. */
  readonly path: string;
  /**
   * The declared `outcome`, resolved to an `ExpectedOutcome` member name; absent
   * when none was declared (rbx then reads it as `ANY`).
   */
  readonly outcome?: string;
}

export interface StressDeclarations {
  readonly stresses: readonly StressDeclaration[];
  /** Generator names, which is what a generator call starts with. */
  readonly generators: readonly string[];
  readonly solutions: readonly DeclaredSolution[];
  /** Top-level testcase group names: what `--fuzz-on` takes. */
  readonly groups: readonly string[];
}

/** A non-empty string, or undefined -- an empty `name:` is one not typed yet. */
function nonEmpty(raw: Wire): string | undefined {
  const value = asString(raw);
  return value === undefined || value.trim() === '' ? undefined : value;
}

function parseStress(raw: Wire): StressDeclaration | undefined {
  const name = nonEmpty(field(raw, 'name'));
  const generator = nonEmpty(field(raw, 'generator', 'name'));
  const finder = nonEmpty(field(raw, 'finder'));
  if (name === undefined || generator === undefined || finder === undefined) {
    return undefined;
  }
  return {
    name,
    generator: { name: generator, args: asString(field(raw, 'generator', 'args')) },
    finder,
  };
}

function parseSolution(raw: Wire): DeclaredSolution | undefined {
  const path = nonEmpty(field(raw, 'path'));
  if (path === undefined) {
    return undefined;
  }
  const outcome = asString(field(raw, 'outcome'));
  return { path, outcome: outcome === undefined ? undefined : normalizeExpectation(outcome) };
}

/** The non-empty, distinct names `each` reads out of `list`, in order. */
function names(list: Wire, each: (raw: Wire) => string | undefined): string[] {
  const seen = new Set<string>();
  for (const raw of asArray(list)) {
    const name = each(raw);
    if (name !== undefined) {
      seen.add(name);
    }
  }
  return [...seen];
}

/**
 * Everything the launcher needs from a parsed `problem.rbx.yml`.
 *
 * Anything that is not a mapping reads as a package declaring nothing, which
 * is also what a manifest caught mid-edit should look like for a moment.
 */
export function parseStressDeclarations(raw: Wire): StressDeclarations {
  const stresses: StressDeclaration[] = [];
  for (const rawStress of asArray(field(raw, 'stresses'))) {
    const stress = parseStress(rawStress);
    if (stress !== undefined) {
      stresses.push(stress);
    }
  }
  const solutions: DeclaredSolution[] = [];
  for (const rawSolution of asArray(field(raw, 'solutions'))) {
    const solution = parseSolution(rawSolution);
    if (solution !== undefined) {
      solutions.push(solution);
    }
  }
  return {
    stresses,
    generators: names(field(raw, 'generators'), (g) => nonEmpty(field(g, 'name'))),
    solutions,
    groups: names(field(raw, 'testcases'), (g) => nonEmpty(field(g, 'name'))),
  };
}

/**
 * What `rbx stress --list --json` printed, or undefined when it is not that.
 *
 * The listing is the launcher's preferred source: rbx expands the solution
 * globs problem.rbx.yml may hold (`sols/wa-*.*`) into the files that exist,
 * which this module cannot do from the YAML alone. Read as tolerantly as the
 * manifest -- a malformed entry costs that entry -- but a document that is
 * not a mapping, or lacks one of the lists, is no listing at all, so the
 * caller falls back rather than offering nothing.
 */
export function parseStressListing(raw: Wire): StressDeclarations | undefined {
  const lists = ['stresses', 'solutions', 'generators', 'groups'];
  if (lists.some((name) => !Array.isArray(field(raw, name)))) {
    return undefined;
  }
  const stresses: StressDeclaration[] = [];
  for (const rawStress of asArray(field(raw, 'stresses'))) {
    // The manifest's shape, `args: null` included (read as no args).
    const stress = parseStress(rawStress);
    if (stress !== undefined) {
      stresses.push(stress);
    }
  }
  const solutions: DeclaredSolution[] = [];
  for (const rawSolution of asArray(field(raw, 'solutions'))) {
    const solution = parseSolution(rawSolution);
    if (solution !== undefined) {
      solutions.push(solution);
    }
  }
  return {
    stresses,
    generators: names(field(raw, 'generators'), nonEmpty),
    solutions,
    groups: names(field(raw, 'groups'), nonEmpty),
  };
}

/**
 * One line saying why `rbx stress --list --json` failed, out of its stderr.
 *
 * rbx reports errors in a Rich panel, so the box drawing is stripped and the
 * line that names the error is preferred over the panel's other lines (an
 * rbx without `--list` says "No such option: --list").
 */
export function listingFailure(stderr: string): string {
  const lines = stderr
    .split(/\r?\n/)
    .map((line) => line.replace(/^[\s│╭╰─┃┏┗━]+|[\s│╮╯─┃┓┛━]+$/g, ''))
    // Not the usage lines, nor the panel's own `Error` title.
    .filter((line) => line !== '' && !/^(Usage|Try) /.test(line) && !/^error$/i.test(line));
  const named = lines.find((line) => /no such option|error/i.test(line));
  const reason = named ?? lines[lines.length - 1] ?? 'rbx printed no listing';
  return reason.length > 200 ? `${reason.slice(0, 199)}…` : reason;
}

/** Whether a manifest path is a glob, which only rbx can expand. */
export function isGlob(path: string): boolean {
  return /[*?[]/.test(path);
}

/**
 * The manifest's declarations without the entries that are globs.
 *
 * What the launcher offers while rbx has not (or could not) list the expanded
 * ones: a glob is not a file a finder or `--reference` can name, so offering
 * one would only build a command rbx refuses.
 */
export function withoutGlobs(declarations: StressDeclarations): StressDeclarations {
  return {
    ...declarations,
    solutions: declarations.solutions.filter((solution) => !isGlob(solution.path)),
    generators: declarations.generators.filter((generator) => !isGlob(generator)),
  };
}
