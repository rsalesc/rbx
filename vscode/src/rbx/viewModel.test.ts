import * as assert from 'assert';
import { test } from 'node:test';

import type { PackageLayout } from './layout';
import type { PackageRunView } from './nodes';
import type { GroupReport, SolutionReport } from './report';
import type { GroupRun, PackageRun, SolutionRun, TestcaseRun } from './store';
import { Row, buildViewModel } from './viewModel';

// The fixtures below transcribe rbx's `outcome-per-group` e2e package: a main
// solution that passes, one declared INCORRECT that fails as declared, and one
// declared INCORRECT that fails in the wrong places. Those three are what a
// naive encoding folds into one red row.

const PKG: PackageLayout = { root: '/w/a' };
const OTHER: PackageLayout = { root: '/w/b' };

function testcase(stem: string, outcome?: string, over: Partial<TestcaseRun> = {}): TestcaseRun {
  return {
    entry: { group: 'main', index: 0 },
    stem,
    evaluation: outcome === undefined ? undefined : { outcome },
    inputPath: '',
    answerPath: '',
    outputPath: '',
    stderrPaths: [],
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

function run(solutions: readonly SolutionRun[]): PackageRun {
  return { skeleton: { solutions: [], entries: [], groups: [] }, solutions };
}

function view(solutions: readonly SolutionRun[]): PackageRunView {
  return { pkg: PKG, run: run(solutions) };
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
  const { rows } = buildViewModel([view([MAIN])]);
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
  const { rows } = buildViewModel([view([MAIN, PARTIAL])]);
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
  const { rows } = buildViewModel([view([MAIN, PARTIAL, MISLABELED])]);
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
  const { rows } = buildViewModel([view([optimistic])]);
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
  const { rows } = buildViewModel([view([stale])]);
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
  const { rows } = buildViewModel([view([scored])]);
  const mismatch = rowById(rows, '/w/a::0').detail?.mismatch;
  assert.strictEqual(mismatch?.pooled, undefined);
  assert.deepStrictEqual(mismatch?.score, { expected: '40..60', got: '30' });
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
  const { rows } = buildViewModel([view([scored])]);
  assert.strictEqual(rowById(rows, '/w/a::0').detail?.mismatch?.score?.expected, '40..');
});

test('only the solution that missed its declaration is counted', () => {
  const model = buildViewModel([view([MAIN, PARTIAL, MISLABELED])]);
  assert.strictEqual(model.mismatches, 1);
  assert.strictEqual(model.empty, false);
});

test('an undeclared or ANY expectation leaves the gutter alone', () => {
  const undeclared = solution(0, 'sols/x.cpp', undefined, [], solutionReport({ index: 0 }));
  const any = solution(1, 'sols/y.cpp', 'ANY', [], solutionReport({ index: 1 }));
  const { rows } = buildViewModel([view([undeclared, any])]);
  assert.strictEqual(rowById(rows, '/w/a::0').gutter, 'none');
  assert.strictEqual(rowById(rows, '/w/a::0').labelHue, undefined);
  assert.strictEqual(rowById(rows, '/w/a::0').labelBold, false);
  assert.strictEqual(rowById(rows, '/w/a::1').gutter, 'none');
});

test('a solution still running has no gutter and never spells a verdict in its meta', () => {
  const pending = solution(0, 'sols/main.cpp', 'ACCEPTED', [
    group('main', [testcase('000', 'accepted'), testcase('001')]),
  ]);
  const { rows } = buildViewModel([view([pending])]);
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
  const { rows } = buildViewModel([view([solution(0, 'sols/main.cpp', 'ACCEPTED', [])])]);
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
  const { rows } = buildViewModel([view([finished])]);
  const row = rowById(rows, '/w/a::0');
  // Roles included, and in this order: the stylesheet hides a *suffix* of this
  // line as the sidebar narrows, so the order is the priority and the score
  // being ahead of both measurements is what keeps it on screen longest.
  assert.deepStrictEqual(row.meta, [
    { text: '[70/100]', hue: 'neutral', role: 'score' },
    { text: '120 ms', hue: 'dim', role: 'time' },
    { text: '2 KiB', hue: 'dim', role: 'memory' },
  ]);
  assert.deepStrictEqual(row.detail?.score, '[70/100]');
  assert.deepStrictEqual(row.detail?.maxTime, '120 ms');
  assert.deepStrictEqual(row.detail?.maxMemory, '2 KiB');
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
  const { rows } = buildViewModel([view([declared])]);
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
  });
  assert.strictEqual(big.labelHue, 'green');
  assert.strictEqual(big.labelBold, true);
  // ...and a group with no declaration of its own borrows none from the
  // solution above it, which declared INCORRECT.
  assert.strictEqual(small.expectation, undefined);
  assert.strictEqual(small.labelHue, undefined);
  // Group mismatches are not solution mismatches.
  assert.strictEqual(buildViewModel([view([declared])]).mismatches, 0);
});

test('a group inherits nothing from a solution declaring ANY, and neither does the row', () => {
  const any = solution(
    0,
    'sols/x.cpp',
    'ANY',
    [group('small', [testcase('000', 'accepted')], groupReport({ name: 'small' }))],
    solutionReport({ expectedOutcome: 'ANY' }),
  );
  const { rows } = buildViewModel([view([any])]);
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
  const { rows } = buildViewModel([view([many])]);
  assert.deepStrictEqual(rowById(rows, '/w/a::0').detail?.histogram, [
    { short: 'WA', hue: 'red', count: 2 },
    { short: 'AC', hue: 'green', count: 1 },
    { short: 'RTE', hue: 'blue', count: 1 },
  ]);
});

