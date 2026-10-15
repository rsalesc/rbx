/**
 * What the statement preview shows, as a pure function of the report.
 *
 * The host (statementPreview.ts) gathers the outputs and the task state; this
 * decides what the toolbar, the banner and the empty state say, and is tested.
 */
import * as path from 'path';

import type { FindingItem, PreviewModel } from '../webview/statementProtocol';
import { StatementOutput, outputLabel } from './statementReport';

/** `12:03`, in the reader's own clock. */
function clock(iso: string): string | undefined {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return undefined;
  }
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Relative to the root when inside it -- shorter, and what the setter types. */
function display(root: string, file: string): string {
  const relative = path.relative(root, file);
  return relative.startsWith('..') || path.isAbsolute(relative) ? file : relative;
}

export function summaryOf(output: StatementOutput): string {
  const parts: string[] = [output.ok ? 'built' : 'failed'];
  const at = output.builtAt === undefined ? undefined : clock(output.builtAt);
  if (at !== undefined) {
    parts.push(at);
  }
  const head = parts.join(' ');
  return output.seconds === undefined ? head : `${head} · ${output.seconds.toFixed(1)}s`;
}

export function findingItems(output: StatementOutput): FindingItem[] {
  return output.findings.map((finding, index) => ({
    index,
    where:
      finding.file === undefined
        ? undefined
        : `${display(output.root, finding.file)}${finding.line === undefined ? '' : `:${finding.line}`}`,
    message: finding.message,
  }));
}

export interface PreviewInputs {
  readonly outputs: readonly StatementOutput[];
  readonly selected?: StatementOutput;
  /** Whether the selected output's file is on disk. */
  readonly exists: boolean;
  readonly building: boolean;
}

export function previewModel(inputs: PreviewInputs): PreviewModel {
  const { outputs, selected, exists, building } = inputs;
  const items = outputs.map((output) => ({
    id: output.id,
    label: outputLabel(output),
    ok: output.ok,
  }));
  if (selected === undefined) {
    return {
      outputs: items,
      ok: true,
      findings: [],
      building,
      hasLog: false,
      hasSource: false,
      empty: {
        message:
          'No statement has been built here yet. Build it, and the preview will open the ' +
          'result and follow every rebuild.',
        action: 'build',
      },
    };
  }
  let empty: PreviewModel['empty'];
  if (!exists) {
    empty = { message: `${outputLabel(selected)} has not been built.`, action: 'build' };
  } else if (selected.format !== 'pdf') {
    empty = {
      message: `This output is ${selected.format === 'md' ? 'Markdown' : 'TeX'}, which opens in an editor rather than here.`,
      action: 'open',
    };
  }
  return {
    outputs: items,
    selected: selected.id,
    summary: summaryOf(selected),
    ok: selected.ok,
    findings: findingItems(selected),
    building,
    hasLog: selected.log !== undefined,
    hasSource: selected.source !== undefined,
    empty,
  };
}
