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
