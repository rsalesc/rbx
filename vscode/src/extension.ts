/**
 * Extension entry point.
 *
 * The extension is a pure reader (design D2/D3): the user runs `rbx run` in the
 * terminal and this watches what lands under `.rbx/runs`. It never drives a
 * build; the only rbx it spawns is read-only, idempotent work behind a feature
 * that asked for it -- see rbxProcess.ts for what makes that safe.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { ActiveProblem } from './activeProblem';
import { ArtifactFileSystemProvider, SCHEME } from './artifactFs';
import { registerCommands } from './commands';
import { DeclaredIndex } from './declared';
import { registerDecorations } from './decorations';
import { registerDiagnostics } from './diagnostics';
import { initLog, log } from './log';
import { CONTEST_FILE_GLOB, CONTEST_MANIFEST, isContestVariantFile } from './rbx/contest';
import { resetBuildDirs, resolveBuildDir } from './rbx/environment';
import { CACHE_DIR, PROBLEM_MANIFEST, TESTSET_MANIFEST } from './rbx/layout';
import { RunDataProvider } from './runData';
import { RunViewProvider } from './runView';
import { registerSolutionLens } from './solutionLens';
import { registerSolutionStatus } from './solutionStatus';
import { registerStatementVarHints } from './statementVarHints';
import { StatementVarsIndex } from './statementVarsIndex';
import { TestsetPanel } from './testsetPanel';
import { TestsetViewProvider } from './testsetView';
import { openVisualization } from './visualizationPanel';

/**
 * Map a changed cache path back to the package it belongs to.
 *
 * Events arrive either as `<pkg>/.rbx/runs/...` during a run, or as the bare
 * `<pkg>/.rbx` when the whole cache directory goes away -- `rbx clean` rmtree's
 * it in one call, and the watcher reports the top removed directory rather than
 * each descendant. Both spellings must resolve to the package root.
 */
function cacheRootOf(fsPath: string): string | undefined {
  const suffix = `${path.sep}${CACHE_DIR}`;
  if (fsPath.endsWith(suffix)) {
    return fsPath.slice(0, -suffix.length);
  }
  const marker = `${suffix}${path.sep}`;
  const index = fsPath.indexOf(marker);
  return index === -1 ? undefined : fsPath.slice(0, index);
}

/**
 * The package a `testset.yml` belongs to, or undefined if it belongs to none.
 *
 * The build directory is named by the active preset and can be nested, so the
 * manifest's own path does not say how far up the package root is. Rather than
 * guess a depth, each ancestor is asked whether *its* build directory is the
 * one this manifest sits in -- which is the same question `testsetPath` answers
 * in the other direction, so the watcher and the reader cannot disagree.
 *
 * Bounded to a few levels because `buildDir` is a build directory, not an
 * arbitrary path, and an unbounded walk would make every stray `testset.yml`
 * in the workspace cost a preset lookup per ancestor.
 */
function testsetRootOf(fsPath: string): string | undefined {
  if (path.basename(fsPath) !== TESTSET_MANIFEST) {
    return undefined;
  }
  let dir = path.dirname(fsPath);
  for (let depth = 0; depth < 4; depth++) {
    const parent = path.dirname(dir);
    if (parent === dir) {
      return undefined;
    }
    if (path.join(parent, resolveBuildDir(parent)) === path.dirname(fsPath)) {
      return parent;
    }
    dir = parent;
  }
  return undefined;
}

/**
 * Map any watched path back to the package it belongs to.
 *
 * Two spellings reach the debounce: run artifacts under `.rbx`, and the testset
 * manifest `rbx build` writes at `<pkg>/<build>/testset.yml`. They feed the same
 * pending set because they invalidate the same store -- a package is reloaded
 * whole, and which of its two producers moved is not a distinction the reload
 * makes.
 */
