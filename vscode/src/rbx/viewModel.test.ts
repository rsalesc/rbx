import * as assert from 'assert';
import { test } from 'node:test';

import type { PackageLayout } from './layout';
import type { PackageRunView } from './nodes';
import type { GroupReport, SolutionReport } from './report';
import type { CompilationEntry, Skeleton } from './model';
import type {
  CompilationFinding,
  GroupRun,
  PackageRun,
  SolutionRun,
  TestcaseRun,
} from './store';
import { Row, buildViewModel } from './viewModel';

// The fixtures below transcribe rbx's `outcome-per-group` e2e package: a main
// solution that passes, one declared INCORRECT that fails as declared, and one
// declared INCORRECT that fails in the wrong places. Those three are what a
// naive encoding folds into one red row.

const PKG: PackageLayout = { buildDir: 'build', root: '/w/a' };

function testcase(stem: string, outcome?: string, over: Partial<TestcaseRun> = {}): TestcaseRun {
  return {
    entry: { group: 'main', index: 0 },
    stem,
    evaluation: outcome === undefined ? undefined : { outcome },
    inputPath: '',
    answerPath: '',
    outputPath: '',
    stderrPaths: [],
    logPath: '',
    interactionPath: '',
    ...over,
  };
}

function groupReport(over: Partial<GroupReport> = {}): GroupReport {
  return {
    name: 'main',
    outcome: 'accepted',
    matchesExpectation: true,
    score: 0,
    maxScore: 0,
    runUnderDoubleTl: false,
    doubleTlVerdicts: [],
    sanitizerWarnings: false,
    unexpectedNoTleVerdicts: [],
    ...over,
  };
}

function group(
  name: string,
  testcases: readonly TestcaseRun[],
  report?: GroupReport,
): GroupRun {
  return { name, testcases, report };
}

function solutionReport(over: Partial<SolutionReport> = {}): SolutionReport {
  return {
    path: 'sols/main.cpp',
    index: 0,
    expectedOutcome: 'ACCEPTED',
    outcome: 'accepted',
    status: 'OK',
    matchesExpectation: true,
    score: 0,
    maxScore: 0,
    failedGroups: [],
    runUnderDoubleTl: false,
    doubleTlVerdicts: [],
    sanitizerWarnings: false,
    groups: [],
    ...over,
  };
}

function solution(
  index: number,
  path: string,
  expectedOutcome: string | undefined,
  groups: readonly GroupRun[],
  report?: SolutionReport,
): SolutionRun {
  return { solution: { path, index, expectedOutcome }, groups, report };
}

function run(
  solutions: readonly SolutionRun[],
  findings: readonly CompilationFinding[] = [],
  skeleton: Partial<Skeleton> = {},
): PackageRun {
  return {
    skeleton: {
      solutions: [],
      entries: [],
      groups: [],
      compilation: [],
      sanitized: false,
      onlyAccepted: false,
      ...skeleton,
    },
    solutions,
    findings,
  };
}

function view(
  solutions: readonly SolutionRun[],
  findings: readonly CompilationFinding[] = [],
  skeleton: Partial<Skeleton> = {},
): PackageRunView {
  return { pkg: PKG, run: run(solutions, findings, skeleton) };
}

function finding(
  path: string,
  over: Partial<CompilationEntry> = {},
): CompilationFinding {
  return {
    entry: {
      path,
      expectedOutcome: 'ACCEPTED',
      status: 'WARNINGS',
      log: 'compilation/0.log',
      warnings: [],
      ...over,
    },
    logPath: `/w/a/.rbx/runs/${over.log ?? 'compilation/0.log'}`,
    sourcePath: `/w/a/${path}`,
  };
}

function rowById(rows: readonly Row[], id: string): Row {
  const row = rows.find((candidate) => candidate.id === id);
  assert.ok(row !== undefined, `no row ${id}`);
  return row;
}

const MAIN = solution(
  0,
  'sols/main.cpp',
  'ACCEPTED',
  [group('main', [testcase('000', 'accepted')], groupReport())],
  solutionReport(),
);

const PARTIAL = solution(
  1,
  'sols/partial.cpp',
  'INCORRECT',
  [group('big', [testcase('001', 'wrong-answer')], groupReport({ name: 'big', outcome: 'wrong-answer' }))],
  solutionReport({
    path: 'sols/partial.cpp',
    index: 1,
    expectedOutcome: 'INCORRECT',
    outcome: 'wrong-answer',
    matchesExpectation: true,
  }),
);

// `outcome: incorrect` with `outcomePerGroup: {'*': tle}`. Both layers are
// declared and only the per-group one is missed -- the pooled `INCORRECT` is
// satisfied, because the solution really does fail. Naming that layer as the
// culprit is the bug this fixture pins.
const MISLABELED_GROUPS = [
  group(
    'small',
    [testcase('000', 'accepted')],
    groupReport({
      name: 'small',
      outcome: 'accepted',
      expectedOutcome: 'TIME_LIMIT_EXCEEDED',
      matchesExpectation: false,
    }),
  ),
  group(
    'big',
    [testcase('001', 'wrong-answer')],
    groupReport({
      name: 'big',
      outcome: 'wrong-answer',
      expectedOutcome: 'TIME_LIMIT_EXCEEDED',
      matchesExpectation: false,
    }),
  ),
];

const MISLABELED = solution(
  2,
  'sols/mislabeled.cpp',
  'INCORRECT',
  MISLABELED_GROUPS,
  solutionReport({
    path: 'sols/mislabeled.cpp',
    index: 2,
    expectedOutcome: 'INCORRECT',
    outcome: 'wrong-answer',
    matchesExpectation: false,
    pooledMatchesExpectation: true,
    failedGroups: ['small', 'big'],
    groups: MISLABELED_GROUPS.map((entry) => entry.report!),
  }),
);

test('a solution that met its ACCEPTED declaration reads green all the way through', () => {
  const { rows } = buildViewModel(view([MAIN]));
  const row = rowById(rows, '/w/a::0');
  assert.strictEqual(row.kind, 'solution');
  assert.strictEqual(row.gutter, 'met');
  assert.strictEqual(row.mismatch, false);
  // `main.cpp`, not `sols/main.cpp`: the default style trims the directory the
  // package's solutions share. The styles are pinned on their own below.
  assert.strictEqual(row.label, 'main.cpp');
  assert.strictEqual(row.labelHue, 'green');
  assert.strictEqual(row.labelBold, true);
  assert.deepStrictEqual(row.verdict, { icon: 'pass', hue: 'green', short: 'AC' });
  assert.strictEqual(row.detail?.mismatch, undefined);
});

