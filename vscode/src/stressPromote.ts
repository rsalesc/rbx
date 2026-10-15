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
 *
 * Not while the session runs: `--slowest` may still renumber its findings,
 * and a dispatched promote would collide with the stress under the busy
 * policy. The view shows Promote disabled then; the command refuses too, for
 * a click that raced the state change.
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
  proposalLabel,
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

/**
 * How long after a dispatched task ends its process end may still arrive.
 * VS Code does not order the two events; a task that ended with no process
 * end (it never started one) is given up on after this.
 */
const PROCESS_END_GRACE_MS = 2_000;

/** A script group's proposal, open in a diff. */
interface Proposal {
  /** The right side, under `rbx-proposed:`. */
  readonly uri: vscode.Uri;
  /**
   * The left side when the script does not exist yet: an empty, read-only
   * stand-in, since a `file:` URI of a missing file opens as an error.
   */
  readonly emptyLeft?: vscode.Uri;
  /** The generator script, absolute, as the package names it. */
  readonly file: string;
  /** The script as the dry run read it; Accept refuses if it moved since. */
  readonly before: string;
  /** What the dry run proposed, to tell whether the user edited it. */
  readonly after: string;
  readonly root: string;
  readonly k: number;
  readonly group: string;
  /** The session the finding came from, for the view's badge. */
  readonly startedAt?: string;
  /** The row's own session, as the view passed it, for Promote again. */
  readonly session?: string;
  /** Whether a tab has shown it yet; until then no tab is no reason to drop it. */
  shown: boolean;
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
  const definition = task.definition as {
    type?: unknown;
    command?: unknown;
    cwd?: unknown;
    args?: unknown;
  };
  return (
    definition.type === TASK_TYPE &&
    definition.command === 'add-finding' &&
    definition.cwd === root &&
    JSON.stringify(definition.args ?? []) === JSON.stringify(args)
  );
}

function isMissing(error: unknown): boolean {
  return (error as NodeJS.ErrnoException | undefined)?.code === 'ENOENT';
}

/**
 * `file` with its symlinks resolved, as far as they exist: a script not yet
 * created resolves through its directory.
 */
async function canonical(file: string): Promise<string> {
  try {
    return await fs.realpath(file);
  } catch {
    try {
      return path.join(await fs.realpath(path.dirname(file)), path.basename(file));
    } catch {
      return path.resolve(file);
    }
  }
}

/** Every URI a tab shows, as strings. */
function shownUris(): Set<string> {
  const shown = new Set<string>();
  for (const tab of vscode.window.tabGroups.all.flatMap((group) => group.tabs)) {
    const input = tab.input;
    if (input instanceof vscode.TabInputTextDiff) {
      shown.add(input.original.toString());
      shown.add(input.modified.toString());
    } else if (input instanceof vscode.TabInputText) {
      shown.add(input.uri.toString());
    }
  }
  return shown;
}

export class StressPromoter implements vscode.Disposable {
  /** Open proposals, by the right side's URI. */
  private readonly proposals = new Map<string, Proposal>();
  /** Tells two proposals for the same script apart. */
  private serial = 0;
  /** Accepts run one at a time, so a double click cannot apply twice. */
  private accepting: Promise<unknown> = Promise.resolve();
  private readonly disposables: vscode.Disposable[] = [];
  /** Listeners waiting on a dispatched `add-finding`, until it ends. */
  private readonly waiting = new Set<vscode.Disposable>();

  constructor(
    private readonly stress: StressViewProvider,
    private readonly dispatcher: Dispatcher,
    private readonly proposed: ProposedFileSystemProvider,
  ) {
    this.disposables.push(
      // A proposal is only reachable through its editor; once no tab shows
      // it, there is no way left to Accept it. Tabs rather than documents:
      // a document is also closed and reopened by a change of language mode.
      vscode.window.tabGroups.onDidChangeTabs(() => this.sweep()),
    );
  }

  dispose(): void {
    for (const disposable of [...this.disposables, ...this.waiting]) {
      disposable.dispose();
    }
    this.waiting.clear();
  }

