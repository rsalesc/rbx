/**
 * Extension entry point.
 *
 * The extension is a pure reader (design D2/D3): the user runs `rbx run` in the
 * terminal and this watches what lands under `.rbx/runs`. It never spawns rbx,
 * because every rbx invocation has side effects on the package cache and could
 * race a run already in flight.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { ActiveProblem } from './activeProblem';
import { ArtifactFileSystemProvider, SCHEME } from './artifactFs';
import { registerCommands } from './commands';
import { DeclaredIndex } from './declared';
import { registerDecorations } from './decorations';
import { initLog, log } from './log';
import { CONTEST_FILE_GLOB, CONTEST_MANIFEST, isContestVariantFile } from './rbx/contest';
import { CACHE_DIR, PROBLEM_MANIFEST } from './rbx/layout';
import { RunDataProvider } from './runData';
import { RunViewProvider } from './runView';
import { registerSolutionLens } from './solutionLens';
import { registerSolutionStatus } from './solutionStatus';

/**
 * Map a changed path back to the package it belongs to.
 *
 * Events arrive either as `<pkg>/.rbx/runs/...` during a run, or as the bare
 * `<pkg>/.rbx` when the whole cache directory goes away -- `rbx clean` rmtree's
 * it in one call, and the watcher reports the top removed directory rather than
 * each descendant. Both spellings must resolve to the package root.
 */
function packageRootOf(fsPath: string): string | undefined {
  const suffix = `${path.sep}${CACHE_DIR}`;
  if (fsPath.endsWith(suffix)) {
    return fsPath.slice(0, -suffix.length);
  }
  const marker = `${suffix}${path.sep}`;
  const index = fsPath.indexOf(marker);
  return index === -1 ? undefined : fsPath.slice(0, index);
}

export function activate(context: vscode.ExtensionContext): void {
  initLog(context);
  log('rbx extension activated.');
  const data = new RunDataProvider();
  // `workspaceState`, not `globalState`: the problem being worked on is a fact
  // about this contest checkout, and remembering it across unrelated windows
  // would land each of them on a root the other opened.
  const active = new ActiveProblem(data, context.workspaceState);
  const view = new RunViewProvider(data, active, context.extensionUri);
  const declared = new DeclaredIndex(data);
  context.subscriptions.push(declared);
  registerDecorations(context, declared);
  registerSolutionLens(context, declared);
  registerSolutionStatus(context, declared);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(RunViewProvider.viewType, view),
    vscode.workspace.registerFileSystemProvider(SCHEME, new ArtifactFileSystemProvider(), {
      isReadonly: true,
      isCaseSensitive: true,
    }),
  );

  registerCommands(context, view, data, active);

  // Artifacts land incrementally as evaluations resolve, which is what gives
  // the view live progress without any streaming protocol: each new `.eval`
  // fills in one testcase. Refreshes are debounced because a run drops many
  // files in quick succession.
  const pending = new Set<string>();
  let timer: NodeJS.Timeout | undefined;

  const touched = (uri: vscode.Uri) => {
    const root = packageRootOf(uri.fsPath);
    if (root === undefined) {
      return;
    }
    pending.add(root);
    if (timer !== undefined) {
      clearTimeout(timer);
    }
    timer = setTimeout(() => {
      timer = undefined;
      for (const changed of pending) {
        log(`Artifacts changed under ${changed}; reloading.`);
        data.invalidate(changed);
      }
      pending.clear();
    }, 200);
  };

  const watch = (glob: string) => {
    const watcher = vscode.workspace.createFileSystemWatcher(glob);
    watcher.onDidCreate(touched);
    watcher.onDidChange(touched);
    watcher.onDidDelete(touched);
    context.subscriptions.push(watcher);
  };

  // Two globs, because they catch different things: the first sees individual
  // artifacts appearing during a run, the second sees the cache directory
  // itself being created or removed -- which is all `rbx clean` produces.
  watch(`**/${CACHE_DIR}/**`);
  watch(`**/${CACHE_DIR}`);

  // A third glob, for a different question: the two above ask *what changed*,
  // this one asks *what is running*. `skeleton.yml` is written when a run
  // starts (rbx/box/solutions.py:746 -- "A new skeleton is what marks a new
  // run"), so following it makes the view track the problem currently running:
  // `rbx contest each run` walks the view through the contest in step with the
  // run itself.
  //
  // Create and change only, never delete: `rbx clean` removes the skeleton,
  // and switching to a package whose run was just deleted is the opposite of
  // following work.
  const skeletons = vscode.workspace.createFileSystemWatcher(
    `**/${CACHE_DIR}/runs/skeleton.yml`,
  );
  const followRun = (uri: vscode.Uri) => {
    const root = packageRootOf(uri.fsPath);
    if (root !== undefined) {
      void active.follow(root);
    }
  };
  skeletons.onDidCreate(followRun);
  skeletons.onDidChange(followRun);
  context.subscriptions.push(skeletons);

  context.subscriptions.push(new vscode.Disposable(() => {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
  }));

  // A package appearing or disappearing changes the set of roots, not just
  // their contents, so it needs a full rediscovery.
  //
  // A manifest being *edited* changes no root, and so does not concern the run
  // view at all -- but it is exactly what the badges and banners are drawn
  // from, which is why the index is re-read on all three events and the run
  // view on only two.
  const manifests = vscode.workspace.createFileSystemWatcher(`**/${PROBLEM_MANIFEST}`);
  // The choices are rebuilt after every rediscovery, not just at startup: a
  // package appearing or disappearing changes what the dropdown can offer, and
  // may take the selected problem with it.
  const rediscover = () => {
    void data
      .refresh()
      .then(() => active.refresh())
      .then(() => declared.refresh());
  };
  manifests.onDidCreate(rediscover);
  manifests.onDidDelete(rediscover);
  manifests.onDidChange(() => void declared.refresh());
  context.subscriptions.push(
    manifests,
    vscode.workspace.onDidChangeWorkspaceFolders(rediscover),
  );

  // The dropdown's letters, order and colours come from `contest.rbx.yml`, and
  // nothing above watches it: renaming `A` to `B`, adding a colour, reordering
  // the list or adding an entry would otherwise reach the view only on a window
  // reload.
  //
  // All three events, unlike the manifest watcher just above -- and for the
  // mirror-image reason. There, an *edit* changes no root and so does not
  // concern the selector; here the identities live *inside* the file, so an
  // edit is the common case, while a create or delete just means a package
  // gained or lost its contest.
  //
  // `active.refresh()` alone, not `rediscover`: a contest file names problems,
  // it does not create packages. The set of package roots is exactly what it
  // was, so re-globbing the workspace and re-reading every manifest would buy
  // nothing but the hitch.
  const contests = vscode.workspace.createFileSystemWatcher(`**/${CONTEST_FILE_GLOB}`);
  const recontest = (uri: vscode.Uri) => {
    // The glob is deliberately loose (see `CONTEST_FILE_GLOB`), so the basename
    // is checked against the names rbx would actually load.
    const name = path.basename(uri.fsPath);
    if (name === CONTEST_MANIFEST || isContestVariantFile(name)) {
      log(`${uri.fsPath} changed; rebuilding the problem list.`);
      void active.refresh();
    }
  };
  contests.onDidCreate(recontest);
  contests.onDidChange(recontest);
  contests.onDidDelete(recontest);
  context.subscriptions.push(contests);

  rediscover();
}

export function deactivate(): void {
  // Nothing to tear down: every disposable is registered on the context.
}
