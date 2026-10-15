/**
 * Extension entry point.
 *
 * The extension is a reader (design D2/D3): whoever starts `rbx run` -- the
 * user in a terminal, or the user through a button that dispatches it to one
 * (dispatch.ts, D3 as amended by #906) -- this watches what lands under
 * `.rbx/runs`. It never runs a build headless or reads a terminal; the only rbx
 * it spawns itself is read-only, idempotent work behind a feature that asked
 * for it -- see rbxProcess.ts for what makes that safe.
 */
import * as path from 'path';
import * as vscode from 'vscode';

import { ActiveProblem } from './activeProblem';
import { ArtifactFileSystemProvider, SCHEME } from './artifactFs';
import { registerCommands } from './commands';
import { DeclaredIndex } from './declared';
import { registerDecorations } from './decorations';
import { registerDiagnostics } from './diagnostics';
import { registerDispatch } from './dispatch';
import { registerInteractionDecorations } from './interactionDecorations';
import { initLog, log } from './log';
import { PROPOSED_SCHEME, ProposedFileSystemProvider } from './proposedFs';
import { CONTEST_FILE_GLOB, CONTEST_MANIFEST, isContestVariantFile } from './rbx/contest';
import { resetBuildDirs, resolveBuildDir } from './rbx/environment';
import {
  ArtifactEvent,
  PackageEvent,
  classifyCachePath,
  classifyPath,
  planRefresh,
} from './rbx/artifactEvents';
import { Coalescer } from './rbx/coalescer';
import {
  CACHE_DIR,
  Ext,
  PROBLEM_MANIFEST,
  STRESS_DIR,
  STRESS_MANIFEST,
  TESTSET_MANIFEST,
} from './rbx/layout';
import { RunDataProvider } from './runData';
import { RunViewProvider } from './runView';
import { registerSolutionLens } from './solutionLens';
import { registerTestplanLens } from './testplanLens';
import { registerSolutionStatus } from './solutionStatus';
import { registerStatementDiagnostics } from './statementDiagnostics';
import { registerStatementPreview } from './statementPreview';
import { StatementReports } from './statementReports';
import { registerStatementVarHints } from './statementVarHints';
import { StatementVarsIndex } from './statementVarsIndex';
import { StressLauncher } from './stressLauncher';
import { StressPromoter } from './stressPromote';
import { StressViewProvider } from './stressView';
import { TestsetPanel } from './testsetPanel';
import { TestsetViewProvider } from './testsetView';
import { openVisualization } from './visualizationPanel';

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

  const panes = registerCommands(context, view, data, active, testset);
  const dispatcher = registerDispatch(context, active, declared, view);
  registerTestplanLens(context, declared, dispatcher, panes);
  // The third view in the container, on the same `data` and `active` as the
  // other two. It needs the dispatcher, which is why it is built only here.
  const stress = new StressViewProvider(
    data,
    active,
    dispatcher,
    context.workspaceState,
    context.extensionUri,
  );
  // Promote answers the view's `rbx.stress.promote`; its script-group
  // proposals live in `proposed`, the one writable scheme the extension has.
  const proposed = new ProposedFileSystemProvider();
  const promoter = new StressPromoter(stress, dispatcher, proposed);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(StressViewProvider.viewType, stress),
    vscode.commands.registerCommand('rbx.stress.new', () => stress.newStress()),
    vscode.commands.registerCommand('rbx.stress.stop', () => stress.stop()),
    vscode.workspace.registerFileSystemProvider(PROPOSED_SCHEME, proposed, {
      isCaseSensitive: true,
    }),
    promoter,
    vscode.commands.registerCommand('rbx.stress.promote', (args: unknown) => promoter.promote(args)),
    vscode.commands.registerCommand('rbx.proposal.accept', (uri: unknown) => promoter.accept(uri)),
    vscode.commands.registerCommand('rbx.proposal.discard', (uri: unknown) => promoter.discard(uri)),
    // The view names the intent (`OpenLauncherArgs`) and this answers it; the
    // launcher checks the argument itself, since a command takes anything.
    vscode.commands.registerCommand('rbx.stress.openLauncher', (args: unknown) =>
      StressLauncher.open(
        {
          extensionUri: context.extensionUri,
          memento: context.workspaceState,
          dispatcher,
          onDidChange: data.onDidChange,
          vars: statementVars,
        },
        args,
      ),
    ),
  );
  // One watcher over every statement build report, shared by the preview and
  // the Problems panel so a finished build is read once.
  const statementReports = new StatementReports();
  context.subscriptions.push(statementReports);
  registerStatementPreview({ context, reports: statementReports, declared, active, dispatcher });
  registerStatementDiagnostics(context, statementReports);
  registerInteractionDecorations(context);

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

  // Artifacts land incrementally as evaluations resolve, which is what gives
  // the view live progress without any streaming protocol: each new `.eval`
  // fills in one testcase. Events are classified as they arrive -- *which*
  // artifact moved, not just which package (artifactEvents.ts) -- and batched,
  // so a store re-reads exactly the files a batch named (#902).
  //
  // The batch has a ceiling as well as a quiet period: a run whose events come
  // faster than the quiet period would otherwise never be flushed, and the view
  // would sit still until the run paused or ended.
  const batches = new Coalescer<PackageEvent>((batch) => {
    const byRoot = new Map<string, ArtifactEvent[]>();
    for (const { root, event } of batch) {
      const events = byRoot.get(root) ?? [];
      events.push(event);
      byRoot.set(root, events);
    }
    for (const [root, events] of byRoot) {
      data.apply(root, planRefresh(events));
    }
  }, { wait: 200, maxWait: 1000 });
  context.subscriptions.push(new vscode.Disposable(() => batches.dispose()));

  const touched = (uri: vscode.Uri) => {
    const classified = classifyPath(uri.fsPath, testsetRootOf);
    if (classified !== undefined) {
      batches.push(classified);
    }
  };

  const watch = (glob: string) => {
    const watcher = vscode.workspace.createFileSystemWatcher(glob);
    watcher.onDidCreate(touched);
    watcher.onDidChange(touched);
    watcher.onDidDelete(touched);
    context.subscriptions.push(watcher);
  };

  // Only what something here reads. `.rbx` also holds the file cacher's
  // storage, the dependency caches, remote and judge state, `runs/.irun` and
  // the bulk of `runs/.stress` -- all of which churn through a build or a
  // stress test, and each write used to schedule a reload of a run that had
  // not changed.
  //
  // The cache directory itself, and `runs/` itself, because removing either is
  // reported as that one directory and nothing under it: `rbx clean` removes
  // `.rbx`, and a new run wipes `runs/` before writing its skeleton.
  watch(`**/${CACHE_DIR}`);
  watch(`**/${CACHE_DIR}/runs`);
  watch(`**/${CACHE_DIR}/runs/{skeleton.yml,report.yml}`);
  // Numeric solution directories only: `.irun` and `.stress` live under
  // `runs/` too. The classifier checks the same shape, since a glob is a
  // filter on the watcher, not a promise about what reaches it.
  watch(`**/${CACHE_DIR}/runs/[0-9]*/*/*${Ext.Eval}`);
  // The stress session, through its manifest alone: rbx rewrites it whenever a
  // finding lands (and at most once a second for the counters), so it is the
  // one file that says the session moved. A finding's own files are opened on
  // demand, and the scratch area beside them is overwritten every iteration --
  // watching either would wake the views as fast as the stress loop spins.
  // `.stress` itself too, which a new session replaces as one directory.
  watch(`**/${CACHE_DIR}/runs/${STRESS_DIR}`);
  watch(`**/${CACHE_DIR}/runs/${STRESS_DIR}/${STRESS_MANIFEST}`);

  // The testset manifest, which `rbx build` writes last (design D2). Written
  // last is what lets this be a single glob rather than a heuristic about when
  // a build has settled -- when it lands, everything it names is already on
  // disk.
  //
  // The glob cannot name the build directory, because its name comes from the
  // preset and differs per workspace; `testsetRootOf` is what decides whether
  // a given `testset.yml` is one of ours, and a stray one maps to no package.
  watch(`**/${TESTSET_MANIFEST}`);

  // A different question: the watchers above ask *what changed*, this one asks
  // *what is running*. `skeleton.yml` is written when a run starts
  // (rbx/box/solutions.py -- "A new skeleton is what marks a new run"), so
  // following it makes the view track the problem being run: `rbx contest each
  // run` walks the view through the contest in step with the run itself.
  //
  // Create and change only, never delete: `rbx clean` removes the skeleton,
  // and switching to a package whose run was just deleted is the opposite of
  // following work.
  const skeletons = vscode.workspace.createFileSystemWatcher(
    `**/${CACHE_DIR}/runs/skeleton.yml`,
  );
  const followRun = (uri: vscode.Uri) => {
    const classified = classifyCachePath(uri.fsPath);
    if (classified !== undefined) {
      void active.follow(classified.root);
    }
  };
  skeletons.onDidCreate(followRun);
  skeletons.onDidChange(followRun);
  context.subscriptions.push(skeletons);

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
    // And the visualizer buttons, which the store reads from the manifest.
    batches.push({ root: path.dirname(uri.fsPath), event: { kind: 'manifest' } });
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
      // Which contests a dispatch could run under lives in the same files.
      void dispatcher.refreshStatus();
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