test('a testcase opens the diff when it failed and the input otherwise', () => {
  const mixed = solution(0, 'sols/main.cpp', 'ACCEPTED', [
    group('main', [testcase('000', 'accepted'), testcase('001', 'wrong-answer'), testcase('002')]),
  ]);
  const { rows } = buildViewModel([view([mixed])]);
  assert.strictEqual(rowById(rows, '/w/a::0::main::000').primaryCommand, 'rbx.openInput');
  assert.strictEqual(rowById(rows, '/w/a::0::main::001').primaryCommand, 'rbx.diffOutput');
  // No evaluation yet: there is nothing to diff against.
  assert.strictEqual(rowById(rows, '/w/a::0::main::002').primaryCommand, 'rbx.openInput');
  assert.strictEqual(rowById(rows, '/w/a::0').primaryCommand, undefined);
});

test('a testcase shows time and memory, and not the checker message', () => {
  const one = solution(0, 'sols/main.cpp', 'ACCEPTED', [
    group('main', [
      testcase('000', 'wrong-answer', {
        evaluation: { outcome: 'wrong-answer', time: 0.05, memory: 1024, message: 'wrong at line 1' },
      }),
    ]),
  ]);
  const { rows } = buildViewModel([view([one])]);
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
  const { rows } = buildViewModel([view([MAIN, PARTIAL, MISLABELED])]);
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
  const model = buildViewModel([{ pkg: PKG, run: undefined }]);
  assert.deepStrictEqual(model.rows, []);
  assert.strictEqual(model.empty, true);
  assert.strictEqual(model.mismatches, 0);
});

test('a lone solution opens by default; one of several does not', () => {
  const solo = buildViewModel([view([MAIN])]);
  const soloRow = rowById(solo.rows, '/w/a::0');
  assert.strictEqual(soloRow.expandable, true);
  assert.strictEqual(soloRow.defaultExpanded, true);

  const many = buildViewModel([view([MAIN, PARTIAL])]);
  assert.strictEqual(rowById(many.rows, '/w/a::0').defaultExpanded, false);
  assert.strictEqual(rowById(many.rows, '/w/a::0::main').defaultExpanded, true);
  assert.strictEqual(rowById(many.rows, '/w/a::0::main::000').expandable, false);
});

test('depth and parentId follow the level the walk actually emitted', () => {
  const single = buildViewModel([view([MAIN])]);
  assert.deepStrictEqual(
    single.rows.map((row) => [row.id, row.depth, row.parentId]),
    [
      ['/w/a::0', 0, undefined],
      ['/w/a::0::main', 1, '/w/a::0'],
      ['/w/a::0::main::000', 2, '/w/a::0::main'],
    ],
  );

  const two = buildViewModel([view([MAIN]), { pkg: OTHER, run: run([MAIN]) }]);
  assert.deepStrictEqual(
    two.rows.map((row) => [row.id, row.kind, row.depth, row.parentId]),
    [
      ['/w/a', 'package', 0, undefined],
      ['/w/a::0', 'solution', 1, '/w/a'],
      ['/w/a::0::main', 'group', 2, '/w/a::0'],
      ['/w/a::0::main::000', 'testcase', 3, '/w/a::0::main'],
      ['/w/b', 'package', 0, undefined],
      ['/w/b::0', 'solution', 1, '/w/b'],
      ['/w/b::0::main', 'group', 2, '/w/b::0'],
      ['/w/b::0::main::000', 'testcase', 3, '/w/b::0::main'],
    ],
  );
});

test('a package row is labelled by its directory and carries no verdict', () => {
  const { rows } = buildViewModel([view([MAIN]), { pkg: OTHER, run: run([MAIN]) }]);
  const row = rowById(rows, '/w/a');
  assert.strictEqual(row.label, 'a');
  assert.strictEqual(row.verdict, undefined);
  assert.strictEqual(row.gutter, 'none');
  assert.strictEqual(row.section, 'rbx.package');
  assert.strictEqual(row.defaultExpanded, true);
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
    buildViewModel([view(solutions)], style)
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

test('each package trims by the prefix its own solutions share', () => {
  const elsewhere = solution(0, 'other/dir/x.cpp', 'ACCEPTED', [], solutionReport({
    path: 'other/dir/x.cpp',
  }));
  const { rows } = buildViewModel(
    [view([MAIN, PARTIAL]), { pkg: OTHER, run: run([elsewhere]) }],
    'trimmed',
  );
  // `/w/b`'s lone solution lives nowhere near `sols/`, and that costs `/w/a`
  // nothing: a shared prefix computed across both packages would be empty.
  assert.strictEqual(rowById(rows, '/w/a::0').label, 'main.cpp');
  assert.strictEqual(rowById(rows, '/w/a::1').label, 'partial.cpp');
  assert.strictEqual(rowById(rows, '/w/b::0').label, 'x.cpp');
});

test('a shortened label keeps the whole path for the tooltip', () => {
  const { rows } = buildViewModel([view([MAIN, PARTIAL])], 'basename');
  assert.strictEqual(rowById(rows, '/w/a::0').labelTitle, 'sols/main.cpp');
  // Nothing was dropped, so there is nothing for a tooltip to add.
  const full = buildViewModel([view([MAIN, PARTIAL])], 'full');
  assert.strictEqual(rowById(full.rows, '/w/a::0').labelTitle, undefined);
});

test('the filter matches the full path whatever the label shows', () => {
  const { rows } = buildViewModel([view([MAIN, PARTIAL])], 'basename');
  assert.strictEqual(rowById(rows, '/w/a::0').search, 'sols/main.cpp ac');
  assert.strictEqual(rowById(rows, '/w/a::1').search, 'sols/partial.cpp wa incorrect');
});