test('a solution that failed exactly as declared is not a mismatch', () => {
  const { rows } = buildViewModel(view([MAIN, PARTIAL]));
  const row = rowById(rows, '/w/a::1');
  assert.strictEqual(row.gutter, 'met');
  // The whole point of the change: partial.cpp is *declared* INCORRECT and it
  // answered wrongly, so the package is working. The row shows a red WA chip
  // because that is what happened, and stays calm about it because it was
  // wanted.
  assert.strictEqual(row.mismatch, false);
  assert.strictEqual(row.labelHue, 'red');
  assert.deepStrictEqual(row.verdict, { icon: 'close', hue: 'red', short: 'WA' });
  assert.strictEqual(row.detail?.mismatch, undefined);
});

test('a solution caught only per-group blames the per-group layer, not the pooled one', () => {
  const { rows } = buildViewModel(view([MAIN, PARTIAL, MISLABELED]));
  const row = rowById(rows, '/w/a::2');
  assert.strictEqual(row.gutter, 'missed');
  assert.strictEqual(row.mismatch, true);
  // `pooled` absent is the whole assertion: the solution's own INCORRECT held,
  // so nothing here may say it was missed. What is named instead is each
  // group's own TLE, beside what that group actually did.
  assert.deepStrictEqual(row.detail?.mismatch, {
    pooled: undefined,
    pooledHeld: 'INCORRECT',
    groups: [
      {
        name: 'small',
        declared: 'TLE',
        declaredHue: 'yellow',
        observed: 'AC',
        observedHue: 'green',
      },
      {
        name: 'big',
        declared: 'TLE',
        declaredHue: 'yellow',
        observed: 'WA',
        observedHue: 'red',
      },
    ],
    score: undefined,
  });
});

test('a solution caught by its pooled declaration blames that one, and no group', () => {
  const optimistic = solution(
    0,
    'sols/optimistic.cpp',
    'ACCEPTED',
    [group('big', [testcase('000', 'wrong-answer')], groupReport({ name: 'big' }))],
    solutionReport({
      path: 'sols/optimistic.cpp',
      expectedOutcome: 'ACCEPTED',
      outcome: 'wrong-answer',
      matchesExpectation: false,
      pooledMatchesExpectation: false,
    }),
  );
  const { rows } = buildViewModel(view([optimistic]));
  assert.deepStrictEqual(rowById(rows, '/w/a::0').detail?.mismatch, {
    pooled: { declared: 'AC', declaredHue: 'green', observed: 'WA', observedHue: 'red' },
    // Not named as held: it is the layer that failed.
    pooledHeld: undefined,
    groups: [],
    score: undefined,
  });
});

test('a report from an rbx with no pooled flag still blames the right layer', () => {
  // The field was added with this card; a report already on disk predates it.
  // With no failing group to explain the miss, the pooled layer is the only
  // thing left that can have caused it.
  const stale = solution(
    0,
    'sols/optimistic.cpp',
    'ACCEPTED',
    [],
    solutionReport({
      path: 'sols/optimistic.cpp',
      expectedOutcome: 'ACCEPTED',
      outcome: 'wrong-answer',
      matchesExpectation: false,
    }),
  );
  const { rows } = buildViewModel(view([stale]));
  assert.strictEqual(rowById(rows, '/w/a::0').detail?.mismatch?.pooled?.declared, 'AC');
});

test('a solution that only missed its score range says so, and accuses no verdict', () => {
  const scored = solution(
    0,
    'sols/partial.cpp',
    'INCORRECT',
    [],
    solutionReport({
      path: 'sols/partial.cpp',
      expectedOutcome: 'INCORRECT',
      outcome: 'wrong-answer',
      status: 'UNEXPECTED_SCORE',
      matchesExpectation: false,
      pooledMatchesExpectation: true,
      score: 30,
      maxScore: 100,
      expectedScore: [40, 60],
    }),
  );
  const { rows } = buildViewModel(view([scored]));
  const mismatch = rowById(rows, '/w/a::0').detail?.mismatch;
  assert.strictEqual(mismatch?.pooled, undefined);
  assert.deepStrictEqual(mismatch?.score, {
    expected: '40..60',
    got: '30',
    gotHue: 'yellow',
  });
});

test('an open-ended score range is not given a ceiling rbx never declared', () => {
  const scored = solution(
    0,
    'sols/partial.cpp',
    'INCORRECT',
    [],
    solutionReport({
      expectedOutcome: 'INCORRECT',
      outcome: 'wrong-answer',
      status: 'UNEXPECTED_SCORE',
      matchesExpectation: false,
      pooledMatchesExpectation: true,
      score: 30,
      expectedScore: [40, 1e9],
    }),
  );
  const { rows } = buildViewModel(view([scored]));
  assert.strictEqual(rowById(rows, '/w/a::0').detail?.mismatch?.score?.expected, '40..');
});

test('only the solution that missed its declaration is counted', () => {
  const model = buildViewModel(view([MAIN, PARTIAL, MISLABELED]));
  assert.strictEqual(model.mismatches, 1);
  assert.strictEqual(model.empty, false);
});

test('an undeclared or ANY expectation leaves the gutter alone', () => {
  const undeclared = solution(0, 'sols/x.cpp', undefined, [], solutionReport({ index: 0 }));
  const any = solution(1, 'sols/y.cpp', 'ANY', [], solutionReport({ index: 1 }));
  const { rows } = buildViewModel(view([undeclared, any]));
  assert.strictEqual(rowById(rows, '/w/a::0').gutter, 'none');
  assert.strictEqual(rowById(rows, '/w/a::0').labelHue, undefined);
  assert.strictEqual(rowById(rows, '/w/a::0').labelBold, false);
  assert.strictEqual(rowById(rows, '/w/a::1').gutter, 'none');
});

test('a solution still running has no gutter and never spells a verdict in its meta', () => {
  const pending = solution(0, 'sols/main.cpp', 'ACCEPTED', [
    group('main', [testcase('000', 'accepted'), testcase('001')]),
  ]);
  const { rows } = buildViewModel(view([pending]));
  const row = rowById(rows, '/w/a::0');
  assert.strictEqual(row.gutter, 'none');
  assert.strictEqual(row.mismatch, false);
  assert.deepStrictEqual(
    row.meta.map((span) => span.text),
    ['1/2'],
  );
  assert.deepStrictEqual(row.verdict, {
    icon: 'circle-outline',
    hue: 'dim',
    short: '?',
  });
});

test('a solution with no testcases at all reads as pending', () => {
  const { rows } = buildViewModel(view([solution(0, 'sols/main.cpp', 'ACCEPTED', [])]));
  assert.deepStrictEqual(
    rowById(rows, '/w/a::0').meta.map((span) => span.text),
    ['pending'],
  );
});

