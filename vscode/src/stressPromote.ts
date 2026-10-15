/**
 * Promote on a stress finding (#908, design S6): `rbx.stress.promote`, and the
 * Accept / Discard of the proposal it opens.
 *
 * Two kinds of group take a finding, and they are promoted two ways:
 *
 *   - **A script group** gets the finding's generator call appended, which
 *     keeps the test reproducible. The line is the user's to word, so it is
 *     proposed rather than written: `add-finding --dry-run --json` -- read-only,
 *     so it may run headless (D3) -- says what the script would become, and
 *     that opens as an editable diff against the real script. Accept applies
 *     the right side through the editor, so it lands on the undo stack like
 *     any other edit; Discard drops it.
 *   - **A manual group**, or a group that does not exist yet, gets the
 *     finding's input copied, or the group created. Those write, so they are
 *     dispatched to the terminal like every other rbx command that changes
 *     something, and the user reads the outcome there.
 *
 * Which groups exist comes from `add-finding --list-groups --json`, also
 * headless and read-only, so the picker offers exactly what rbx would accept.
 * Nothing here decides what goes into a group: that is rbx's, and the pure
 * half (argv, parsing, name checks) is rbx/promote.ts.
 */
import * as fs from 'fs/promises';
import * as path from 'path';
import * as vscode from 'vscode';

import { Dispatcher, dispatchEnabled } from './dispatch';
import { log } from './log';
import { PROPOSED_SCHEME, ProposedFileSystemProvider } from './proposedFs';
import { TASK_TYPE } from './rbx/dispatch';
import {
  ADD_FINDING,
  PickRow,
  PromoteGroup,
  addToGroupArgs,
  commandLine,
  defaultManualGlob,
  defaultScriptPath,
  dryRunArgs,
  failureMessage,
  groupNameError,
  listGroupsArgs,
  manualGlobError,
  newManualArgs,
  newScriptArgs,
  newScriptPathError,
  parseDryRun,
  parseGroupList,
  pickRows,
  proposalTitle,
  sameText,
  scriptGroupName,
} from './rbx/promote';
import { resolveRbx, run } from './rbxProcess';
import { findingGone } from './stressCommands';
import type { PromoteArgs, StressViewProvider } from './stressView';

/**
 * How long a headless `add-finding` may take. Generous: it is quick once rbx
 * is warm, but the first command in a fresh environment pays for imports and
 * cache setup, and timing that out would read as a broken button.
 */
const HEADLESS_TIMEOUT_MS = 60_000;

/** A script group's proposal, open in a diff. */
interface Proposal {
  /** The right side, under `rbx-proposed:`. */
  readonly uri: vscode.Uri;
  /** The generator script, absolute. */
  readonly file: string;
  /** The script as the dry run read it; Accept refuses if it moved since. */
  readonly before: string;
  readonly root: string;
  readonly k: number;
  readonly group: string;
  /** The session the finding came from, for the view's badge. */
  readonly startedAt?: string;
  /** The row's own session, as the view passed it, for Promote again. */
  readonly session?: string;
}

function asPromoteArgs(raw: unknown): PromoteArgs | undefined {
  if (typeof raw !== 'object' || raw === null) {
    return undefined;
  }
  const { root, finding, session } = raw as Record<string, unknown>;
  if (typeof root !== 'string' || typeof finding !== 'number') {
    return undefined;
  }
  return { root, finding, ...(typeof session === 'string' ? { session } : {}) };
}

/** Whether `task` is a dispatched `add-finding` with exactly these args in `root`. */
function isAddFinding(task: vscode.Task, root: string, args: readonly string[]): boolean {
  const definition = task.definition as { type?: unknown; command?: unknown; cwd?: unknown; args?: unknown };
  return (
    definition.type === TASK_TYPE &&
    definition.command === 'add-finding' &&
    definition.cwd === root &&
    JSON.stringify(definition.args ?? []) === JSON.stringify(args)
  );
}

export class StressPromoter implements vscode.Disposable {
  /** Open proposals, by the right side's URI. */
  private readonly proposals = new Map<string, Proposal>();
  /** Tells two proposals for the same script apart. */
  private serial = 0;
  private readonly disposables: vscode.Disposable[] = [];

  constructor(
    private readonly stress: StressViewProvider,
    private readonly dispatcher: Dispatcher,
    private readonly proposed: ProposedFileSystemProvider,
  ) {
    this.disposables.push(
      // A proposal is only reachable through its editor; once that is gone,
      // so is any way to Accept it.
      vscode.workspace.onDidCloseTextDocument((document) => {
        if (document.uri.scheme === PROPOSED_SCHEME) {
          this.forget(document.uri);
        }
      }),
    );
  }

