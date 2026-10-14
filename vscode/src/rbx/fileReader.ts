/**
 * Reading many small YAML artifacts without hurting anyone.
 *
 * Three things the store used to get wrong on a large run (#902), each fixed
 * here once:
 *
 *   - **Unbounded fan-out.** Every `.eval` of the run was read in one
 *     `Promise.all`, which on a big package is tens of thousands of open files
 *     at once -- enough to hit `EMFILE`. Reads now go through a `Limiter`.
 *   - **Errors read as absence.** Any failure, `EMFILE` included, became "no
 *     evaluation", so a testcase that *had* a verdict rendered as pending. A
 *     missing file and a failed read are now different results.
 *   - **No reuse.** A full reload re-read and re-parsed files it had already
 *     read. Results are now cached by path and `(mtime, size)`; a stat is the
 *     whole cost of an unchanged file.
 */
import * as fs from 'fs/promises';
import { parse as parseYaml } from 'yaml';

export type ReadResult =
  /** No such file -- for a run artifact, "not there yet". */
  | { readonly kind: 'missing' }
  | { readonly kind: 'ok'; readonly value: unknown }
  /** The file exists, or may, but could not be read. Never cached. */
  | { readonly kind: 'error'; readonly message: string };

const MISSING: ReadResult = { kind: 'missing' };

/** Runs at most `limit` tasks at once, in the order they were asked for. */
export class Limiter {
  private active = 0;
  private readonly queue: Array<() => void> = [];

  constructor(private readonly limit: number) {}

  async run<T>(task: () => Promise<T>): Promise<T> {
    if (this.active >= this.limit) {
      await new Promise<void>((resolve) => this.queue.push(resolve));
    } else {
      this.active += 1;
    }
    try {
      return await task();
    } finally {
      const next = this.queue.shift();
      if (next !== undefined) {
        // The slot passes straight to the next task; `active` is unchanged.
        next();
      } else {
        this.active -= 1;
      }
    }
  }
}

/** The subset of `fs/promises` the cache uses, injectable for tests. */
export interface FileSystem {
  stat(path: string): Promise<{ mtimeMs: number; size: number }>;
  readFile(path: string, encoding: 'utf8'): Promise<string>;
}

function isMissing(error: unknown): boolean {
  const code = (error as NodeJS.ErrnoException | undefined)?.code;
  // ENOTDIR: a parent was replaced by a file, or a dangling symlink in the way.
  return code === 'ENOENT' || code === 'ENOTDIR';
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

interface Entry {
  readonly mtimeMs: number;
  readonly size: number;
  readonly value: unknown;
}

/** What a cache has done since it was made, for the reload log line. */
export interface ReadStats {
  /** Files actually read and parsed. */
  reads: number;
  /** Files whose cached parse was reused after a stat. */
  hits: number;
  missing: number;
  errors: number;
}

export function emptyStats(): ReadStats {
  return { reads: 0, hits: 0, missing: 0, errors: 0 };
}

export class YamlFileCache {
  private readonly entries = new Map<string, Entry>();
  readonly stats: ReadStats = emptyStats();

  constructor(
    private readonly limiter: Limiter = new Limiter(32),
    private readonly files: FileSystem = fs,
  ) {}

  /**
   * Read and parse one file, reusing the last parse if it has not changed.
   *
   * Text that does not parse reads as `missing`, not `error`: it is a file
   * caught mid-write by a reader racing an older rbx, and the event for the
   * finished write will bring the reader back.
   */
  read(filePath: string): Promise<ReadResult> {
    return this.limiter.run(() => this.readNow(filePath));
  }

  forget(filePath: string): void {
    this.entries.delete(filePath);
  }

  clear(): void {
    this.entries.clear();
  }

  private async readNow(filePath: string): Promise<ReadResult> {
    let stat: { mtimeMs: number; size: number };
    try {
      stat = await this.files.stat(filePath);
    } catch (error) {
      return this.failed(filePath, error);
    }
    const cached = this.entries.get(filePath);
    if (cached !== undefined && cached.mtimeMs === stat.mtimeMs && cached.size === stat.size) {
      this.stats.hits += 1;
      return { kind: 'ok', value: cached.value };
    }
    let text: string;
    try {
      text = await this.files.readFile(filePath, 'utf8');
    } catch (error) {
      return this.failed(filePath, error);
    }
    this.stats.reads += 1;
    let value: unknown;
    try {
      value = parseYaml(text);
    } catch {
      this.entries.delete(filePath);
      this.stats.missing += 1;
      return MISSING;
    }
    this.entries.set(filePath, { mtimeMs: stat.mtimeMs, size: stat.size, value });
    return { kind: 'ok', value };
  }

  private failed(filePath: string, error: unknown): ReadResult {
    this.entries.delete(filePath);
    if (isMissing(error)) {
      this.stats.missing += 1;
      return MISSING;
    }
    this.stats.errors += 1;
    return { kind: 'error', message: describe(error) };
  }
}
