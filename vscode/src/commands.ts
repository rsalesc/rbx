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
import { TestcaseEntry } from './rbx/model';
import { Ext, solutionSourcePath, testArtifactPath, testsetFilePath } from './rbx/layout';
import { RunNode, TestcaseNode } from './rbx/nodes';
import { Channel, LABELS, labelPrefix as displayPrefix } from './rbx/panes';
import {
  TestsetNode,
  TestsetTestcaseNode,
  testsetNodeId,
} from './rbx/testsetViewModel';
import { RunDataProvider } from './runData';
import { RunViewProvider } from './runView';
import { TestcasePanes } from './testcasePanes';
import { TestsetPanelRequest, TestsetViewProvider } from './testsetView';
import { openVisualization, openVisualizationExternally } from './visualizationPanel';
import { runVisualizer } from './visualize';
import { solutionVisualizationDest, testcaseInputPath } from './rbx/visualizeRun';

/** `sols/wa.cpp/main/1-gen-000` -- the display prefix shared by a testcase's tabs. */
function labelPrefix(node: TestcaseNode): string {
  return displayPrefix(node.run.solution.path, node.group.name, node.testcase.stem);
}

function isTestcase(node: Node | undefined): node is TestcaseNode {
  return node?.kind === 'testcase';
}

/**
 * Everything a command in this file can be invoked on.
 *
 * Two views, two node shapes, one set of commands wherever the two views ask
 * for the same thing. `rbx.openGeneratorScript` and `rbx.openCopiedFrom` are
 * exactly that case: where a testcase came from is the same fact whether it was
 * reached through a run or through a build, and a second pair of commands would
 * be a second pair to keep in step.
 */
type Node = RunNode | TestsetNode;

function isBuiltTestcase(node: Node | undefined): node is TestsetTestcaseNode {
  return node?.kind === 'testsetTestcase';
}

/**
 * The `GenerationTestcaseEntry` behind a row, from either view, with the
 * package it belongs to.
 *
 * The manifest dumps the entries the skeleton embeds verbatim (design D2), so
 * the two views hold the very same record and the commands below need nothing
 * else to tell them apart.
 */