test('a finished solution shows score, time and memory but never its verdict', () => {
  const finished = solution(
    0,
    'sols/main.cpp',
    'ACCEPTED',
    [group('main', [testcase('000', 'accepted')], groupReport())],
    solutionReport({ score: 70, maxScore: 100, maxTime: 0.12, maxMemory: 2048 }),
  );
  const { rows } = buildViewModel(view([finished]));
  const row = rowById(rows, '/w/a::0');
  // Roles included, and in this order: the stylesheet hides a *suffix* of this
  // line as the sidebar narrows, so the order is the priority and the score
  // being ahead of both measurements is what keeps it on screen longest.
  assert.deepStrictEqual(row.meta, [
    { text: '[70/100]', hue: 'yellow', role: 'score' },
    { text: '120 ms', hue: 'dim', role: 'time' },
    { text: '2 KiB', hue: 'dim', role: 'memory' },
  ]);
  assert.deepStrictEqual(row.detail?.score, '[70/100]');
  assert.deepStrictEqual(row.detail?.scoreHue, 'yellow');
  assert.deepStrictEqual(row.detail?.maxTime, '120 ms');
  assert.deepStrictEqual(row.detail?.maxMemory, '2 KiB');
});

test('the score is hued like the console hues it: full green, zero red', () => {
  const scoreHueOf = (score: number) => {
    const run = solution(
      0,
      'sols/main.cpp',
      'ACCEPTED',
      [],
      solutionReport({ score, maxScore: 100 }),
    );
    const { rows } = buildViewModel(view([run]));
    const row = rowById(rows, '/w/a::0');
    // The meta line and the card must agree: they are the same score twice,
    // and a row whose `[0/100]` is red above a card whose `[0/100]` is not
    // reads as two different numbers.
    assert.strictEqual(row.meta[0]?.hue, row.detail?.scoreHue);
    return row.meta[0]?.hue;
  };
  assert.strictEqual(scoreHueOf(100), 'green');
  assert.strictEqual(scoreHueOf(30), 'yellow');
  assert.strictEqual(scoreHueOf(0), 'red');
});

test('only a group with its own outcomePerGroup declaration gets a gutter', () => {
  const declared = solution(
    0,
    'sols/main.cpp',
    'INCORRECT',
    [
      group('small', [testcase('000', 'accepted')], groupReport({ name: 'small' })),
      group(
        'big',
        [testcase('001', 'wrong-answer')],
        groupReport({
          name: 'big',
          outcome: 'wrong-answer',
          expectedOutcome: 'ACCEPTED',
          matchesExpectation: false,
        }),
      ),
    ],
    solutionReport({ expectedOutcome: 'INCORRECT', outcome: 'wrong-answer' }),
  );
  const { rows } = buildViewModel(view([declared]));
  const small = rowById(rows, '/w/a::0::small');
  const big = rowById(rows, '/w/a::0::big');
  assert.strictEqual(small.gutter, 'none');
  assert.strictEqual(big.gutter, 'missed');
  assert.strictEqual(big.mismatch, true);
  // A group that declares one draws it in both channels, exactly as a solution
  // does. Leaving the group level out of both is what made four groups that all
  // wanted a TLE read as four ordinary rows with a warning beside them.
  assert.deepStrictEqual(big.expectation, {
    label: 'AC',
    hue: 'green',
    bold: true,
    glyph: '\u2713',
    badge: '\u2713',
  });
  assert.strictEqual(big.labelHue, 'green');
  assert.strictEqual(big.labelBold, true);
  // ...and a group with no declaration of its own borrows none from the
  // solution above it, which declared INCORRECT.
  assert.strictEqual(small.expectation, undefined);
  assert.strictEqual(small.labelHue, undefined);
  // Group mismatches are not solution mismatches.
  assert.strictEqual(buildViewModel(view([declared])).mismatches, 0);
});

test('a group inherits nothing from a solution declaring ANY, and neither does the row', () => {
  const any = solution(
    0,
    'sols/x.cpp',
    'ANY',
    [group('small', [testcase('000', 'accepted')], groupReport({ name: 'small' }))],
    solutionReport({ expectedOutcome: 'ANY' }),
  );
  const { rows } = buildViewModel(view([any]));
  // ANY is how a setter declares nothing, so it earns no chip -- the same rule
  // the gutter already applied.
  assert.strictEqual(rowById(rows, '/w/a::0').expectation, undefined);
  assert.strictEqual(rowById(rows, '/w/a::0::small').expectation, undefined);
});

test('the histogram is ordered by count, ties by outcome name', () => {
  const many = solution(0, 'sols/main.cpp', 'ACCEPTED', [
    group('main', [
      testcase('000', 'accepted'),
      testcase('001', 'wrong-answer'),
      testcase('002', 'wrong-answer'),
      testcase('003', 'runtime-error'),
      testcase('004'),
    ]),
  ], solutionReport({ outcome: 'wrong-answer', matchesExpectation: false }));
  const { rows } = buildViewModel(view([many]));
  assert.deepStrictEqual(rowById(rows, '/w/a::0').detail?.histogram, [
    { short: 'WA', hue: 'red', count: 2 },
    { short: 'AC', hue: 'green', count: 1 },
    { short: 'RTE', hue: 'blue', count: 1 },
  ]);
});

test('every testcase opens the panes, whatever it did', () => {
  const mixed = solution(0, 'sols/main.cpp', 'ACCEPTED', [
    group('main', [testcase('000', 'accepted'), testcase('001', 'wrong-answer'), testcase('002')]),
  ]);
  const { rows } = buildViewModel(view([mixed]));
  // One gesture, not three. Which channel the second pane lands on is the
  // opener's sticky state -- a row that picked a command by outcome would reset
  // it every time the selection moved, which is exactly what makes the switch
  // useless for comparing one channel across several tests.
  for (const stem of ['000', '001', '002']) {
    assert.strictEqual(
      rowById(rows, `/w/a::0::main::${stem}`).primaryCommand,
      'rbx.openTestcase',
    );
  }
});

test('a solution opens its source, and a group opens nothing', () => {
  const one = solution(0, 'sols/main.cpp', 'ACCEPTED', [
    group('main', [testcase('000', 'accepted')]),
  ]);
  const { rows } = buildViewModel(view([one]));
  assert.strictEqual(rowById(rows, '/w/a::0').primaryCommand, 'rbx.openSolution');
  // A group is a heading over testcases; there is no file behind it to open.
  assert.strictEqual(rowById(rows, '/w/a::0::main').primaryCommand, undefined);
});

