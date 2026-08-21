/**
 * How a solution row names its solution.
 *
 * Packages overwhelmingly keep every solution under one directory -- `sols/` in
 * the presets -- so the path rbx records repeats that directory on every row
 * and spends the sidebar's narrow label column saying nothing. The user picks
 * how much of the path to keep through `rbx.solutionLabel`; this module is the
 * whole of that decision, kept free of `vscode` so it stays testable under
 * plain `node --test` like the rest of `rbx/`.
 */
export type SolutionLabelStyle = 'full' | 'trimmed' | 'basename';

export const DEFAULT_SOLUTION_LABEL_STYLE: SolutionLabelStyle = 'trimmed';

/** The configured style, or the default for anything unrecognized. */
export function asSolutionLabelStyle(value: unknown): SolutionLabelStyle {
  return value === 'full' || value === 'trimmed' || value === 'basename'
    ? value
    : DEFAULT_SOLUTION_LABEL_STYLE;
}

/**
 * rbx writes solution paths with the separator of the host that ran it, so a
 * package generated on Windows and read on macOS arrives with backslashes.
 * Every rule below is about path *segments*, and it can only be if the two
 * separators have already been made one.
 */
function segments(solutionPath: string): string[] {
  return solutionPath.split(/[\\/]+/).filter((segment) => segment !== '');
}

/**
 * The longest directory prefix every path shares, as a string ending in `/`.
 *
 * Whole segments only, and never the basename: `main.cpp` and `mai_x.cpp` share
 * three characters and nothing that can be dropped, and a package whose
 * solutions all sit at the root shares no directory at all. Both cases return
 * the empty prefix, which is what leaves the paths alone.
 */
export function commonDirPrefix(paths: readonly string[]): string {
  if (paths.length === 0) {
    return '';
  }
  const dirs = paths.map((solutionPath) => segments(solutionPath).slice(0, -1));
  const common: string[] = [];
  for (let i = 0; i < dirs[0].length; i++) {
    const segment = dirs[0][i];
    if (!dirs.every((dir) => dir[i] === segment)) {
      break;
    }
    common.push(segment);
  }
  return common.length === 0 ? '' : `${common.join('/')}/`;
}

/**
 * The label for each path, keyed by the path itself.
 *
 * Computed over the whole list rather than one path at a time because
 * `trimmed` is a fact about the set: what a row drops depends on what its
 * siblings kept. Callers pass one package's solutions, so a contest workspace
 * is not flattened to the least common denominator of every package in it.
 */
export function solutionLabels(
  paths: readonly string[],
  style: SolutionLabelStyle,
): Map<string, string> {
  const prefix = style === 'trimmed' ? commonDirPrefix(paths) : '';
  const labels = new Map<string, string>();
  for (const solutionPath of paths) {
    const parts = segments(solutionPath);
    const normalized = parts.join('/');
    const label = ((): string => {
      switch (style) {
        case 'full':
          return normalized;
        case 'basename':
          // The last segment, not `path.posix.basename`: this module is reached
          // by the webview bundle, which is built for the browser and cannot
          // resolve a node builtin. `segments` has already dropped the empty
          // pieces, so there is no trailing-slash case for basename to handle.
          return parts[parts.length - 1] ?? '';
        case 'trimmed':
          // The prefix always stops short of the basename, so the slice is
          // never empty; the fallback is for a path that somehow did not start
          // with the prefix its own set produced.
          return normalized.startsWith(prefix) ? normalized.slice(prefix.length) : normalized;
      }
    })();
    labels.set(solutionPath, label === '' ? solutionPath : label);
  }
  return labels;
}
