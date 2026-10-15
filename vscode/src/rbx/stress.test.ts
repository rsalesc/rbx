import * as assert from 'assert';
import { test } from 'node:test';
import { parse as parseYaml } from 'yaml';

import {
  STRESS_SUPPORTED_VERSION,
  StressManifest,
  parseStressManifest,
  stressLiveness,
} from './stress';

/** Verbatim from a real `rbx stress -g 'gens/gen.cpp [1..1000]' -f sols/wa.cpp -n 2`. */
const REAL_MANIFEST = `
version: 1
state: done
spec:
  name: null
  generator: gens/gen.cpp [1..1000]
  finder: sols/wa.cpp
  fuzz: null
  slowest: false
  timeout: 30
  findingsLimit: 2
  timelimit: 1000
  doubleTL: false
startedAt: '2026-10-15T10:35:23.566269+02:00'
elapsed: 0.57
executed: 2
skipped: 0
solutions:
- sols/ac.cpp
- sols/wa.cpp
findings:
- index: 1
  generator:
    name: gens/gen.cpp
    args: '352'
  duration: 4
  results:
  - solution: 1
    outcome: wrong-answer
    time: 0.00421
    memory: 999424
- index: 2
  generator:
    name: gens/gen.cpp
    args: '17'
  duration: null
  results:
  - solution: 1
    outcome: wrong-answer
    time: 0.0039
    memory: null
`;

test('a real manifest reads in full', () => {
  assert.deepStrictEqual(parseStressManifest(parseYaml(REAL_MANIFEST)), {
    state: 'done',
    spec: {
      name: undefined,
      generator: 'gens/gen.cpp [1..1000]',
      finder: 'sols/wa.cpp',
      fuzz: undefined,
      slowest: false,
      timeout: 30,
      findingsLimit: 2,
      timelimit: 1000,
      doubleTL: false,
    },
    startedAt: '2026-10-15T10:35:23.566269+02:00',
    elapsed: 0.57,
    executed: 2,
    skipped: 0,
    solutions: ['sols/ac.cpp', 'sols/wa.cpp'],
    findings: [
      {
        index: 1,
        generator: { name: 'gens/gen.cpp', args: '352' },
        duration: 4,
        results: [{ solution: 1, outcome: 'wrong-answer', time: 0.00421, memory: 999424 }],
      },
      {
        index: 2,
        generator: { name: 'gens/gen.cpp', args: '17' },
        duration: undefined,
        results: [{ solution: 1, outcome: 'wrong-answer', time: 0.0039, memory: undefined }],
      },
    ],
    pid: undefined,
    host: undefined,
  });
});

test('an unknown version is not read optimistically', () => {
  const raw = parseYaml(REAL_MANIFEST) as Record<string, unknown>;
  assert.strictEqual(STRESS_SUPPORTED_VERSION, 1);
  assert.strictEqual(parseStressManifest({ ...raw, version: 2 }), undefined);
  assert.strictEqual(parseStressManifest({ ...raw, version: undefined }), undefined);
});

test('nothing usable reads as no session', () => {
  assert.strictEqual(parseStressManifest(undefined), undefined);
  assert.strictEqual(parseStressManifest('stress.yml'), undefined);
  assert.strictEqual(parseStressManifest([]), undefined);
});

test('a state this reader does not know, or none, is not guessed at', () => {
  const raw = parseYaml(REAL_MANIFEST) as Record<string, unknown>;
  assert.strictEqual(parseStressManifest({ ...raw, state: 'paused' }), undefined);
  assert.strictEqual(parseStressManifest({ ...raw, state: undefined }), undefined);
  for (const state of ['running', 'done', 'interrupted', 'failed']) {
    assert.strictEqual(parseStressManifest({ ...raw, state })?.state, state);
  }
});

test('fuzz keeps null (no fuzzing) apart from [] (every group)', () => {
  const raw = parseYaml(REAL_MANIFEST) as Record<string, unknown>;
  const spec = raw.spec as Record<string, unknown>;
  const fuzz = (value: unknown) =>
    parseStressManifest({ ...raw, spec: { ...spec, generator: null, fuzz: value } })?.spec;

  assert.strictEqual(fuzz(null)?.fuzz, undefined);
  assert.deepStrictEqual(fuzz([])?.fuzz, []);
  assert.deepStrictEqual(fuzz(['main', 7, 'big'])?.fuzz, ['main', 'big']);
  assert.strictEqual(fuzz([])?.generator, undefined);
});