test('a testcase shows time and memory, and not the checker message', () => {
  const one = solution(0, 'sols/main.cpp', 'ACCEPTED', [
    group('main', [
      testcase('000', 'wrong-answer', {
        evaluation: { outcome: 'wrong-answer', time: 0.05, memory: 1024, message: 'wrong at line 1' },
      }),
    ]),
  ]);
  const { rows } = buildViewModel(view([one]));
  const row = rowById(rows, '/w/a::0::main::000');
  // The whole array, so a checker's free-form line cannot creep back into a
  // 22px row and push the timings out of it.
  assert.deepStrictEqual(row.meta, [
    { text: '50 ms', hue: 'dim', role: 'time' },
    { text: '1 KiB', hue: 'dim', role: 'memory' },
  ]);
  assert.strictEqual(row.expandable, false);
  assert.strictEqual(row.section, 'rbx.testcase');
  assert.strictEqual(row.detail, undefined);
});

test('the search haystack carries the verdict, and mismatch only when missed', () => {
  const { rows } = buildViewModel(view([MAIN, PARTIAL, MISLABELED]));
  // `ac` once, not twice: on a healthy solution the declaration and the verdict
  // are the same word.
  assert.strictEqual(rowById(rows, '/w/a::0').search, 'sols/main.cpp ac');
  assert.strictEqual(rowById(rows, '/w/a::1').search, 'sols/partial.cpp wa incorrect');
  assert.strictEqual(
    rowById(rows, '/w/a::2').search,
    'sols/mislabeled.cpp wa incorrect mismatch',
  );
  assert.strictEqual(rowById(rows, '/w/a::0::main::000').search, 'main/000 ac');
  // Typing `tle` reaches the group that *wanted* one, which is the only way to
  // find it: nothing it produced is spelled TLE.
  assert.strictEqual(rowById(rows, '/w/a::2::small').search, 'small ac tle mismatch');
});

test('a package with no run on disk produces an empty model', () => {
  const model = buildViewModel({ pkg: PKG, run: undefined });
  assert.deepStrictEqual(model.rows, []);
  assert.strictEqual(model.empty, true);
  assert.strictEqual(model.mismatches, 0);
});

test('a run that covered no solution is empty too', () => {
  // A different thing from no run at all, and the one the view actually meets
  // while a run is starting: `skeleton.yml` is written before the first
  // solution resolves, so the report is readable and lists nothing.
  const model = buildViewModel(view([]));
  assert.deepStrictEqual(model.rows, []);
  assert.strictEqual(model.empty, true);
  assert.strictEqual(model.mismatches, 0);
});

test('a lone solution opens by default; one of several does not', () => {
  const solo = buildViewModel(view([MAIN]));
  const soloRow = rowById(solo.rows, '/w/a::0');
  assert.strictEqual(soloRow.expandable, true);
  assert.strictEqual(soloRow.defaultExpanded, true);

  const many = buildViewModel(view([MAIN, PARTIAL]));
  assert.strictEqual(rowById(many.rows, '/w/a::0').defaultExpanded, false);
  assert.strictEqual(rowById(many.rows, '/w/a::0::main').defaultExpanded, true);
  assert.strictEqual(rowById(many.rows, '/w/a::0::main::000').expandable, false);
});

test('a solution starts at depth 0, and every child names the row above it', () => {
  // Depth 0 for the solution is the whole of what dropping the package level
  // bought: the selector says which package this is, so nothing indents under
  // it and there is no offset to derive from the walk.
  const { rows } = buildViewModel(view([MAIN, PARTIAL]));
  assert.deepStrictEqual(
    rows.map((row) => [row.id, row.kind, row.depth, row.parentId]),
    [
      ['/w/a::0', 'solution', 0, undefined],
      ['/w/a::0::main', 'group', 1, '/w/a::0'],
      ['/w/a::0::main::000', 'testcase', 2, '/w/a::0::main'],
      ['/w/a::1', 'solution', 0, undefined],
      ['/w/a::1::big', 'group', 1, '/w/a::1'],
      ['/w/a::1::big::001', 'testcase', 2, '/w/a::1::big'],
    ],
  );
});

// `rbx.solutionLabel`. The styles themselves are pinned in solutionLabel.test.ts;
// what these hold to account is that the view model reaches them and that the
// row keeps the whole path in the two places the label is not the whole path.

const NESTED = solution(3, 'sols/slow/tle.cpp', 'INCORRECT', [], solutionReport({
  path: 'sols/slow/tle.cpp',
  index: 3,
  expectedOutcome: 'INCORRECT',
  outcome: 'time-limit-exceeded',
}));

test('the label style picks how much of a solution path a row shows', () => {
  const solutions = [MAIN, PARTIAL, NESTED];
  const labelsOf = (style: Parameters<typeof buildViewModel>[1]): string[] =>
    buildViewModel(view(solutions), style)
      .rows.filter((row) => row.kind === 'solution')
      .map((row) => row.label);

  assert.deepStrictEqual(labelsOf('full'), [
    'sols/main.cpp',
    'sols/partial.cpp',
    'sols/slow/tle.cpp',
  ]);
  assert.deepStrictEqual(labelsOf('trimmed'), ['main.cpp', 'partial.cpp', 'slow/tle.cpp']);
  assert.deepStrictEqual(labelsOf('basename'), ['main.cpp', 'partial.cpp', 'tle.cpp']);
  // The default is what the host omits the argument to get.
  assert.deepStrictEqual(labelsOf(undefined), labelsOf('trimmed'));
});

test('trimming is computed over this package alone', () => {
  const elsewhere = solution(1, 'other/dir/x.cpp', 'ACCEPTED', [], solutionReport({
    path: 'other/dir/x.cpp',
    index: 1,
  }));
  // A sibling package keeping its solutions somewhere unusual can no longer
  // reach this model at all -- only the selected package's solutions decide
  // what the prefix is, and here they share nothing, so nothing is dropped.
  const { rows } = buildViewModel(view([MAIN, elsewhere]), 'trimmed');
  assert.strictEqual(rowById(rows, '/w/a::0').label, 'sols/main.cpp');
  assert.strictEqual(rowById(rows, '/w/a::1').label, 'other/dir/x.cpp');
});

test('a shortened label keeps the whole path for the tooltip', () => {
  const { rows } = buildViewModel(view([MAIN, PARTIAL]), 'basename');
  assert.strictEqual(rowById(rows, '/w/a::0').labelTitle, 'sols/main.cpp');
  // Nothing was dropped, so there is nothing for a tooltip to add.
  const full = buildViewModel(view([MAIN, PARTIAL]), 'full');
  assert.strictEqual(rowById(full.rows, '/w/a::0').labelTitle, undefined);
});