  /** `rbx.stress.promote`. */
  async promote(raw: unknown): Promise<void> {
    const args = asPromoteArgs(raw);
    if (args === undefined) {
      log(`rbx.stress.promote called with unexpected arguments: ${JSON.stringify(raw)}`);
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
    if (this.stress.isRunning(root, manifest)) {
      void vscode.window.showInformationMessage(
        `rbx: wait for the stress to finish before promoting finding #${k} -- ` +
          'its findings may still change while it runs.',
      );
      return;
    }
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
    // Checked against the groups that can take findings only, which is what
    // --list-groups lists: a name held by another kind of group gets past
    // this, and rbx refuses it in the terminal instead.
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
  accept(raw: unknown): Promise<void> {
    const next = this.accepting.then(() => this.acceptNow(raw));
    // A failed accept must not wedge the ones behind it.
    this.accepting = next.catch((error) => log(`rbx.proposal.accept failed: ${String(error)}`));
    return next;
  }

  /** `rbx.proposal.discard`, from the proposal's editor title. */
  async discard(raw: unknown): Promise<void> {
    const proposal = this.proposalOf(raw);
    if (proposal === undefined) {
      log('rbx.proposal.discard: no open proposal to discard.');
      return;
    }
    await this.close(proposal);
  }

  private async acceptNow(raw: unknown): Promise<void> {
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
      log(`rbx.proposal.accept: the proposal for ${proposal.file} has no text left.`);
      return;
    }

    const realUri = vscode.Uri.file(proposal.file);
    // The disk, and the editor's copy, which may hold unsaved edits the
    // replacement below would silently overwrite. A script the dry run found
    // missing reads as '' -- rbx proposes creating it -- and is only stale if
    // something has appeared there since.
    let onDisk: string | undefined;
    try {
      onDisk = await fs.readFile(proposal.file, 'utf8');
    } catch (error) {
      if (!isMissing(error)) {
        void vscode.window.showErrorMessage(
          `rbx: could not read ${path.basename(proposal.file)} (${String(error)}); ` +
            'the proposal is still open.',
        );
        return;
      }
      onDisk = undefined;
    }
    if (onDisk === undefined && proposal.before !== '') {
      await this.refuseStale(proposal, text, 'was deleted');
      return;
    }
    if (onDisk !== undefined && !sameText(onDisk, proposal.before)) {
      await this.refuseStale(proposal, text, 'changed on disk');
      return;
    }
    const open = vscode.workspace.textDocuments.find(
      (each) => each.uri.toString() === realUri.toString(),
    );
    if (open?.isDirty && !sameText(open.getText(), proposal.before)) {
      const show = 'Show script';
      const choice = await vscode.window.showErrorMessage(
        `rbx: ${proposal.group}'s script has unsaved changes in an editor. ` +
          'Save or revert them, then Accept again.',
        show,
      );
      if (choice === show) {
        await vscode.window.showTextDocument(open, { preview: false });
      }
      return;
    }

    // Through the editor rather than onto the disk, so the change is one undo
    // away and an open editor of the script never disagrees with the file.
    const edit = new vscode.WorkspaceEdit();
    let real: vscode.TextDocument;
    if (onDisk === undefined) {
      edit.createFile(realUri, { ignoreIfExists: true });
      edit.insert(realUri, new vscode.Position(0, 0), text);
      if (!(await vscode.workspace.applyEdit(edit))) {
        this.notApplied(proposal);
        return;
      }
      real = await vscode.workspace.openTextDocument(realUri);
    } else {
      real = open ?? (await vscode.workspace.openTextDocument(realUri));
      edit.replace(
        realUri,
        new vscode.Range(real.positionAt(0), real.positionAt(real.getText().length)),
        text,
      );
      if (!(await vscode.workspace.applyEdit(edit))) {
        this.notApplied(proposal);
        return;
      }
    }
    if (!(await real.save())) {
      // The edit is in the editor, so the proposal has done its job; what is
      // left is an ordinary unsaved file, which the user knows how to save.
      await this.close(proposal);
      this.stress.markPromoted(proposal.root, proposal.startedAt, proposal.k, proposal.group);
      void vscode.window.showWarningMessage(
        `rbx: added finding #${proposal.k} to ${proposal.group}'s script, but could not save ` +
          `${path.basename(proposal.file)}. Save it yourself.`,
      );
      await vscode.window.showTextDocument(real, { preview: false });
      return;
    }
    await this.close(proposal);
    this.stress.markPromoted(proposal.root, proposal.startedAt, proposal.k, proposal.group);
    const show = 'Open script';
    const choice = await vscode.window.showInformationMessage(
      `rbx: added finding #${proposal.k} to ${proposal.group}.`,
      show,
    );
    if (choice === show) {
      await vscode.window.showTextDocument(realUri, { preview: false });
    }
  }

  private notApplied(proposal: Proposal): void {
    void vscode.window.showErrorMessage(
      `rbx: could not edit ${path.basename(proposal.file)}; the proposal is still open.`,
    );
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

    // The script as the package names it, not rbx's `file`: that is the
    // physical path (rbx resolves its cwd), and in a workspace reached
    // through a symlink it would be a second URI for the file the editor has
    // open under the first. rbx's is only checked against it.
    const file = path.resolve(root, group.path);
    const [ours, theirs] = await Promise.all([canonical(file), canonical(dry.file)]);
    if (ours !== theirs) {
      log(`rbx proposed a change to ${dry.file}, but ${group.name}'s script is ${file}.`);
      void vscode.window.showErrorMessage(
        `rbx: the proposal for ${group.name} is for ${dry.file}, not its script ${group.path}. ` +
          'Nothing was changed.',
      );
      return;
    }

    let exists = true;
    try {
      await fs.access(file);
    } catch {
      exists = false;
    }

    const label = proposalLabel(group.path);
    const serial = String(++this.serial);
    const uri = vscode.Uri.from({ scheme: PROPOSED_SCHEME, path: `/${label}`, query: serial });
    const emptyLeft = exists
      ? undefined
      : vscode.Uri.from({ scheme: PROPOSED_SCHEME, path: `/${label}`, query: `${serial}-empty` });
    this.proposed.put(uri, dry.after);
    if (emptyLeft !== undefined) {
      this.proposed.put(emptyLeft, '', true);
    }
    this.proposals.set(uri.toString(), {
      uri,
      ...(emptyLeft === undefined ? {} : { emptyLeft }),
      file,
      before: dry.before,
      after: dry.after,
      root,
      k,
      group: group.name,
      ...(startedAt === undefined ? {} : { startedAt }),
      ...(session === undefined ? {} : { session }),
      shown: false,
    });
    await vscode.commands.executeCommand(
      'vscode.diff',
      emptyLeft ?? vscode.Uri.file(file),
      uri,
      proposalTitle(k, group.name),
      { preview: false },
    );
  }

  /**
   * Accept found the script moved under the proposal. Promoting again makes a
   * fresh one from the script as it is now -- which would drop whatever the
   * user wrote into this one, so that is offered for the clipboard first.
   */
  private async refuseStale(proposal: Proposal, text: string, what: string): Promise<void> {
    const again = 'Promote again';
    const copy = 'Copy my edits';
    const edited = !sameText(text, proposal.after);
    const choice = await vscode.window.showErrorMessage(
      `rbx: ${proposal.group}'s script ${what} since the proposal; promote again.` +
        (edited ? ' A new proposal will not keep your edits to this one.' : ''),
      ...(edited ? [copy, again] : [again]),
    );
    if (choice === copy) {
      // The proposal stays open, so the edits are also still there to read.
      await vscode.env.clipboard.writeText(text);
      void vscode.window.showInformationMessage(
        'rbx: copied your version of the script. Promote again when you are ready.',
      );
      return;
    }
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
    if (uri === undefined) {
      return undefined;
    }
    // The empty left side of a new script stands for its proposal too.
    return (
      this.proposals.get(uri.toString()) ??
      [...this.proposals.values()].find((each) => each.emptyLeft?.toString() === uri?.toString())
    );
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
    this.forget(proposal);
  }

  /** Forget every proposal a tab showed and none shows any more. */
  private sweep(): void {
    const shown = shownUris();
    for (const proposal of [...this.proposals.values()]) {
      if (shown.has(proposal.uri.toString())) {
        proposal.shown = true;
      } else if (proposal.shown) {
        this.forget(proposal);
      }
    }
  }

  private forget(proposal: Proposal): void {
    this.proposals.delete(proposal.uri.toString());
    this.proposed.drop(proposal.uri);
    if (proposal.emptyLeft !== undefined) {
      this.proposed.drop(proposal.emptyLeft);
    }
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
    const listeners: vscode.Disposable[] = [];
    const stop = () => {
      ended = true;
      for (const listener of listeners) {
        listener.dispose();
        this.waiting.delete(listener);
      }
    };
    listeners.push(
      vscode.tasks.onDidEndTaskProcess((event) => {
        if (ended || !isAddFinding(event.execution.task, root, args)) {
          return;
        }
        stop();
        if (event.exitCode === 0) {
          this.stress.markPromoted(root, startedAt, k, group);
        }
      }),
      // A task can end without its process ever ending -- one that failed to
      // start, or a terminal closed under it -- and then nothing is marked.
      // The process end may land after this, so it gets a moment first.
      vscode.tasks.onDidEndTask((event) => {
        if (!ended && isAddFinding(event.execution.task, root, args)) {
          setTimeout(stop, PROCESS_END_GRACE_MS);
        }
      }),
    );
    for (const listener of listeners) {
      this.waiting.add(listener);
    }
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
        stop();
      }
    }
  }

  // --- headless -------------------------------------------------------------

  /**
   * Run `rbx testcases add-finding <args>` headless in `root`, and return its
   * stdout -- or undefined, having said why, when it failed. Only for the
   * read-only modes (`--list-groups`, `--dry-run`), as design D3 allows.
   *
   * No `-C`, unlike a dispatch: add-finding reads one problem's stress
   * session and testset, which no contest selection changes.
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
      log(
        `rbx ${argv.join(' ')} failed in ${root} (exit ${result.code ?? 'none'}): ` +
          result.stderr.trim(),
      );
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
