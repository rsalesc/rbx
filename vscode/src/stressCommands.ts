/**
 * Open, Compare and Copy on a stress finding (#908).
 *
 * The files open read-only through the `rbx:` scheme, like every other
 * artifact: a finding's input is evidence, and an edit to it would be an edit
 * nobody could reproduce. Not through `TestcasePanes`, whose two panes and
 * sticky channel are built around one solution's run of one testcase -- a
 * finding is one input and several solutions' outputs side by side, which is
 * a different shape of question.
 *
 * Which files exist, and what each tab is called, is stressFindings.ts.
 */
import * as fs from 'fs/promises';
import * as path from 'path';
import * as vscode from 'vscode';

import { artifactUri } from './artifactFs';
import { PackageLayout, findingDir } from './rbx/layout';
import { StressFinding, StressManifest } from './rbx/stress';
import { FindingFile, FindingFiles, compareCandidates, findingFiles } from './rbx/stressFindings';
import { generatorCallString } from './rbx/stressSpec';

/**
 * Said whenever a finding the view showed is no longer what is on disk --
 * here, and by promotion, which refuses a stale row the same way.
 */
export function findingGone(k: number): void {
  void vscode.window.showInformationMessage(
    `rbx: finding #${k} is no longer on disk -- a newer stress session has probably replaced it.`,
  );
}

/** Basename -> size for one finding's directory; empty when it is gone. */
export async function findingEntries(pkg: PackageLayout, k: number): Promise<Map<string, number>> {
  const dir = findingDir(pkg, k);
  let names: string[];
  try {
    names = await fs.readdir(dir);
  } catch {
    return new Map();
  }
  const sized = await Promise.all(
    names.map(async (name): Promise<[string, number] | undefined> => {
      try {
        return [name, (await fs.stat(path.join(dir, name))).size];
      } catch {
        return undefined;
      }
    }),
  );
  return new Map(sized.filter((entry): entry is [string, number] => entry !== undefined));
}

/**
 * The finding `k` of `manifest`, with its files -- or undefined, having said
 * so, when either is gone.
 */
async function resolve(
  pkg: PackageLayout,
  manifest: StressManifest | undefined,
  k: number,
): Promise<{ finding: StressFinding; files: FindingFiles } | undefined> {
  const finding = manifest?.findings.find((each) => each.index === k);
  if (manifest === undefined || finding === undefined) {
    findingGone(k);
    return undefined;
  }
  const files = findingFiles(pkg, manifest.solutions, finding, await findingEntries(pkg, k));
  if (files.input === undefined && files.answer === undefined && files.outputs.length === 0) {
    findingGone(k);
    return undefined;
  }
  return { finding, files };
}

function uriOf(file: FindingFile): vscode.Uri {
  return artifactUri(file.path, file.label);
}

async function show(file: FindingFile, column: vscode.ViewColumn): Promise<void> {
  const document = await vscode.workspace.openTextDocument(uriOf(file));
  // Not previews: a finding opens several files at once, and a preview tab
  // is replaced by the next one opened into its group.
  await vscode.window.showTextDocument(document, {
    viewColumn: column,
    preview: false,
    preserveFocus: column === vscode.ViewColumn.Beside,
  });
}

async function pickStderr(stderrs: readonly FindingFile[]): Promise<void> {
  const picked =
    stderrs.length === 1
      ? stderrs[0]
      : (
          await vscode.window.showQuickPick(
            stderrs.map((file) => ({ label: file.name, file })),
            { placeHolder: 'Open whose stderr?' },
          )
        )?.file;
  if (picked !== undefined) {
    await show(picked, vscode.ViewColumn.Beside);
  }
}

/**
 * Open finding `k`: its input where the user is, and the reference answer
 * and every solution's output in one group beside it. A non-empty stderr is
 * offered rather than opened -- it is usually a debugging print, and one tab
 * per solution of it would bury the outputs.
 */
export async function openFinding(
  pkg: PackageLayout,
  manifest: StressManifest | undefined,
  k: number,
): Promise<void> {
  const resolved = await resolve(pkg, manifest, k);
  if (resolved === undefined) {
    return;
  }
  const { files } = resolved;
  // The input where the user is, and the rest beside it; with no input,
  // whatever is first takes its place, so there is still a column to be
  // beside.
  const [first, ...rest] = [
    ...(files.input === undefined ? [] : [files.input]),
    ...compareCandidates(files),
  ];
  await show(first, vscode.ViewColumn.Active);
  for (const file of rest) {
    await show(file, vscode.ViewColumn.Beside);
  }
  if (files.stderrs.length > 0) {
    const open = 'Open stderr…';
    const names = files.stderrs.map((file) => file.name.replace(/ stderr$/, '')).join(', ');
    const choice = await vscode.window.showInformationMessage(
      `rbx: finding #${k} has stderr from ${names}.`,
      open,
    );
    if (choice === open) {
      await pickStderr(files.stderrs);
    }
  }
}

/** Diff two of finding `k`'s outputs, the reference answer among them. */
export async function compareFinding(
  pkg: PackageLayout,
  manifest: StressManifest | undefined,
  k: number,
): Promise<void> {
  const resolved = await resolve(pkg, manifest, k);
  if (resolved === undefined) {
    return;
  }
  const candidates = compareCandidates(resolved.files);
  if (candidates.length < 2) {
    void vscode.window.showInformationMessage(
      `rbx: finding #${k} has fewer than two outputs on disk, so there is nothing to compare.`,
    );
    return;
  }
  let left = candidates[0];
  let right = candidates[1];
  // Two is the common case -- a finder that broke one solution against the
  // answer -- and asking which two of two would be a question with one answer.
  if (candidates.length > 2) {
    const items = candidates.map((file) => ({ label: file.name, file }));
    const first = await vscode.window.showQuickPick(items, {
      placeHolder: `Finding #${k}: compare which output…`,
    });
    if (first === undefined) {
      return;
    }
    const second = await vscode.window.showQuickPick(
      items.filter((item) => item !== first),
      { placeHolder: `…with which? (${first.label} goes on the left)` },
    );
    if (second === undefined) {
      return;
    }
    left = first.file;
    right = second.file;
  }
  await vscode.commands.executeCommand(
    'vscode.diff',
    uriOf(left),
    uriOf(right),
    `#${k}: ${left.name} ↔ ${right.name}`,
  );
}

/** Copy finding `k`'s generator call, which reproduces its input. */
export async function copyFindingCall(manifest: StressManifest | undefined, k: number): Promise<void> {
  const finding = manifest?.findings.find((each) => each.index === k);
  if (finding === undefined) {
    findingGone(k);
    return;
  }
  const call = generatorCallString(finding.generator);
  await vscode.env.clipboard.writeText(call);
  void vscode.window.showInformationMessage(`rbx: copied \`${call}\`.`);
}