test('the filter matches the full path whatever the label shows', () => {
  const { rows } = buildViewModel(view([MAIN, PARTIAL]), 'basename');
  assert.strictEqual(rowById(rows, '/w/a::0').search, 'sols/main.cpp ac');
  assert.strictEqual(rowById(rows, '/w/a::1').search, 'sols/partial.cpp wa incorrect');
});

// `sols/slow.cpp` declares TLE and gets one, so every expectation-shaped
// channel in the view reads clean -- the gutter is `met`, the chip is TLE, the
// status is OK. The only thing saying its slowness is borderline is the warning
// rbx published, and before it existed here this row was indistinguishable from
// a decisively slow one.
const BORDERLINE_SLOW = solution(
  0,
  'sols/slow.cpp',
  'TIME_LIMIT_EXCEEDED',
  [
    group(
      'small',
      [testcase('000', 'time-limit-exceeded')],
      groupReport({ name: 'small', outcome: 'time-limit-exceeded' }),
    ),
    group(
      'big',
      [testcase('001', 'time-limit-exceeded')],
      groupReport({ name: 'big', outcome: 'time-limit-exceeded', runUnderDoubleTl: true }),
    ),
  ],
  solutionReport({
    path: 'sols/slow.cpp',
    expectedOutcome: 'TIME_LIMIT_EXCEEDED',
    outcome: 'time-limit-exceeded',
    matchesExpectation: true,
    runUnderDoubleTl: true,
    groups: [
      groupReport({ name: 'small', outcome: 'time-limit-exceeded' }),
      groupReport({ name: 'big', outcome: 'time-limit-exceeded', runUnderDoubleTl: true }),
    ],
  }),
);

test('a solution that only fit in double TL is warned about while still matching', () => {
  const { rows } = buildViewModel(view([BORDERLINE_SLOW]));
  const row = rowById(rows, '/w/a::0');

  // The gutter says warned, not missed: the declaration held, and `mismatch`
  // -- which is what the header counts and the red rule keys on -- stays false.
  assert.strictEqual(row.gutter, 'warned');
  assert.strictEqual(row.mismatch, false);
  assert.strictEqual(row.verdict?.short, 'TLE');
  assert.deepStrictEqual(
    row.warnings.map((warning) => warning.kind),
    ['double-tl-passed'],
  );
});

test('a solution warning names the groups it came from', () => {
  const { rows } = buildViewModel(view([BORDERLINE_SLOW]));
  const row = rowById(rows, '/w/a::0');
  assert.deepStrictEqual(row.warnings[0].groups, ['big']);
});

test('a group carries its own warning, with no attribution to repeat', () => {
  const { rows } = buildViewModel(view([BORDERLINE_SLOW]));
  assert.deepStrictEqual(rowById(rows, '/w/a::0::small').warnings, []);
  const big = rowById(rows, '/w/a::0::big');
  assert.strictEqual(big.gutter, 'warned');
  assert.deepStrictEqual(
    big.warnings.map((warning) => warning.kind),
    ['double-tl-passed'],
  );
  // The row is already the attribution; repeating `big` in the sentence on the
  // `big` row says nothing.
  assert.deepStrictEqual(big.warnings[0].groups, []);
});

test('the two double-TL facts stay independent rather than merging', () => {
  // Both are unions over the pooled layer and every group, so two groups can
  // each raise one -- gating one on the other is how the second was lost on the
  // console side (#607).
  const both = solution(
    0,
    'sols/slow.cpp',
    'TIME_LIMIT_EXCEEDED',
    [],
    solutionReport({
      expectedOutcome: 'TIME_LIMIT_EXCEEDED',
      outcome: 'time-limit-exceeded',
      runUnderDoubleTl: true,
      doubleTlVerdicts: ['wrong-answer'],
      groups: [
        groupReport({ name: 'small', runUnderDoubleTl: true }),
        groupReport({ name: 'big', doubleTlVerdicts: ['wrong-answer'] }),
      ],
    }),
  );
  const row = rowById(buildViewModel(view([both])).rows, '/w/a::0');

  assert.deepStrictEqual(
    row.warnings.map((warning) => warning.kind),
    ['double-tl-passed', 'double-tl-verdicts'],
  );
  // Each fact names only the group that raised *it*.
  assert.deepStrictEqual(row.warnings[0].groups, ['small']);
  assert.deepStrictEqual(row.warnings[1].groups, ['big']);
  assert.deepStrictEqual(
    row.warnings[1].verdicts.map((verdict) => verdict.text),
    ['WA'],
  );
});

test('a warned solution is counted apart from a mismatched one', () => {
  const { mismatches, warned } = buildViewModel(view([MAIN, BORDERLINE_SLOW]));
  // A run where every declaration held still has something to report.
  assert.strictEqual(mismatches, 0);
  assert.strictEqual(warned, 1);
});

test('a testcase carries no double-TL warning: that fact is decided a layer above it', () => {
  const { rows } = buildViewModel(view([BORDERLINE_SLOW]));
  assert.deepStrictEqual(rowById(rows, '/w/a::0::big::001').warnings, []);
});

// A solution that passed and still tripped a sanitizer. Every channel that
// answers "did the declaration hold" says yes, which is the whole reason the
// warning has to be a fourth one.
const SANITIZED = solution(
  0,
  'sols/main.cpp',
  'ACCEPTED',
  [
    group('small', [testcase('000', 'accepted')], groupReport({ name: 'small' })),
    group(
      'big',
      [
        testcase('001', 'accepted'),
        testcase('002', 'accepted', { evaluation: { outcome: 'accepted', sanitizerWarnings: true } }),
      ],
      groupReport({ name: 'big', sanitizerWarnings: true }),
    ),
  ],
  solutionReport({
    sanitizerWarnings: true,
    groups: [
      groupReport({ name: 'small' }),
      groupReport({ name: 'big', sanitizerWarnings: true }),
    ],
  }),
);

test('a solution that passed with a sanitizer finding is warned, not clean', () => {
  const { rows, warned, mismatches } = buildViewModel(view([SANITIZED]));
  const row = rowById(rows, '/w/a::0');

  assert.strictEqual(row.gutter, 'warned');
  assert.strictEqual(row.mismatch, false);
  assert.deepStrictEqual(
    row.warnings.map((warning) => warning.kind),
    ['sanitizer'],
  );
  // Named, so the reader is not sent through every group looking for it.
  assert.deepStrictEqual(row.warnings[0].groups, ['big']);
  assert.strictEqual(warned, 1);
  assert.strictEqual(mismatches, 0);
});

