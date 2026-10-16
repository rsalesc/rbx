/**
 * Reading `rbx assets --json` / `rbx contest assets --json`, and shaping it
 * into the Assets view's tree.
 *
 * Which files belong to a package, and as what, is rbx's to say
 * (rbx/box/asset_listing.py): globs come back expanded, statement templates
 * resolved, every path absolute. This module only reads that answer and
 * decides how to lay it out -- split into categories or flat.
 *
 * Pure: no `vscode` import, so `node --test` covers it directly. A malformed
 * payload reads as `undefined`.
 */
import * as path from 'path';

import { parseLeadingObject } from './varsPayload';
import { Wire, asArray, asRecord, asString } from './wire';

/** The listing version this reader understands; rbx's `ASSET_LISTING_VERSION`. */
export const ASSET_LISTING_VERSION = 1;

export type AssetCategory =
  | 'manifest'
  | 'statement'
  | 'solution'
  | 'generator'
  | 'checker'
  | 'interactor'
  | 'validator'
  | 'visualizer'
  | 'testplan'
  | 'manual_test';

const CATEGORIES: readonly AssetCategory[] = [
  'manifest',
  'statement',
  'solution',
  'generator',
  'checker',
  'interactor',
  'validator',
  'visualizer',
  'testplan',
  'manual_test',
];

export interface ListedAsset {
  readonly category: AssetCategory;
  /** Absolute. */
  readonly path: string;
  readonly detail: Readonly<Record<string, string>>;
}

export interface ListedProblem {
  readonly shortName?: string;
  readonly name?: string;
  readonly title?: string;
  readonly root: string;
  readonly error?: string;
  readonly assets: readonly ListedAsset[];
}

export interface ListedContest {
  readonly root: string;
  readonly manifest: string;
  readonly variant?: string;
  readonly title?: string;
  readonly assets: readonly ListedAsset[];
}

export interface AssetListing {
  readonly scope: 'problem' | 'contest';
  readonly contest?: ListedContest;
  readonly problems: readonly ListedProblem[];
  /** Absolute paths of every YAML file the listing was read from. */
  readonly sources: readonly string[];
}

/** The rbx arguments that list a root of `scope`, under contest `variant`. */
export function assetListingArgs(scope: 'problem' | 'contest', variant?: string): string[] {
  if (scope === 'problem') {
    return ['assets', '--json'];
  }
  return variant === undefined
    ? ['contest', 'assets', '--json']
    : ['contest', '-C', variant, 'assets', '--json'];
}

function readCategory(value: Wire): AssetCategory | undefined {
  return CATEGORIES.find((category) => category === value);
}

function readDetail(value: Wire): Record<string, string> {
  const res: Record<string, string> = {};
  for (const [key, each] of Object.entries(asRecord(value) ?? {})) {
    if (typeof each === 'string') {
      res[key] = each;
    }
  }
  return res;
}

function readAssets(value: Wire): ListedAsset[] {
  const res: ListedAsset[] = [];
  for (const each of asArray(value)) {
    const record = asRecord(each);
    const category = readCategory(record?.category);
    const file = asString(record?.path);
    if (category !== undefined && file !== undefined) {
      res.push({ category, path: file, detail: readDetail(record?.detail) });
    }
  }
  return res;
}

function readProblem(value: Wire): ListedProblem | undefined {
  const record = asRecord(value);
  const root = asString(record?.root);
  if (record === undefined || root === undefined) {
    return undefined;
  }
  return {
    shortName: asString(record.short_name),
    name: asString(record.name),
    title: asString(record.title),
    root,
    error: asString(record.error),
    assets: readAssets(record.assets),
  };
}

function readContest(value: Wire): ListedContest | undefined {
  const record = asRecord(value);
  const root = asString(record?.root);
  const manifest = asString(record?.manifest);
  if (record === undefined || root === undefined || manifest === undefined) {
    return undefined;
  }
  return {
    root,
    manifest,
    variant: asString(record.variant),
    title: asString(record.title),
    assets: readAssets(record.assets),
  };
}

