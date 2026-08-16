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

import { ArtifactFileSystemProvider, SCHEME } from './artifactFs';
import { registerCommands } from './commands';
import { initLog, log } from './log';
import { CACHE_DIR, PROBLEM_MANIFEST } from './rbx/layout';
import { RunTreeProvider } from './runTree';

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
  const tree = new RunTreeProvider();

  context.subscriptions.push(
    vscode.window.registerTreeDataProvider('rbx.run', tree),
    vscode.workspace.registerFileSystemProvider(SCHEME, new ArtifactFileSystemProvider(), {
      isReadonly: true,
      isCaseSensitive: true,
    }),
  );

  registerCommands(context, tree);

  // Artifacts land incrementally as evaluations resolve, which is what gives
  // the tree live progress without any streaming protocol: each new `.eval`
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
        tree.invalidate(changed);
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

  context.subscriptions.push(new vscode.Disposable(() => {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
  }));

  // A package appearing or disappearing changes the set of roots, not just
  // their contents, so it needs a full rediscovery.
  const manifests = vscode.workspace.createFileSystemWatcher(`**/${PROBLEM_MANIFEST}`);
  manifests.onDidCreate(() => tree.refresh());
  manifests.onDidDelete(() => tree.refresh());
  context.subscriptions.push(
    manifests,
    vscode.workspace.onDidChangeWorkspaceFolders(() => tree.refresh()),
  );

  void tree.refresh();
}

export function deactivate(): void {
  // Nothing to tear down: every disposable is registered on the context.
}
