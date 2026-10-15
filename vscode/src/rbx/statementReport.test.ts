import * as assert from 'assert';
import { test } from 'node:test';

import {
  StatementOutput,
  defaultOutput,
  outputLabel,
  parseStatementReport,
  saveTargets,
  statementDiagnostics,
  statementReportPath,
} from './statementReport';

const ROOT = '/w/a';

function report(...outputs: object[]): unknown {
  return { version: 1, outputs };
}

const EN = {
  kind: 'statement',
  language: 'en',
  variant: 'default',
  format: 'pdf',
  path: 'build/statement-en.pdf',
  source: 'statement/statement.rbx.tex',
  status: 'ok',
  builtAt: '2026-10-15T00:00:00Z',
  seconds: 1.5,
};

const FAILED_PT = {
  ...EN,
  language: 'pt',
  path: 'build/statement-pt.pdf',
  source: 'statement/statement-pt.rbx.tex',
  status: 'failed',
  findings: [
    {
      origin: 'latex',
      severity: 'error',
      message: 'Undefined control sequence.',
      file: 'statement/statement-pt.rbx.tex',
      line: 3,
      context: '\\foo',
    },
    { origin: 'latex', severity: 'error', message: 'Emergency stop.' },
  ],
};

test('the report lives in the cache dir', () => {
  assert.strictEqual(statementReportPath(ROOT), '/w/a/.rbx/statements/report.yml');
});

test('paths resolve against the root; absolute ones stay put', () => {
  const [output] = parseStatementReport(
    report({ ...EN, source: '/presets/default/statement.rbx.tex' }),
    ROOT,
    'problem',
  );
  assert.strictEqual(output.path, '/w/a/build/statement-en.pdf');
  assert.strictEqual(output.source, '/presets/default/statement.rbx.tex');
  assert.strictEqual(output.ok, true);
  assert.deepStrictEqual(output.findings, []);
});

test('an unknown version reads as empty', () => {
  assert.deepStrictEqual(parseStatementReport({ version: 2, outputs: [EN] }, ROOT, 'problem'), []);
  assert.deepStrictEqual(parseStatementReport('garbage', ROOT, 'problem'), []);
});

test('an entry without kind, format or path is skipped', () => {
  const outputs = parseStatementReport(
    report({ ...EN, path: undefined }, { ...EN, kind: 3 }, EN),
    ROOT,
    'problem',
  );
  assert.strictEqual(outputs.length, 1);
});

test('findings are parsed, and a line below 1 reads as unlocated', () => {
  const [output] = parseStatementReport(
    report({ ...FAILED_PT, findings: [{ message: 'x', line: 0, file: 'a.tex' }] }),
    ROOT,
    'problem',
  );
  assert.strictEqual(output.ok, false);
  assert.deepStrictEqual(output.findings, [
    { origin: 'build', severity: 'error', message: 'x', file: '/w/a/a.tex', line: undefined, context: undefined },
  ]);
});

test('ids are stable and distinct', () => {
  const first = parseStatementReport(report(EN, FAILED_PT), ROOT, 'problem');
  const again = parseStatementReport(report(FAILED_PT, EN), ROOT, 'problem');
  assert.notStrictEqual(first[0].id, first[1].id);
  assert.deepStrictEqual(
    first.map((output) => output.id).sort(),
    again.map((output) => output.id).sort(),
  );
});

test('labels name what differs and leave the defaults unsaid', () => {
  const [en] = parseStatementReport(report(EN), ROOT, 'problem');
  assert.strictEqual(outputLabel(en), 'statement · en');
  const [variant] = parseStatementReport(report({ ...EN, variant: 'icpc', format: 'tex' }), ROOT, 'problem');
  assert.strictEqual(outputLabel(variant), 'statement · en · icpc · tex');
  const [contest] = parseStatementReport(report({ ...EN, name: 'main-en' }), '/w', 'contest');
  assert.strictEqual(outputLabel(contest), 'contest statement main-en');
});