function provenance(node: Node | undefined): { root: string; entry: TestcaseEntry } | undefined {
  if (isTestcase(node)) {
    return { root: node.pkg.root, entry: node.testcase.entry };
  }
  if (isBuiltTestcase(node)) {
    return { root: node.pkg.root, entry: node.entry };
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
  // Optional so the extension can be wired up without the Tests view; the
  // commands it owns then report that there is nothing to act on rather than
  // failing to register, which would leave dead entries in the palette.
  testset?: TestsetViewProvider,
): void {
  /**
   * The seam where two invocation paths arrive in two shapes.
   *
   * A keyboard or double-click invocation goes through runView.ts, which
   * resolves the row itself and passes a real `RunNode`. A `webview/context`
   * menu item never does: VS Code invokes the command with the row's
   * `data-vscode-context` object, so all that arrives is the id inside it.
   */
  const resolve = (arg: unknown): Node | undefined => {
    if (typeof arg === 'object' && arg !== null && 'kind' in arg) {
      return arg as Node;
    }
    const id = (arg as { rbxNodeId?: unknown } | undefined)?.rbxNodeId;
    if (typeof id !== 'string') {
      return undefined;
    }
    // The Run view first, because its ids are rooted at the package and cannot
    // collide with a bare group name. A row from either view resolves through
    // the map its own host rebuilt on the last post.
    return view.nodeById(id) ?? testset?.nodeById(id);
  };

  const register = (id: string, handler: (node: Node | undefined) => unknown) => {
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
    const source = provenance(node);
    const entry = source?.entry;
    if (source === undefined || entry?.generatorScript === undefined) {
      return;
    }
    // Relative to the package, the way rbx records every other path in the
    // skeleton; `generatorScript` is a script in the package, not an artifact.
    await openSource(
      path.resolve(source.root, entry.generatorScript),
      entry.generatorScript,
      // rbx counts a script's lines from 1, the editor from 0.
      Math.max(0, (entry.generatorScriptLine ?? 1) - 1),
    );
  });

  register('rbx.openCopiedFrom', async (node) => {
    const source = provenance(node);
    const copiedFrom = source?.entry.copiedFrom;
    if (source === undefined || copiedFrom === undefined) {
      return;
    }
    // The manual testcase the setter wrote, so it opens as itself on `file:`
    // rather than through the read-only `rbx:` scheme: rbx did not generate it
    // and fixing a bad manual test means editing it.
    await openSource(path.resolve(source.root, copiedFrom), copiedFrom, 0);
  });

  // --- The Tests view -------------------------------------------------------
  //
  // A built testcase is not a run of one: there is no output, no stderr and no
  // log, so nothing here is a channel. What it has instead is provenance, an
  // answer beside its input, and -- when a visualizer ran -- a picture.

  register('rbx.openBuiltTestcase', async (node) => {
    if (!isBuiltTestcase(node)) {
      return;
    }
    await panes.openBuilt(node.pkg, node.group, node.stem);
  });

  // One registration per channel, following the run view's channel commands:
  // these reach the palette, and "rbx: Open Answer Visualization" is something
  // a user can find by typing what they want.
  const visualizationChannels: readonly (readonly [
    string,
    'input' | 'output',
    string,
  ])[] = [
    ['rbx.openTestVisualization', 'input', 'input'],
    ['rbx.openTestAnswerVisualization', 'output', 'answer'],
  ];
  for (const [id, channel, name] of visualizationChannels) {
    register(id, async (node) => {
      if (!isBuiltTestcase(node)) {
        return;
      }
      const relative = node.test?.visualization?.[channel];
      if (relative === undefined) {
        vscode.window.showInformationMessage(
          `No ${name} visualization was built for this testcase.`,
        );
        return;
      }
      const realPath = await firstExisting([testsetFilePath(node.pkg, relative)]);
      if (realPath === undefined) {
        vscode.window.showInformationMessage(
          `No file at ${relative}. Run \`rbx build --visualize\` again to rebuild the visualizations.`,
        );
        return;
      }
      // `Visualizer.extension` is a free string, so this may be an SVG, an HTML
      // page or something with no viewer at all. `openVisualization` owns that
      // fork: HTML gets framed in a panel, everything else goes to the editor.
      await openVisualization(context, {
        root: node.pkg.root,
        filePath: realPath,
        label: `${node.group}/${node.stem} (${name})`,
      });
    });
  }

  // The two on-demand visualizers -- `v` and `V` in `rbx ui`.
  //
  // These are the only commands in the extension that *run* rbx rather than
  // reading what it left behind (design D1 of the visualize design). The pair
  // above opens a visualization `rbx build --visualize` already wrote; these
  // produce one now, which is the only way to reach a solution's output, since
  // no build flag visualizes those.
  register('rbx.visualizeTest', async (node) => {
    // Reachable from both views: the input is the same file either way, and it
    // is what selects which visualizer applies.
    if (isBuiltTestcase(node)) {
      await runVisualizer(
        context,
        node.pkg.root,
        {
          kind: 'input',
          inputPath: testcaseInputPath(node.pkg, node.group, node.stem),
        },
        `${node.group}/${node.stem} (input)`,
      );
      return;
    }
    if (isTestcase(node)) {
      await runVisualizer(
        context,
        node.pkg.root,
        { kind: 'input', inputPath: node.testcase.inputPath },
        `${node.group.name}/${node.testcase.stem} (input)`,
      );
    }
  });

  register('rbx.visualizeSolutionOutput', async (node) => {
    // Run view only: there is no solution, and so no output, in the Tests view.
    if (!isTestcase(node)) {
      vscode.window.showInformationMessage(
        'Visualizing an output needs a solution -- open a testcase under one in the Run view.',
      );
      return;
    }
    await runVisualizer(
      context,
      node.pkg.root,
      {
        kind: 'output',
        inputPath: node.testcase.inputPath,
        outputPath: node.testcase.outputPath,
        answerPath: node.testcase.answerPath,
        // Written under the build directory rather than beside the run
        // artifact, so the `.rbx` watcher never sees it -- see
        // `solutionVisualizationDest`.
        dest: solutionVisualizationDest(
          node.pkg,
          node.run.solution.index,
          node.group.name,
          node.testcase.stem,
        ),
      },
      `${node.run.solution.path}/${node.group.name}/${node.testcase.stem} (output)`,
    );
  });

  // Not a row command: it acts on the visualization panel that has focus, which
  // is why it takes no node and why its `when` clause is `activeWebviewPanelId`.
  // Registered directly rather than through `register`, whose whole job is to
  // resolve an argument this command does not take.
  context.subscriptions.push(
    vscode.commands.registerCommand('rbx.openVisualizationExternally', () =>
      openVisualizationExternally(),
    ),
  );

  register('rbx.copyTestPath', async (node) => {
    if (!isBuiltTestcase(node)) {
      return;
    }
    await vscode.env.clipboard.writeText(
      testArtifactPath(node.pkg, node.group, node.stem, Ext.Input),
    );
  });

  register('rbx.revealTestInExplorer', async (node) => {
    if (!isBuiltTestcase(node)) {
      return;
    }
    await vscode.commands.executeCommand(
      'revealInExplorer',
      vscode.Uri.file(testArtifactPath(node.pkg, node.group, node.stem, Ext.Input)),
    );
  });

  // One registration per tab rather than one command asking which: these are
  // palette entries, and "rbx: Show Constraint Coverage" is something a user can
  // find by typing what they want. The same argument the channel commands make.
  const tabs: readonly (readonly [string, TestsetPanelRequest['tab']])[] = [
    ['rbx.openTestsetPanel', 'gallery'],
    ['rbx.openTestsetCoverage', 'coverage'],
    ['rbx.openTestsetStats', 'stats'],
  ];
  for (const [id, tab] of tabs) {
    register(id, (node) => {
      if (testset === undefined) {
        vscode.window.showInformationMessage('The rbx Tests view is not available.');
        return;
      }
      // A row when the ask came from one, and the current selection when it came
      // from the palette -- where there is no row to name and the view is
      // already showing what the user means.
      const selection = testset.selection();
      const nodeId =
        node?.kind === 'testsetGroup' || node?.kind === 'testsetTestcase'
          ? testsetNodeId(node)
          : // A testcase names itself; a group's row id *is* its name, which is
            // the whole of what a coverage or stats tab needs to open on.
            (selection?.testId ?? selection?.group);
      testset.requestPanel(tab, nodeId);
    });
  }

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