  dispose(): void {
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
  }

  /** `rbx.stress.promote`. */
  async promote(raw: unknown): Promise<void> {
    const args = asPromoteArgs(raw);
    if (args === undefined) {
      return;
    }
    const { root } = args;
    const manifest = await this.stress.sessionFor(root, args.session);
    const finding = manifest?.findings.find((each) => each.index === args.finding);
    if (manifest === undefined || finding === undefined) {
      findingGone(args.finding);
      return;
    }
    const k = finding.index;
    const startedAt = manifest.startedAt;

    const listed = await this.headless(root, listGroupsArgs(), 'rbx: listing the test groups…');
    if (listed === undefined) {
      return;
    }
    const groups = parseGroupList(listed);
    if (groups === undefined) {
      this.unreadable('--list-groups', listed);
      return;
    }

    const row = await this.pick(k, groups);
    if (row === undefined) {
      return;
    }
    const existing = groups.map((group) => group.name);
    switch (row.kind) {
      case 'group':
        if (row.group.kind === 'script') {
          await this.propose(root, k, row.group, startedAt, args.session);
        } else {
          await this.dispatchAdd(root, addToGroupArgs(k, row.group.name), k, startedAt, row.group.name);
        }
        return;
      case 'new-script': {
        const script = await vscode.window.showInputBox({
          title: `Promote finding #${k} into a new script group`,
          prompt:
            'The new .txt generator script, relative to the problem. ' +
            'The group is named after the file.',
          value: defaultScriptPath(existing),
          validateInput: (value) => newScriptPathError(value.trim(), existing),
        });
        if (script === undefined) {
          return;
        }
        const scriptPath = script.trim();
        await this.dispatchAdd(
          root,
          newScriptArgs(k, scriptPath),
          k,
          startedAt,
          scriptGroupName(scriptPath),
        );
        return;
      }
      case 'new-manual': {
        const name = await vscode.window.showInputBox({
          title: `Promote finding #${k} into a new manual group`,
          prompt: 'The name of the new test group.',
          validateInput: (value) => groupNameError(value.trim(), existing),
        });
        if (name === undefined) {
          return;
        }
        const groupName = name.trim();
        const glob = await vscode.window.showInputBox({
          title: `Promote finding #${k} into ${groupName}`,
          prompt: 'Where the group keeps its inputs: a glob with a `*`, ending in `.in`.',
          value: defaultManualGlob(groupName),
          validateInput: (value) => manualGlobError(value.trim()),
        });
        if (glob === undefined) {
          return;
        }
        await this.dispatchAdd(root, newManualArgs(k, groupName, glob.trim()), k, startedAt, groupName);
        return;
      }
    }
  }

  /** `rbx.proposal.accept`, from the proposal's editor title. */
  async accept(raw: unknown): Promise<void> {
    const proposal = this.proposalOf(raw);
    if (proposal === undefined) {
      void vscode.window.showInformationMessage(
        'rbx: this proposal was already accepted or discarded.',
      );
      return;
    }
    const document = vscode.workspace.textDocuments.find(
      (each) => each.uri.toString() === proposal.uri.toString(),
    );
    // Saved first, though it only ever goes to memory: closing a dirty
    // editor below would otherwise ask whether to save a file nobody sees.
    if (document?.isDirty) {
      await document.save();
    }
    const text = document?.getText() ?? this.proposed.text(proposal.uri);
    if (text === undefined) {
      return;
    }

    const realUri = vscode.Uri.file(proposal.file);
    // Both the disk and the editor's copy, which may hold unsaved edits the
    // replacement below would silently overwrite.
    let onDisk: string | undefined;
    try {
      onDisk = await fs.readFile(proposal.file, 'utf8');
    } catch {
      onDisk = undefined;
    }
    let real: vscode.TextDocument | undefined;
    try {
      real = await vscode.workspace.openTextDocument(realUri);
    } catch {
      real = undefined;
    }
    if (
      onDisk === undefined ||
      real === undefined ||
      !sameText(onDisk, proposal.before) ||
      !sameText(real.getText(), proposal.before)
    ) {
      await this.refuseStale(proposal);
      return;
    }

    // Through the editor rather than onto the disk, so the change is one undo
    // away and an open editor of the script never disagrees with the file.
    const edit = new vscode.WorkspaceEdit();
    edit.replace(
      realUri,
      new vscode.Range(real.positionAt(0), real.positionAt(real.getText().length)),
      text,
    );
    if (!(await vscode.workspace.applyEdit(edit)) || !(await real.save())) {
      void vscode.window.showErrorMessage(
        `rbx: could not write ${path.basename(proposal.file)}; the proposal is still open.`,
      );
      return;
    }
    await this.close(proposal);
    this.stress.markPromoted(proposal.root, proposal.startedAt, proposal.k, proposal.group);
    const open = 'Open script';
    const choice = await vscode.window.showInformationMessage(
      `rbx: added finding #${proposal.k} to ${proposal.group}.`,
      open,
    );
    if (choice === open) {
      await vscode.window.showTextDocument(realUri, { preview: false });
    }
  }