function outputs(): StatementOutput[] {
  return [
    ...parseStatementReport(
      report(
        { ...EN, kind: 'tutorial', path: 'build/tutorial-en.pdf', source: 'statement/editorial.rbx.tex' },
        { ...EN, format: 'tex', path: 'build/statement-en.tex' },
        EN,
        FAILED_PT,
      ),
      ROOT,
      'problem',
    ),
    ...parseStatementReport(report({ ...EN, name: 'main-en', source: 'statements/contest.rbx.tex' }), '/w', 'contest'),
  ];
}

test('the default keeps the current choice while it exists', () => {
  const all = outputs();
  const pt = all.find((output) => output.language === 'pt');
  assert.strictEqual(defaultOutput(all, '/w/a/statement/statement.rbx.tex', pt?.id), pt);
});

test('the default follows the file being edited, preferring its PDF', () => {
  const picked = defaultOutput(outputs(), '/w/a/statement/statement.rbx.tex');
  assert.strictEqual(picked?.path, '/w/a/build/statement-en.pdf');
  const tutorial = defaultOutput(outputs(), '/w/a/statement/editorial.rbx.tex');
  assert.strictEqual(tutorial?.kind, 'tutorial');
  const contest = defaultOutput(outputs(), '/w/statements/contest.rbx.tex');
  assert.strictEqual(contest?.scope, 'contest');
});

test('with nothing to go on, a problem statement PDF wins', () => {
  const picked = defaultOutput(outputs(), '/elsewhere.txt');
  assert.strictEqual(picked?.kind, 'statement');
  assert.strictEqual(picked?.scope, 'problem');
  assert.strictEqual(picked?.format, 'pdf');
  assert.strictEqual(defaultOutput([]), undefined);
});

test('diagnostics: located ones on their line, unlocated on the source top', () => {
  const [pt] = parseStatementReport(report(FAILED_PT), ROOT, 'problem');
  assert.deepStrictEqual(statementDiagnostics([pt]), [
    {
      origin: 'latex',
      path: '/w/a/statement/statement-pt.rbx.tex',
      line: 2,
      severity: 'error',
      message: 'Undefined control sequence.\n\\foo',
      outputs: ['statement · pt'],
    },
    {
      origin: 'latex',
      path: '/w/a/statement/statement-pt.rbx.tex',
      line: 0,
      severity: 'error',
      message: 'Emergency stop.',
      outputs: ['statement · pt'],
    },
  ]);
});

test('diagnostics: one error two outputs share is reported once', () => {
  const shared = {
    origin: 'latex',
    severity: 'error',
    message: 'Missing $ inserted.',
    file: '/chrome/template.rbx.tex',
    line: 14,
  };
  const parsed = parseStatementReport(
    report(
      { ...FAILED_PT, findings: [shared] },
      { ...FAILED_PT, language: 'en', path: 'build/statement-en.pdf', findings: [shared] },
    ),
    ROOT,
    'problem',
  );
  const diagnostics = statementDiagnostics(parsed);
  assert.strictEqual(diagnostics.length, 1);
  assert.deepStrictEqual([...diagnostics[0].outputs].sort(), ['statement · en', 'statement · pt']);
});

test('diagnostics: an ok output reports nothing', () => {
  assert.deepStrictEqual(statementDiagnostics(parseStatementReport(report(EN), ROOT, 'problem')), []);
});

test('a save rebuilds what is built from the file, else what sits beside it', () => {
  const parsed = parseStatementReport(
    report(EN, {
      ...EN,
      kind: 'tutorial',
      path: 'build/tutorial-en.pdf',
      source: 'statement/editorial.rbx.tex',
    }),
    ROOT,
    'problem',
  );
  assert.deepStrictEqual(saveTargets(parsed, '/w/a/statement/editorial.rbx.tex'), [
    { command: 'tutorials', root: ROOT },
  ]);
  assert.deepStrictEqual(saveTargets(parsed, '/w/a/statement/imgs/fig.png'), [
    { command: 'statements', root: ROOT },
    { command: 'tutorials', root: ROOT },
  ]);
  assert.deepStrictEqual(saveTargets(parsed, '/w/a/sols/main.cpp'), []);
});
