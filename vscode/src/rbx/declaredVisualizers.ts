/**
 * Which visualizers `problem.rbx.yml` declares, per testcase.
 *
 * This answers one question the views need before they can offer a *lazy*
 * visualize button: would `rbx visualize` find a visualizer for this testcase,
 * or would it come back with "No visualizer declared"? Offering a button that
 * can only fail is worse than offering none.
 *
 * **rbx is the source of truth, not this file.** The resolution below is a
 * second implementation of `testcase_extractors.py:180-195,368-374`, kept
 * deliberately small and pinned by tests so the duplication is visible and
 * cheap to re-check. It decides only whether a button is *drawn*; the actual
 * visualizer is always chosen by rbx, which resolves the entry properly. So the
 * worst a drift here can do is show a button that reports nothing to visualize,
 * or hide one that would have worked -- never run the wrong program.
 *
 * The precedence, which rbx defines and this mirrors:
 *
 *   - `visualizer` and `solutionVisualizer` may be declared on the package, on
 *     a group, and on a subgroup (`TestcaseGroup extends TestcaseSubgroup`).
 *   - The innermost declaration wins, and the two fields resolve
 *     *independently* -- a subgroup overriding only `visualizer` keeps the
 *     package's `solutionVisualizer`.
 *   - The solution channel falls back to the input visualizer when no
 *     `solutionVisualizer` is in force, matching
 *     `run_solution_visualizers_for_entries`.
 */
import { Wire, asArray, asString, field } from './wire';

/** What a testcase can be visualized into, before anything has been run. */
export interface DeclaredVisualizers {
  /** A `visualizer` is in force, so `rbx visualize input` would find one. */
  readonly input: boolean;
  /** A `solutionVisualizer` (or the input fallback) is in force. */
  readonly output: boolean;
}

export const NO_VISUALIZERS: DeclaredVisualizers = { input: false, output: false };

/** One level of the declaration tree: the package, a group, or a subgroup. */
interface VisualizerScope {
  readonly visualizer?: string;
  readonly solutionVisualizer?: string;
  /** Keyed by group/subgroup name. */
  readonly children: ReadonlyMap<string, VisualizerScope>;
}

/** The whole tree, as declared. */
export interface VisualizerDeclarations {
  readonly root: VisualizerScope;
}

/**
 * A declaration is a `CodeItem`, so it is an object with a `path`.
 *
 * Read as "is one declared", not "which one": which program runs is rbx's
 * decision, and reading the path here would invite this file to grow into a
 * resolver it must not become.
 */
function declaredPath(raw: Wire): string | undefined {
  return asString(field(raw, 'path'));
}

function scopeOf(raw: Wire, depth: number): VisualizerScope {
  const children = new Map<string, VisualizerScope>();
  // Bounded like `manifest.ts` does: rbx's schema nests one level, but this
  // parses a hand-edited file and a YAML alias cycle must not hang the host.
  if (depth <= 4) {
    for (const child of asArray(field(raw, 'subgroups'))) {
      const name = asString(field(child, 'name'));
      if (name !== undefined) {
        children.set(name, scopeOf(child, depth + 1));
      }
    }
  }
  return {
    visualizer: declaredPath(field(raw, 'visualizer')),
    solutionVisualizer: declaredPath(field(raw, 'solutionVisualizer')),
    children,
  };
}

/** Parse the declaration tree out of a `problem.rbx.yml`. */
export function parseVisualizerDeclarations(raw: Wire): VisualizerDeclarations {
  const groups = new Map<string, VisualizerScope>();
  for (const group of asArray(field(raw, 'testcases'))) {
    const name = asString(field(group, 'name'));
    if (name !== undefined) {
      groups.set(name, scopeOf(group, 1));
    }
  }
  return {
    root: {
      visualizer: declaredPath(field(raw, 'visualizer')),
      solutionVisualizer: declaredPath(field(raw, 'solutionVisualizer')),
      children: groups,
    },
  };
}

/**
 * What is in force for a testcase, addressed by its subgroup path.
 *
 * `path` is `subgroup_entry.group` as rbx writes it: `main` for a testcase
 * directly in a group, `main/sub` for one in a subgroup
 * (`testcase_extractors.py:195`). An unknown segment simply stops the walk, so
 * a manifest that has changed since the last build degrades to the outermost
 * declaration rather than reporting nothing.
 */
export function resolveDeclaredVisualizers(
  declarations: VisualizerDeclarations,
  path: string | undefined,
): DeclaredVisualizers {
  let scope = declarations.root;
  let visualizer = scope.visualizer;
  let solutionVisualizer = scope.solutionVisualizer;

  for (const segment of (path ?? '').split('/')) {
    if (segment === '') {
      continue;
    }
    const child = scope.children.get(segment);
    if (child === undefined) {
      break;
    }
    scope = child;
    // Independently: overriding one channel must not clear the other.
    visualizer = child.visualizer ?? visualizer;
    solutionVisualizer = child.solutionVisualizer ?? solutionVisualizer;
  }

  return {
    input: visualizer !== undefined,
    // The same fallback rbx applies: a package declaring only `visualizer`
    // uses it for both channels.
    output: (solutionVisualizer ?? visualizer) !== undefined,
  };
}
