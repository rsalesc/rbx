/**
 * Promoting a test into the testset, from wherever the editor shows one
 * (design: docs/plans/2026-10-15-promotion-sinks-design.md):
 *
 *   - a testplan statement (the lens and the context menu),
 *   - a stress finding (the Stress view),
 *   - a test row of the Run or Tests view, an ad-hoc `irun` one included,
 *   - an input file, or the text of an editor.
 *
 * Every one is the same flow over `rbx testcases promote`. Which groups can
 * take the test comes from `--list-sinks --json`; what promoting it changes
 * comes from `--dry-run --json`, as a plan of file changes. Both are
 * read-only, so they run headless (D3). Nothing here decides what goes where:
 * that is rbx's, and the pure half is rbx/promote.ts.
 *
 * The plan is shown before anything is written: every file it edits opens
 * as a diff whose right side the user may still change (a generator call's
 * arguments, a comment). **Accept** applies the whole plan -- the edits as
 * they now read, the files it creates and deletes -- as one `WorkspaceEdit`,
 * so the promotion is one undo away and an open editor never disagrees with
 * its file. A plan with nothing to read (a file copied into a folder) is
 * confirmed in a dialog instead. Either way a deletion is confirmed first.
 */
import * as fs from 'fs/promises';
import * as path from 'path';
import * as vscode from 'vscode';

import { log } from './log';
import { PROPOSED_SCHEME, ProposedFileSystemProvider } from './proposedFs';
import {
  Destination,
  Form,
  PROMOTE,
  PickRow,
  Plan,
  Sink,
  copyPathError,
  defaultManualGlob,
  defaultScriptPath,
  doneMessage,
  failureMessage,
  formRows,
  groupNameError,
  listSinksArgs,
  manualGlobError,
  newScriptPathError,
  nothingToDo,
  parsePlan,
  parseSinks,
  pickRows,
  planArgs,
  planSummary,
  proposalLabel,
  proposalTitle,
  sameText,
  stemError,
  textChanges,
} from './rbx/promote';
import { resolveRbx, run } from './rbxProcess';

/**
 * How long a headless `promote` may take. Generous: a dry run of a generated
 * test may compile its generator first, which on a cold cache takes minutes.
 */
const HEADLESS_TIMEOUT_MS = 5 * 60_000;

/** What to promote, and what to do about it. */
export interface PromoteRequest {
  readonly root: string;
  /** Selectors `rbx testcases promote` takes: `script:line`, `group/index`, `finding:K`, `file:IN`. */
  readonly sources: readonly string[];
  /** How to name it in titles and messages. */
  readonly label: string;
  /** The stress session a `finding:K` was picked from. */
  readonly session?: string;
  /** Whether the source is still there; checked again after every prompt. */
  readonly stillThere?: () => Promise<boolean>;
  /** Told the sink's name once the promotion is written. */
  readonly onPromoted?: (sink: string) => void;
}

/** One edited (or new) text file of a proposal, open as a diff. */
interface TextProposal {
  /** The right side, under `rbx-proposed:`. */
  readonly uri: vscode.Uri;
  /** The left side of a file that does not exist yet: empty and read-only. */
  readonly emptyLeft?: vscode.Uri;
  /** The real file, absolute. */
  readonly file: string;
  /** The file as the plan read it ('' for a new one). */
  readonly before: string;
  readonly created: boolean;
}

/** A plan, open for review. */
interface Proposal {
  readonly request: PromoteRequest;
  readonly plan: Plan;
  readonly texts: readonly TextProposal[];
  /** Whether a tab has shown it yet; until then no tab is no reason to drop it. */
  shown: boolean;
}

function isMissing(error: unknown): boolean {
  return (error as NodeJS.ErrnoException | undefined)?.code === 'ENOENT';
}

