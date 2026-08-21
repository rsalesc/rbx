/**
 * The compile phase, as entries in the Problems panel.
 *
 * The Compilation Findings panel answers "which solutions have something
 * wrong"; this answers "where". They are the same facts on two surfaces, and
 * the split between them is not arbitrary: the panel is a list of *solutions*
 * and lives beside the run it belongs to, while Problems is a list of
 * *locations* and belongs to the file you are editing. A setter fixing a
 * warning wants the second one, and wants it without opening the sidebar at
 * all.
 *
 * Pure, like the rest of `rbx/`: no `vscode` import, so `node --test` can hold
 * every decision here to account. The host half (../diagnostics.ts) turns what
 * this returns into `vscode.Diagnostic`s and owns the collection.
 */
import { packageFilePath } from './layout';
import { PackageRunView } from './nodes';
import { CompilationFinding } from './store';

export interface Finding {
  /** Absolute path of the file this belongs to. */
  readonly path: string;
  /** Zero-based, ready for a `Range`. rbx records compiler lines 1-based. */
  readonly line: number;
  readonly severity: 'error' | 'warning';
  readonly message: string;
  /** The compiler flag, on the warnings that carry one. */
  readonly flag?: string;
  /**
   * The stored compiler output, absolute.
   *
   * Carried on every entry, but only an error's is rendered as a link: a
   * warning already says everything it has to say in its message, while an
   * error's message here is deliberately a summary and the log is the rest of
   * it.
   */
  readonly logPath: string;
}

/**
 * What an error entry says, given that it does not know where the error is.
 *
 * rbx parses locations out of *warnings* only, so a failed compile has no line
 * to point at and this lands at the top of the file. The message therefore has
 * to do two things a located diagnostic would not: say plainly that the file
 * did not compile -- the reason a solution vanished from the run -- and send
 * the reader to the output that does have the details.
 */
function failureMessage(finding: CompilationFinding): string {
  const reason = finding.entry.reason;
  return reason === undefined
    ? 'This solution failed to compile, and was left out of the run.'
    : `This solution failed to compile (${reason}), and was left out of the run.`;
}

/** Every finding in every package, in skeleton order. */
export function buildDiagnostics(packages: readonly PackageRunView[]): Finding[] {
  const findings: Finding[] = [];
  for (const { pkg, run } of packages) {
    for (const finding of run?.findings ?? []) {
      if (finding.entry.status === 'FAILED') {
        findings.push({
          path: finding.sourcePath,
          // Line 1 of the file, because there is no better answer -- see
          // `failureMessage`. Never a guessed line: a diagnostic that points at
          // the wrong line is worse than one that points at the file.
          line: 0,
          severity: 'error',
          message: failureMessage(finding),
          logPath: finding.logPath,
        });
        continue;
      }
      for (const warning of finding.entry.warnings) {
        findings.push({
          // The file the *compiler* named, which is not always the file being
          // compiled.
          path: packageFilePath(pkg, warning.file),
          // Compilers count from 1 and VS Code counts from 0. `max` guards a
          // record that somehow says line 0, which would otherwise land on -1.
          line: Math.max(0, warning.line - 1),
          severity: 'warning',
          message: warning.msg,
          flag: warning.flag,
          logPath: finding.logPath,
        });
      }
    }
  }
  return findings;
}

/**
 * The same findings, grouped by the file they belong to.
 *
 * A `DiagnosticCollection` is set per URI and replaces everything it holds for
 * that URI in one call, so the grouping has to happen before the host touches
 * it -- setting one entry at a time would leave each file showing only its last
 * warning.
 */
export function byFile(findings: readonly Finding[]): Map<string, Finding[]> {
  const grouped = new Map<string, Finding[]>();
  for (const finding of findings) {
    const bucket = grouped.get(finding.path);
    if (bucket === undefined) {
      grouped.set(finding.path, [finding]);
    } else {
      bucket.push(finding);
    }
  }
  return grouped;
}