export function parseAssetListing(stdout: string): AssetListing | undefined {
  const record = asRecord(parseLeadingObject(stdout));
  if (record === undefined || record.version !== ASSET_LISTING_VERSION) {
    return undefined;
  }
  const scope = record.scope;
  if (scope !== 'problem' && scope !== 'contest') {
    return undefined;
  }
  const problems: ListedProblem[] = [];
  for (const each of asArray(record.problems)) {
    const problem = readProblem(each);
    if (problem !== undefined) {
      problems.push(problem);
    }
  }
  return {
    scope,
    contest: readContest(record.contest),
    problems,
    sources: asArray(record.sources).filter((each): each is string => typeof each === 'string'),
  };
}

// ---------------------------------------------------------------------------
// The tree model.

export type AssetNode =
  | {
      readonly kind: 'category';
      readonly id: string;
      readonly label: string;
      readonly icon: string;
      readonly description: string;
      readonly children: readonly AssetNode[];
    }
  | {
      readonly kind: 'folder';
      readonly id: string;
      readonly label: string;
      readonly description: string;
      readonly children: readonly AssetNode[];
    }
  | {
      readonly kind: 'asset';
      readonly id: string;
      readonly label: string;
      readonly description: string;
      readonly asset: ListedAsset;
    };

interface CategorySpec {
  readonly label: string;
  readonly icon: string;
  readonly members: readonly AssetCategory[];
}

/** Split mode's folders, in display order. The manifest sits above them. */
const SPLIT: readonly CategorySpec[] = [
  { label: 'Statements', icon: 'book', members: ['statement'] },
  { label: 'Solutions', icon: 'code', members: ['solution'] },
  { label: 'Generators', icon: 'wand', members: ['generator'] },
  { label: 'Checker', icon: 'pass', members: ['checker'] },
  { label: 'Interactor', icon: 'comment-discussion', members: ['interactor'] },
  { label: 'Validators', icon: 'shield', members: ['validator'] },
  { label: 'Visualizer', icon: 'eye', members: ['visualizer'] },
  { label: 'Tests', icon: 'beaker', members: ['testplan', 'manual_test'] },
];

const ROLE: Record<AssetCategory, string> = {
  manifest: 'manifest',
  statement: 'statement',
  solution: 'solution',
  generator: 'generator',
  checker: 'checker',
  interactor: 'interactor',
  validator: 'validator',
  visualizer: 'visualizer',
  testplan: 'testplan',
  manual_test: 'manual test',
};

const OUTCOME: Record<string, string> = {
  ANY: 'any',
  ACCEPTED: 'AC',
  ACCEPTED_OR_TLE: 'AC or TLE',
  WRONG_ANSWER: 'WA',
  INCORRECT: 'incorrect',
  RUNTIME_ERROR: 'RTE',
  TIME_LIMIT_EXCEEDED: 'TLE',
  MEMORY_LIMIT_EXCEEDED: 'MLE',
  OUTPUT_LIMIT_EXCEEDED: 'OLE',
  TLE_OR_RTE: 'TLE or RTE',
  TLE_OR_MLE: 'TLE or MLE',
  MLE_OR_RTE: 'MLE or RTE',
};

/** The facts shown after a row's label, without its role. */
function facts(asset: ListedAsset): string[] {
  const d = asset.detail;
  switch (asset.category) {
    case 'solution':
      return d.outcome === undefined ? [] : [`expects ${OUTCOME[d.outcome] ?? d.outcome}`];
    case 'statement': {
      const parts = [d.kind === 'statement' ? undefined : d.kind, d.language, d.type];
      return parts.filter((part): part is string => part !== undefined && part !== '');
    }
    case 'testplan':
    case 'manual_test':
      return d.group === undefined ? [] : [`group ${d.group}`];
    default:
      return [];
  }
}

function relative(file: string, root: string): string {
  const rel = path.relative(root, file);
  return rel.startsWith('..') || path.isAbsolute(rel) ? file : rel;
}

