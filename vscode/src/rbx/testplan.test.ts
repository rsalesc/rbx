import * as assert from 'assert';
import { test } from 'node:test';

import cases from './testplan.cases.json';
import {
  generateArgs,
  parseGenerated,
  selector,
  statementAt,
  testplanStatements,
  validationSummary,
} from './testplan';

// The same cases tests/rbx/box/stressing/testplan_cases_test.py holds rbx's
// own parser to, so the two cannot drift apart.
for (const each of cases) {
  test(`testplanStatements agrees with rbx: ${each.name}`, () => {
    assert.deepStrictEqual(testplanStatements(each.script), each.statements);
  });
}

test('testplanStatements tolerates CRLF and an unterminated block', () => {
  assert.deepStrictEqual(testplanStatements('gen 1\r\n@input {\r\n1\r\n'), [
    { line: 1, endLine: 1, kind: 'call' },
    { line: 2, endLine: 4, kind: 'input' },
  ]);
});

test('statementAt finds the statement a line belongs to', () => {
  const statements = testplanStatements('gen 1\n\n@input {\n1\n}\ngen 2\n');
  assert.strictEqual(statementAt(statements, 1)?.line, 1);
  assert.strictEqual(statementAt(statements, 2), undefined);
  assert.strictEqual(statementAt(statements, 4)?.line, 3);
  assert.strictEqual(statementAt(statements, 6)?.line, 6);
});

test('selector is package-relative with forward slashes', () => {
  assert.strictEqual(selector('tests\\plan.txt', 12), 'tests/plan.txt:12');
});

test('argv for generate', () => {
  assert.deepStrictEqual(generateArgs('p.txt:3', { output: true }), [
    'testcases',
    'generate',
    'p.txt:3',
    '--output',
    '--json',
  ]);
  assert.deepStrictEqual(generateArgs('p.txt:3', { validate: true }), [
    'testcases',
    'generate',
    'p.txt:3',
    '--validate',
    '--json',
  ]);
});

const GENERATED = {
  test: 'gen/1',
  source: 'tests/plan.txt:4',
  call: 'gen 5',
  input: '/p/build/tests/gen/001.in',
  answer: null,
  validation: [{ validator: 'validator.cpp', ok: false, message: 'N out of range\n' }],
};

test('parseGenerated reads the last JSON line', () => {
  const parsed = parseGenerated(`Compiling…\n${JSON.stringify(GENERATED)}\n`);
  assert.deepStrictEqual(parsed, {
    test: 'gen/1',
    source: 'tests/plan.txt:4',
    call: 'gen 5',
    input: '/p/build/tests/gen/001.in',
    answer: undefined,
    validation: [{ validator: 'validator.cpp', ok: false, message: 'N out of range\n' }],
  });
});

test('parseGenerated refuses another shape', () => {
  assert.strictEqual(parseGenerated('{"test": "gen/1"}'), undefined);
  assert.strictEqual(
    parseGenerated(JSON.stringify({ ...GENERATED, validation: [{ ok: 'yes' }] })),
    undefined,
  );
  assert.strictEqual(parseGenerated(JSON.stringify({ ...GENERATED, answer: 3 })), undefined);
});

test('validationSummary says who rejected it and why', () => {
  const parsed = parseGenerated(JSON.stringify(GENERATED));
  assert.ok(parsed !== undefined);
  assert.deepStrictEqual(validationSummary(parsed), {
    ok: false,
    text: 'tests/plan.txt:4 (gen/1) is invalid. validator.cpp: N out of range',
  });
  assert.deepStrictEqual(
    validationSummary({ ...parsed, validation: [{ validator: 'v.cpp', ok: true }] }),
    { ok: true, text: 'tests/plan.txt:4 (gen/1) is valid: v.cpp accepted it.' },
  );
  assert.deepStrictEqual(validationSummary({ ...parsed, validation: [] }), {
    ok: true,
    text: 'No validator applies to tests/plan.txt:4 (gen/1).',
  });
});
