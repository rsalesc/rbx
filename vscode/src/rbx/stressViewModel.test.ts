import * as assert from 'assert';
import { test } from 'node:test';

import { StressManifest } from './stress';
import { StressDeclaration } from './stressDeclarations';
import { defaultLaunch } from './stressSpec';
import {
  buildStressViewModel,
  declaredRunLaunch,
  formatDuration,
  specSummary,
} from './stressViewModel';

const DECLARED: StressDeclaration[] = [
  {
    name: 'wa-small',
    generator: { name: 'gen', args: '[1..10]' },
    finder: '[sols/wa.cpp] ~ WRONG_ANSWER',
  },
];

function manifest(overrides: Partial<StressManifest> = {}): StressManifest {
  return {
    state: 'done',
    spec: { name: 'wa-small', slowest: false, timeout: 10, findingsLimit: 2, doubleTL: false },
    startedAt: '2026-10-15T12:00:00+00:00',
    elapsed: 4.5,
    executed: 120,
    skipped: 0,
    solutions: ['sols/main.cpp', 'sols/wa.cpp'],
    findings: [
      {
        index: 1,
        generator: { name: 'gen', args: '5 123' },
        duration: 1250,
        results: [
          { solution: 0, outcome: 'accepted' },
          { solution: 1, outcome: 'wrong-answer' },
        ],
      },
    ],
    ...overrides,
  };
}

test('declared stresses read as name plus `call · finder`', () => {
  const model = buildStressViewModel({
    declared: DECLARED,
    alive: true,
    task: false,
    dispatch: true,
  });
  assert.deepStrictEqual(model.declared, [
    { name: 'wa-small', summary: 'gen [1..10] · [sols/wa.cpp] ~ WRONG_ANSWER' },
  ]);
  assert.strictEqual(model.noPackage, false);
  assert.strictEqual(model.status, undefined);
  assert.deepStrictEqual(model.findings, []);
});

test('a finished session: status, counters and one chip per result', () => {
  const model = buildStressViewModel({
    declared: DECLARED,
    manifest: manifest(),
    alive: true,
    task: true,
    promoted: new Map([[1, 'main']]),
    comparable: new Set([1]),
    dispatch: true,
  });
  assert.deepStrictEqual(model.status, {
    state: 'done',
    label: 'Done',
    hue: 'green',
    executed: 120,
    skipped: 0,
    findings: 1,
    findingsLimit: 2,
    elapsed: 4.5,
    timeout: 10,
    startedAtMs: undefined,
    spec: 'wa-small',
    stoppable: false,
    external: false,
  });
  assert.deepStrictEqual(model.findings, [
    {
      k: 1,
      call: 'gen 5 123',
      duration: '1.3 s',
      chips: [
        { solution: 'main.cpp', path: 'sols/main.cpp', short: 'AC', icon: 'pass', hue: 'green' },
        { solution: 'wa.cpp', path: 'sols/wa.cpp', short: 'WA', icon: 'close', hue: 'red' },
      ],
      promoted: 'main',
      canCompare: true,
    },
  ]);
  assert.strictEqual(model.session, '2026-10-15T12:00:00+00:00');
});

test('a running session keeps its start for the client clock; a dead one reads stale', () => {
  const running = manifest({ state: 'running' });
  const live = buildStressViewModel({
    declared: [],
    manifest: running,
    alive: true,
    task: true,
    dispatch: true,
  });
  assert.strictEqual(live.status?.state, 'running');
  assert.strictEqual(live.status?.startedAtMs, Date.parse('2026-10-15T12:00:00+00:00'));

  const stale = buildStressViewModel({
    declared: [],
    manifest: running,
    alive: false,
    task: false,
    dispatch: true,
  });
  assert.strictEqual(stale.status?.state, 'stale');
  assert.strictEqual(stale.status?.hue, 'orange');
  assert.strictEqual(stale.status?.startedAtMs, undefined);
  // Nothing left to stop, and nothing to stop it from either.
  assert.strictEqual(stale.status?.stoppable, false);
  assert.strictEqual(stale.status?.external, false);
});

