/**
 * A writable, in-memory filesystem for proposed edits, under `rbx-proposed:`.
 *
 * The right side of a promotion's diff (#908). It has to be a document the
 * user can edit -- the point of proposing the generator call rather than
 * writing it is that they can reword the comment or tweak the line first --
 * and it must not be the real file, which nothing may touch until Accept.
 * An untitled document would do the first and not the second's job of a
 * stable name: its tab would read `Untitled-1`, where this one reads as the
 * script it proposes to change.
 *
 * The URI path is the script's path relative to the package, so the tab is
 * titled after it; the query tells two proposals for the same script apart.
 * Nothing here ever reaches disk, and an entry lives only as long as the
 * proposal does (`drop`). So a diff tab VS Code restores after a window
 * reload opens on FileNotFound: the proposal died with the window that made
 * it, and promoting again is the way back.
 *
 * An entry may be marked read-only: the empty left side standing in for a
 * script that does not exist yet, which there is nothing to edit in.
 */
import * as vscode from 'vscode';

export const PROPOSED_SCHEME = 'rbx-proposed';

interface Entry {
  data: Uint8Array;
  mtime: number;
  readonly ctime: number;
  readonly readonly: boolean;
}

export class ProposedFileSystemProvider implements vscode.FileSystemProvider {
  private readonly files = new Map<string, Entry>();
  private readonly emitter = new vscode.EventEmitter<vscode.FileChangeEvent[]>();
  readonly onDidChangeFile = this.emitter.event;

  /** Hold `text` at `uri`, replacing whatever was there. */
  put(uri: vscode.Uri, text: string, readonly = false): void {
    const now = Date.now();
    this.files.set(uri.toString(), {
      data: new TextEncoder().encode(text),
      mtime: now,
      ctime: now,
      readonly,
    });
  }

  /** What `uri` holds, or undefined once it was dropped. */
  text(uri: vscode.Uri): string | undefined {
    const file = this.files.get(uri.toString());
    return file === undefined ? undefined : new TextDecoder().decode(file.data);
  }

  drop(uri: vscode.Uri): void {
    this.files.delete(uri.toString());
  }

  watch(): vscode.Disposable {
    // Only VS Code's own saves write these files, and it already knows.
    return new vscode.Disposable(() => undefined);
  }

  stat(uri: vscode.Uri): vscode.FileStat {
    const file = this.entry(uri);
    return {
      type: vscode.FileType.File,
      ctime: file.ctime,
      mtime: file.mtime,
      size: file.data.byteLength,
      ...(file.readonly ? { permissions: vscode.FilePermission.Readonly } : {}),
    };
  }

  readFile(uri: vscode.Uri): Uint8Array {
    return this.entry(uri).data;
  }

  writeFile(uri: vscode.Uri, content: Uint8Array): void {
    // Saving into a proposal that was already accepted or discarded would
    // bring it back with nothing to apply it to: `entry` refuses.
    const file = this.entry(uri);
    if (file.readonly) {
      throw vscode.FileSystemError.NoPermissions(uri);
    }
    file.data = content;
    file.mtime = Date.now();
    // No change event: the only writer is the editor's own save, and telling
    // it about its own write would only make it re-read what it just wrote.
  }

  readDirectory(): [string, vscode.FileType][] {
    return [];
  }

  createDirectory(uri: vscode.Uri): void {
    throw vscode.FileSystemError.NoPermissions(uri);
  }

  delete(uri: vscode.Uri): void {
    throw vscode.FileSystemError.NoPermissions(uri);
  }

  rename(uri: vscode.Uri): void {
    throw vscode.FileSystemError.NoPermissions(uri);
  }

  private entry(uri: vscode.Uri): Entry {
    const file = this.files.get(uri.toString());
    if (file === undefined) {
      throw vscode.FileSystemError.FileNotFound(uri);
    }
    return file;
  }
}