function packageRootOf(fsPath: string): string | undefined {
  return cacheRootOf(fsPath) ?? testsetRootOf(fsPath);
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
  // The Tests view shares `data` and `active` with the Run view rather than
  // discovering the workspace a second time: the two are two readings of one
  // package, and a second `ActiveProblem` would let them drift onto different
  // problems in the same window.
  const testset = new TestsetViewProvider(data, active, context.extensionUri, (request) => {
    const root = active.selected();
    if (root !== undefined) {
      TestsetPanel.show(context, data, root, request);
    }
  });
  const declared = new DeclaredIndex(data);
  context.subscriptions.push(declared);
  // Populated lazily, on the first hint request in a statement, and dropped
  // whenever the manifest it was expanded from changes (the watcher below).
  const statementVars = new StatementVarsIndex();
  context.subscriptions.push(statementVars);
  registerDecorations(context, declared);
  registerSolutionLens(context, declared);
  registerSolutionStatus(context, declared);
  registerStatementVarHints(context, declared, statementVars);
  // Fed by the same `onDidChange` the run view is, so the Problems entries and
  // the Compilation Findings panel can never describe different runs.
  registerDiagnostics(context, data);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(RunViewProvider.viewType, view),
    vscode.window.registerWebviewViewProvider(TestsetViewProvider.viewType, testset),
    vscode.workspace.registerFileSystemProvider(SCHEME, new ArtifactFileSystemProvider(), {
      isReadonly: true,
      isCaseSensitive: true,
    }),
  );

  registerCommands(context, view, data, active, testset);

  // The panel follows the sidebar's highlight, so arrowing the list scrolls the
  // gallery to the testcase being read. `reveal` is a no-op when no panel is
  // open, which is the common case and deliberately costs nothing.
  context.subscriptions.push(
    testset.onDidChangeSelection((selection) => {
      if (selection.testId !== undefined) {
        TestsetPanel.reveal(selection.testId);
      }
    }),
  );

  // A click in the gallery has to land where a click in the sidebar does. The
  // panel does not own those commands and must not reach for them, so it names
  // an intent and this routes it: a testcase through the sidebar's node (which
  // is what the command signature expects), a file through the same opener the
  // Tests view's visualization commands use.
  context.subscriptions.push(
    TestsetPanel.onDidRequestOpen((request) => {
      if (request.kind === 'file') {
        void openVisualization(context, {
          root: request.root,
          filePath: request.filePath,
          label: `${request.group}/${request.stem}`,
        });
        return;
      }
      const node = testset.nodeById(`${request.group}::${request.stem}`);
      if (node !== undefined) {
        void vscode.commands.executeCommand('rbx.openBuiltTestcase', node);
      }
    }),
  );

  /**
   * Whether this path is a visualization, and so says nothing about a run.
   *
   * `rbx.visualizeSolutionOutput` passes `--dest` under the build directory,
   * which nothing here watches, so the extension's own visualizations are
   * already invisible to this. A *hand-typed* `rbx visualize output` has no
   * `--dest` and lands beside the run artifact instead, i.e. inside
   * `.rbx/runs/<i>/<group>/output_visualization/` -- and that would invalidate
   * the run view and redraw the tree for a file that carries no verdict, no
   * timing and no progress.
   */
  const isVisualizationArtifact = (fsPath: string): boolean =>
    fsPath.includes(`${path.sep}output_visualization${path.sep}`) ||
    fsPath.includes(`${path.sep}visualization${path.sep}`);

  // Artifacts land incrementally as evaluations resolve, which is what gives
  // the view live progress without any streaming protocol: each new `.eval`
  // fills in one testcase. Refreshes are debounced because a run drops many
  // files in quick succession.
  const pending = new Set<string>();
  let timer: NodeJS.Timeout | undefined;

  const touched = (uri: vscode.Uri) => {
    if (isVisualizationArtifact(uri.fsPath)) {
      return;
    }
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

  // A third: the testset manifest, which `rbx build` writes last (design D2).
  // Written last is what lets this be a single glob rather than a heuristic
  // about when a build has settled -- when it lands, everything it names is
  // already on disk. It joins the same debounce as the artifacts above, so a
  // build finishing while a run is in flight still costs one reload.
  //
  // The glob cannot name the build directory, because its name comes from the
  // preset and differs per workspace; `packageRootOf` is what decides whether a
  // given `testset.yml` is one of ours, and a stray one maps to no package and
  // is dropped.
  watch(`**/${TESTSET_MANIFEST}`);

  // A fourth glob, for a different question: the three above ask *what
  // changed*, this one asks *what is running*. `skeleton.yml` is written when
  // a run starts (rbx/box/solutions.py:746 -- "A new skeleton is what marks a
  // new run"), so following it makes the view track the problem being run:
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
  // view at all -- but it is exactly what the badges, the banners and the
  // statement var hints are drawn from, which is why the indexes are re-read on
  // all three events and the run view on only two.
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
  // A third reader of the same events: the vars an edited manifest expands to.
  // All three, on the manifest's own directory, because that directory *is* the
  // package root `rbx vars` is asked in -- a created or deleted manifest drops
  // an entry that would otherwise answer for a package that no longer exists.
  const revars = (uri: vscode.Uri) => statementVars.invalidate(path.dirname(uri.fsPath));
  manifests.onDidCreate((uri) => {
    revars(uri);
    rediscover();
  });
  manifests.onDidDelete((uri) => {
    revars(uri);
    rediscover();
  });
  manifests.onDidChange((uri) => {
    revars(uri);
    void declared.refresh();
  });
  context.subscriptions.push(
    manifests,
    vscode.workspace.onDidChangeWorkspaceFolders(rediscover),
  );

  // The preset decides where the build directory is, so editing it moves every
  // path the Tests view and the testcase panes are built from. Nothing else
  // above notices: the packages are unchanged, only the name of a directory
  // inside them, and a stale `PackageLayout` would keep pointing at the old one
  // until the window was reloaded.
  //
  // Both spellings are watched for the same reason `findPresetDir` reads both:
  // an installed preset lives in `.local.rbx/`, a preset under development is a
  // checkout with a bare `preset.rbx.yml`. The environment file is named by the
  // preset and so cannot be globbed by name -- watching the directory catches
  // it whatever it is called.
  const presets = vscode.workspace.createFileSystemWatcher(
    `{**/preset.rbx.yml,**/.local.rbx/**}`,
  );
  const repoint = () => {
    resetBuildDirs();
    rediscover();
  };
  presets.onDidCreate(repoint);
  presets.onDidChange(repoint);
  presets.onDidDelete(repoint);
  context.subscriptions.push(presets);

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