test('a group row carries the finding without repeating its own name', () => {
  const { rows } = buildViewModel(view([SANITIZED]));
  assert.deepStrictEqual(rowById(rows, '/w/a::0::small').warnings, []);
  const big = rowById(rows, '/w/a::0::big');
  assert.deepStrictEqual(
    big.warnings.map((warning) => warning.kind),
    ['sanitizer'],
  );
  assert.deepStrictEqual(big.warnings[0].groups, []);
});

test('a sanitized testcase carries the mark, so the reader knows which stderr', () => {
  const { rows } = buildViewModel(view([SANITIZED]));
  assert.strictEqual(rowById(rows, '/w/a::0::big::001').gutter, 'none');
  const marked = rowById(rows, '/w/a::0::big::002');
  assert.strictEqual(marked.gutter, 'warned');
  assert.deepStrictEqual(
    marked.warnings.map((warning) => warning.kind),
    ['sanitizer'],
  );
  assert.ok(marked.search.includes('sanitizer'));
});

test('a marked testcase is not counted as a warned solution', () => {
  // The strip counts solutions. A run whose solution row is clean must not be
  // reported as warned because a testcase row underneath carries a mark.
  const testcaseOnly = solution(0, 'sols/main.cpp', 'ACCEPTED', [
    group('main', [
      testcase('000', 'accepted', {
        evaluation: { outcome: 'accepted', sanitizerWarnings: true },
      }),
    ]),
  ]);
  const { warned } = buildViewModel(view([testcaseOnly]));
  assert.strictEqual(warned, 0);
});

test('a sanitizer warning does not answer to a double-tl filter', () => {
  const { rows } = buildViewModel(view([SANITIZED]));
  const search = rowById(rows, '/w/a::0').search;
  assert.ok(search.includes('warning'));
  assert.ok(search.includes('sanitizer'));
  // The token used to be a fixed pair, so this row claimed a fact it never had.
  assert.ok(!search.includes('double-tl'));
});

test('a warned row is reachable by filtering for it', () => {
  const { rows } = buildViewModel(view([BORDERLINE_SLOW]));
  const search = rowById(rows, '/w/a::0').search;
  assert.ok(search.includes('warning'));
  assert.ok(search.includes('double-tl'));
});

test('a solution rbx did not warn about carries no warnings', () => {
  const { rows, warned } = buildViewModel(view([MAIN]));
  assert.deepStrictEqual(rowById(rows, '/w/a::0').warnings, []);
  assert.strictEqual(rowById(rows, '/w/a::0').gutter, 'met');
  assert.strictEqual(warned, 0);
});

test('a solution that both missed and warned draws the miss', () => {
  // One glyph, and the miss is the more serious of the two. The warning is
  // still in the card underneath, so nothing is lost by ranking them.
  const both = solution(
    0,
    'sols/broken.cpp',
    'TIME_LIMIT_EXCEEDED',
    [],
    solutionReport({
      expectedOutcome: 'TIME_LIMIT_EXCEEDED',
      outcome: 'wrong-answer',
      matchesExpectation: false,
      runUnderDoubleTl: true,
    }),
  );
  const { rows, mismatches, warned } = buildViewModel(view([both]));
  const row = rowById(rows, '/w/a::0');

  assert.strictEqual(row.gutter, 'missed');
  assert.strictEqual(row.mismatch, true);
  assert.strictEqual(row.warnings.length, 1);
  // Counted once, in the more serious channel.
  assert.strictEqual(mismatches, 1);
  assert.strictEqual(warned, 0);
});

// `big` hides a WA under a soft TLE, and rbx says no expectation accepts it.
const HIDDEN_WA = solution(
  0,
  'sols/slow-and-wrong.cpp',
  'TIME_LIMIT_EXCEEDED',
  [
    group(
      'big',
      [
        testcase('000', 'accepted'),
        testcase('001', 'time-limit-exceeded', {
          evaluation: { outcome: 'time-limit-exceeded', noTleOutcome: 'wrong-answer' },
        }),
      ],
      groupReport({
        name: 'big',
        outcome: 'time-limit-exceeded',
        unexpectedNoTleVerdicts: ['wrong-answer'],
      }),
    ),
  ],
  solutionReport({
    expectedOutcome: 'TIME_LIMIT_EXCEEDED',
    outcome: 'time-limit-exceeded',
    doubleTlVerdicts: ['wrong-answer'],
  }),
);

test('a testcase shows the verdict a soft TLE hid, beside the one it got', () => {
  const { rows } = buildViewModel(view([HIDDEN_WA]));
  const leaf = rowById(rows, '/w/a::0::big::001');

  assert.strictEqual(leaf.verdict?.short, 'TLE');
  assert.strictEqual(leaf.verdict?.under?.text, 'WA');
  // Hued by what it is, not by the chip it glosses -- the disagreement between
  // the two is the reason it is on the row at all.
  assert.strictEqual(leaf.verdict?.under?.hue, 'red');
});

test('a testcase with no hidden verdict shows only what it got', () => {
  const { rows } = buildViewModel(view([HIDDEN_WA]));
  assert.strictEqual(rowById(rows, '/w/a::0::big::000').verdict?.under, undefined);
});

test('a hidden verdict rbx did not flag is not shown', () => {
  // The evaluation carries it either way; whether it is worth showing is rbx's
  // answer, and an empty list is a `no`. A solution declared `incorrect` that
  // answers wrongly under a soft TLE lands here -- the setter said as much.
  const quiet = solution(
    0,
    'sols/slow.cpp',
    'INCORRECT',
    [
      group(
        'big',
        [
          testcase('000', 'time-limit-exceeded', {
            evaluation: { outcome: 'time-limit-exceeded', noTleOutcome: 'wrong-answer' },
          }),
        ],
        groupReport({ name: 'big', outcome: 'time-limit-exceeded' }),
      ),
    ],
    solutionReport({ expectedOutcome: 'INCORRECT', outcome: 'time-limit-exceeded' }),
  );
  const { rows } = buildViewModel(view([quiet]));
  assert.strictEqual(rowById(rows, '/w/a::0::big::000').verdict?.under, undefined);
});

test('a hidden verdict is not shown before its group has a report', () => {
  // Mid-run there is no published answer to read, and guessing one would put
  // the expectation matcher back into this extension.
  const pending = solution(0, 'sols/slow.cpp', 'TIME_LIMIT_EXCEEDED', [
    group('big', [
      testcase('000', 'time-limit-exceeded', {
        evaluation: { outcome: 'time-limit-exceeded', noTleOutcome: 'wrong-answer' },
      }),
    ]),
  ]);
  const { rows } = buildViewModel(view([pending]));
  assert.strictEqual(rowById(rows, '/w/a::0::big::000').verdict?.under, undefined);
});