  /** `rbx.proposal.discard`, from the proposal's editor title. */
  async discard(raw: unknown): Promise<void> {
    const proposal = this.proposalOf(raw);
    if (proposal !== undefined) {
      await this.close(proposal);
    }
  }

  // --- script groups --------------------------------------------------------

  private async propose(
    root: string,
    k: number,
    group: PromoteGroup,
    startedAt: string | undefined,
    session: string | undefined,
  ): Promise<void> {
    const stdout = await this.headless(
      root,
      dryRunArgs(k, group.name),
      `rbx: proposing finding #${k} for ${group.name}…`,
    );
    if (stdout === undefined) {
      return;
    }
    const dry = parseDryRun(stdout);
    if (dry === undefined) {
      this.unreadable('--dry-run', stdout);
      return;
    }
    if (sameText(dry.after, dry.before)) {
      // rbx skips a call the script already has, so there is nothing to
      // review -- but the finding is in the group, which the badge should say.
      this.stress.markPromoted(root, startedAt, k, group.name);
      void vscode.window.showInformationMessage(`rbx: finding #${k} is already in ${group.name}.`);
      return;
    }

    const relative = path.relative(root, dry.file);
    const label = relative.startsWith('..') || path.isAbsolute(relative)
      ? path.basename(dry.file)
      : relative.split(path.sep).join('/');
    const uri = vscode.Uri.from({
      scheme: PROPOSED_SCHEME,
      path: `/${label}`,
      query: String(++this.serial),
    });
    this.proposed.put(uri, dry.after);
    this.proposals.set(uri.toString(), {
      uri,
      file: dry.file,
      before: dry.before,
      root,
      k,
      group: group.name,
      ...(startedAt === undefined ? {} : { startedAt }),
      ...(session === undefined ? {} : { session }),
    });
    await vscode.commands.executeCommand(
      'vscode.diff',
      vscode.Uri.file(dry.file),
      uri,
      proposalTitle(k, group.name),
      { preview: false },
    );
  }

  private async refuseStale(proposal: Proposal): Promise<void> {
    const again = 'Promote again';
    const choice = await vscode.window.showErrorMessage(
      `rbx: ${proposal.group}'s script changed since the proposal; promote again.`,
      again,
    );
    if (choice !== again) {
      return;
    }
    await this.close(proposal);
    const args: PromoteArgs = {
      root: proposal.root,
      finding: proposal.k,
      ...(proposal.session === undefined ? {} : { session: proposal.session }),
    };
    await this.promote(args);
  }

  /** The proposal a title-bar button (or the palette) acts on. */
  private proposalOf(raw: unknown): Proposal | undefined {
    let uri: vscode.Uri | undefined;
    if (raw instanceof vscode.Uri && raw.scheme === PROPOSED_SCHEME) {
      uri = raw;
    } else {
      // The palette passes nothing, and a diff's title bar may pass the left
      // side; the active tab names the right side either way.
      const input = vscode.window.tabGroups.activeTabGroup.activeTab?.input;
      if (input instanceof vscode.TabInputTextDiff && input.modified.scheme === PROPOSED_SCHEME) {
        uri = input.modified;
      } else if (input instanceof vscode.TabInputText && input.uri.scheme === PROPOSED_SCHEME) {
        uri = input.uri;
      }
    }
    return uri === undefined ? undefined : this.proposals.get(uri.toString());
  }

  /** Close every tab showing `proposal`, and forget it. */
  private async close(proposal: Proposal): Promise<void> {
    const key = proposal.uri.toString();
    const document = vscode.workspace.textDocuments.find((each) => each.uri.toString() === key);
    // Discarding still saves, into memory about to be dropped: closing a
    // dirty editor would otherwise stop to ask about it.
    if (document?.isDirty) {
      await document.save();
    }
    const tabs = vscode.window.tabGroups.all
      .flatMap((group) => group.tabs)
      .filter((tab) => {
        const input = tab.input;
        return (
          (input instanceof vscode.TabInputTextDiff && input.modified.toString() === key) ||
          (input instanceof vscode.TabInputText && input.uri.toString() === key)
        );
      });
    if (tabs.length > 0) {
      await vscode.window.tabGroups.close(tabs);
    }
    this.forget(proposal.uri);
  }