async function exists(file: string): Promise<boolean> {
  try {
    await fs.access(file);
    return true;
  } catch {
    return false;
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

export class Promoter implements vscode.Disposable {
  private readonly proposals = new Set<Proposal>();
  /** Tells two proposals for the same file apart. */
  private serial = 0;
  /** Accepts run one at a time, so a double click cannot apply twice. */
  private accepting: Promise<unknown> = Promise.resolve();
  private readonly disposables: vscode.Disposable[] = [];

  constructor(private readonly proposed: ProposedFileSystemProvider) {
    this.disposables.push(
      // A proposal is only reachable through its editors; once no tab shows
      // any of them, there is no way left to Accept it.
      vscode.window.tabGroups.onDidChangeTabs(() => this.sweep()),
    );
  }

  dispose(): void {
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
  }

  /** Promote `request.sources`: pick where, how, then review the plan. */
  async promote(request: PromoteRequest): Promise<void> {
    const listed = await this.headless(
      request.root,
      [...PROMOTE, ...listSinksArgs(request.sources)],
      `rbx: finding where ${request.label} can go…`,
    );
    if (listed === undefined) {
      return;
    }
    const sinks = parseSinks(listed);
    if (sinks === undefined) {
      this.unreadable('--list-sinks', listed);
      return;
    }

    const row = await this.pickDestination(request.label, sinks);
    if (row === undefined) {
      return;
    }
    const existing = sinks.map((sink) => sink.name);
    let destination: Destination;
    let form: Form | undefined;
    let pathOption: string | undefined;
    let name: string | undefined;
    switch (row.kind) {
      case 'separator':
        return;
      case 'sink': {
        destination = { kind: 'sink', name: row.sink.name };
        form = await this.pickForm(request.label, row.sink);
        if (form === undefined) {
          return;
        }
        if (row.sink.kind === 'glob') {
          name = await this.askStem(request.label, row.sink.name);
          if (name === undefined) {
            return;
          }
        } else if (form === 'copy') {
          pathOption = await this.askCopyPath(request.label, row.sink);
          if (pathOption === undefined) {
            return;
          }
        }
        break;
      }
      case 'new-script': {
        const script = await vscode.window.showInputBox({
          title: `Promote ${request.label} into a new script group`,
          prompt:
            'The new .txt generator script, relative to the problem. ' +
            'The group is named after the file.',
          value: defaultScriptPath(existing),
          validateInput: (value) => newScriptPathError(value.trim(), existing),
        });
        if (script === undefined) {
          return;
        }
        destination = { kind: 'new-script', path: script.trim() };
        break;
      }
      case 'new-manual': {
        const groupName = await vscode.window.showInputBox({
          title: `Promote ${request.label} into a new manual group`,
          prompt: 'The name of the new test group.',
          validateInput: (value) => groupNameError(value.trim(), existing),
        });
        if (groupName === undefined) {
          return;
        }
        const glob = await vscode.window.showInputBox({
          title: `Promote ${request.label} into ${groupName.trim()}`,
          prompt: 'Where the group keeps its inputs: a glob with a `*`, ending in `.in`.',
          value: defaultManualGlob(groupName.trim()),
          validateInput: (value) => manualGlobError(value.trim()),
        });
        if (glob === undefined) {
          return;
        }
        destination = { kind: 'new-manual', name: groupName.trim(), glob: glob.trim() };
        break;
      }
    }

    if (request.stillThere !== undefined && !(await request.stillThere())) {
      return;
    }
    const stdout = await this.headless(
      request.root,
      [
        ...PROMOTE,
        ...planArgs(request.sources, destination, {
          ...(form === undefined ? {} : { form }),
          ...(pathOption === undefined ? {} : { path: pathOption }),
          ...(name === undefined ? {} : { name }),
          ...(request.session === undefined ? {} : { session: request.session }),
        }),
      ],
      `rbx: planning the promotion of ${request.label}…`,
    );
    if (stdout === undefined) {
      return;
    }
    const plan = parsePlan(stdout);
    if (plan === undefined) {
      this.unreadable('--dry-run', stdout);
      return;
    }
    if (plan.changes.length === 0) {
      if (plan.skipped.length > 0) {
        // Already there: as good as promoted, which a caller may want to say.
        request.onPromoted?.(plan.sink.name);
      }
      void vscode.window.showInformationMessage(`rbx: nothing to promote -- ${nothingToDo(plan)}`);
      return;
    }
    await this.propose(request, plan);
  }

  // --- the prompts ----------------------------------------------------------

  private async pickDestination(label: string, sinks: readonly Sink[]): Promise<PickRow | undefined> {
    const items = pickRows(sinks).map((row) =>
      row.kind === 'separator'
        ? { label: row.label, kind: vscode.QuickPickItemKind.Separator, row }
        : {
            label: row.label,
            description: row.description,
            ...('detail' in row && row.detail !== undefined ? { detail: row.detail } : {}),
            row,
          },
    );
    const picked = await vscode.window.showQuickPick(items, {
      title: `Promote ${label}`,
      placeHolder: 'Into which test group?',
      matchOnDescription: true,
    });
    return picked?.row;
  }

  /** The form, asked only when the sink takes more than one. */
  private async pickForm(label: string, sink: Sink): Promise<Form | undefined> {
    const rows = formRows(sink);
    if (rows.length <= 1) {
      return rows[0]?.form ?? sink.form;
    }
    const picked = await vscode.window.showQuickPick(
      rows.map((row) => ({ label: row.label, description: row.description, form: row.form })),
      {
        title: `Promote ${label} into ${sink.name}`,
        placeHolder: sink.inPlace ? 'Already here -- change it into:' : 'Add it as:',
      },
    );
    return picked?.form;
  }

  /** Where a `@copy` file goes: rbx's suggestion, or what the user makes of it. */
  private async askCopyPath(label: string, sink: Sink): Promise<string | undefined> {
    const suggested = sink.suggested ?? `tests/${sink.name}/*.in`;
    const typed = await vscode.window.showInputBox({
      title: `Promote ${label} into ${sink.name} as a @copy`,
      prompt:
        'Where the input file goes: a file, or a pattern whose `*` becomes the next free ' +
        'name. Suggested from the other @copy lines of the group.',
      value: suggested,
      validateInput: (value) => copyPathError(value.trim()),
    });
    if (typed === undefined) {
      return undefined;
    }
    // Unchanged, rbx picks the same place itself; saying nothing keeps it so.
    return typed.trim() === suggested ? '' : typed.trim();
  }

  private async askStem(label: string, group: string): Promise<string | undefined> {
    const stem = await vscode.window.showInputBox({
      title: `Promote ${label} into ${group}`,
      prompt: 'The file name, without `.in`. Leave it empty for the next free one (000, 001, …).',
      validateInput: (value) => stemError(value.trim()),
    });
    return stem?.trim();
  }

  // --- the proposal ---------------------------------------------------------

  private async propose(request: PromoteRequest, plan: Plan): Promise<void> {
    const serial = String(++this.serial);
    const texts: TextProposal[] = [];
    for (const change of textChanges(plan)) {
      const created = change.action === 'create';
      const after = change.action === 'modify' ? change.after : 'content' in change ? change.content : '';
      const before = change.action === 'modify' ? change.before : '';
      const label = proposalLabel(path.relative(request.root, change.path));
      const uri = vscode.Uri.from({ scheme: PROPOSED_SCHEME, path: `/${label}`, query: serial });
      this.proposed.put(uri, after);
      let emptyLeft: vscode.Uri | undefined;
      if (created) {
        emptyLeft = vscode.Uri.from({ scheme: PROPOSED_SCHEME, path: `/${label}`, query: `${serial}-empty` });
        this.proposed.put(emptyLeft, '', true);
      }
      texts.push({ uri, ...(emptyLeft === undefined ? {} : { emptyLeft }), file: change.path, before, created });
    }
    const proposal: Proposal = { request, plan, texts, shown: false };

    if (texts.length === 0) {
      // Nothing to read or reword: say what will happen, and do it.
      await this.applyNow(proposal, true);
      return;
    }
    this.proposals.add(proposal);
    for (const text of texts) {
      await vscode.commands.executeCommand(
        'vscode.diff',
        text.emptyLeft ?? vscode.Uri.file(text.file),
        text.uri,
        proposalTitle(request.label, plan, path.relative(request.root, text.file)),
        { preview: false },
      );
    }
  }

  /** `rbx.proposal.accept`, from a proposal's editor title. */
  accept(raw: unknown): Promise<void> {
    const next = this.accepting.then(async () => {
      const proposal = this.proposalOf(raw);
      if (proposal === undefined) {
        void vscode.window.showInformationMessage('rbx: this proposal was already accepted or discarded.');
        return;
      }
      await this.applyNow(proposal, false);
    });
    // A failed accept must not wedge the ones behind it.
    this.accepting = next.catch((error) => log(`rbx.proposal.accept failed: ${String(error)}`));
    return next;
  }

  /** `rbx.proposal.discard`, from a proposal's editor title. */
  async discard(raw: unknown): Promise<void> {
    const proposal = this.proposalOf(raw);
    if (proposal === undefined) {
      log('rbx.proposal.discard: no open proposal to discard.');
      return;
    }
    await this.close(proposal);
  }

  /**
   * Apply `proposal`: refuse anything stale, confirm, then one WorkspaceEdit.
   * `confirmAll` asks before anything at all -- for a plan nobody has seen.
   */
  private async applyNow(proposal: Proposal, confirmAll: boolean): Promise<void> {
    const { plan, request } = proposal;
    const texts = new Map<string, string>();
    for (const text of proposal.texts) {
      const document = vscode.workspace.textDocuments.find(
        (each) => each.uri.toString() === text.uri.toString(),
      );
      // Saved first, though it only ever goes to memory: closing a dirty
      // editor below would otherwise ask whether to save a file nobody sees.
      if (document?.isDirty) {
        await document.save();
      }
      const current = document?.getText() ?? this.proposed.text(text.uri);
      if (current === undefined) {
        log(`rbx.proposal.accept: the proposal for ${text.file} has no text left.`);
        return;
      }
      texts.set(text.file, current);
    }

    const stale = await this.staleness(proposal);
    if (stale !== undefined) {
      await this.refuseStale(proposal, stale);
      return;
    }

    const deletes = plan.changes.filter((change) => change.action === 'delete');
    if (confirmAll || deletes.length > 0) {
      const listing = plan.changes
        .map((change) => `${change.action} ${path.relative(request.root, change.path)}`)
        .join('\n');
      const go = 'Promote';
      const choice = await vscode.window.showWarningMessage(
        `Promote ${request.label} into ${plan.sink.name}? ` +
          (deletes.length > 0
            ? `This deletes ${deletes.length === 1 ? 'a file' : `${deletes.length} files`}; Undo brings ${deletes.length === 1 ? 'it' : 'them'} back.`
            : planSummary(plan)),
        { modal: true, detail: listing },
        go,
      );
      if (choice !== go) {
        return;
      }
    }

    const edit = new vscode.WorkspaceEdit();
    const edited: vscode.Uri[] = [];
    for (const change of plan.changes) {
      const uri = vscode.Uri.file(change.path);
      if (change.action === 'create') {
        const contents =
          'from' in change
            ? await fs.readFile(change.from)
            : new TextEncoder().encode(texts.get(change.path) ?? change.content);
        edit.createFile(uri, { contents });
      } else if (change.action === 'modify') {
        const document = await vscode.workspace.openTextDocument(uri);
        edit.replace(
          uri,
          new vscode.Range(document.positionAt(0), document.positionAt(document.getText().length)),
          texts.get(change.path) ?? change.after,
        );
        edited.push(uri);
      }
    }
    // Deletions last, so a moved input is in its new place before its old
    // one goes, whatever order the edit is replayed in.
    for (const change of deletes) {
      edit.deleteFile(vscode.Uri.file(change.path), { ignoreIfNotExists: true });
    }
    if (!(await vscode.workspace.applyEdit(edit))) {
      void vscode.window.showErrorMessage(
        `rbx: could not promote ${request.label}; nothing was changed. The proposal is still open.`,
      );
      return;
    }
    const unsaved: string[] = [];
    for (const uri of edited) {
      const document = vscode.workspace.textDocuments.find((each) => each.uri.toString() === uri.toString());
      if (document !== undefined && document.isDirty && !(await document.save())) {
        unsaved.push(path.basename(uri.fsPath));
      }
    }
    await this.close(proposal);
    request.onPromoted?.(plan.sink.name);
    if (unsaved.length > 0) {
      void vscode.window.showWarningMessage(
        `rbx: ${doneMessage(request.label, plan)} Could not save ${unsaved.join(', ')}; save it yourself.`,
      );
      return;
    }
    const target = this.landing(plan);
    const open = 'Open';
    const choice = await vscode.window.showInformationMessage(
      `rbx: ${doneMessage(request.label, plan)}`,
      ...(target === undefined ? [] : [open]),
    );
    if (choice === open && target !== undefined) {
      await vscode.window.showTextDocument(vscode.Uri.file(target), { preview: false });
    }
  }

  /** The file to open after promoting: the script edited, else the file written. */
  private landing(plan: Plan): string | undefined {
    const edit = plan.changes.find((change) => change.action === 'modify' && !change.path.endsWith('.yml'));
    const create = plan.changes.find((change) => change.action === 'create');
    return (edit ?? create)?.path;
  }

  /** Why the plan no longer applies, or undefined when it still does. */
  private async staleness(proposal: Proposal): Promise<string | undefined> {
    const rel = (file: string) => path.relative(proposal.request.root, file);
    for (const change of proposal.plan.changes) {
      if (change.action === 'create' && (await exists(change.path))) {
        return `${rel(change.path)} appeared`;
      }
      if (change.action === 'delete' && !(await exists(change.path))) {
        return `${rel(change.path)} is gone`;
      }
      if (change.action === 'create' && 'from' in change && !(await exists(change.from))) {
        return `the input to copy (${change.from}) is gone`;
      }
      if (change.action !== 'modify') {
        continue;
      }
      let onDisk: string;
      try {
        onDisk = await fs.readFile(change.path, 'utf8');
      } catch (error) {
        if (isMissing(error)) {
          return `${rel(change.path)} was deleted`;
        }
        return `${rel(change.path)} could not be read (${String(error)})`;
      }
      if (!sameText(onDisk, change.before)) {
        return `${rel(change.path)} changed on disk`;
      }
      const open = vscode.workspace.textDocuments.find(
        (each) => each.uri.toString() === vscode.Uri.file(change.path).toString(),
      );
      if (open?.isDirty && !sameText(open.getText(), change.before)) {
        return `${rel(change.path)} has unsaved changes in an editor`;
      }
    }
    return undefined;
  }

  /**
   * Accept found the disk moved under the proposal. Promoting again makes a
   * fresh one from the files as they are now -- which would drop whatever the
   * user wrote into this one, so that is offered for the clipboard first.
   */
  private async refuseStale(proposal: Proposal, what: string): Promise<void> {
    const again = 'Promote again';
    const copy = 'Copy my edits';
    const edited = proposal.texts.filter((text) => {
      const now = this.proposed.text(text.uri);
      const change = proposal.plan.changes.find((each) => each.path === text.file);
      const after =
        change?.action === 'modify' ? change.after : change !== undefined && 'content' in change ? change.content : '';
      return now !== undefined && !sameText(now, after);
    });
    const choice = await vscode.window.showErrorMessage(
      `rbx: ${what} since the promotion was planned; promote again.` +
        (edited.length > 0 ? ' A new proposal will not keep your edits to this one.' : ''),
      ...(edited.length > 0 ? [copy, again] : [again]),
    );
    if (choice === copy) {
      await vscode.env.clipboard.writeText(
        edited.map((text) => this.proposed.text(text.uri) ?? '').join('\n'),
      );
      void vscode.window.showInformationMessage('rbx: copied your edits. Promote again when you are ready.');
      return;
    }
    if (choice !== again) {
      return;
    }
    await this.close(proposal);
    await this.promote(proposal.request);
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
    const key = uri.toString();
    for (const proposal of this.proposals) {
      if (proposal.texts.some((text) => text.uri.toString() === key || text.emptyLeft?.toString() === key)) {
        return proposal;
      }
    }
    return undefined;
  }

  /** Close every tab showing `proposal`, and forget it. */
  private async close(proposal: Proposal): Promise<void> {
    const keys = new Set(proposal.texts.map((text) => text.uri.toString()));
    for (const document of vscode.workspace.textDocuments) {
      // Discarding still saves, into memory about to be dropped: closing a
      // dirty editor would otherwise stop to ask about it.
      if (keys.has(document.uri.toString()) && document.isDirty) {
        await document.save();
      }
    }
    const tabs = vscode.window.tabGroups.all
      .flatMap((group) => group.tabs)
      .filter((tab) => {
        const input = tab.input;
        return (
          (input instanceof vscode.TabInputTextDiff && keys.has(input.modified.toString())) ||
          (input instanceof vscode.TabInputText && keys.has(input.uri.toString()))
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
    for (const proposal of [...this.proposals]) {
      if (proposal.texts.some((text) => shown.has(text.uri.toString()))) {
        proposal.shown = true;
      } else if (proposal.shown) {
        this.forget(proposal);
      }
    }
  }

  private forget(proposal: Proposal): void {
    this.proposals.delete(proposal);
    for (const text of proposal.texts) {
      this.proposed.drop(text.uri);
      if (text.emptyLeft !== undefined) {
        this.proposed.drop(text.emptyLeft);
      }
    }
  }

  // --- headless -------------------------------------------------------------

  /**
   * Run `rbx <argv>` headless in `root`, and return its stdout -- or
   * undefined, having said why, when it failed. Only for the read-only modes
   * (`--list-sinks`, `--dry-run`), as design D3 allows.
   */
  private async headless(root: string, argv: string[], title: string): Promise<string | undefined> {
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
    log(`rbx testcases promote ${mode} printed something unexpected: ${stdout.trim()}`);
    void vscode.window.showErrorMessage(
      `rbx: could not read what \`rbx testcases promote ${mode}\` printed. ` +
        'Is rbx up to date? (See the rbx output channel.)',
    );
  }
}
