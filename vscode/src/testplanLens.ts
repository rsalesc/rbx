/**
 * A lens row over every statement of a testplan (#910):
 * `Generate · Validate · Run · Promote`, each acting on that one test.
 *
 * A testplan is an rbx-format `.txt` generator script (manifest.ts marks it),
 * and a test in one is addressed as `<script>:<line>`, the line its statement
 * starts on -- which needs no built testset (testplan.ts).
 *
 * How each action runs follows design D3:
 *
 *   - **Generate** and **Validate** run `rbx testcases generate --json`
 *     headless. They are read-mostly and idempotent -- they rewrite one test's
 *     files under `build/`, exactly as `rbx build` would -- and what they
 *     produce is shown here: the files in the testcase panes, the validators'
 *     verdict in a notification.
 *   - **Run** (`rbx irun -t`) and **Promote** (`rbx testcases promote`) are
 *     dispatched to a terminal: one runs solutions, the other writes the
 *     package -- a new `.in`, the plan without that line, perhaps a new group
 *     in `problem.rbx.yml` -- and the user reads the outcome there.
 *
 * Every action saves the plan first: rbx reads it from disk, and a line number
 * counted in unsaved text would name another statement there.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { DeclaredIndex } from './declared';
import { Dispatcher, dispatchEnabled } from './dispatch';
import { log } from './log';
import { defaultManualGlob, failureMessage, groupNameError, manualGlobError, parseGroupList } from './rbx/promote';
import {
  Generated,
  PROMOTE,
  generateArgs,
  parseGenerated,
  promoteCommandLine,
  promoteListArgs,
  promoteNewManualArgs,
  promoteToGroupArgs,
  selector,
  statementAt,
  stemError,
  testplanStatements,
  validationSummary,
} from './rbx/testplan';
import { resolveRbx, run } from './rbxProcess';
import { TestcasePanes } from './testcasePanes';

const SETTING = 'rbx.testplanCodeLens';

/**
 * Generating may compile the generator, the validator and the main solution
 * first, which on a cold cache takes far longer than listing groups does.
 */
const GENERATE_TIMEOUT_MS = 5 * 60_000;
const LIST_TIMEOUT_MS = 60_000;

const COMMANDS = {
  generate: 'rbx.testplan.generate',
  validate: 'rbx.testplan.validate',
  run: 'rbx.testplan.run',
  promote: 'rbx.testplan.promote',
} as const;

export class TestplanLensProvider implements vscode.CodeLensProvider {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses: vscode.Event<void> = this.changed.event;

  constructor(private readonly declared: DeclaredIndex) {}

  provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
    if (!enabled() || this.declared.declarationFor(document.uri)?.asset.testplan !== true) {
      return [];
    }
    const lenses: vscode.CodeLens[] = [];
    const dispatch = dispatchEnabled();
    for (const statement of testplanStatements(document.getText())) {
      const range = new vscode.Range(statement.line - 1, 0, statement.line - 1, 0);
      const args = [document.uri, statement.line];
      lenses.push(
        new vscode.CodeLens(range, {
          title: '$(file) Generate',
          tooltip: 'Generate this test (and its answer) and open it',
          command: COMMANDS.generate,
          arguments: args,
        }),
        new vscode.CodeLens(range, {
          title: '$(check) Validate',
          tooltip: "Generate this test and run its group's validators on it",
          command: COMMANDS.validate,
          arguments: args,
        }),
      );
      if (dispatch) {
        lenses.push(
          new vscode.CodeLens(range, {
            title: '$(play) Run',
            tooltip: 'Run the solutions on this test with `rbx irun` in a terminal',
            command: COMMANDS.run,
            arguments: args,
          }),
        );
      }
      // A `@copy` is already a file; rbx refuses to promote one.
      if (statement.kind !== 'copy') {
        lenses.push(
          new vscode.CodeLens(range, {
            title: '$(arrow-up) Promote',
            tooltip: 'Move this test into a manual test group, as a file',
            command: COMMANDS.promote,
            arguments: args,
          }),
        );
      }
    }
    return lenses;
  }

  refresh(): void {
    this.changed.fire();
  }

  dispose(): void {
    this.changed.dispose();
  }
}

function enabled(): boolean {
  return vscode.workspace.getConfiguration().get<boolean>(SETTING, true);
}

/** One test of one testplan, resolved and saved to disk. */
interface Target {
  readonly root: string;
  /** `<script>:<line>`, relative to `root`. */
  readonly sel: string;
}

class TestplanActions {
  constructor(
    private readonly declared: DeclaredIndex,
    private readonly dispatcher: Dispatcher,
    private readonly panes: TestcasePanes,
  ) {}