function assetNode(
  idPrefix: string,
  asset: ListedAsset,
  root: string,
  withRole: boolean,
  label?: string,
): AssetNode {
  const description = [withRole ? ROLE[asset.category] : undefined, ...facts(asset)]
    .filter((part) => part !== undefined)
    .join(' · ');
  return {
    kind: 'asset',
    id: `${idPrefix}:${asset.category}:${asset.path}`,
    label: label ?? relative(asset.path, root),
    description,
    asset,
  };
}

/**
 * The Tests folder's rows: testplans one per row, manual tests grouped under
 * the directory they live in, so a glob over fifty files is one row.
 */
function testNodes(idPrefix: string, assets: readonly ListedAsset[], root: string): AssetNode[] {
  const nodes: AssetNode[] = [];
  for (const asset of assets) {
    if (asset.category === 'testplan') {
      nodes.push(assetNode(idPrefix, asset, root, false));
    }
  }
  const byDir = new Map<string, ListedAsset[]>();
  for (const asset of assets) {
    if (asset.category === 'manual_test') {
      const dir = path.dirname(asset.path);
      byDir.set(dir, [...(byDir.get(dir) ?? []), asset]);
    }
  }
  for (const [dir, files] of byDir) {
    const groups = Array.from(new Set(files.map((file) => file.detail.group).filter(Boolean)));
    nodes.push({
      kind: 'folder',
      id: `${idPrefix}:manual:${dir}`,
      label: `${relative(dir, root)}/`,
      description: [
        `${files.length} manual`,
        groups.length === 1 ? `group ${groups[0]}` : undefined,
      ]
        .filter((part) => part !== undefined)
        .join(' · '),
      children: files.map((file) => assetNode(idPrefix, file, dir, false, path.basename(file.path))),
    });
  }
  return nodes;
}

/** The children of a problem (or a contest), in split or flat mode. */
export function assetNodes(
  idPrefix: string,
  assets: readonly ListedAsset[],
  root: string,
  mode: 'split' | 'flat',
): AssetNode[] {
  const manifest = assets.filter((asset) => asset.category === 'manifest');
  const rest = assets.filter((asset) => asset.category !== 'manifest');
  const top = manifest.map((asset) => assetNode(idPrefix, asset, root, false));

  if (mode === 'flat') {
    const order = (asset: ListedAsset) => CATEGORIES.indexOf(asset.category);
    const sorted = [...rest].sort((a, b) => order(a) - order(b));
    return [...top, ...sorted.map((asset) => assetNode(idPrefix, asset, root, true))];
  }

  const folders: AssetNode[] = [];
  for (const spec of SPLIT) {
    const members = rest.filter((asset) => spec.members.includes(asset.category));
    if (members.length === 0) {
      continue;
    }
    const isTests = spec.members.includes('testplan');
    const children = isTests
      ? testNodes(idPrefix, members, root)
      : members.map((asset) => assetNode(idPrefix, asset, root, false));
    folders.push({
      kind: 'category',
      id: `${idPrefix}:category:${spec.label}`,
      label: spec.label,
      icon: spec.icon,
      description: categoryDescription(spec, members),
      children,
    });
  }
  return [...top, ...folders];
}

function categoryDescription(spec: CategorySpec, members: readonly ListedAsset[]): string {
  if (spec.members.includes('statement')) {
    const languages = Array.from(new Set(members.map((asset) => asset.detail.language).filter(Boolean)));
    return languages.join(' · ');
  }
  if (spec.members.includes('testplan')) {
    const plans = members.filter((asset) => asset.category === 'testplan').length;
    const manual = members.length - plans;
    return [plans > 0 ? `${plans} testplan${plans > 1 ? 's' : ''}` : undefined, manual > 0 ? `${manual} manual` : undefined]
      .filter((part) => part !== undefined)
      .join(' · ');
  }
  if (members.length === 1) {
    return '';
  }
  return String(members.length);
}

/** `A · cats`, or the directory name for a problem without a letter. */
export function problemLabel(problem: ListedProblem): string {
  const name = problem.name ?? path.basename(problem.root);
  return problem.shortName === undefined ? name : `${problem.shortName} · ${name}`;
}
