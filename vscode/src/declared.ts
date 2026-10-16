/**
 * What every discovered `problem.rbx.yml` declares, keyed by absolute path.
 *
 * One index, read once per manifest change, because two channels now draw the
 * same fact: the Explorer badge (decorations.ts) and the banner above line one
 * of a solution (solutionBanner.ts). Reading the manifest twice would let them
 * disagree for as long as the two reads are apart -- which is exactly the
 * window in which the setter is editing the file.
 */
import * as fs from 'fs/promises';
import * as path from 'path';
import * as vscode from 'vscode';

import { log } from './log';
import { expandLangTemplate, langTemplatePattern } from './rbx/langTemplate';
import { PackageLayout, manifestPath } from './rbx/layout';
import { ListedProblem } from './rbx/assetListing';
import { globPattern, isGlob } from './rbx/globPattern';
import { GlobRule, mergeListed } from './rbx/listedDeclarations';
import { DeclaredAsset, parseManifest } from './rbx/manifest';
import { readYamlFile } from './rbx/store';
import { RunDataProvider } from './runData';

/** A declaration, and the package whose manifest made it. */
export interface Declared {
  readonly asset: DeclaredAsset;
  /**
   * The root of the package that declared it, which is also the directory rbx
   * has to be asked in about anything else that package holds. Kept alongside
   * the asset rather than recomputed from the file's own path: a declared path
   * may be absolute, and then nothing about it says which root claimed it.
   */
  readonly root: string;
}

async function readdirOrEmpty(dir: string): Promise<string[]> {
  try {
    return await fs.readdir(dir);
  } catch {
    return [];
  }
}

export class DeclaredIndex {
  private readonly changed = new vscode.EventEmitter<void>();
  /** Fired after every re-read, whether or not anything actually moved. */
  readonly onDidChange: vscode.Event<void> = this.changed.event;

  /** What the manifests and rbx's listings together declare: what lookups read. */
  private index = new Map<string, Declared>();
  /** What the manifest parse alone found, keyed by absolute path. */
  private manifestIndex = new Map<string, Declared>();
  /** The manifest entries whose path is a glob, to trace listed files back to. */
  private rules: GlobRule[] = [];
  /** rbx's listings (assetsView.ts), every problem of every root. */
  private listed: readonly ListedProblem[] = [];
  /**
   * The `{lang}` templates the manifests declare, as patterns. A file created
   * or deleted under one changes what the template expands to without any
   * manifest changing -- `rbx lang add` at a contest root copies a statement
   * into every problem and edits only the contest's list.
   */
  private templates: RegExp[] = [];

  constructor(private readonly data: RunDataProvider) {}

  /** Re-read every discovered package's manifest. */
  async refresh(): Promise<void> {
    const packages = await this.data.discovered();
    const next = new Map<string, Declared>();
    const templates: RegExp[] = [];
    const rules: GlobRule[] = [];
    for (const pkg of packages) {
      await this.indexPackage(pkg, next, templates, rules);
    }
    this.manifestIndex = next;
    this.templates = templates;
    this.rules = rules;
    this.remerge();
  }

  /**
   * rbx listed the workspace's assets again (assetsView.ts). Its files fill in
   * what the manifest parse cannot see: globs, includes, fields it skips.
   */
  setListings(problems: readonly ListedProblem[]): void {
    this.listed = problems;
    this.remerge();
  }

  private remerge(): void {
    this.index = mergeListed(this.manifestIndex, this.rules, this.listed);
    log(`Indexed ${this.index.size} declared file(s).`);
    this.changed.fire();
  }

  private async indexPackage(
    pkg: PackageLayout,
    into: Map<string, Declared>,
    templates: RegExp[],
    rules: GlobRule[],
  ): Promise<void> {
    const raw = await readYamlFile(manifestPath(pkg));
    if (raw === undefined) {
      return;
    }
    for (const asset of parseManifest(raw)) {
      // Declared paths are relative to the package root. `resolve` also leaves
      // an absolute one alone, which rbx permits and some packages use. A
      // wildcard statement's `{lang}` template stands for one file per language.
      const declared = path.resolve(pkg.root, asset.path);
      if (isGlob(declared)) {
        // No file of its own; rbx's listing supplies the files it expands to.
        rules.push({ root: pkg.root, asset, pattern: globPattern(declared) });
        continue;
      }
      const pattern = langTemplatePattern(declared);
      if (pattern !== undefined) {
        templates.push(pattern);
      }
      for (const fsPath of await expandLangTemplate(declared, readdirOrEmpty)) {
        into.set(fsPath, { asset, root: pkg.root });
      }
    }
  }

  /** What `uri` is declared as, or `undefined` for a file no manifest names. */
  assetFor(uri: vscode.Uri): DeclaredAsset | undefined {
    return this.declarationFor(uri)?.asset;
  }

  /**
   * What `uri` is declared as and by which package, or `undefined` for a file
   * no manifest names. For callers that need the root as well as the asset:
   * both come from the one lookup, and a caller holding one already knows the
   * other is there.
   *
   * Anything that is not a file on disk is undeclared by construction:
   * artifacts opened through the extension's own read-only scheme are not
   * workspace files and must never be drawn as if they were.
   */
  declarationFor(uri: vscode.Uri): Declared | undefined {
    return uri.scheme === 'file' ? this.index.get(uri.fsPath) : undefined;
  }

  /** Whether `fsPath` is a file some declared `{lang}` template stands for. */
  matchesLangTemplate(fsPath: string): boolean {
    return this.templates.some((pattern) => pattern.test(fsPath));
  }

  /** Absolute paths of every declared solution, for the editor button's `when`. */
  solutionPaths(): string[] {
    return this.pathsOf('solution');
  }

  /**
   * Every declared statement source and the package declaring it: what the
   * manifest parse alone says, for a package rbx has not listed (statementSources.ts).
   */
  statementDeclarations(): { file: string; root: string }[] {
    const declarations: { file: string; root: string }[] = [];
    for (const [fsPath, declared] of this.index) {
      if (declared.asset.role === 'statement') {
        declarations.push({ file: fsPath, root: declared.root });
      }
    }
    return declarations;
  }

  /** Absolute paths of every testplan, for the editor context menu's `when`. */
  testplanPaths(): string[] {
    const paths: string[] = [];
    for (const [fsPath, declared] of this.index) {
      if (declared.asset.testplan === true) {
        paths.push(fsPath);
      }
    }
    return paths;
  }

  private pathsOf(role: DeclaredAsset['role']): string[] {
    const paths: string[] = [];
    for (const [fsPath, declared] of this.index) {
      if (declared.asset.role === role) {
        paths.push(fsPath);
      }
    }
    return paths;
  }

  /** How many files are declared across the workspace. */
  get size(): number {
    return this.index.size;
  }

  dispose(): void {
    this.changed.dispose();
  }
}
