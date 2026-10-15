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
 *   - **Run** (`rbx irun -t`) is dispatched to a terminal, where the user
 *     reads the verdicts.
 *   - **Promote** is promoter.ts: rbx plans the promotion headless, and the
 *     plan opens for review before the editor applies it.
 *
 * Every action saves the plan first: rbx reads it from disk, and a line number
 * counted in unsaved text would name another statement there.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { DeclaredIndex } from './declared';
import { Dispatcher, dispatchEnabled } from './dispatch';
import { log } from './log';
import { Promoter } from './promoter';
import { failureMessage } from './rbx/promote';
import {
  Generated,
  StatementKind,
  generateArgs,
  parseGenerated,
  selector,
  statementAt,
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
      lenses.push(
        new vscode.CodeLens(range, {
          title: '$(arrow-up) Promote',
          tooltip:
            'Move this test into another group, or freeze it into a @copy where it is',
          command: COMMANDS.promote,
          arguments: args,
        }),
      );
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
  /** What the statement on that line is, if one starts there. */
  readonly kind?: StatementKind;
}

class TestplanActions {
  constructor(
    private readonly declared: DeclaredIndex,
    private readonly dispatcher: Dispatcher,
    private readonly panes: TestcasePanes,
    private readonly promoter: Promoter,
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
    const document = open ?? (await vscode.workspace.openTextDocument(uri));
    const statementLine = line;
    const kind = testplanStatements(document.getText()).find(
      (statement) => statement.line === statementLine,
    )?.kind;
    return {
      root: declared.root,
      sel: selector(path.relative(declared.root, uri.fsPath), line),
      kind,
    };
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
    if (target !== undefined) {
      await this.promoter.promote({ root: target.root, sources: [target.sel], label: target.sel });
    }
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
  promoter: Promoter,
): void {
  const provider = new TestplanLensProvider(declared);
  const actions = new TestplanActions(declared, dispatcher, panes, promoter);
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
