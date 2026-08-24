/**
 * Where a package keeps its build directory, as rbx would resolve it.
 *
 * `buildDir` is an environment setting (`Environment.buildDir` in
 * rbx/box/environment.py), so a preset is free to rename it -- and presets do:
 * a preset shipping `buildDir: build.rbx` lets a checkout gitignore one glob.
 * Hardcoding `build` here silently emptied the Tests view and pointed every
 * testcase pane at a path that does not exist.
 *
 * Resolved by reading the same files rbx reads rather than by asking rbx, which
 * the extension never does (design D2/D3): `presets.find_local_preset` walks up
 * for `.local.rbx/preset.rbx.yml`, `Preset.env` names an environment file beside
 * it, and `Environment.buildDir` is the answer. Every step is optional, and any
 * step that is missing, unreadable or the wrong shape falls back to `build` --
 * which is both rbx's default and what a package with no preset at all has.
 */
import * as fs from 'fs';
import * as path from 'path';
import { parse as parseYaml } from 'yaml';

/** rbx's default when no environment says otherwise (`Environment.buildDir`). */
export const DEFAULT_BUILD_DIR = 'build';

const PRESET_MANIFEST = 'preset.rbx.yml';
const LOCAL_PRESET_DIR = '.local.rbx';

/**
 * Cache keyed by package root.
 *
 * Resolution touches two small files per package and is asked for on every
 * path build, so it is memoized rather than repeated. `resetBuildDirs` is what
 * the watcher calls when a preset or environment file changes -- the whole map
 * is dropped, because a preset lives above the packages it governs and one
 * edit can move all of them at once.
 */
const cache = new Map<string, string>();

export function resetBuildDirs(): void {
  cache.clear();
}

function readYaml(filePath: string): unknown {
  let text: string;
  try {
    text = fs.readFileSync(filePath, 'utf8');
  } catch {
    return undefined;
  }
  try {
    return parseYaml(text);
  } catch {
    // Caught half-written, or hand-edited into something invalid. The fallback
    // is a directory that may not exist, which the views already render as
    // "nothing built yet" -- the same as being genuinely unbuilt.
    return undefined;
  }
}

function stringField(raw: unknown, key: string): string | undefined {
  if (typeof raw !== 'object' || raw === null) {
    return undefined;
  }
  const value = (raw as Record<string, unknown>)[key];
  return typeof value === 'string' && value !== '' ? value : undefined;
}

/** Ancestors of `from`, nearest first, stopping at the filesystem root. */
function* ancestors(from: string): Generator<string> {
  let current = path.resolve(from);
  for (;;) {
    yield current;
    const parent = path.dirname(current);
    if (parent === current) {
      return;
    }
    current = parent;
  }
}

/**
 * The active preset's directory, mirroring `presets.find_local_preset`.
 *
 * Two spellings, in rbx's order: an installed preset lives in `.local.rbx/`
 * beside the contest, and a preset being *developed* is a checkout with a bare
 * `preset.rbx.yml` at its top. The nested form is only consulted when no
 * installed one is found anywhere above, which is the order rbx uses.
 */
function findPresetDir(root: string): string | undefined {
  for (const dir of ancestors(root)) {
    if (fs.existsSync(path.join(dir, LOCAL_PRESET_DIR, PRESET_MANIFEST))) {
      return path.join(dir, LOCAL_PRESET_DIR);
    }
  }
  for (const dir of ancestors(root)) {
    if (fs.existsSync(path.join(dir, PRESET_MANIFEST))) {
      return dir;
    }
  }
  return undefined;
}

function resolveUncached(root: string): string {
  const presetDir = findPresetDir(root);
  if (presetDir === undefined) {
    return DEFAULT_BUILD_DIR;
  }
  const env = stringField(readYaml(path.join(presetDir, PRESET_MANIFEST)), 'env');
  if (env === undefined) {
    return DEFAULT_BUILD_DIR;
  }
  const buildDir = stringField(readYaml(path.join(presetDir, env)), 'buildDir');
  if (buildDir === undefined) {
    return DEFAULT_BUILD_DIR;
  }
  // An absolute `buildDir` would escape the package. rbx joins it onto the
  // package root with pathlib, where an absolute right-hand side *replaces*
  // the root -- a behaviour worth mirroring nowhere, so it is refused here.
  return path.isAbsolute(buildDir) ? DEFAULT_BUILD_DIR : buildDir;
}

/**
 * The build directory for a package, relative to its root.
 *
 * A relative path, not a bare name: nothing stops an environment from spelling
 * it `out/build`, and callers join it onto the root themselves (`layout.ts`).
 */
export function resolveBuildDir(root: string): string {
  const cached = cache.get(root);
  if (cached !== undefined) {
    return cached;
  }
  const resolved = resolveUncached(root);
  cache.set(root, resolved);
  return resolved;
}
