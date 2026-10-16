import * as assert from 'assert';
import { test } from 'node:test';

import { expandLangTemplate, langTemplatePattern } from './langTemplate';

/** A fake directory tree: directory -> its entries. */
function readdirOf(tree: Record<string, string[]>) {
  return async (dir: string) => tree[dir] ?? [];
}

test('a path without {lang} is returned as is, even when it does not exist', async () => {
  assert.deepStrictEqual(await expandLangTemplate('/p/statement.rbx.tex', readdirOf({})), [
    '/p/statement.rbx.tex',
  ]);
});

test('{lang} in a file name expands to every file that fits it', async () => {
  const readdir = readdirOf({
    '/p/documents': ['statement-en.rbx.tex', 'statement-pt.rbx.tex', 'tutorial-en.rbx.tex', 'assets'],
  });
  const expanded = await expandLangTemplate('/p/documents/statement-{lang}.rbx.tex', readdir);
  assert.deepStrictEqual(expanded.sort(), [
    '/p/documents/statement-en.rbx.tex',
    '/p/documents/statement-pt.rbx.tex',
  ]);
});

test('{lang} in a directory expands too, binding one language for the whole path', async () => {
  const readdir = readdirOf({
    '/p': ['en', 'pt', 'problem.rbx.yml'],
    '/p/en': ['statement-en.tex', 'statement-pt.tex'],
    '/p/pt': ['statement-pt.tex'],
  });
  const expanded = await expandLangTemplate('/p/{lang}/statement-{lang}.tex', readdir);
  assert.deepStrictEqual(expanded.sort(), ['/p/en/statement-en.tex', '/p/pt/statement-pt.tex']);
});

test('a template pattern matches the paths it could expand to, one language throughout', () => {
  const pattern = langTemplatePattern('/p/{lang}/statement-{lang}.rbx.tex');
  assert.ok(pattern !== undefined);
  assert.ok(pattern.test('/p/pt/statement-pt.rbx.tex'));
  assert.ok(!pattern.test('/p/pt/statement-en.rbx.tex'));
  assert.ok(!pattern.test('/p/pt/statement-pt.rbx.texx'));
  // Dots are literal, not "any character".
  assert.ok(!pattern.test('/p/pt/statement-ptXrbxXtex'));
  assert.strictEqual(langTemplatePattern('/p/statement.rbx.tex'), undefined);
});

test('a template that fits no file expands to nothing', async () => {
  assert.deepStrictEqual(
    await expandLangTemplate('/p/missing/statement-{lang}.tex', readdirOf({})),
    [],
  );
});
