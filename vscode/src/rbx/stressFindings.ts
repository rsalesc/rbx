/**
 * The files of one stress finding, as the editor opens them (#908).
 *
 * Pure: the host lists the finding's directory and hands the names and sizes
 * in, so what is opened, what Compare offers and what each tab is called are
 * all decided here.
 *
 * Every label ends in a `#k ...` segment of its own. That last segment is the
 * tab title (see artifactFs.ts), so a finding's tabs say which finding they
 * are -- and, just as much, it keeps them from being taken for the testcase
 * panes, which recognise their tabs by the bare `input.in` / `output.out`
 * titles (panes.ts `paneKindOf`).
 */
import * as path from 'path';

import { Ext, PackageLayout, findingAnswerPath, findingArtifactPath, findingInputPath } from './layout';
import { StressFinding } from './stress';

export interface FindingFile {
  readonly kind: 'input' | 'answer' | 'output' | 'stderr';
  /** Absolute, on disk. */
  readonly path: string;
  /** The `rbx:` display path; its last segment is the tab title. */
  readonly label: string;
  /** How a QuickPick or a diff title names it. */
  readonly name: string;
}

export interface FindingFiles {
  readonly input?: FindingFile;
  /** The reference answer, when the finder needed one. */
  readonly answer?: FindingFile;
  /** Every solution that left an output, in the manifest's solution order. */
  readonly outputs: readonly FindingFile[];
  /** Every solution whose stderr has something in it. */
  readonly stderrs: readonly FindingFile[];
}

/**
 * The files of finding `finding`, given what its directory holds.
 *
 * `entries` maps a basename in `findings/<k>/` to its size. Solutions are
 * walked in the manifest's order rather than the results', because the
 * reference solution can have left an output without being one of the
 * results (see `StressFinding.results`), and its output is worth a look too.
 */
export function findingFiles(
  pkg: PackageLayout,
  solutions: readonly string[],
  finding: StressFinding,
  entries: ReadonlyMap<string, number>,
): FindingFiles {
  const k = finding.index;
  const prefix = `stress/#${k}`;
  const has = (file: string) => entries.has(path.basename(file));
  const input = findingInputPath(pkg, k);
  const answer = findingAnswerPath(pkg, k);
  const outputs: FindingFile[] = [];
  const stderrs: FindingFile[] = [];
  solutions.forEach((solution, index) => {
    const dir = path.posix.dirname(solution);
    const base = path.posix.basename(solution);
    const at = (name: string) => (dir === '.' ? `${prefix}/${name}` : `${prefix}/${dir}/${name}`);
    const output = findingArtifactPath(pkg, k, index, Ext.Output);
    if (has(output)) {
      outputs.push({
        kind: 'output',
        path: output,
        label: at(`#${k} ${base}${Ext.Output}`),
        name: solution,
      });
    }
    const stderr = findingArtifactPath(pkg, k, index, Ext.Stderr);
    if ((entries.get(path.basename(stderr)) ?? 0) > 0) {
      stderrs.push({
        kind: 'stderr',
        path: stderr,
        label: at(`#${k} ${base}${Ext.Stderr}`),
        name: `${solution} stderr`,
      });
    }
  });
  return {
    input: has(input)
      ? { kind: 'input', path: input, label: `${prefix}/#${k} input.in`, name: 'input' }
      : undefined,
    answer: has(answer)
      ? { kind: 'answer', path: answer, label: `${prefix}/#${k} answer.ans`, name: 'expected answer' }
      : undefined,
    outputs,
    stderrs,
  };
}

/** What Compare offers: the reference answer first, then every output. */
export function compareCandidates(files: FindingFiles): FindingFile[] {
  return [...(files.answer === undefined ? [] : [files.answer]), ...files.outputs];
}
