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
 * Events arrive as `<pkg>/.rbx/runs/...`, so the package root is the parent of
 * the `.rbx` segment.
 */
function packageRootOf(fsPath: string): string | undefined {
  const marker = `${path.sep}${CACHE_DIR}${path.sep}`;
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
  const watcher = vscode.workspace.createFileSystemWatcher(`**/${CACHE_DIR}/runs/**`);
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
        tree.invalidate(changed);
      }
      pending.clear();
    }, 200);
  };

  watcher.onDidCreate(touched);
  watcher.onDidChange(touched);
  watcher.onDidDelete(touched);
  context.subscriptions.push(watcher, new vscode.Disposable(() => {
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