test('a declared stress names itself; an unlimited run has no time limit', () => {
  const raw = parseYaml(REAL_MANIFEST) as Record<string, unknown>;
  const spec = raw.spec as Record<string, unknown>;
  const parsed = parseStressManifest({
    ...raw,
    spec: { ...spec, name: 'wa-small', slowest: true, timelimit: null, doubleTL: true },
  });
  assert.strictEqual(parsed?.spec.name, 'wa-small');
  assert.strictEqual(parsed?.spec.slowest, true);
  assert.strictEqual(parsed?.spec.timelimit, undefined);
  assert.strictEqual(parsed?.spec.doubleTL, true);
});

test('a malformed finding or result costs that entry, not the session', () => {
  const raw = parseYaml(REAL_MANIFEST) as Record<string, unknown>;
  const parsed = parseStressManifest({
    ...raw,
    findings: [
      { generator: { name: 'gens/gen.cpp' } },
      { index: 3, generator: {} },
      {
        index: 4,
        generator: { name: 'gens/gen.cpp' },
        results: [{ solution: 0 }, { outcome: 'accepted' }, { solution: 0, outcome: 'accepted' }],
      },
      'garbage',
    ],
  });
  assert.deepStrictEqual(parsed?.findings, [
    {
      index: 4,
      generator: { name: 'gens/gen.cpp', args: undefined },
      duration: undefined,
      results: [{ solution: 0, outcome: 'accepted', time: undefined, memory: undefined }],
    },
  ]);
});

test('counters and lists default to empty rather than failing the session', () => {
  const parsed = parseStressManifest({ version: 1, state: 'running', spec: { finder: 'x' } });
  assert.deepStrictEqual(parsed, {
    state: 'running',
    spec: {
      name: undefined,
      generator: undefined,
      finder: 'x',
      fuzz: undefined,
      slowest: false,
      timeout: undefined,
      findingsLimit: undefined,
      timelimit: undefined,
      doubleTL: false,
    },
    startedAt: undefined,
    elapsed: 0,
    executed: 0,
    skipped: 0,
    solutions: [],
    findings: [],
    pid: undefined,
    host: undefined,
  });
});

test('the process writing the session is read when rbx names it', () => {
  const raw = parseYaml(REAL_MANIFEST) as Record<string, unknown>;
  const parsed = parseStressManifest({ ...raw, pid: 4242, host: 'box' });
  assert.strictEqual(parsed?.pid, 4242);
  assert.strictEqual(parsed?.host, 'box');
  const odd = parseStressManifest({ ...raw, pid: '4242', host: 7 });
  assert.strictEqual(odd?.pid, undefined);
  assert.strictEqual(odd?.host, undefined);
  // 0 and negatives would signal a process group, and read as alive forever.
  for (const pid of [0, -1, -4242, 1.5]) {
    assert.strictEqual(parseStressManifest({ ...raw, pid })?.pid, undefined, String(pid));
  }
});

function session(overrides: Partial<StressManifest>): StressManifest {
  const raw = parseYaml(REAL_MANIFEST) as Record<string, unknown>;
  return { ...parseStressManifest(raw)!, ...overrides };
}

test('a running session whose process is gone from this host is stale', () => {
  const asked: number[] = [];
  const probe = (alive: boolean) => ({
    hostname: 'box',
    isAlive: (pid: number) => {
      asked.push(pid);
      return alive;
    },
  });
  const running = session({ state: 'running', pid: 4242, host: 'box' });
  assert.strictEqual(stressLiveness(running, probe(false)), 'stale');
  assert.strictEqual(stressLiveness(running, probe(true)), 'live');
  assert.deepStrictEqual(asked, [4242, 4242]);
});

test('liveness cannot be told without a pid on this host, and an ended session stands', () => {
  const dead = { hostname: 'box', isAlive: () => false };
  for (const overrides of [
    { pid: undefined, host: 'box' },
    { pid: 4242, host: undefined },
    { pid: 4242, host: 'elsewhere' },
  ]) {
    assert.strictEqual(
      stressLiveness(session({ state: 'running', ...overrides }), dead),
      'unknown',
      JSON.stringify(overrides),
    );
  }
  for (const state of ['done', 'interrupted', 'failed'] as const) {
    assert.strictEqual(stressLiveness(session({ state, pid: 4242, host: 'box' }), dead), 'live');
  }
});
