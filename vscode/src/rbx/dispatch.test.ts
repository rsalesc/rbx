import * as assert from 'assert';
import { test } from 'node:test';

import {
  Invocation,
  NO_CONTEST,
  asExtraArgs,
  collides,
  collisions,
  definedContest,
  rbxArgs,
  rbxEnv,
  scopeOf,
  taskDefinition,
  taskName,
} from './dispatch';

function invocation(overrides: Partial<Invocation> = {}): Invocation {
  return {
    command: 'run',
    cwd: '/c/A',
    solutions: [],
    extraArgs: [],
    contest: NO_CONTEST,
    ...overrides,
  };
}

test('rbx run with no solutions runs every solution', () => {
  assert.deepStrictEqual(rbxArgs(invocation()), ['run']);
});

test('rbx run puts extra args before the solutions', () => {
  assert.deepStrictEqual(
    rbxArgs(invocation({ solutions: ['sols/my main.cpp'], extraArgs: ['-v4', '--sanitized'] })),
    ['run', '-v4', '--sanitized', 'sols/my main.cpp'],
  );
});

test('rbx build ignores the run-only extra args', () => {
  assert.deepStrictEqual(rbxArgs(invocation({ command: 'build', extraArgs: ['-v4'] })), [
    'build',
  ]);
});

test('a contest run is inline, so it never opens the TUI in a task terminal', () => {
  assert.deepStrictEqual(rbxArgs(invocation({ command: 'contest-run', extraArgs: ['-v4'] })), [
    'contest',
    'each',
    '--inline',
    'run',
    '-v4',
  ]);
});

test('a variant is selected with the root -C option, ahead of the subcommand', () => {
  assert.deepStrictEqual(
    rbxArgs(invocation({ contest: { kind: 'variant', id: 'div1' }, solutions: ['a.cpp'] })),
    ['-C', 'div1', 'run', 'a.cpp'],
  );
});

test('the canonical passes no -C but clears an inherited RBX_CONTEST', () => {
  const canonical = invocation({ contest: { kind: 'canonical' } });
  assert.deepStrictEqual(rbxArgs(canonical), ['run']);
  assert.deepStrictEqual(rbxEnv(canonical.contest), { RBX_CONTEST: '' });
});

test('no contest leaves the environment alone', () => {
  assert.strictEqual(rbxEnv(NO_CONTEST), undefined);
  assert.strictEqual(rbxEnv({ kind: 'variant', id: 'div1' }), undefined);
});

test('the task name says which contest it runs under', () => {
  assert.strictEqual(taskName(invocation({ solutions: ['sols/a.cpp'] })), 'run sols/a.cpp');
  assert.strictEqual(
    taskName(invocation({ command: 'build', contest: { kind: 'variant', id: 'div2' } })),
    'build [div2]',
  );
  assert.strictEqual(
    taskName(invocation({ command: 'contest-run', contest: { kind: 'canonical' } })),
    'run all problems [default contest]',
  );
});

test('the definition round-trips the contest selection', () => {
  assert.deepStrictEqual(taskDefinition(invocation({ solutions: ['a.cpp'] })), {
    type: 'rbx',
    command: 'run',
    cwd: '/c/A',
    solutions: ['a.cpp'],
  });
  const variant = taskDefinition(invocation({ contest: { kind: 'variant', id: 'div1' } }));
  assert.deepStrictEqual(definedContest(variant.contest), { kind: 'variant', id: 'div1' });
  const canonical = taskDefinition(invocation({ contest: { kind: 'canonical' } }));
  assert.deepStrictEqual(definedContest(canonical.contest), { kind: 'canonical' });
  assert.strictEqual(definedContest(taskDefinition(invocation()).contest), undefined);
});

test('scope follows the command', () => {
  assert.strictEqual(scopeOf('run'), 'problem');
  assert.strictEqual(scopeOf('build'), 'problem');
  assert.strictEqual(scopeOf('contest-run'), 'contest');
});

// The busy policy. These are the cases the issue's acceptance hangs on:
// dispatching while busy must never interleave with a running command.

test('busy: any two commands in the same package collide', () => {
  assert.ok(collides('/c/A', '/c/A'));
  assert.ok(collides('/c/A/', '/c/A'));
  assert.ok(collides('/c/./A', '/c/A'));
});

test('busy: a contest command collides with every package under it, both ways', () => {
  assert.ok(collides('/c', '/c/A'));
  assert.ok(collides('/c/problems/A', '/c'));
});

test('busy: different packages run side by side', () => {
  assert.ok(!collides('/c/A', '/c/B'));
  // A shared string prefix is not containment.
  assert.ok(!collides('/c/A', '/c/AB'));
  assert.ok(!collides('/c/AB', '/c/A'));
  // Two contests side by side.
  assert.ok(!collides('/c1', '/c2/A'));
});

test('busy: collisions picks exactly the tasks in the way', () => {
  const running = [
    { name: 'build', cwd: '/c/A' },
    { name: 'run', cwd: '/c/B' },
    { name: 'contest', cwd: '/c' },
    { name: 'elsewhere', cwd: '/other/A' },
  ];
  assert.deepStrictEqual(
    collisions(running, '/c/A').map((task) => task.name),
    ['build', 'contest'],
  );
  assert.deepStrictEqual(
    collisions(running, '/c').map((task) => task.name),
    ['build', 'run', 'contest'],
  );
  assert.deepStrictEqual(collisions(running, '/c/C').map((task) => task.name), ['contest']);
  assert.deepStrictEqual(collisions(running, '/fresh'), []);
});

test('extra args keep only non-empty strings', () => {
  assert.deepStrictEqual(asExtraArgs(['-v4', '', 3, null, '--sanitized']), ['-v4', '--sanitized']);
  assert.deepStrictEqual(asExtraArgs('-v4'), []);
  assert.deepStrictEqual(asExtraArgs(undefined), []);
});
