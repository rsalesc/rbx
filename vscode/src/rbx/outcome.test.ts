import * as assert from 'assert';
import * as fs from 'fs';
import * as path from 'path';
import { test } from 'node:test';

import {
  expectationBadge,
  expectationColor,
  expectationTooltip,
  expectedShortName,
  outcomeIcon,
  shortName,
} from './outcome';

// The colors are asserted against the CLI palette in
// `get_outcome_style_verdict` (rbx/box/solutions.py) rather than against
// "green means good": the two views are read side by side, so a verdict that
// is yellow in the terminal must not be red in the tree.
const CLI_PALETTE: Record<string, string> = {
  accepted: 'charts.green',
  'wrong-answer': 'charts.red',
  'time-limit-exceeded': 'charts.yellow',
  'idleness-limit-exceeded': 'charts.yellow',
  'memory-limit-exceeded': 'charts.yellow',
  'output-limit-exceeded': 'charts.orange',
  'runtime-error': 'charts.blue',
  'compilation-error': 'charts.blue',
  'judge-failed': 'charts.purple',
  'internal-error': 'charts.purple',
  skipped: 'descriptionForeground',
};

test('every outcome carries the color the CLI prints it in', () => {
  for (const [outcome, color] of Object.entries(CLI_PALETTE)) {
    assert.strictEqual(outcomeIcon(outcome).color, color, outcome);
  }
});

test('every outcome gets its own codicon', () => {
  const icons = Object.keys(CLI_PALETTE).map((o) => outcomeIcon(o).icon);
  assert.strictEqual(new Set(icons).size, icons.length, icons.join(','));
});

test('an unevaluated testcase reads as pending, not as a failure', () => {
  assert.deepStrictEqual(outcomeIcon(undefined), {
    icon: 'circle-outline',
    color: 'descriptionForeground',
  });
});

test('an outcome rbx grew after this extension shipped is not called a pass', () => {
  // Same fallback `shortName` takes: unknown is unknown, never green.
  assert.strictEqual(shortName('teleported'), 'XX');
  assert.deepStrictEqual(outcomeIcon('teleported'), {
    icon: 'question',
    color: 'charts.purple',
  });
});

// Every member of `ExpectedOutcome` (rbx/box/schema.py), so a variant rbx adds
// fails here rather than silently rendering as unknown in the tree.
const EXPECTED_OUTCOMES = [
  'ANY',
  'ACCEPTED',
  'ACCEPTED_OR_TLE',
  'WRONG_ANSWER',
  'INCORRECT',
  'RUNTIME_ERROR',
  'TIME_LIMIT_EXCEEDED',
  'MEMORY_LIMIT_EXCEEDED',
  'OUTPUT_LIMIT_EXCEEDED',
  'TLE_OR_RTE',
  'JUDGE_FAILED',
  'COMPILATION_ERROR',
];

test('every declared expectation has a name of its own', () => {
  // This is what replaced deriving an `Outcome` key by lowercasing an
  // `ExpectedOutcome` name: the enums have different members, so the old
  // derivation held only by coincidence.
  for (const expected of EXPECTED_OUTCOMES) {
    assert.notStrictEqual(expectedShortName(expected), 'XX', expected);
  }
});

test('expectation names are unchanged by the move to a table', () => {
  assert.strictEqual(expectedShortName('ACCEPTED'), 'AC');
  assert.strictEqual(expectedShortName('ACCEPTED_OR_TLE'), 'AC or TLE');
  assert.strictEqual(expectedShortName('TLE_OR_RTE'), 'TLE or RTE');
  assert.strictEqual(expectedShortName('INCORRECT'), 'INCORRECT');
  assert.strictEqual(expectedShortName('MEMORY_LIMIT_EXCEEDED'), 'MLE');
  assert.strictEqual(expectedShortName('JUDGE_FAILED'), 'FL');
  assert.strictEqual(expectedShortName(undefined), '?');
  assert.strictEqual(expectedShortName('TELEPORTED'), 'XX');
});

test('a badge is at most two characters, which VS Code enforces at runtime', () => {
  // `FileDecoration.validate` throws on a longer badge, so an over-long entry
  // is a crash in the view rather than a cosmetic slip.
  for (const expected of EXPECTED_OUTCOMES) {
    const badge = expectationBadge(expected);
    if (badge !== undefined) {
      assert.ok(badge.length <= 2, `${expected} -> ${badge}`);
    }
  }
});

test('badges are the two-letter spelling rbx itself accepts in the YAML', () => {
  // Not a vocabulary of the view's own: these are the aliases a setter types
  // into problem.rbx.yml, so the mark echoes their own file.
  assert.strictEqual(expectationBadge('ACCEPTED'), 'AC');
  assert.strictEqual(expectationBadge('WRONG_ANSWER'), 'WA');
  assert.strictEqual(expectationBadge('TIME_LIMIT_EXCEEDED'), 'TL');
  assert.strictEqual(expectationBadge('MEMORY_LIMIT_EXCEEDED'), 'ML');
  assert.strictEqual(expectationBadge('OUTPUT_LIMIT_EXCEEDED'), 'OL');
  assert.strictEqual(expectationBadge('RUNTIME_ERROR'), 'RE');
  assert.strictEqual(expectationBadge('JUDGE_FAILED'), 'JF');
  assert.strictEqual(expectationBadge('COMPILATION_ERROR'), 'CE');
});