test('only a session VS Code started can be stopped from here', () => {
  const running = manifest({ state: 'running' });
  const ours = buildStressViewModel({
    declared: [],
    manifest: running,
    alive: true,
    task: true,
    dispatch: true,
  });
  assert.strictEqual(ours.status?.stoppable, true);
  assert.strictEqual(ours.status?.external, false);
  const theirs = buildStressViewModel({
    declared: [],
    manifest: running,
    alive: true,
    task: false,
    dispatch: true,
  });
  assert.strictEqual(theirs.status?.stoppable, false);
  assert.strictEqual(theirs.status?.external, true);
});

test('`alive` only matters for a running manifest', () => {
  for (const state of ['done', 'interrupted', 'failed'] as const) {
    const model = buildStressViewModel({
      declared: [],
      manifest: manifest({ state }),
      alive: false,
      task: true,
      dispatch: true,
    });
    assert.strictEqual(model.status?.state, state);
    assert.strictEqual(model.status?.stoppable, false);
  }
});

test('a result naming no known solution still gets a chip', () => {
  const model = buildStressViewModel({
    declared: [],
    manifest: manifest({
      findings: [
        { index: 3, generator: { name: 'gen' }, results: [{ solution: 7, outcome: 'nonsense' }] },
      ],
    }),
    alive: true,
    task: true,
    dispatch: true,
  });
  assert.deepStrictEqual(model.findings[0].chips, [
    { solution: '#7', path: '#7', short: 'XX', icon: 'question', hue: 'purple' },
  ]);
  assert.strictEqual(model.findings[0].call, 'gen');
  assert.strictEqual(model.findings[0].duration, undefined);
  assert.strictEqual(model.findings[0].canCompare, false);
});

test('an ad-hoc spec is summarised as the flags that said it', () => {
  assert.strictEqual(
    specSummary({
      generator: 'gen [1..9]',
      finder: '[a.cpp] != [b.cpp]',
      slowest: true,
      doubleTL: false,
    }),
    '-g gen [1..9] -f [a.cpp] != [b.cpp] --slowest',
  );
  assert.strictEqual(specSummary({ fuzz: [], slowest: false, doubleTL: false }), '--fuzz');
  assert.strictEqual(
    specSummary({ fuzz: ['main', 'big'], slowest: false, doubleTL: false }),
    '--fuzz-on main --fuzz-on big',
  );
});

test('durations read in ms, seconds, then minutes', () => {
  assert.strictEqual(formatDuration(850), '850 ms');
  assert.strictEqual(formatDuration(1234), '1.2 s');
  assert.strictEqual(formatDuration(125_000), '2m 05s');
});

test('Run on a declared stress takes the last launch only when it was this stress', () => {
  const remembered = {
    ...defaultLaunch({ kind: 'declared', name: 'wa-small' }),
    timeout: 60,
  };
  assert.deepStrictEqual(declaredRunLaunch('wa-small', DECLARED, remembered), {
    launch: remembered,
    declared: DECLARED[0],
  });

  const other = { ...remembered, source: { kind: 'declared', name: 'tle' } };
  assert.deepStrictEqual(declaredRunLaunch('wa-small', DECLARED, other).launch, {
    ...defaultLaunch({ kind: 'declared', name: 'wa-small' }),
  });
  assert.deepStrictEqual(
    declaredRunLaunch('wa-small', DECLARED, undefined).launch,
    defaultLaunch({ kind: 'declared', name: 'wa-small' }),
  );
});

test('a remembered launch that no longer validates, or is malformed, falls back', () => {
  const invalid = { ...defaultLaunch({ kind: 'declared', name: 'wa-small' }), timeout: 0 };
  assert.strictEqual(declaredRunLaunch('wa-small', DECLARED, invalid).launch.timeout, 10);
  const malformed = {
    ...defaultLaunch({ kind: 'declared', name: 'wa-small' }),
    finder: { rows: 42, join: 'all' },
  };
  assert.deepStrictEqual(
    declaredRunLaunch('wa-small', DECLARED, malformed).launch,
    defaultLaunch({ kind: 'declared', name: 'wa-small' }),
  );
  // Replaced rows need the declaration; without it, the default runs by name.
  const rows = {
    ...defaultLaunch({ kind: 'declared', name: 'gone' }),
    finder: { rows: [{ kind: 'break', solution: 'sols/wa.cpp', outcome: 'WRONG_ANSWER' }], join: 'all' },
  };
  assert.deepStrictEqual(declaredRunLaunch('gone', DECLARED, rows), {
    launch: defaultLaunch({ kind: 'declared', name: 'gone' }),
    declared: undefined,
  });
});
