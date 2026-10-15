/**
 * Promote from the views and from files: the entry points of promoter.ts
 * that are not a testplan lens or a stress finding.
 *
 *   - **Promote This Test…** on a testcase row of the Run or Tests view: the
 *     test by its name (`group/index`), so it can move between groups or be
 *     frozen into a `@copy` where it is. The input of an ad-hoc `irun` row has
 *     no name; it is promoted as the file it is, from a copy, since the next
 *     `irun` replaces the original.
 *   - **Promote This Input…** on a `.in` file in the explorer, or on an
 *     editor: the file, or -- for an unsaved buffer or a selection -- its text,
 *     from a scratch copy.
 */
import * as fs from 'fs/promises';
import * as path from 'path';
import * as vscode from 'vscode';

import { ActiveProblem } from './activeProblem';
import { scratchFiles } from './irunCommands';
import { Promoter } from './promoter';
import { testSelector } from './rbx/irun';
import { TestcaseNode } from './rbx/nodes';
import { TestsetTestcaseNode } from './rbx/testsetViewModel';
import { RunDataProvider } from './runData';
import { RunViewProvider } from './runView';
import { TestsetViewProvider } from './testsetView';

export const PROMOTE_COMMANDS = {
  test: 'rbx.promoteTest',
  input: 'rbx.promoteInput',
} as const;

interface Wiring {
  readonly promoter: Promoter;
  readonly data: RunDataProvider;
  readonly active: ActiveProblem;
  readonly view: RunViewProvider;
  readonly testset: TestsetViewProvider;
}

/** The deepest discovered package containing `file`. */
async function packageContaining(data: RunDataProvider, file: string): Promise<string | undefined> {
  const roots = (await data.discovered())
    .map((pkg) => pkg.root)
    .filter((root) => {
      const relative = path.relative(root, file);
      return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative);
    })
    .sort((a, b) => b.length - a.length);
  return roots[0];
}

function withNewline(text: string): string {
  return text.endsWith('\n') ? text : `${text}\n`;
}

export function registerPromoteCommands(context: vscode.ExtensionContext, wiring: Wiring): void {
  const { promoter, data, active, view, testset } = wiring;

  /** A row of either view, by node or by the id a context menu passes. */
  const rowOf = (arg: unknown): TestcaseNode | TestsetTestcaseNode | undefined => {
    const node =
      typeof arg === 'object' && arg !== null && 'kind' in arg
        ? (arg as { kind: string })
        : (() => {
            const id = (arg as { rbxNodeId?: unknown } | undefined)?.rbxNodeId;
            return typeof id === 'string' ? (view.nodeById(id) ?? testset.nodeById(id)) : undefined;
          })();
    return node?.kind === 'testcase' || node?.kind === 'testsetTestcase'
      ? (node as TestcaseNode | TestsetTestcaseNode)
      : undefined;
  };

  const promoteRow = async (arg: unknown): Promise<void> => {
    const node = rowOf(arg);
    if (node === undefined) {
      void vscode.window.showInformationMessage('rbx: pick a test in the Run or Tests view first.');
      return;
    }
    const root = node.pkg.root;
    const entry = node.kind === 'testsetTestcase' ? node.entry : node.testcase.entry;
    const selector = node.kind === 'testsetTestcase' ? `${entry.group}/${entry.index}` : testSelector(entry);
    if (selector !== undefined) {
      await promoter.promote({ root, sources: [selector], label: selector });
      return;
    }
    // An ad-hoc input: no name to promote it by, only its file.
    if (node.kind !== 'testcase') {
      return;
    }
    let input: string;
    try {
      input = await fs.readFile(node.testcase.inputPath, 'utf8');
    } catch {
      void vscode.window.showInformationMessage('rbx: this test input is no longer on disk.');
      return;
    }
    const files = await scratchFiles({ 'input.in': input });
    await promoter.promote({ root, sources: [`file:${files['input.in']}`], label: 'this ad-hoc input' });
  };

  const promoteInput = async (arg: unknown): Promise<void> => {
    // From the explorer: the file clicked.
    if (arg instanceof vscode.Uri && arg.scheme === 'file') {
      const root = await packageContaining(data, arg.fsPath);
      const target = root ?? active.selected();
      if (target === undefined) {
        void vscode.window.showInformationMessage('rbx: no problem found to promote this into.');
        return;
      }
      await promoter.promote({
        root: target,
        sources: [`file:${arg.fsPath}`],
        label: path.basename(arg.fsPath),
      });
      return;
    }
    const editor = vscode.window.activeTextEditor;
    if (editor === undefined) {
      void vscode.window.showInformationMessage('rbx: open the input to promote in an editor first.');
      return;
    }
    const document = editor.document;
    const root =
      (document.uri.scheme === 'file' ? await packageContaining(data, document.uri.fsPath) : undefined) ??
      active.selected();
    if (root === undefined) {
      void vscode.window.showInformationMessage('rbx: no problem found to promote this into.');
      return;
    }
    // The file itself when it is saved and whole; else its text, from a copy.
    if (document.uri.scheme === 'file' && !document.isDirty && editor.selection.isEmpty) {
      await promoter.promote({
        root,
        sources: [`file:${document.uri.fsPath}`],
        label: path.basename(document.uri.fsPath),
      });
      return;
    }
    const text = editor.selection.isEmpty ? document.getText() : document.getText(editor.selection);
    if (text.trim() === '') {
      void vscode.window.showInformationMessage('rbx: this input is empty.');
      return;
    }
    const files = await scratchFiles({ 'input.in': withNewline(text) });
    await promoter.promote({
      root,
      sources: [`file:${files['input.in']}`],
      label: editor.selection.isEmpty ? 'this input' : 'the selected input',
    });
  };

  context.subscriptions.push(
    vscode.commands.registerCommand(PROMOTE_COMMANDS.test, promoteRow),
    vscode.commands.registerCommand(PROMOTE_COMMANDS.input, promoteInput),
  );
}