test('a compound expectation keeps rbx `+` spelling for "or"', () => {
  // From rbx's own `ac+tle` and `tle+re` aliases, and honest besides: `A+`
  // says accepted, and more is tolerated.
  assert.strictEqual(expectationBadge('ACCEPTED_OR_TLE'), 'A+');
  assert.strictEqual(expectationBadge('TLE_OR_RTE'), 'T+');
});

test('badges carry no symbols, the row already having a codicon', () => {
  // A second symbolic alphabet beside the verdict codicon reads as noise, and
  // a codicon cannot go here anyway -- `FileDecoration.badge` is a string.
  for (const expected of EXPECTED_OUTCOMES) {
    const badge = expectationBadge(expected);
    if (badge !== undefined) {
      assert.match(badge, /^[A-Z][A-Z+]$/, `${expected} -> ${badge}`);
    }
  }
});

test('a declaration is coloured by its own hue, as rbx prints it', () => {
  // `ExpectedOutcome.style()` transposed onto `charts.*`: a solution declared
  // TLE is yellow here exactly as `rbx run` prints it yellow.
  assert.strictEqual(expectationColor('ACCEPTED'), 'charts.green');
  assert.strictEqual(expectationColor('ACCEPTED_OR_TLE'), 'charts.green');
  assert.strictEqual(expectationColor('WRONG_ANSWER'), 'charts.red');
  assert.strictEqual(expectationColor('INCORRECT'), 'charts.red');
  assert.strictEqual(expectationColor('TIME_LIMIT_EXCEEDED'), 'charts.yellow');
  assert.strictEqual(expectationColor('MEMORY_LIMIT_EXCEEDED'), 'charts.yellow');
  assert.strictEqual(expectationColor('RUNTIME_ERROR'), 'charts.blue');
  assert.strictEqual(expectationColor('COMPILATION_ERROR'), 'charts.blue');
  // rbx's own style() has no branch for OLE and falls through to magenta, so
  // this is purple rather than the orange an OLE *outcome* draws.
  assert.strictEqual(expectationColor('OUTPUT_LIMIT_EXCEEDED'), 'charts.purple');
  assert.strictEqual(expectationColor('ANY'), undefined);
  assert.strictEqual(expectationColor(undefined), undefined);
});

test('a met expectation leaves #664 icon exactly as it was', () => {
  for (const [outcome, color] of Object.entries(CLI_PALETTE)) {
    assert.deepStrictEqual(outcomeIcon(outcome, 'met'), outcomeIcon(outcome), outcome);
    assert.strictEqual(outcomeIcon(outcome, 'met').color, color, outcome);
  }
});

test('a missed expectation swaps in the marked variant of the same verdict', () => {
  // The verdict stays legible -- a solution that missed by timing out still
  // shows a clock -- but the row stops claiming the run went to plan.
  assert.deepStrictEqual(outcomeIcon('time-limit-exceeded', 'missed'), {
    icon: 'rbx-watch-mismatch',
    color: 'charts.red',
  });
  assert.deepStrictEqual(outcomeIcon('accepted', 'missed'), {
    icon: 'rbx-pass-mismatch',
    color: 'charts.red',
  });
});

test('a pending row has no mismatch icon, having nothing to have missed', () => {
  // There is no glyph for it in the font, and naming one that does not exist
  // renders as blank rather than as an error.
  assert.deepStrictEqual(outcomeIcon(undefined, 'missed'), outcomeIcon(undefined));
});

test('every verdict the tree can draw has a contributed mismatch icon', () => {
  // The font is generated by scripts/build-mismatch-font.py from its own list
  // of icon ids. If DISPLAY grows a verdict that the generator and
  // package.json do not know about, the mismatched row renders *blank* -- VS
  // Code does not complain about an unknown icon id. This is that guard.
  const manifest = JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', '..', 'package.json'), 'utf8'),
  ) as { contributes: { icons: Record<string, { default: { fontCharacter: string } }> } };
  const contributed = manifest.contributes.icons;

  for (const outcome of [...Object.keys(CLI_PALETTE), 'teleported']) {
    const { icon } = outcomeIcon(outcome, 'missed');
    assert.ok(icon in contributed, `${outcome} -> ${icon} is not contributed`);
  }

  const characters = Object.values(contributed).map((i) => i.default.fontCharacter);
  assert.strictEqual(
    new Set(characters).size,
    characters.length,
    'two icons share a font character',
  );
});

test('the hover names both sides in rbx own spelling', () => {
  assert.strictEqual(
    expectationTooltip('WRONG_ANSWER', 'wrong-answer', 'met'),
    'Expected WA, got WA',
  );
  assert.strictEqual(
    expectationTooltip('ACCEPTED', 'time-limit-exceeded', 'missed'),
    'Expected AC, but got TLE',
  );
  // Nothing is claimed about an outcome that does not exist yet.
  assert.strictEqual(expectationTooltip('ACCEPTED', undefined, 'unknown'), 'Expected AC');
});

test('a miss caught only per group does not accuse the pooled expectation', () => {
  // `sols/mislabeled.cpp` in the outcome-per-group fixture: its pooled
  // INCORRECT is satisfied -- it does fail -- and only the per-group layer
  // catches it, so naming INCORRECT as the broken promise would be wrong.
  assert.strictEqual(
    expectationTooltip('INCORRECT', 'wrong-answer', 'missed', ['small', 'big']),
    'Declared INCORRECT, but small, big did not match',
  );
});
