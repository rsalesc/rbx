import * as assert from 'assert';
import { test } from 'node:test';

import { buildDiagnostics, byFile } from './diagnostics';
import type { PackageLayout } from './layout';
import type { PackageRunView } from './nodes';
import type { CompilationEntry } from './model';
import type { CompilationFinding, PackageRun } from './store';

const PKG: PackageLayout = { root: '/w/a' };

function finding(path: string, over: Partial<CompilationEntry> = {}): CompilationFinding {
  return {
    entry: {
      path,
      expectedOutcome: 'ACCEPTED',
      status: 'WARNINGS',
      log: 'compilation/0.log',
      warnings: [],
      ...over,
    },
    logPath: '/w/a/.rbx/runs/compilation/0.log',
    sourcePath: `/w/a/${path}`,
  };
}

function view(findings: readonly CompilationFinding[]): PackageRunView {
  const run: PackageRun = {
    skeleton: {
      solutions: [],
      entries: [],
      groups: [],
      compilation: [],
      sanitized: false,
      onlyAccepted: false,
    },
    solutions: [],
    findings,
  };
  return { pkg: PKG, run };
}

test('a package with nothing to report produces no entries', () => {
  assert.deepStrictEqual(buildDiagnostics([view([])]), []);
});

test('a package that has never run produces no entries', () => {
  assert.deepStrictEqual(buildDiagnostics([{ pkg: PKG, run: undefined }]), []);
});

test('a warning lands on its own line, one-based to zero-based', () => {
  const [entry] = buildDiagnostics([
    view([
      finding('sols/main.cpp', {
        warnings: [{ file: 'sols/main.cpp', line: 22, flag: '-Wshadow', msg: 'shadows' }],
      }),
    ]),
  ]);
  assert.strictEqual(entry.path, '/w/a/sols/main.cpp');
  assert.strictEqual(entry.line, 21);
  assert.strictEqual(entry.severity, 'warning');
  assert.strictEqual(entry.message, 'shadows');
  assert.strictEqual(entry.flag, '-Wshadow');
});

test('a warning lands on the file the compiler named, not the one compiled', () => {
  // rbx keeps any first-party file that warned, so the two are not always the
  // same file -- and an entry on the wrong file is worse than no entry.
  const [entry] = buildDiagnostics([
    view([
      finding('sols/main.cpp', {
        warnings: [{ file: 'sols/common.cpp', line: 3, msg: 'x' }],
      }),
    ]),
  ]);
  assert.strictEqual(entry.path, '/w/a/sols/common.cpp');
});

test('an absolute path from the compiler is left alone', () => {
  const [entry] = buildDiagnostics([
    view([
      finding('sols/main.cpp', {
        warnings: [{ file: '/opt/include/thing.cpp', line: 9, msg: 'x' }],
      }),
    ]),
  ]);
  assert.strictEqual(entry.path, '/opt/include/thing.cpp');
});

test('a line of 0 cannot produce a negative one', () => {
  const [entry] = buildDiagnostics([
    view([finding('sols/main.cpp', { warnings: [{ file: 'sols/main.cpp', line: 0, msg: 'x' }] })]),
  ]);
  assert.strictEqual(entry.line, 0);
});

test('a warning with no flag carries none', () => {
  const [entry] = buildDiagnostics([
    view([finding('sols/main.cpp', { warnings: [{ file: 'sols/main.cpp', line: 4, msg: 'x' }] })]),
  ]);
  assert.strictEqual(entry.flag, undefined);
});

test('a failed compile is one error at the top of the solution', () => {
  // There is no line to point at: rbx parses locations out of warnings only,
  // and a guessed line would underline the wrong code.
  const [entry] = buildDiagnostics([view([finding('sols/broken.cpp', { status: 'FAILED' })])]);
  assert.strictEqual(entry.path, '/w/a/sols/broken.cpp');
  assert.strictEqual(entry.line, 0);
  assert.strictEqual(entry.severity, 'error');
  // The message has to say the thing that is otherwise invisible: the solution
  // is not in the run.
  assert.ok(entry.message.includes('left out of the run'));
});

test('a failure names its reason when rbx gave one', () => {
  const [entry] = buildDiagnostics([
    view([finding('sols/broken.cpp', { status: 'FAILED', reason: "'g++' was not found" })]),
  ]);
  assert.ok(entry.message.includes("'g++' was not found"));
});

test('every entry knows where the compiler output went', () => {
  const entries = buildDiagnostics([
    view([
      finding('sols/broken.cpp', { status: 'FAILED' }),
      finding('sols/main.cpp', { warnings: [{ file: 'sols/main.cpp', line: 4, msg: 'x' }] }),
    ]),
  ]);
  assert.deepStrictEqual(
    entries.map((entry) => entry.logPath),
    ['/w/a/.rbx/runs/compilation/0.log', '/w/a/.rbx/runs/compilation/0.log'],
  );
});

test('findings from several packages are all reported', () => {
  const other: PackageRunView = {
    pkg: { root: '/w/b' },
    run: {
      skeleton: {
      solutions: [],
      entries: [],
      groups: [],
      compilation: [],
      sanitized: false,
      onlyAccepted: false,
    },
      solutions: [],
      findings: [
        {
          entry: {
            path: 'sols/x.cpp',
            status: 'FAILED',
            log: 'compilation/0.log',
            warnings: [],
          },
          logPath: '/w/b/.rbx/runs/compilation/0.log',
          sourcePath: '/w/b/sols/x.cpp',
        },
      ],
    },
  };
  const entries = buildDiagnostics([view([finding('sols/broken.cpp', { status: 'FAILED' })]), other]);
  assert.deepStrictEqual(
    entries.map((entry) => entry.path),
    ['/w/a/sols/broken.cpp', '/w/b/sols/x.cpp'],
  );
});

test('entries are grouped by file, because a collection is set per file', () => {
  // Setting one at a time would leave each file showing only its last warning.
  const grouped = byFile(
    buildDiagnostics([
      view([
        finding('sols/main.cpp', {
          warnings: [
            { file: 'sols/main.cpp', line: 22, msg: 'a' },
            { file: 'sols/main.cpp', line: 25, msg: 'b' },
            { file: 'sols/other.cpp', line: 3, msg: 'c' },
          ],
        }),
      ]),
    ]),
  );
  assert.deepStrictEqual([...grouped.keys()], ['/w/a/sols/main.cpp', '/w/a/sols/other.cpp']);
  assert.strictEqual(grouped.get('/w/a/sols/main.cpp')?.length, 2);
  assert.strictEqual(grouped.get('/w/a/sols/other.cpp')?.length, 1);
});
