/**
 * Starting an ad-hoc run from the editor (#907), and following it to its result.
 *
 * Three entry points, each a dispatched `rbx irun` in a visible terminal
 * (design D3, as amended by #906):
 *
 *   - **Run Solutions on This Test…** on a testcase row of the Run or Tests
 *     view: `-t <group>/<index>`, with the row's own solution ticked.
 *   - **Run Solutions on This Input** on any text buffer, untitled included:
 *     the text goes to a temporary file and runs with `--input`, so no prompt
 *     is ever left waiting in the terminal.
 *   - **Run Solutions on a Generator Call…**: `-g`, prefilled from the
 *     selection or the line under the cursor.
 *
 * Every one asks which solutions in the same quick pick, adds `-cp` on an
 * interactive problem so the transcript is kept, and -- once the run it
 * started has a verdict -- opens the testcase panes on it, the way clicking
 * its row would.
 */
import * as fs from 'fs/promises';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';

import { ActiveProblem } from './activeProblem';
import { Dispatcher } from './dispatch';
import { log } from './log';
import {
  IrunCheck,
  IrunTarget,
  generatorCallFrom,
  irunArgs,
  isCommunication,
  solutionChoices,
  testSelector,
} from './rbx/irun';
import { manifestPath, packageLayout } from './rbx/layout';
import { parseManifest } from './rbx/manifest';
import { TestcaseNode } from './rbx/nodes';
import { readYamlFile } from './rbx/store';
import { TestsetTestcaseNode } from './rbx/testsetViewModel';
import { RunDataProvider } from './runData';
import { RunViewProvider } from './runView';
import { TestcasePanes } from './testcasePanes';
import { TestsetViewProvider } from './testsetView';

export const IRUN_COMMANDS = {
  test: 'rbx.irunTest',
  input: 'rbx.irunInput',
  generator: 'rbx.irunGenerator',
} as const;

/**
 * Opens the panes on the result of the ad-hoc run this extension just started.
 *
 * Three states, so a stale `.irun` from before the dispatch is never mistaken
 * for the new one: `armed` at dispatch, `started` once the new skeleton lands,
 * and back to idle once the panes are opened -- or once some other run starts,
 * which is what the user is looking at now.
 */
class AdhocFollower implements vscode.Disposable {
  private state: { readonly phase: 'armed' | 'started'; readonly root: string } | undefined;
  private readonly subscription: vscode.Disposable;

  constructor(
    private readonly data: RunDataProvider,
    private readonly panes: TestcasePanes,
  ) {
    this.subscription = data.onDidChange((change) => {
      const state = this.state;
      if (state === undefined || change.root !== state.root || change.plan === undefined) {
        return;
      }
      if (change.plan.started === 'run') {
        this.state = undefined;
        return;
      }
      if (change.plan.started === 'irun' && state.phase === 'armed') {
        this.state = { phase: 'started', root: state.root };
      }
      if (this.state?.phase === 'started' && change.plan.irun) {
        void this.openWhenJudged(state.root);
      }
    });
  }

  arm(root: string): void {
    this.state = { phase: 'armed', root };
  }

  private async openWhenJudged(root: string): Promise<void> {
    const pkg = packageLayout(root);
    const run = await this.data.report(pkg, 'irun');
    // The first solution in run order: the row's own, when that is how it
    // started, since the picker keeps manifest order and ticks that one.
    const first = run?.solutions[0];
    const group = first?.groups.find((candidate) => candidate.testcases.length > 0);
    const testcase = group?.testcases[0];
    if (first === undefined || group === undefined || testcase?.evaluation === undefined) {
      return; // Not judged yet; the next `.eval` event asks again.
    }
    if (this.state?.phase !== 'started' || this.state.root !== root) {
      return; // Opened already by an overlapping tick.
    }
    this.state = undefined;
    const node: TestcaseNode = { kind: 'testcase', pkg, run: first, group, testcase };
    await this.panes.open(node);
  }

  dispose(): void {
    this.subscription.dispose();
  }
}

/** The package a document belongs to: the deepest discovered root above it. */
export async function packageOf(
  data: RunDataProvider,
  document: vscode.TextDocument | undefined,
): Promise<string | undefined> {
  if (document === undefined || document.uri.scheme !== 'file') {
    return undefined;
  }
  const file = document.uri.fsPath;
  const roots = (await data.discovered())
    .map((pkg) => pkg.root)
    .filter((root) => {
      const relative = path.relative(root, file);
      return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative);
    })
    .sort((a, b) => b.length - a.length);
  return roots[0];
}

