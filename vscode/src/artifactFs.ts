/**
 * A read-only filesystem for rbx artifacts, under the `rbx:` scheme.
 *
 * Artifacts are already real files on disk, so we could open them directly --
 * but that invites the user to edit a generated file, and it gives every tab
 * the same useless title (`1-gen-000.out`, five times over). Instead the URI
 * *path* is a human-readable label whose last segment becomes the tab title,
 * and the real location travels in the query:
 *
 *   rbx:/sols%2Fwa.cpp/main/1-gen-000/output.out?<encoded absolute path>
 *
 * A FileSystemProvider is used rather than a TextDocumentContentProvider so
 * large testcases stream lazily instead of being held in memory as a string.
 */
import * as fs from 'fs/promises';
import * as vscode from 'vscode';

export const SCHEME = 'rbx';

/**
 * Build a URI that displays as `label` and reads from `realPath`.
 *
 * `label` is a slash-separated display path; its last segment is the tab title,
 * so it should carry the file extension to keep syntax highlighting.
 */
export function artifactUri(realPath: string, label: string): vscode.Uri {
  return vscode.Uri.from({
    scheme: SCHEME,
    path: label.startsWith('/') ? label : `/${label}`,
    query: encodeURIComponent(realPath),
  });
}

function realPathOf(uri: vscode.Uri): string {
  return decodeURIComponent(uri.query);
}

function notPermitted(uri: vscode.Uri): never {
  throw vscode.FileSystemError.NoPermissions(uri);
}

export class ArtifactFileSystemProvider implements vscode.FileSystemProvider {
  private readonly emitter = new vscode.EventEmitter<vscode.FileChangeEvent[]>();
  readonly onDidChangeFile = this.emitter.event;

  watch(): vscode.Disposable {
    // Artifacts are content-addressed symlinks: rbx replaces the link rather
    // than rewriting the target, so an open document never changes underneath
    // the user. Nothing to watch.
    return new vscode.Disposable(() => undefined);
  }

  async stat(uri: vscode.Uri): Promise<vscode.FileStat> {
    let stats;
    try {
      stats = await fs.stat(realPathOf(uri));
    } catch {
      throw vscode.FileSystemError.FileNotFound(uri);
    }
    return {
      type: vscode.FileType.File,
      ctime: stats.ctimeMs,
      mtime: stats.mtimeMs,
      size: stats.size,
      permissions: vscode.FilePermission.Readonly,
    };
  }

  async readFile(uri: vscode.Uri): Promise<Uint8Array> {
    try {
      return await fs.readFile(realPathOf(uri));
    } catch {
      throw vscode.FileSystemError.FileNotFound(uri);
    }
  }

  readDirectory(uri: vscode.Uri): [string, vscode.FileType][] {
    return notPermitted(uri);
  }

  createDirectory(uri: vscode.Uri): void {
    return notPermitted(uri);
  }

  writeFile(uri: vscode.Uri): void {
    return notPermitted(uri);
  }

  delete(uri: vscode.Uri): void {
    return notPermitted(uri);
  }

  rename(uri: vscode.Uri): void {
    return notPermitted(uri);
  }
}
