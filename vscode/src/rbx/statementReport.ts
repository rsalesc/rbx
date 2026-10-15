/**
 * The statement build report rbx publishes at `.rbx/statements/report.yml`.
 *
 * Everything the statement preview and its diagnostics know comes from here:
 * which outputs exist and where, whether the last build of each one failed, and
 * where each error is *in the files the setter edits* -- rbx traced it there
 * through the Jinja renders and the pdflatex log
 * (rbx/box/statements/sourcemap.py). Nothing below re-derives an output name or
 * reads a LaTeX log; that would be the run report's drift all over again
 * (docs/plans/2026-10-15-statement-preview-design.md).
 *
 * A package writes one under its root, and so does a contest, so a problem in a
 * contest has two to read.
 */
import * as path from 'path';

import { RbxCommand, statementCommand } from './dispatch';
import { CACHE_DIR } from './layout';
import { Wire, asArray, asNumber, asRecord, asString, field } from './wire';

/** The only report version this extension understands. */
export const STATEMENT_REPORT_VERSION = 1;

export function statementReportPath(root: string): string {
  return path.join(root, CACHE_DIR, 'statements', 'report.yml');
}

export type ReportScope = 'problem' | 'contest';

export interface StatementFinding {
  /** `latex`, `template` or `build`. */
  readonly origin: string;
  readonly severity: 'error' | 'warning';
  readonly message: string;
  /** Absolute; absent when rbx could not locate it. */
  readonly file?: string;
  /** 1-based, as rbx records it. */
  readonly line?: number;
  readonly context?: string;
}

export interface StatementOutput {
  /** Stable across rebuilds: what a picker remembers its choice by. */
  readonly id: string;
  readonly scope: ReportScope;
  /** The root whose report this came from. */
  readonly root: string;
  /** `statement`, `tutorial` or `document`. */
  readonly kind: string;
  /** A contest statement's or document's name. */
  readonly name?: string;
  readonly language?: string;
  readonly variant?: string;
  /** The output's extension: `pdf`, `tex` or `md`. */
  readonly format: string;
  /** Absolute. May not exist, for an output that has never built. */
  readonly path: string;
  /** The file it is built from, absolute. */
  readonly source?: string;
  readonly ok: boolean;
  readonly builtAt?: string;
  readonly seconds?: number;
  readonly findings: readonly StatementFinding[];
  /** The full pdflatex log, absolute, while the build directory keeps it. */
  readonly log?: string;
}

function resolveIn(root: string, value: Wire): string | undefined {
  const text = asString(value);
  return text === undefined ? undefined : path.resolve(root, text);
}

function parseFinding(raw: Wire, root: string): StatementFinding | undefined {
  const message = asString(field(raw, 'message'));
  if (message === undefined) {
    return undefined;
  }
  const line = asNumber(field(raw, 'line'));
  return {
    origin: asString(field(raw, 'origin')) ?? 'build',
    severity: asString(field(raw, 'severity')) === 'warning' ? 'warning' : 'error',
    message,
    file: resolveIn(root, field(raw, 'file')),
    line: line !== undefined && line >= 1 ? line : undefined,
    context: asString(field(raw, 'context')),
  };
}

/**
 * The outputs in one report, or none when it is not a version this extension
 * reads. An entry missing what identifies it is skipped, never guessed at.
 */
export function parseStatementReport(
  raw: Wire,
  root: string,
  scope: ReportScope,
): StatementOutput[] {
  if (asNumber(field(raw, 'version')) !== STATEMENT_REPORT_VERSION) {
    return [];
  }
  const outputs: StatementOutput[] = [];
  for (const entry of asArray(field(raw, 'outputs'))) {
    if (asRecord(entry) === undefined) {
      continue;
    }
    const kind = asString(field(entry, 'kind'));
    const format = asString(field(entry, 'format'));
    const output = resolveIn(root, field(entry, 'path'));
    if (kind === undefined || format === undefined || output === undefined) {
      continue;
    }
    const name = asString(field(entry, 'name'));
    const language = asString(field(entry, 'language'));
    const variant = asString(field(entry, 'variant'));
    outputs.push({
      id: [scope, root, kind, name ?? '', language ?? '', variant ?? '', format].join('\u0000'),
      scope,
      root,
      kind,
      name,
      language,
      variant,
      format,
      path: output,
      source: resolveIn(root, field(entry, 'source')),
      ok: asString(field(entry, 'status')) === 'ok',
      builtAt: asString(field(entry, 'builtAt')),
      seconds: asNumber(field(entry, 'seconds')),
      findings: asArray(field(entry, 'findings'))
        .map((finding) => parseFinding(finding, root))
        .filter((finding): finding is StatementFinding => finding !== undefined),
      log: resolveIn(root, field(entry, 'log')),
    });
  }
  return outputs;
}