/** The problem to run in: the document's own, else the one the views show. */
export async function rootFor(
  data: RunDataProvider,
  active: ActiveProblem,
  document: vscode.TextDocument | undefined,
): Promise<string | undefined> {
  const root = (await packageOf(data, document)) ?? active.selected();
  if (root === undefined) {
    void vscode.window.showInformationMessage('rbx: no problem found to run this in.');
  }
  return root;
}

/** Ask which solutions; undefined if the user backed out or ticked none. */
async function pickSolutions(
  root: string,
  preselect: readonly string[],
): Promise<string[] | undefined> {
  const raw = await readYamlFile(manifestPath(packageLayout(root)));
  const choices = solutionChoices(raw === undefined ? [] : parseManifest(raw), preselect);
  if (choices.length === 0) {
    void vscode.window.showInformationMessage('rbx: this problem declares no solutions to run.');
    return undefined;
  }
  const picked = await vscode.window.showQuickPick(
    choices.map((choice) => ({
      label: choice.path,
      description: choice.expectation?.toLowerCase().replace(/_/g, ' '),
      picked: choice.picked,
    })),
    {
      canPickMany: true,
      title: 'Run which solutions?',
      placeHolder: 'Tick the solutions to run on this test',
    },
  );
  if (picked === undefined || picked.length === 0) {
    return undefined;
  }
  return picked.map((item) => item.label);
}

/** `-cp` on an interactive problem, so the transcript pane has something to show. */
async function rootArgsFor(root: string): Promise<string[]> {
  return isCommunication(await readYamlFile(manifestPath(packageLayout(root)))) ? ['-cp'] : [];
}

/** A fresh directory for one dispatch's typed files, which outlive the dispatch. */
export async function scratchFiles(
  files: Record<string, string>,
): Promise<Record<string, string>> {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'rbx-irun-'));
  const written: Record<string, string> = {};
  for (const [name, text] of Object.entries(files)) {
    const file = path.join(dir, name);
    await fs.writeFile(file, text);
    written[name] = file;
  }
  return written;
}

/**
 * What a row of either view runs on.
 *
 * A testcase with a name runs by it. The one that has none -- an ad-hoc run's
 * own input -- runs again from a copy of its files: `irun` replaces `.irun`
 * before it reads anything, so pointing it at the original would hand it a
 * file it has just deleted.
 */
async function targetOfRow(
  node: TestcaseNode | TestsetTestcaseNode,
): Promise<IrunTarget | undefined> {
  if (node.kind === 'testsetTestcase') {
    return { kind: 'test', selector: `${node.entry.group}/${node.entry.index}` };
  }
  // An ad-hoc row of `irun -t main/1` keeps that entry, so it runs by name too.
  const selector = testSelector(node.testcase.entry);
  if (selector !== undefined) {
    return { kind: 'test', selector };
  }
  const readOrUndefined = (file: string) => fs.readFile(file, 'utf8').catch(() => undefined);
  const input = await readOrUndefined(node.testcase.inputPath);
  if (input === undefined) {
    void vscode.window.showInformationMessage('rbx: this test input is no longer on disk.');
    return undefined;
  }
  const answer = await readOrUndefined(node.testcase.answerPath);
  const files = await scratchFiles(
    answer === undefined ? { 'input.in': input } : { 'input.in': input, 'answer.out': answer },
  );
  return { kind: 'input', input: files['input.in'], answer: files['answer.out'] };
}

/** How to judge typed input: against the main solution, another editor, or not at all. */
async function askCheck(
  current: vscode.TextDocument,
): Promise<{ readonly check: IrunCheck; readonly answer?: string } | undefined> {
  const others = vscode.workspace.textDocuments.filter(
    (document) =>
      document !== current &&
      (document.uri.scheme === 'file' || document.uri.scheme === 'untitled'),
  );
  type Item = vscode.QuickPickItem & { readonly mode: 'main' | 'editor' | 'none' };
  const items: Item[] = [
    {
      mode: 'main',
      label: "Check against the main solution's answer",
      description: 'default',
    },
    ...(others.length === 0
      ? []
      : [
          {
            mode: 'editor' as const,
            label: 'Check against an answer in another editor…',
          },
        ]),
    { mode: 'none', label: "Don't check, just run", description: '--no-check' },
  ];
  const choice = await vscode.window.showQuickPick(items, { title: 'Expected answer' });
  if (choice === undefined) {
    return undefined;
  }
  if (choice.mode === 'main') {
    return { check: 'answer' };
  }
  if (choice.mode === 'none') {
    return { check: 'none' };
  }
  const editor = await vscode.window.showQuickPick(
    others.map((document) => ({
      label: path.basename(document.fileName),
      description: document.uri.scheme === 'file' ? vscode.workspace.asRelativePath(document.uri) : 'unsaved',
      document,
    })),
    { title: 'Which editor holds the expected answer?' },
  );
  return editor === undefined ? undefined : { check: 'answer', answer: editor.document.getText() };
}

