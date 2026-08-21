/**
 * Commands that open artifacts.
 *
 * Every *generated* file opens through the read-only `rbx:` scheme (see
 * artifactFs.ts), so it can never be edited by accident and each tab gets a
 * title that says which solution and testcase it belongs to. A solution's
 * source is the one thing here rbx did not generate: it opens as itself, on
 * the `file:` scheme, because editing it is the whole point of reaching it.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { ActiveProblem } from './activeProblem';
import { artifactUri, firstExisting } from './artifactFs';
import { solutionSourcePath } from './rbx/layout';
import { RunNode, TestcaseNode } from './rbx/nodes';
import { Channel, LABELS, labelPrefix as displayPrefix } from './rbx/panes';
import { RunDataProvider } from './runData';
import { RunViewProvider } from './runView';
import { TestcasePanes } from './testcasePanes';

/** `sols/wa.cpp/main/1-gen-000` -- the display prefix shared by a testcase's tabs. */
function labelPrefix(node: TestcaseNode): string {
  return displayPrefix(node.run.solution.path, node.group.name, node.testcase.stem);
}

function isTestcase(node: RunNode | undefined): node is TestcaseNode {
  return node?.kind === 'testcase';
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

/**
 * Open a first-party file -- one rbx did not generate -- at `line`.
 *
 * On the `file:` scheme rather than through `rbx:`, and that is the whole
 * distinction this helper marks: a solution, a generator script and a manual
 * testcase are all things the setter wrote, and the point of reaching one is to
 * edit it. Generated artifacts stay read-only.
 *
 * `declared` is the path as rbx recorded it, which is what a missing-file
 * message has to quote: the absolute path resolved against the package root
 * would name a location the setter never typed.
 */
async function openSource(
  realPath: string,
  declared: string,
  line: number,
): Promise<void> {
  if ((await firstExisting([realPath])) === undefined) {
    // The skeleton names files `problem.rbx.yml` declared, so a missing one
    // means the package changed since the run, not that the row is bad.
    vscode.window.showInformationMessage(
      `No file at ${declared}. The package may have changed since this run.`,
    );
    return;
  }
  const document = await vscode.workspace.openTextDocument(vscode.Uri.file(realPath));
  const position = new vscode.Position(line, 0);
  // `preview: true` to match every other row in the view: arrowing down a list
  // of solutions reuses one tab instead of littering the tab bar.
  await vscode.window.showTextDocument(document, {
    preview: true,
    selection: new vscode.Range(position, position),
  });
}

export function registerCommands(
  context: vscode.ExtensionContext,
  view: RunViewProvider,
  data: RunDataProvider,
  active: ActiveProblem,
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

  // The manual escape hatch, so it has to cover everything a watcher can miss
  // -- the runs *and* the problem list. Rebuilding only the runs would re-post
  // the stale choices, leaving the button unable to fix the one thing a user
  // reaches for it to fix. `data` first: `active.refresh()` reads the roots it
  // rediscovers.
  register('rbx.refresh', () => data.refresh().then(() => active.refresh()));

  register('rbx.openSolution', async (node) => {
    // Three row kinds reach the same file, and the only thing that differs is
    // where in it to land: a solution row and a finding row open at the top,
    // and a warning line under a finding opens at the line the compiler named.
    // One command rather than two, because "open this solution's source" is one
    // thing to ask for however the reader got to the row.
    const target = ((): { path: string; declared: string; line: number } | undefined => {
      switch (node?.kind) {
        case 'solution':
          return {
            path: solutionSourcePath(node.pkg, node.run.solution.path),
            declared: node.run.solution.path,
            line: 0,
          };
        case 'finding':
          return { path: node.finding.sourcePath, declared: node.finding.entry.path, line: 0 };
        case 'findingWarning':
          return {
            path: node.finding.sourcePath,
            declared: node.finding.entry.path,
            // Compilers count lines from 1 and VS Code counts from 0.
            line: Math.max(0, node.warning.line - 1),
          };
        default:
          return undefined;
      }
    })();
    if (target === undefined) {
      return;
    }
    await openSource(target.path, target.declared, target.line);
  });

  register('rbx.openInput', async (node) => {
    if (!isTestcase(node)) {
      return;
    }
    await openArtifact(
      node,
      [node.testcase.inputPath],
      LABELS.input,
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
      LABELS.answer,
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
      LABELS.output,
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
      LABELS.stderr,
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
        available === output ? LABELS.output : LABELS.answer,
        '',
      );
      return;
    }
    const prefix = labelPrefix(node);
    await vscode.commands.executeCommand(
      'vscode.diff',
      artifactUri(output, `${prefix}/${LABELS.output}`),
      artifactUri(answer, `${prefix}/${LABELS.answer}`),
      `${node.run.solution.path} · ${node.group.name}/${node.testcase.stem}`,
    );
  });

  register('rbx.openCompileLog', async (node) => {
    if (node?.kind !== 'finding' && node?.kind !== 'findingWarning') {
      return;
    }
    const finding = node.finding;
    const realPath = await firstExisting([finding.logPath]);
    if (realPath === undefined) {
      vscode.window.showInformationMessage(
        'The compiler output for this solution is no longer on disk. Run `rbx run` again.',
      );
      return;
    }
    // Through the `rbx:` scheme like every other artifact: read-only, streamed
    // rather than held as a string -- a compile error can be a very long file --
    // and titled after the solution it belongs to.
    const uri = artifactUri(realPath, `${finding.entry.path}/compile.log`);
    const document = await vscode.workspace.openTextDocument(uri);
    await vscode.window.showTextDocument(document, { preview: true });
  });

  // The panes outlive any one command, because the channel they are on is
  // sticky across testcases -- so the state lives in one object the four
  // commands below share, rather than in each of them.
  const panes = new TestcasePanes();

  register('rbx.openTestcase', async (node) => {
    if (!isTestcase(node)) {
      return;
    }
    await panes.open(node);
  });

  // One registration per channel rather than a single command taking an
  // argument: these are palette entries, and "rbx: Show Stderr" is something a
  // user can find by typing what they want, while a command that asks which
  // channel in a second step is not.
  const channels: readonly (readonly [string, Channel])[] = [
    ['rbx.showOutput', 'out'],
    ['rbx.showStderr', 'err'],
    ['rbx.showLog', 'log'],
  ];
  for (const [id, channel] of channels) {
    // A node is passed when the card's button was clicked, and absent from the
    // palette -- where the panes act on whatever they are already showing.
    register(id, async (node) => {
      await panes.setChannel(channel, isTestcase(node) ? node : undefined);
    });
  }

  register('rbx.openGeneratorScript', async (node) => {
    if (!isTestcase(node)) {
      return;
    }
    const entry = node.testcase.entry;
    if (entry.generatorScript === undefined) {
      return;
    }
    // Relative to the package, the way rbx records every other path in the
    // skeleton; `generatorScript` is a script in the package, not an artifact.
    await openSource(
      path.resolve(node.pkg.root, entry.generatorScript),
      entry.generatorScript,
      // rbx counts a script's lines from 1, the editor from 0.
      Math.max(0, (entry.generatorScriptLine ?? 1) - 1),
    );
  });

  register('rbx.openCopiedFrom', async (node) => {
    if (!isTestcase(node)) {
      return;
    }
    const copiedFrom = node.testcase.entry.copiedFrom;
    if (copiedFrom === undefined) {
      return;
    }
    // The manual testcase the setter wrote, so it opens as itself on `file:`
    // rather than through the read-only `rbx:` scheme: rbx did not generate it
    // and fixing a bad manual test means editing it.
    await openSource(path.resolve(node.pkg.root, copiedFrom), copiedFrom, 0);
  });

  register('rbx.copyPath', async (node) => {
    if (!isTestcase(node)) {
      return;
    }
    await vscode.env.clipboard.writeText(node.testcase.inputPath);
  });

  // Not registered through `register`: this one takes no row.
  //
  // It used to hang off the package row, and when that row went away its
  // `webview/context` entry became unreachable -- no row emits
  // `webviewSection == 'rbx.package'` any more. Rather than re-point it at a
  // row that means something else, it is now a palette command over the *view*:
  // the view shows one problem, so "reveal the package" has exactly one answer
  // without a row to ask.
  context.subscriptions.push(
    vscode.commands.registerCommand('rbx.revealInExplorer', async () => {
      const root = active.selected();
      if (root === undefined) {
        vscode.window.showInformationMessage('No rbx problem found in this workspace.');
        return;
      }
      await vscode.commands.executeCommand('revealInExplorer', vscode.Uri.file(root));
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('rbx.selectProblem', async () => {
      const problems = active.problems();
      if (problems.length === 0) {
        void vscode.window.showInformationMessage('No rbx problem found in this workspace.');
        return;
      }
      // The palette twin of the dropdown, and the only way to switch problems
      // when the dropdown is hidden -- `renderSelector` draws nothing for a
      // single problem, and a keyboard user may never open the sidebar at all.
      const picked = await vscode.window.showQuickPick(
        problems.map((problem) => ({
          label: problem.label,
          description: problem.group,
          detail: problem.root,
          root: problem.root,
        })),
        { placeHolder: 'Show which problem in the Run view?' },
      );
      if (picked !== undefined) {
        active.select(picked.root);
      }
    }),
  );
}
