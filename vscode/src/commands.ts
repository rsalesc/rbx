/**
 * Commands that open artifacts.
 *
 * Every *generated* file opens through the read-only `rbx:` scheme (see
 * artifactFs.ts), so it can never be edited by accident and each tab gets a
 * title that says which solution and testcase it belongs to. A solution's
 * source is the one thing here rbx did not generate: it opens as itself, on
 * the `file:` scheme, because editing it is the whole point of reaching it.
 */
import * as fs from 'fs/promises';
import * as vscode from 'vscode';

import { artifactUri } from './artifactFs';
import { solutionSourcePath } from './rbx/layout';
import { RunNode, TestcaseNode } from './rbx/nodes';
import { RunDataProvider } from './runData';
import { RunViewProvider } from './runView';

/** `sols/wa.cpp/main/1-gen-000` -- the display prefix shared by a testcase's tabs. */
function labelPrefix(node: TestcaseNode): string {
  return `${node.run.solution.path}/${node.group.name}/${node.testcase.stem}`;
}

function isTestcase(node: RunNode | undefined): node is TestcaseNode {
  return node?.kind === 'testcase';
}

async function firstExisting(paths: readonly string[]): Promise<string | undefined> {
  for (const candidate of paths) {
    try {
      await fs.access(candidate);
      return candidate;
    } catch {
      // Try the next candidate.
    }
  }
  return undefined;
}

async function openArtifact(
  node: TestcaseNode,
  paths: readonly string[],
  fileName: string,
  missingMessage: string,
): Promise<void> {
  const realPath = await firstExisting(paths);
  if (realPath === undefined) {
    vscode.window.showInformationMessage(missingMessage);
    return;
  }
  const uri = artifactUri(realPath, `${labelPrefix(node)}/${fileName}`);
  const document = await vscode.workspace.openTextDocument(uri);
  await vscode.window.showTextDocument(document, { preview: true });
}

export function registerCommands(
  context: vscode.ExtensionContext,
  view: RunViewProvider,
  data: RunDataProvider,
): void {
  /**
   * The seam where two invocation paths arrive in two shapes.
   *
   * A keyboard or double-click invocation goes through runView.ts, which
   * resolves the row itself and passes a real `RunNode`. A `webview/context`
   * menu item never does: VS Code invokes the command with the row's
   * `data-vscode-context` object, so all that arrives is the id inside it.
   */
  const resolve = (arg: unknown): RunNode | undefined => {
    if (typeof arg === 'object' && arg !== null && 'kind' in arg) {
      return arg as RunNode;
    }
    const id = (arg as { rbxNodeId?: unknown } | undefined)?.rbxNodeId;
    return typeof id === 'string' ? view.nodeById(id) : undefined;
  };

  const register = (id: string, handler: (node: RunNode | undefined) => unknown) => {
    context.subscriptions.push(
      vscode.commands.registerCommand(id, (arg: unknown) => handler(resolve(arg))),
    );
  };

  register('rbx.refresh', () => data.refresh());

  register('rbx.openSolution', async (node) => {
    if (node?.kind !== 'solution') {
      return;
    }
    const source = solutionSourcePath(node.pkg, node.run.solution.path);
    if ((await firstExisting([source])) === undefined) {
      // The skeleton names a solution `problem.rbx.yml` declares, so a missing
      // file means the package changed since the run, not that the row is bad.
      vscode.window.showInformationMessage(
        `No file at ${node.run.solution.path}. The package may have changed since this run.`,
      );
      return;
    }
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(source));
    // `preview: true` to match every other row in the view: arrowing down a
    // list of solutions reuses one tab instead of littering the tab bar.
    await vscode.window.showTextDocument(document, { preview: true });
  });

  register('rbx.openInput', async (node) => {
    if (!isTestcase(node)) {
      return;
    }
    await openArtifact(
      node,
      [node.testcase.inputPath],
      'input.in',
      'No input on disk for this testcase. Run `rbx build` first.',
    );
  });

  register('rbx.openAnswer', async (node) => {
    if (!isTestcase(node)) {
      return;
    }
    await openArtifact(
      node,
      [node.testcase.answerPath],
      'answer.out',
      'No expected answer on disk for this testcase.',
    );
  });

  register('rbx.openOutput', async (node) => {
    if (!isTestcase(node)) {
      return;
    }
    await openArtifact(
      node,
      [node.testcase.outputPath],
      'output.out',
      'This solution produced no output for this testcase.',
    );
  });

  register('rbx.openStderr', async (node) => {
    if (!isTestcase(node)) {
      return;
    }
    await openArtifact(
      node,
      node.testcase.stderrPaths,
      'stderr.err',
      'This solution wrote nothing to stderr for this testcase.',
    );
  });

  register('rbx.diffOutput', async (node) => {
    if (!isTestcase(node)) {
      return;
    }
    const output = await firstExisting([node.testcase.outputPath]);
    const answer = await firstExisting([node.testcase.answerPath]);
    if (output === undefined || answer === undefined) {
      // A TLE or RTE never produced a complete output; showing whichever half
      // exists is more useful than an empty diff.
      const available = output ?? answer;
      if (available === undefined) {
        vscode.window.showInformationMessage(
          'Nothing to compare: neither the output nor the expected answer is on disk.',
        );
        return;
      }
      await openArtifact(
        node,
        [available],
        available === output ? 'output.out' : 'answer.out',
        '',
      );
      return;
    }
    const prefix = labelPrefix(node);
    await vscode.commands.executeCommand(
      'vscode.diff',
      artifactUri(output, `${prefix}/output.out`),
      artifactUri(answer, `${prefix}/answer.out`),
      `${node.run.solution.path} · ${node.group.name}/${node.testcase.stem}`,
    );
  });

  register('rbx.copyPath', async (node) => {
    if (!isTestcase(node)) {
      return;
    }
    await vscode.env.clipboard.writeText(node.testcase.inputPath);
  });

  register('rbx.revealInExplorer', async (node) => {
    if (node?.kind !== 'package') {
      return;
    }
    await vscode.commands.executeCommand(
      'revealInExplorer',
      vscode.Uri.file(node.pkg.root),
    );
  });
}
