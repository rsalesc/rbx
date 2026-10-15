import * as assert from 'assert';
import { test } from 'node:test';

import {
  Invocation,
  NO_CONTEST,
  RBX_COMMANDS,
  asExtraArgs,
  carriesArgs,
  collides,
  collisions,
  definedContest,
  isOneShot,
  needsShellQuoting,
  rbxArgs,
  rbxEnv,
  runningAt,
  scopeOf,
  statementCommand,
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

test('root options go ahead of the subcommand, and into the task identity', () => {
  const capture = invocation({
    command: 'irun',
    args: ['-t', 'main/0'],
    rootArgs: ['-cp'],
    contest: { kind: 'variant', id: 'div1' },
  });
  assert.deepStrictEqual(rbxArgs(capture), ['-C', 'div1', '-cp', 'irun', '-t', 'main/0']);
  assert.deepStrictEqual(taskDefinition(capture).rootArgs, ['-cp']);
  assert.strictEqual(taskDefinition(invocation()).rootArgs, undefined);
});

test('an ad-hoc run is named after what it runs on, not after a solution', () => {
  const irun = (args: string[]) => taskName(invocation({ command: 'irun', args }));
  assert.strictEqual(irun(['sols/a.cpp', '-t', 'main/1']), 'run on main/1');
  assert.strictEqual(irun(['sols/a.cpp', '-g', 'gen 1 2']), 'run on gen 1 2');
  assert.strictEqual(irun(['sols/a.cpp', '--input', '/t/in.txt']), 'run on typed input');
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
  assert.strictEqual(scopeOf('stress'), 'problem');
  assert.strictEqual(scopeOf('add-finding'), 'problem');
});

const STRESS_ARGS = ['-g', 'gens/gen.cpp [1..9]', '-f', '[sols/wa.cpp]', '--no-promote'];

test('a stress puts its argv tail after the subcommand, and nothing of run', () => {
  assert.deepStrictEqual(
    rbxArgs(invocation({ command: 'stress', args: STRESS_ARGS, extraArgs: ['-v4'], solutions: ['x'] })),
    ['stress', ...STRESS_ARGS],
  );
  assert.deepStrictEqual(
    rbxArgs(
      invocation({
        command: 'stress',
        args: ['wa', '--no-promote'],
        contest: { kind: 'variant', id: 'd1' },
      }),
    ),
    ['-C', 'd1', 'stress', 'wa', '--no-promote'],
  );
});

test('add-finding is a testcases subcommand', () => {
  assert.deepStrictEqual(
    rbxArgs(invocation({ command: 'add-finding', args: ['1', '2', '--group', 'main'] })),
    ['testcases', 'add-finding', '1', '2', '--group', 'main'],
  );
});

test('exactly the argv-tail commands are handed their args', () => {
  for (const command of RBX_COMMANDS) {
    assert.strictEqual(
      carriesArgs(command),
      ['stress', 'add-finding', 'irun', 'promote'].includes(command),
      command,
    );
  }
  assert.strictEqual(isOneShot('promote'), true);
  assert.strictEqual(isOneShot('add-finding'), true);
  assert.strictEqual(isOneShot('irun'), false);
});

test('irun and promote carry their argv tail, and are named for the test', () => {
  const irun = invocation({ command: 'irun', args: ['-t', 'tests/plan.txt:3'] });
  const promote = invocation({
    command: 'promote',
    args: ['tests/plan.txt:3', '--group', 'corner'],
  });
  assert.deepStrictEqual(rbxArgs(irun), ['irun', '-t', 'tests/plan.txt:3']);
  assert.deepStrictEqual(rbxArgs(promote), [
    'testcases',
    'promote',
    'tests/plan.txt:3',
    '--group',
    'corner',
  ]);
  assert.strictEqual(taskName(irun), 'run on tests/plan.txt:3');
  assert.strictEqual(taskName(promote), 'promote tests/plan.txt:3');
  assert.strictEqual(scopeOf('irun'), 'problem');
  assert.strictEqual(scopeOf('promote'), 'problem');
});

test('a stress task is named for what it stresses', () => {
  const name = (args: string[]) => taskName(invocation({ command: 'stress', args }));
  assert.strictEqual(name(['wa-small', '--no-promote']), 'stress wa-small');
  assert.strictEqual(name(STRESS_ARGS), 'stress gens/gen.cpp [1..9]');
  assert.strictEqual(name(['--fuzz-on', 'main', '--no-promote']), 'stress fuzz');
  assert.strictEqual(name(['--fuzz', '--no-promote']), 'stress fuzz');
  assert.strictEqual(
    taskName(invocation({ command: 'add-finding', args: ['1', '--group', 'main'] })),
    'add finding',
  );
  // Nothing to name it after: an argv this extension would not build.
  assert.strictEqual(name(['--slowest', '--no-promote']), 'stress session');
  assert.strictEqual(taskName(invocation({ command: 'stress' })), 'stress session');
});

test('runningAt finds that command in exactly that package', () => {
  const running = [
    { id: 1, command: 'stress', cwd: '/c/A' },
    { id: 2, command: 'stress', cwd: '/c/A/../A/' },
    { id: 3, command: 'run', cwd: '/c/A' },
    { id: 4, command: 'stress', cwd: '/c/AB' },
    { id: 5, command: 'stress', cwd: '/c' },
    { id: 6, command: undefined, cwd: '/c/A' },
  ];
  assert.deepStrictEqual(
    runningAt(running, '/c/A', 'stress').map((task) => task.id),
    [1, 2],
  );
  assert.deepStrictEqual(runningAt(running, '/c/B', 'stress'), []);
});

test('only what a shell would read as syntax needs quoting', () => {
  for (const safe of [
    'stress',
    '--no-promote',
    '-g',
    'sols/main.cpp',
    './sols/a_b.cpp',
    '/abs/path',
    '1',
    '-C',
    'div1',
    'a=b',
    'a:b+c%',
  ]) {
    assert.strictEqual(needsShellQuoting(safe), false, safe);
  }
  for (const unsafe of [
    'gens/gen.cpp [1..9]',
    '[sols/a.cpp] ~ WA && [b] != [c]',
    '"a b.cpp"',
    'gen $x',
    'a|b',
    'a!b',
    'a*b',
    '',
    // zsh `=cmd` expansion; PowerShell splatting and the array operator.
    '=python',
    '@args',
    'a@b',
    'a,b',
    '_x',
    ':x',
    '+x',
    '%x',
  ]) {
    assert.strictEqual(needsShellQuoting(unsafe), true, unsafe);
  }
});

test('the argv tail is part of a stress task identity', () => {
  assert.deepStrictEqual(taskDefinition(invocation({ command: 'stress', args: STRESS_ARGS })), {
    type: 'rbx',
    command: 'stress',
    cwd: '/c/A',
    args: STRESS_ARGS,
  });
  assert.strictEqual('args' in taskDefinition(invocation({ command: 'build' })), false);
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

test('statement builds dispatch the build subcommands, contest ones at the contest', () => {
  assert.deepStrictEqual(rbxArgs(invocation({ command: 'statements', extraArgs: ['-v4'] })), [
    'statements',
    'build',
    '--no-validate',
  ]);
  assert.deepStrictEqual(
    rbxArgs(invocation({ command: 'contest-statements', contest: { kind: 'variant', id: 'div1' } })),
    ['-C', 'div1', 'contest', 'statements', 'build', '--no-validate'],
  );
  assert.strictEqual(scopeOf('statements'), 'problem');
  assert.strictEqual(scopeOf('contest-statements'), 'contest');
  assert.strictEqual(taskName(invocation({ command: 'statements' })), 'build statements');
  assert.strictEqual(
    taskName(invocation({ command: 'contest-tutorials' })),
    'build contest tutorials',
  );
  assert.deepStrictEqual(rbxArgs(invocation({ command: 'tutorials' })), [
    'tutorials',
    'build',
    '--no-validate',
  ]);
  assert.deepStrictEqual(rbxArgs(invocation({ command: 'contest-tutorials' })), [
    'contest',
    'tutorials',
    'build',
    '--no-validate',
  ]);
});

test('a statement output is rebuilt by the command for its kind and scope', () => {
  assert.strictEqual(statementCommand('problem', 'statement'), 'statements');
  assert.strictEqual(statementCommand('problem', 'tutorial'), 'tutorials');
  assert.strictEqual(statementCommand('contest', 'statement'), 'contest-statements');
  assert.strictEqual(statementCommand('contest', 'document'), 'contest-statements');
  assert.strictEqual(statementCommand('contest', 'tutorial'), 'contest-tutorials');
  assert.strictEqual(scopeOf('contest-tutorials'), 'contest');
});