  /**
   * The test a command names: `(uri, line)` from a lens, or nothing from the
   * palette or the context menu, which act on the statement at the cursor.
   */
  private async target(rawUri: unknown, rawLine: unknown): Promise<Target | undefined> {
    let uri: vscode.Uri | undefined;
    let line: number | undefined;
    if (rawUri instanceof vscode.Uri && typeof rawLine === 'number') {
      uri = rawUri;
      line = rawLine;
    } else {
      const editor = vscode.window.activeTextEditor;
      uri = rawUri instanceof vscode.Uri ? rawUri : editor?.document.uri;
      if (editor !== undefined && uri?.toString() === editor.document.uri.toString()) {
        const statements = testplanStatements(editor.document.getText());
        line = statementAt(statements, editor.selection.active.line + 1)?.line;
        if (line === undefined) {
          void vscode.window.showInformationMessage(
            'rbx: put the cursor on a test in the testplan first.',
          );
          return undefined;
        }
      }
    }
    if (uri === undefined || line === undefined) {
      return undefined;
    }
    const declared = this.declared.declarationFor(uri);
    if (declared?.asset.testplan !== true) {
      void vscode.window.showInformationMessage(
        'rbx: this file is not a .txt generator script declared in a problem.rbx.yml.',
      );
      return undefined;
    }
    const open = vscode.workspace.textDocuments.find(
      (document) => document.uri.toString() === uri.toString(),
    );
    if (open?.isDirty && !(await open.save())) {
      void vscode.window.showErrorMessage(
        'rbx: save the testplan first -- rbx reads it from disk.',
      );
      return undefined;
    }
    return { root: declared.root, sel: selector(path.relative(declared.root, uri.fsPath), line) };
  }

  async generate(rawUri: unknown, rawLine: unknown): Promise<void> {
    const target = await this.target(rawUri, rawLine);
    if (target === undefined) {
      return;
    }
    const generated = await this.runGenerate(target, { output: true }, `rbx: generating ${target.sel}…`);
    if (generated !== undefined) {
      await this.panes.openGenerated(generated.test, generated.input, generated.answer);
    }
  }

  async validate(rawUri: unknown, rawLine: unknown): Promise<void> {
    const target = await this.target(rawUri, rawLine);
    if (target === undefined) {
      return;
    }
    const generated = await this.runGenerate(
      target,
      { validate: true },
      `rbx: validating ${target.sel}…`,
    );
    if (generated === undefined) {
      return;
    }
    const summary = validationSummary(generated);
    const open = 'Open input';
    const choice = summary.ok
      ? await vscode.window.showInformationMessage(`rbx: ${summary.text}`, open)
      : await vscode.window.showErrorMessage(`rbx: ${summary.text}`, open);
    if (choice === open) {
      await this.panes.openGenerated(generated.test, generated.input, undefined);
    }
  }

  async run(rawUri: unknown, rawLine: unknown): Promise<void> {
    const target = await this.target(rawUri, rawLine);
    if (target !== undefined) {
      await this.dispatcher.dispatch({ command: 'irun', root: target.root, args: ['-t', target.sel] });
    }
  }

  async promote(rawUri: unknown, rawLine: unknown): Promise<void> {
    const target = await this.target(rawUri, rawLine);
    if (target === undefined) {
      return;
    }
    const listed = await this.headless(
      target.root,
      [...PROMOTE, ...promoteListArgs()],
      'rbx: listing the manual test groups…',
      LIST_TIMEOUT_MS,
    );
    if (listed === undefined) {
      return;
    }
    const groups = parseGroupList(listed.stdout)?.filter((group) => group.kind === 'manual');
    if (groups === undefined) {
      this.unreadable('promote --list-groups', listed.stdout);
      return;
    }

    const NEW = '$(add) New manual group…';
    const picked = await vscode.window.showQuickPick(
      [
        ...groups.map((group) => ({ label: group.name, description: group.path, group })),
        { label: NEW, description: 'a folder of .in files, added to problem.rbx.yml' },
      ],
      {
        title: `Promote ${target.sel}`,
        placeHolder: 'Into which manual test group? The line is removed from the testplan.',
        matchOnDescription: true,
      },
    );
    if (picked === undefined) {
      return;
    }

    let groupName: string;
    let glob: string | undefined;
    if ('group' in picked) {
      groupName = picked.group.name;
    } else {
      const existing = groups.map((group) => group.name);
      const name = await vscode.window.showInputBox({
        title: `Promote ${target.sel} into a new manual group`,
        prompt: 'The name of the new test group.',
        validateInput: (value) => groupNameError(value.trim(), existing),
      });
      if (name === undefined) {
        return;
      }
      groupName = name.trim();
      const typed = await vscode.window.showInputBox({
        title: `Promote ${target.sel} into ${groupName}`,
        prompt: 'Where the group keeps its inputs: a glob with a `*`, ending in `.in`.',
        value: defaultManualGlob(groupName),
        validateInput: (value) => manualGlobError(value.trim()),
      });
      if (typed === undefined) {
        return;
      }
      glob = typed.trim();
    }

    const stem = await vscode.window.showInputBox({
      title: `Promote ${target.sel} into ${groupName}`,
      prompt: 'The file name, without `.in`. Leave it empty for the next free one (000, 001, …).',
      validateInput: (value) => stemError(value.trim()),
    });
    if (stem === undefined) {
      return;
    }
    const args =
      glob === undefined
        ? promoteToGroupArgs(target.sel, groupName, stem.trim())
        : promoteNewManualArgs(target.sel, groupName, glob, stem.trim());

    if (!dispatchEnabled()) {
      const line = promoteCommandLine(args);
      const copy = 'Copy command';
      const choice = await vscode.window.showInformationMessage(
        `rbx: dispatching to the terminal is disabled (rbx.dispatch.enabled), so ${target.sel} ` +
          `was not promoted. Run \`${line}\` yourself.`,
        copy,
      );
      if (choice === copy) {
        await vscode.env.clipboard.writeText(line);
      }
      return;
    }
    await this.dispatcher.dispatch({ command: 'promote', root: target.root, args });
  }

