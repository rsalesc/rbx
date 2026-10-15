import * as assert from 'assert';
import { test } from 'node:test';

import { StatementOutput } from './statementReport';
import { findingItems, previewModel, summaryOf } from './statementPreviewModel';

function output(over: Partial<StatementOutput> = {}): StatementOutput {
  return {
    id: 'en',
    scope: 'problem',
    root: '/w/a',
    kind: 'statement',
    language: 'en',
    variant: 'default',
    format: 'pdf',
    path: '/w/a/build/statement-en.pdf',
    source: '/w/a/statement/statement.rbx.tex',
    ok: true,
    seconds: 1.42,
    findings: [],
    ...over,
  };
}

test('the summary says how the last build went and how long it took', () => {
  assert.strictEqual(summaryOf(output()), 'built · 1.4s');
  assert.strictEqual(summaryOf(output({ ok: false, seconds: undefined })), 'failed');
  const at = new Date(2026, 9, 15, 9, 5);
  assert.strictEqual(summaryOf(output({ builtAt: at.toISOString() })), 'built 09:05 · 1.4s');
  assert.strictEqual(summaryOf(output({ builtAt: 'not a date', seconds: undefined })), 'built');
});

test('findings show where, relative to the root when inside it', () => {
  const items = findingItems(
    output({
      ok: false,
      findings: [
        { origin: 'latex', severity: 'error', message: 'a', file: '/w/a/statement/s.rbx.tex', line: 3 },
        { origin: 'latex', severity: 'error', message: 'b', file: '/chrome/t.rbx.tex', line: 9 },
        { origin: 'latex', severity: 'error', message: 'c' },
      ],
    }),
  );
  assert.deepStrictEqual(items, [
    { index: 0, where: 'statement/s.rbx.tex:3', message: 'a' },
    { index: 1, where: '/chrome/t.rbx.tex:9', message: 'b' },
    { index: 2, where: undefined, message: 'c' },
  ]);
});

test('with no outputs the panel offers to build', () => {
  const model = previewModel({ outputs: [], exists: false, building: false });
  assert.deepStrictEqual(model.outputs, []);
  assert.strictEqual(model.empty?.action, 'build');
});

test('an output that never built offers to build it', () => {
  const selected = output({ ok: false });
  const model = previewModel({ outputs: [selected], selected, exists: false, building: true });
  assert.strictEqual(model.empty?.action, 'build');
  assert.strictEqual(model.building, true);
  assert.strictEqual(model.selected, 'en');
});

test('a built PDF has nothing in the way', () => {
  const selected = output({ log: '/w/a/build/statements/st/en-default/statement.log' });
  const model = previewModel({ outputs: [selected], selected, exists: true, building: false });
  assert.strictEqual(model.empty, undefined);
  assert.strictEqual(model.hasLog, true);
  assert.strictEqual(model.hasSource, true);
  assert.deepStrictEqual(model.outputs, [{ id: 'en', label: 'statement · en', ok: true }]);
});

test('a non-PDF output is opened, not rendered', () => {
  const selected = output({ format: 'md', path: '/w/a/build/statement-en.md' });
  const model = previewModel({ outputs: [selected], selected, exists: true, building: false });
  assert.strictEqual(model.empty?.action, 'open');
  assert.match(model.empty?.message ?? '', /Markdown/);
});
