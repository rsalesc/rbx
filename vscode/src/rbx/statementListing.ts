/**
 * Reading `rbx statements ls --json` / `rbx contest statements ls --json`.
 *
 * Which files are statement sources is rbx's to say: a `language: '*'` entry
 * stands for one file per language of a list the problem may inherit from its
 * contest through `!include`s, a concrete entry overrides the wildcard one, and
 * `extends` fills in a missing `file`. The command answers with the resolved
 * entries, plus `sources`: every YAML file the answer was read from, which is
 * what a cached answer has to be dropped on (rbx/box/statements/listing.py).
 *
 * The manifest parse (manifest.ts) stays as the fallback for a package rbx
 * could not answer for -- an rbx too old to have the command, or a manifest
 * halfway through an edit -- and `mergeStatementSources` decides between them.
 *
 * Pure: no `vscode` import, so `node --test` covers it directly. Every
 * malformed shape reads as `undefined`, i.e. "use the fallback".
 */
import { DispatchScope } from './dispatch';
import { parseLeadingObject } from './varsPayload';
import { Wire, asArray, asNumber, asRecord, asString } from './wire';

/** The listing version this reader understands; rbx's `LISTING_VERSION`. */
export const LISTING_VERSION = 1;

export type ListedKind = 'statement' | 'tutorial' | 'document';

export interface ListedStatement {
  readonly kind: ListedKind;
  readonly language: string;
  readonly variant: string;
  /** Absolute. Absent for an entry rbx itself would refuse to build. */
  readonly file?: string;
}

export interface StatementListing {
  readonly scope: DispatchScope;
  /** Absolute package (or contest) root. */
  readonly root: string;
  readonly statements: readonly ListedStatement[];
  /** Absolute paths of every YAML file the listing was read from. */
  readonly sources: readonly string[];
}

/** The rbx arguments that list the statements of a package of `scope`. */
export function listingArgs(scope: DispatchScope): string[] {
  return scope === 'contest' ? ['contest', 'statements', 'ls', '--json'] : ['statements', 'ls', '--json'];
}

function readKind(value: Wire): ListedKind | undefined {
  return value === 'statement' || value === 'tutorial' || value === 'document' ? value : undefined;
}

function readStatement(value: Wire): ListedStatement | undefined {
  const record = asRecord(value);
  const kind = readKind(record?.kind);
  const language = asString(record?.language);
  const variant = asString(record?.variant);
  if (record === undefined || kind === undefined || language === undefined || variant === undefined) {
    return undefined;
  }
  return { kind, language, variant, file: asString(record.file) };
}

/**
 * The listing rbx printed, or `undefined` for anything this reader cannot
 * trust: another version, another shape, or a single malformed entry -- a
 * listing with an entry dropped would hide that statement's button for as
 * long as the answer is cached, where the fallback would at least show it.
 */
export function parseStatementListing(stdout: string): StatementListing | undefined {
  const record = asRecord(parseLeadingObject(stdout));
  if (record === undefined || asNumber(record.version) !== LISTING_VERSION) {
    return undefined;
  }
  const scope = record.scope;
  const root = asString(record.root);
  if ((scope !== 'problem' && scope !== 'contest') || root === undefined) {
    return undefined;
  }
  const rawStatements = asArray(record.statements);
  const statements = rawStatements.map(readStatement);
  const sources = asArray(record.sources).map(asString);
  if (
    !Array.isArray(record.statements) ||
    !Array.isArray(record.sources) ||
    statements.some((statement) => statement === undefined) ||
    sources.some((source) => source === undefined)
  ) {
    return undefined;
  }
  return {
    scope,
    root,
    statements: statements as ListedStatement[],
    sources: sources as string[],
  };
}

/** What a statement source file is, and which package builds it. */
export interface StatementSource {
  readonly root: string;
  readonly scope: DispatchScope;
  readonly kind: ListedKind;
}

/** A statement the manifest parse found, for a package rbx did not answer for. */
export interface FallbackStatement {
  readonly file: string;
  readonly root: string;
}

/**
 * Every statement source file, keyed by absolute path.
 *
 * rbx's answer for a root is the whole truth about that root: the fallback's
 * entries are used only for problem roots no listing covers. A file both a
 * problem and its contest name (a contest statement may well sit inside a
 * problem directory) belongs to the problem, which is listed first.
 */
export function mergeStatementSources(
  listings: readonly StatementListing[],
  fallback: readonly FallbackStatement[],
): Map<string, StatementSource> {
  const merged = new Map<string, StatementSource>();
  const answered = new Set(listings.map((listing) => listing.root));
  const ordered = [...listings].sort((a, b) => (a.scope === b.scope ? 0 : a.scope === 'problem' ? -1 : 1));
  for (const listing of ordered) {
    for (const statement of listing.statements) {
      if (statement.file !== undefined && !merged.has(statement.file)) {
        merged.set(statement.file, { root: listing.root, scope: listing.scope, kind: statement.kind });
      }
    }
  }
  for (const { file, root } of fallback) {
    if (!answered.has(root) && !merged.has(file)) {
      merged.set(file, { root, scope: 'problem', kind: 'statement' });
    }
  }
  return merged;
}