  /**
   * `rbx testcases generate --json`, headless. Exit 1 with a parseable
   * document is a test that failed validation, which is an answer, not an
   * error; anything else that is not exit 0 is said as rbx said it.
   */
  private async runGenerate(
    target: Target,
    options: { output?: boolean; validate?: boolean },
    title: string,
  ): Promise<Generated | undefined> {
    const result = await this.headless(
      target.root,
      generateArgs(target.sel, options),
      title,
      GENERATE_TIMEOUT_MS,
      true,
    );
    if (result === undefined) {
      return undefined;
    }
    const generated = parseGenerated(result.stdout);
    if (generated !== undefined && (result.code === 0 || result.code === 1)) {
      return generated;
    }
    if (result.code !== 0) {
      this.failed(result.code, result.stderr);
      return undefined;
    }
    this.unreadable('generate', result.stdout);
    return undefined;
  }

  /**
   * Run `rbx <argv>` in `root`, behind a progress notification. Undefined,
   * having said why, when rbx could not be found or started -- or exited
   * non-zero, unless `allowFailure` leaves that for the caller to read.
   */
  private async headless(
    root: string,
    argv: string[],
    title: string,
    timeoutMs: number,
    allowFailure = false,
  ): Promise<{ code: number | null; stdout: string; stderr: string } | undefined> {
    const rbx = await resolveRbx(root);
    if (rbx === undefined) {
      void vscode.window.showErrorMessage(
        'Could not find rbx. Set "rbx.executable" to its full path, or open VS Code from a terminal.',
      );
      return undefined;
    }
    log(`${rbx} ${argv.join(' ')}`);
    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title },
      () => run(rbx, argv, root, timeoutMs),
    );
    if (result.spawnError !== undefined) {
      void vscode.window.showErrorMessage(`rbx: could not start rbx: ${result.spawnError.message}`);
      return undefined;
    }
    if (result.code !== 0) {
      log(`rbx ${argv.join(' ')} failed in ${root} (exit ${result.code ?? 'none'}): ${result.stderr.trim()}`);
      if (!allowFailure) {
        this.failed(result.code, result.stderr);
        return undefined;
      }
    }
    return result;
  }

  private failed(code: number | null, stderr: string): void {
    void vscode.window.showErrorMessage(`rbx: ${failureMessage(code, stderr)}`);
  }

  /** Exit 0 with output that is not the promised JSON: an rbx of another shape. */
  private unreadable(mode: string, stdout: string): void {
    log(`rbx testcases ${mode} printed something unexpected: ${stdout.trim()}`);
    void vscode.window.showErrorMessage(
      `rbx: could not read what \`rbx testcases ${mode}\` printed. ` +
        'Is rbx up to date? (See the rbx output channel.)',
    );
  }
}

export function registerTestplanLens(
  context: vscode.ExtensionContext,
  declared: DeclaredIndex,
  dispatcher: Dispatcher,
  panes: TestcasePanes,
): void {
  const provider = new TestplanLensProvider(declared);
  const actions = new TestplanActions(declared, dispatcher, panes);
  const syncContext = () => {
    // The context menu keys on this list, since a `when` cannot ask the index
    // whether a file is a testplan.
    void vscode.commands.executeCommand('setContext', 'rbx.testplanFiles', declared.testplanPaths());
  };
  syncContext();
  context.subscriptions.push(
    provider,
    vscode.languages.registerCodeLensProvider({ scheme: 'file' }, provider),
    declared.onDidChange(() => {
      provider.refresh();
      syncContext();
    }),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(SETTING) || event.affectsConfiguration('rbx.dispatch.enabled')) {
        provider.refresh();
      }
    }),
    vscode.commands.registerCommand(COMMANDS.generate, (uri: unknown, line: unknown) =>
      actions.generate(uri, line),
    ),
    vscode.commands.registerCommand(COMMANDS.validate, (uri: unknown, line: unknown) =>
      actions.validate(uri, line),
    ),
    vscode.commands.registerCommand(COMMANDS.run, (uri: unknown, line: unknown) =>
      actions.run(uri, line),
    ),
    vscode.commands.registerCommand(COMMANDS.promote, (uri: unknown, line: unknown) =>
      actions.promote(uri, line),
    ),
  );
}