test('the hidden verdict joins the row it is on in the filter', () => {
  const { rows } = buildViewModel(view([HIDDEN_WA]));
  // Typing `wa` has to find the testcases where a soft TLE hid one; they are
  // exactly the rows a WA filter would otherwise miss.
  assert.ok(rowById(rows, '/w/a::0::big::001').search.includes('wa'));
});

test('only leaves carry a hidden verdict', () => {
  // It is a fact about one run of one testcase. A group or a solution that
  // aggregated them would be inventing a verdict nothing produced.
  const { rows } = buildViewModel(view([HIDDEN_WA]));
  assert.strictEqual(rowById(rows, '/w/a::0').verdict?.under, undefined);
  assert.strictEqual(rowById(rows, '/w/a::0::big').verdict?.under, undefined);
});

// --- Compilation findings ----------------------------------------------------

test('a run that compiled cleanly has no findings at all', () => {
  // Absent, not empty: the panel's presence in the view is itself the signal,
  // so a package with nothing to report must not carry a header saying so.
  assert.strictEqual(buildViewModel(view([MAIN])).findings, undefined);
});

test('a solution that failed to compile is reported though it is in no row', () => {
  // The whole point. rbx filters it out of the skeleton's `solutions` before
  // the run starts, so `rows` cannot know it exists.
  const model = buildViewModel(
    view([MAIN], [finding('sols/broken.cpp', { status: 'FAILED', log: 'compilation/0.log' })]),
  );
  assert.ok(!model.rows.some((row) => row.label.includes('broken')));
  const findings = model.findings;
  assert.ok(findings !== undefined);
  assert.strictEqual(findings.rows.length, 1);
  assert.strictEqual(findings.rows[0].severity, 'error');
  assert.strictEqual(findings.rows[0].summary, 'CE');
});

test('a solution that tripped a sanitizer gets a row of its own in the panel', () => {
  // Not a compile finding, and in the panel anyway: the tree answers per
  // solution, and the panel is where a reader asks what this run had to say
  // about the package as a list.
  const model = buildViewModel(view([SANITIZED]));
  const findings = model.findings;
  assert.ok(findings !== undefined);
  assert.strictEqual(findings.rows.length, 1);
  const row = findings.rows[0];
  assert.strictEqual(row.kind, 'sanitizer');
  assert.strictEqual(row.label, 'main.cpp');
  // The count is the testcases that tripped, not the groups and not the whole
  // testset: one in `edge`-like `big`, two more nowhere.
  assert.strictEqual(row.summary, '1 sanitized');
  // Never an error: the solution compiled, ran and answered.
  assert.strictEqual(row.severity, 'warning');
  assert.strictEqual(findings.errors, false);
  // Nothing to expand, and its own click goes to the source rather than to a
  // compile log that says nothing about it.
  assert.deepStrictEqual(row.warnings, []);
  assert.strictEqual(row.primaryCommand, 'rbx.openSolution');
  // The solution's own id, so every action resolves to the node the host
  // already knows.
  assert.strictEqual(row.id, '/w/a::0');
});

test('a run whose sanitizer never fired carries no panel', () => {
  assert.strictEqual(buildViewModel(view([MAIN])).findings, undefined);
});

test('a sanitizer row joins the compile findings rather than replacing them', () => {
  const model = buildViewModel(
    view([SANITIZED], [finding('sols/broken.cpp', { status: 'FAILED' })]),
  );
  const kinds = model.findings?.rows.map((row) => row.kind);
  // The compile phase first: a solution that never compiled never reached a
  // sanitizer.
  assert.deepStrictEqual(kinds, ['compilation', 'sanitizer']);
  assert.strictEqual(model.findings?.badge, 2);
  // Still opened by the compile error alone.
  assert.strictEqual(model.findings?.errors, true);
});

test('the badge counts rows and reddens as soon as one failed to compile', () => {
  const model = buildViewModel(
    view(
      [MAIN],
      [
        finding('sols/warned.cpp', {
          warnings: [{ file: 'sols/x.cpp', line: 4, flag: '-Wsign-compare', msg: 'comparison' }],
        }),
        finding('sols/broken.cpp', { status: 'FAILED' }),
      ],
    ),
  );
  // Rows, not warnings: the badge has to agree with what opening it shows.
  assert.strictEqual(model.findings?.badge, 2);
  assert.strictEqual(model.findings?.hue, 'red');
  assert.strictEqual(model.findings?.errors, true);
});

test('a warnings-only run stays yellow and does not ask to be opened', () => {
  const model = buildViewModel(
    view(
      [MAIN],
      [finding('sols/warned.cpp', { warnings: [{ file: 'sols/x.cpp', line: 4, msg: 'comparison' }] })],
    ),
  );
  assert.strictEqual(model.findings?.hue, 'yellow');
  assert.strictEqual(model.findings?.errors, false);
});

test('the summary counts warnings, singular when there is one', () => {
  const model = buildViewModel(
    view(
      [MAIN],
      [
        finding('sols/one.cpp', { warnings: [{ file: 'sols/x.cpp', line: 4, msg: 'a' }] }),
        finding('sols/three.cpp', {
          warnings: [
            { file: 'sols/x.cpp', line: 4, msg: 'a' },
            { file: 'sols/x.cpp', line: 5, msg: 'b' },
            { file: 'sols/x.cpp', line: 6, msg: 'c' },
          ],
        }),
      ],
    ),
  );
  assert.deepStrictEqual(
    model.findings?.rows.map((row) => row.summary),
    ['1 warn', '3 warns'],
  );
});

test('a finding row is hued by what its solution declared, not by severity', () => {
  // The label is the identity channel here as it is in the tree, so a row in
  // the panel and the same row above it are recognisably the same solution.
  // Severity has the gutter and the wash to itself.
  const model = buildViewModel(
    view(
      [MAIN],
      [finding('sols/wa.cpp', { status: 'FAILED', expectedOutcome: 'WRONG_ANSWER' })],
    ),
  );
  assert.strictEqual(model.findings?.rows[0].labelHue, 'red');
  assert.strictEqual(model.findings?.rows[0].labelBold, false);
  assert.strictEqual(model.findings?.rows[0].severity, 'error');
});

test('a finding label is trimmed against the solutions it sits with', () => {
  // Labelled on its own, a solution absent from `solutions` would be trimmed
  // against a different prefix from every row above it.
  const model = buildViewModel(view([MAIN], [finding('sols/broken.cpp')]), 'trimmed');
  assert.strictEqual(model.findings?.rows[0].label, 'broken.cpp');
  assert.strictEqual(model.findings?.rows[0].labelTitle, 'sols/broken.cpp');
});