interface Wiring {
  readonly dispatcher: Dispatcher;
  readonly active: ActiveProblem;
  readonly data: RunDataProvider;
  readonly view: RunViewProvider;
  readonly testset: TestsetViewProvider;
  readonly panes: TestcasePanes;
}

export function registerIrunCommands(context: vscode.ExtensionContext, wiring: Wiring): void {
  const { dispatcher, active, data, view, testset, panes } = wiring;
  const follower = new AdhocFollower(data, panes);
  context.subscriptions.push(follower);

  const start = async (
    root: string,
    target: IrunTarget,
    preselect: readonly string[],
    check: IrunCheck = 'answer',
  ): Promise<void> => {
    const solutions = await pickSolutions(root, preselect);
    if (solutions === undefined) {
      return;
    }
    log(`Dispatching rbx irun (${target.kind}) in ${root}.`);
    follower.arm(root);
    await dispatcher.dispatch({
      command: 'irun',
      root,
      args: irunArgs(target, solutions, check),
      rootArgs: await rootArgsFor(root),
    });
  };

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

  context.subscriptions.push(
    vscode.commands.registerCommand(IRUN_COMMANDS.test, async (arg: unknown) => {
      const node = rowOf(arg);
      if (node === undefined) {
        void vscode.window.showInformationMessage('rbx: pick a test in the Run or Tests view first.');
        return;
      }
      const target = await targetOfRow(node);
      if (target === undefined) {
        return;
      }
      const preselect = node.kind === 'testcase' ? [node.run.solution.path] : [];
      await start(node.pkg.root, target, preselect);
    }),

    vscode.commands.registerCommand(IRUN_COMMANDS.input, async () => {
      const editor = vscode.window.activeTextEditor;
      if (editor === undefined) {
        void vscode.window.showInformationMessage('rbx: open the input to run in an editor first.');
        return;
      }
      // The selection when there is one: a sample pasted among notes runs on its own.
      const text = editor.selection.isEmpty
        ? editor.document.getText()
        : editor.document.getText(editor.selection);
      if (text.trim() === '') {
        void vscode.window.showInformationMessage('rbx: this input is empty.');
        return;
      }
      const root = await rootFor(data, active, editor.document);
      if (root === undefined) {
        return;
      }
      const judged = await askCheck(editor.document);
      if (judged === undefined) {
        return;
      }
      const files = await scratchFiles(
        judged.answer === undefined
          ? { 'input.in': withNewline(text) }
          : { 'input.in': withNewline(text), 'answer.out': withNewline(judged.answer) },
      );
      await start(
        root,
        { kind: 'input', input: files['input.in'], answer: files['answer.out'] },
        [],
        judged.check,
      );
    }),

    vscode.commands.registerCommand(IRUN_COMMANDS.generator, async () => {
      const editor = vscode.window.activeTextEditor;
      const suggested =
        editor === undefined
          ? undefined
          : editor.selection.isEmpty
            ? generatorCallFrom(editor.document.lineAt(editor.selection.active.line).text)
            : generatorCallFrom(editor.document.getText(editor.selection));
      const call = await vscode.window.showInputBox({
        title: 'Run solutions on a generator call',
        prompt: 'A generator declared in problem.rbx.yml, then its arguments',
        placeHolder: 'gen 10 20',
        value: suggested ?? '',
        validateInput: (value) => (value.trim() === '' ? 'Name a generator to call.' : undefined),
      });
      if (call === undefined) {
        return;
      }
      const root = await rootFor(data, active, editor?.document);
      if (root === undefined) {
        return;
      }
      await start(root, { kind: 'generator', call: call.trim() }, []);
    }),
  );
}

/** A file a line-reading solution can read to the end of. */
function withNewline(text: string): string {
  return text.endsWith('\n') ? text : `${text}\n`;
}