/**
 * How the picker names an output: what it is, then what tells it apart from
 * its siblings. The default variant goes unsaid, as it does in rbx's own file
 * names.
 */
export function outputLabel(output: StatementOutput): string {
  const parts: string[] = [];
  if (output.scope === 'contest') {
    parts.push(`contest ${output.kind}${output.name === undefined ? '' : ` ${output.name}`}`);
  } else {
    parts.push(output.kind);
  }
  if (output.language !== undefined && output.scope === 'problem') {
    parts.push(output.language);
  }
  if (output.variant !== undefined && output.variant !== 'default') {
    parts.push(output.variant);
  }
  if (output.format !== 'pdf') {
    parts.push(output.format);
  }
  return parts.join(' · ');
}

/**
 * The output the preview should show.
 *
 * The one already showing, while it still exists; otherwise the one built from
 * the file being edited; otherwise a problem's own PDF before a contest's, and
 * a statement before a tutorial, since that is what "preview the statement"
 * means when nothing narrows it.
 */
export function defaultOutput(
  outputs: readonly StatementOutput[],
  activeFile?: string,
  current?: string,
): StatementOutput | undefined {
  const kept = outputs.find((output) => output.id === current);
  if (kept !== undefined) {
    return kept;
  }
  const fromActive = outputs.filter(
    (output) => activeFile !== undefined && output.source === activeFile,
  );
  const rank = (output: StatementOutput): number =>
    (output.format === 'pdf' ? 0 : 4) +
    (output.scope === 'problem' ? 0 : 2) +
    (output.kind === 'statement' ? 0 : 1);
  const best = (candidates: readonly StatementOutput[]) =>
    [...candidates].sort((a, b) => rank(a) - rank(b))[0];
  return best(fromActive) ?? best(outputs);
}

/** One entry for the Problems panel. */
export interface StatementDiagnostic {
  /** `latex`, `template` or `build`: who reported it. */
  readonly origin: string;
  /** Absolute path of the file this belongs to. */
  readonly path: string;
  /** Zero-based, ready for a `Range`. */
  readonly line: number;
  readonly severity: 'error' | 'warning';
  readonly message: string;
  /** The outputs whose last build reported it. */
  readonly outputs: readonly string[];
}

/**
 * Every finding of every output, as diagnostics.
 *
 * An unlocated finding lands on the top of the output's source, because the
 * setter needs to hear about it and that is the file they will open; one with
 * nowhere to go at all is left out. Two outputs built from the same template
 * report the same error twice, and the setter needs to see it once, naming
 * both.
 */
export function statementDiagnostics(
  outputs: readonly StatementOutput[],
): StatementDiagnostic[] {
  const merged = new Map<string, StatementDiagnostic>();
  for (const output of outputs) {
    for (const finding of output.findings) {
      const file = finding.file ?? output.source;
      if (file === undefined) {
        continue;
      }
      const line = finding.file !== undefined && finding.line !== undefined ? finding.line - 1 : 0;
      const message =
        finding.context === undefined ? finding.message : `${finding.message}\n${finding.context}`;
      const key = [file, line, finding.severity, message].join('\u0000');
      const existing = merged.get(key);
      merged.set(key, {
        origin: finding.origin,
        path: file,
        line,
        severity: finding.severity,
        message,
        outputs: [...(existing?.outputs ?? []), outputLabel(output)],
      });
    }
  }
  return [...merged.values()];
}

/** One build a save asks for. */
export interface SaveTarget {
  readonly command: RbxCommand;
  readonly root: string;
}

function isInside(dir: string, file: string): boolean {
  const relative = path.relative(dir, file);
  return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative);
}

/**
 * What saving `file` should rebuild.
 *
 * The outputs built *from* that file, when there are any: a tutorial's source
 * often sits beside the statement's, and rebuilding both would leave the one
 * being edited queued behind the one that was not. Otherwise every output whose
 * source sits in the same directory tree, since that is where the figures and
 * `\input`s a statement pulls in live.
 */
export function saveTargets(outputs: readonly StatementOutput[], file: string): SaveTarget[] {
  const exact = outputs.filter((output) => output.source === file);
  const chosen =
    exact.length > 0
      ? exact
      : outputs.filter(
          (output) => output.source !== undefined && isInside(path.dirname(output.source), file),
        );
  const targets = new Map<string, SaveTarget>();
  for (const output of chosen) {
    const command = statementCommand(output.scope, output.kind);
    targets.set(`${command}\u0000${output.root}`, { command, root: output.root });
  }
  return [...targets.values()];
}