test('a warning carries its position and flag, and its message only as a title', () => {
  const model = buildViewModel(
    view(
      [MAIN],
      [
        finding('sols/warned.cpp', {
          warnings: [
            { file: 'sols/x.cpp', line: 41, flag: '-Wsign-compare', msg: 'comparison of integer expressions' },
            { file: 'sols/x.cpp', line: 88, msg: 'unflagged something' },
          ],
        }),
      ],
    ),
  );
  const warnings = model.findings?.rows[0].warnings ?? [];
  assert.deepStrictEqual(
    warnings.map((warning) => [warning.line, warning.flag]),
    [
      [41, '-Wsign-compare'],
      [88, ''],
    ],
  );
  assert.strictEqual(warnings[0].title, 'comparison of integer expressions');
});

test('the signature changes when a warning becomes an error', () => {
  // What the client compares to decide the panel should open again. Identity
  // alone would let the same file turn from warned to broken unannounced.
  const warned = buildViewModel(view([MAIN], [finding('sols/x.cpp')]));
  const failed = buildViewModel(view([MAIN], [finding('sols/x.cpp', { status: 'FAILED' })]));
  assert.notStrictEqual(warned.findings?.signature, failed.findings?.signature);
});

test('the signature is stable across re-posts of the same run', () => {
  const first = buildViewModel(view([MAIN], [finding('sols/x.cpp')]));
  const second = buildViewModel(view([MAIN], [finding('sols/x.cpp')]));
  assert.strictEqual(first.findings?.signature, second.findings?.signature);
});

test('a run where nothing compiled is empty and still reports', () => {
  // The view is empty *and* has everything to say -- the case that used to show
  // a bare "no run found".
  const model = buildViewModel(view([], [finding('sols/broken.cpp', { status: 'FAILED' })]));
  assert.strictEqual(model.empty, true);
  assert.strictEqual(model.findings?.rows.length, 1);
});

// The card, built here so the renderer is handed facts rather than decisions.
// Both of these were parsed out of every run already and shown nowhere: the
// checker's message and where the testcase came from.

test('a testcase carries the checker message its row cannot hold', () => {
  const failing = solution(0, 'sols/wa.cpp', 'WRONG_ANSWER', [
    group('main', [
      testcase('000', 'wrong-answer', {
        evaluation: {
          outcome: 'wrong-answer',
          message: 'wrong answer, expected 14, found 12',
        },
      }),
    ]),
  ]);
  const { rows } = buildViewModel(view([failing]));
  const row = rowById(rows, '/w/a::0::main::000');
  assert.strictEqual(row.card?.title, 'main/000');
  assert.strictEqual(row.card?.checker, 'wrong answer, expected 14, found 12');
  // And still not on the row itself, which is 22px tall and already spending
  // its width on the timings.
  assert.ok(!row.meta.some((span) => span.text.includes('wrong answer')));
});

test('a checker that never ran leaves the card without a message', () => {
  // A hard TLE never reached the checker, and neither has a testcase whose
  // evaluation has not landed yet. Both read as "nothing to say" rather than as
  // an empty message.
  const slow = solution(0, 'sols/tle.cpp', 'TIME_LIMIT_EXCEEDED', [
    group('main', [
      testcase('000', 'time-limit-exceeded'),
      testcase('001', 'wrong-answer', { evaluation: { outcome: 'wrong-answer', message: '' } }),
      testcase('002'),
    ]),
  ]);
  const { rows } = buildViewModel(view([slow]));
  for (const stem of ['000', '001', '002']) {
    assert.strictEqual(rowById(rows, `/w/a::0::main::${stem}`).card?.checker, undefined);
  }
});

test('provenance names the generator call, and opens only what is a real file', () => {
  const generated = solution(0, 'sols/main.cpp', 'ACCEPTED', [
    group('main', [
      testcase('000', 'accepted', {
        entry: {
          group: 'main',
          index: 0,
          generatorName: 'gen_random',
          generatorArgs: '5 3 --seed=7',
          generatorScript: 'gens/script.txt',
          generatorScriptLine: 12,
        },
      }),
    ]),
  ]);
  const { rows } = buildViewModel(view([generated]));
  assert.deepStrictEqual(rowById(rows, '/w/a::0::main::000').card?.origins, [
    {
      // The arguments come with the name: every test in a group is usually the
      // same generator at different sizes, and the arguments are what tell them
      // apart. A generator *name* is not a path, so there is nothing to open.
      text: 'gen_random 5 3 --seed=7',
      title: 'Generated by gen_random 5 3 --seed=7',
    },
    {
      // rbx records a script entry as a real `path:line`, so this one opens.
      text: 'gens/script.txt:12',
      open: 'rbx.openGeneratorScript',
      title: 'Generated from gens/script.txt:12',
    },
  ]);
});

test('a copied testcase says where it was copied from, and opens it', () => {
  const copied = solution(0, 'sols/main.cpp', 'ACCEPTED', [
    group('samples', [
      testcase('000', 'accepted', {
        entry: { group: 'samples', index: 0, copiedFrom: 'tests/manual/01.in' },
      }),
    ]),
  ]);
  const { rows } = buildViewModel(view([copied]));
  assert.deepStrictEqual(rowById(rows, '/w/a::0::samples::000').card?.origins, [
    {
      text: 'tests/manual/01.in',
      open: 'rbx.openCopiedFrom',
      title: 'Copied from tests/manual/01.in',
    },
  ]);
});

test('only testcases carry a card', () => {
  // The card describes one testcase. A solution row has its own detail card,
  // and a group row is a heading with no artifacts behind it at all.
  const one = solution(0, 'sols/main.cpp', 'ACCEPTED', [
    group('main', [testcase('000', 'accepted')]),
  ]);
  const { rows } = buildViewModel(view([one]));
  assert.strictEqual(rowById(rows, '/w/a::0').card, undefined);
  assert.strictEqual(rowById(rows, '/w/a::0::main').card, undefined);
  assert.notStrictEqual(rowById(rows, '/w/a::0::main::000').card, undefined);
});


test('a sanitized run carries its notices', () => {
  const { notices } = buildViewModel(
    view([MAIN], [], { sanitized: true, onlyAccepted: true }),
  );
  assert.deepStrictEqual(
    notices.map((notice) => notice.kind),
    ['sanitized-run', 'accepted-only'],
  );
});

test('a sanitized run the user narrowed themselves says only the first', () => {
  // Naming solutions on the command line is a deliberate act, so the shortened
  // list is not news; the dropped time limit still is.
  const { notices } = buildViewModel(view([MAIN], [], { sanitized: true }));
  assert.deepStrictEqual(
    notices.map((notice) => notice.kind),
    ['sanitized-run'],
  );
});

test('an ordinary run carries no notices', () => {
  assert.deepStrictEqual(buildViewModel(view([MAIN])).notices, []);
});
