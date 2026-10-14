import * as assert from 'assert';
import { test } from 'node:test';

import { FileSystem, Limiter, YamlFileCache } from './fileReader';

function errno(code: string): Error {
  return Object.assign(new Error(`${code}: boom`), { code });
}

/** An in-memory filesystem that counts reads. */
class MemoryFs implements FileSystem {
  readonly files = new Map<string, { text: string; mtimeMs: number }>();
  readonly failures = new Map<string, string>();
  reads = 0;

  write(filePath: string, text: string, mtimeMs: number): void {
    this.files.set(filePath, { text, mtimeMs });
  }

  async stat(filePath: string): Promise<{ mtimeMs: number; size: number }> {
    const failure = this.failures.get(filePath);
    if (failure !== undefined) {
      throw errno(failure);
    }
    const file = this.files.get(filePath);
    if (file === undefined) {
      throw errno('ENOENT');
    }
    return { mtimeMs: file.mtimeMs, size: file.text.length };
  }

  async readFile(filePath: string): Promise<string> {
    this.reads += 1;
    const file = this.files.get(filePath);
    if (file === undefined) {
      throw errno('ENOENT');
    }
    return file.text;
  }
}

test('an unchanged file is parsed once', async () => {
  const fs = new MemoryFs();
  fs.write('/a.eval', 'outcome: accepted', 1);
  const cache = new YamlFileCache(new Limiter(4), fs);

  const first = await cache.read('/a.eval');
  const second = await cache.read('/a.eval');

  assert.deepStrictEqual(first, { kind: 'ok', value: { outcome: 'accepted' } });
  assert.deepStrictEqual(second, first);
  assert.strictEqual(fs.reads, 1);
  assert.deepStrictEqual(cache.stats, { reads: 1, hits: 1, missing: 0, errors: 0 });
});

test('a rewritten file is read again', async () => {
  const fs = new MemoryFs();
  fs.write('/a.eval', 'outcome: accepted', 1);
  const cache = new YamlFileCache(new Limiter(4), fs);
  await cache.read('/a.eval');

  fs.write('/a.eval', 'outcome: wrong-answer', 2);

  assert.deepStrictEqual(await cache.read('/a.eval'), {
    kind: 'ok',
    value: { outcome: 'wrong-answer' },
  });
});

test('a missing file and a failed read are different results', async () => {
  const fs = new MemoryFs();
  fs.failures.set('/busy.eval', 'EMFILE');
  const cache = new YamlFileCache(new Limiter(4), fs);

  assert.deepStrictEqual(await cache.read('/nowhere.eval'), { kind: 'missing' });
  assert.deepStrictEqual(await cache.read('/busy.eval'), {
    kind: 'error',
    message: 'EMFILE: boom',
  });
});

test('a failed read is retried rather than remembered', async () => {
  const fs = new MemoryFs();
  fs.write('/a.eval', 'outcome: accepted', 1);
  fs.failures.set('/a.eval', 'EIO');
  const cache = new YamlFileCache(new Limiter(4), fs);
  assert.strictEqual((await cache.read('/a.eval')).kind, 'error');

  fs.failures.delete('/a.eval');

  assert.strictEqual((await cache.read('/a.eval')).kind, 'ok');
});

test('text caught mid-write reads as not there yet', async () => {
  const fs = new MemoryFs();
  fs.write('/a.eval', 'result: {outcome: [', 1);
  const cache = new YamlFileCache(new Limiter(4), fs);

  assert.deepStrictEqual(await cache.read('/a.eval'), { kind: 'missing' });
});

test('the limiter never runs more than its limit at once', async () => {
  const limiter = new Limiter(3);
  let active = 0;
  let peak = 0;
  const task = async () => {
    active += 1;
    peak = Math.max(peak, active);
    await new Promise((resolve) => setImmediate(resolve));
    active -= 1;
  };

  await Promise.all(Array.from({ length: 50 }, () => limiter.run(task)));

  assert.strictEqual(peak, 3);
  assert.strictEqual(active, 0);
});

test('a task that throws still frees its slot', async () => {
  const limiter = new Limiter(1);

  await assert.rejects(limiter.run(() => Promise.reject(new Error('no'))));

  assert.strictEqual(await limiter.run(async () => 42), 42);
});