  private forget(uri: vscode.Uri): void {
    this.proposals.delete(uri.toString());
    this.proposed.drop(uri);
  }

  // --- manual and new groups ------------------------------------------------

  /**
   * Dispatch `add-finding` with `args` to the terminal, and badge the finding
   * once that task exits cleanly -- not when it starts, since rbx may still
   * refuse it (a name taken meanwhile, a glob outside the package).
   */
  private async dispatchAdd(
    root: string,
    args: string[],
    k: number,
    startedAt: string | undefined,
    group: string,
  ): Promise<void> {
    if (!dispatchEnabled()) {
      const copy = 'Copy command';
      const choice = await vscode.window.showInformationMessage(
        `rbx: dispatching to the terminal is disabled (rbx.dispatch.enabled), so finding #${k} ` +
          `was not added to ${group}. Run \`${commandLine(args)}\` yourself.`,
        copy,
      );
      if (choice === copy) {
        await vscode.env.clipboard.writeText(commandLine(args));
      }
      return;
    }
    let ended = false;
    const listener = vscode.tasks.onDidEndTaskProcess((event) => {
      if (!isAddFinding(event.execution.task, root, args)) {
        return;
      }
      ended = true;
      listener.dispose();
      if (event.exitCode === 0) {
        this.stress.markPromoted(root, startedAt, k, group);
      }
    });
    try {
      await this.dispatcher.dispatch({ command: 'add-finding', root, args });
    } finally {
      // Nothing started -- the user backed out of a prompt, or no rbx was
      // found -- leaves nothing to wait for. A task that already ended was
      // caught above.
      if (
        !ended &&
        !vscode.tasks.taskExecutions.some((execution) => isAddFinding(execution.task, root, args))
      ) {
        listener.dispose();
      }
    }
  }

  // --- headless -------------------------------------------------------------

  /**
   * Run `rbx testcases add-finding <args>` headless in `root`, and return its
   * stdout -- or undefined, having said why, when it failed. Only for the
   * read-only modes (`--list-groups`, `--dry-run`), as design D3 allows.
   */
  private async headless(root: string, args: string[], title: string): Promise<string | undefined> {
    const rbx = await resolveRbx(root);
    if (rbx === undefined) {
      void vscode.window.showErrorMessage(
        'Could not find rbx. Set "rbx.executable" to its full path, or open VS Code from a terminal.',
      );
      return undefined;
    }
    const argv = [...ADD_FINDING, ...args];
    log(`${rbx} ${argv.join(' ')}`);
    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title },
      () => run(rbx, argv, root, HEADLESS_TIMEOUT_MS),
    );
    if (result.spawnError !== undefined) {
      void vscode.window.showErrorMessage(`rbx: could not start rbx: ${result.spawnError.message}`);
      return undefined;
    }
    if (result.code !== 0) {
      log(`rbx ${argv.join(' ')} failed in ${root} (exit ${result.code ?? 'none'}): ${result.stderr.trim()}`);
      void vscode.window.showErrorMessage(`rbx: ${failureMessage(result.code, result.stderr)}`);
      return undefined;
    }
    return result.stdout;
  }

  /** Exit 0 with output that is not the promised JSON: an rbx of another shape. */
  private unreadable(mode: string, stdout: string): void {
    log(`rbx testcases add-finding ${mode} printed something unexpected: ${stdout.trim()}`);
    void vscode.window.showErrorMessage(
      `rbx: could not read what \`rbx testcases add-finding ${mode}\` printed. ` +
        'Is rbx up to date? (See the rbx output channel.)',
    );
  }

  private async pick(k: number, groups: readonly PromoteGroup[]): Promise<PickRow | undefined> {
    const items = pickRows(groups).map((row) =>
      row.kind === 'separator'
        ? { label: row.label, kind: vscode.QuickPickItemKind.Separator, row }
        : { label: row.label, description: row.description, row },
    );
    const picked = await vscode.window.showQuickPick(items, {
      title: `Promote finding #${k}`,
      placeHolder: 'Into which test group?',
      matchOnDescription: true,
    });
    return picked?.row;
  }
}
