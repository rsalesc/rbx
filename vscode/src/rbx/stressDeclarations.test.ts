import * as assert from 'assert';
import { test } from 'node:test';
import { parse as parseYaml } from 'yaml';

import {
  isGlob,
  listingFailure,
  parseStressDeclarations,
  parseStressListing,
  withoutGlobs,
} from './stressDeclarations';

const MANIFEST = `
name: sum
generators:
  - name: gen
    path: gens/gen.cpp
  - name: gen-big
    path: gens/big.cpp
solutions:
  - path: sols/main.cpp
    outcome: accepted
  - path: sols/wa.cpp
    outcome: wa
  - path: sols/slow.cpp
    outcome: tle
  - path: sols/any.cpp
testcases:
  - name: samples
    testcaseGlob: tests/*.in
  - name: main
    generatorScript: {path: gens/main.txt}
stresses:
  - name: wa-small
    generator: {name: gen, args: '[1..10]'}
    finder: '[sols/wa.cpp] ~ WRONG_ANSWER'
  - name: seedless
    generator: {name: gen}
    finder: sols/slow.cpp
`;

test('a whole manifest reads into what the launcher offers', () => {
  assert.deepStrictEqual(parseStressDeclarations(parseYaml(MANIFEST)), {
    stresses: [
      {
        name: 'wa-small',
        generator: { name: 'gen', args: '[1..10]' },
        finder: '[sols/wa.cpp] ~ WRONG_ANSWER',
      },
      { name: 'seedless', generator: { name: 'gen', args: undefined }, finder: 'sols/slow.cpp' },
    ],
    generators: ['gen', 'gen-big'],
    solutions: [
      { path: 'sols/main.cpp', outcome: 'ACCEPTED' },
      { path: 'sols/wa.cpp', outcome: 'WRONG_ANSWER' },
      { path: 'sols/slow.cpp', outcome: 'TIME_LIMIT_EXCEEDED' },
      { path: 'sols/any.cpp', outcome: undefined },
    ],
    groups: ['samples', 'main'],
  });
});

test('nothing parsable reads as a package declaring nothing', () => {
  const empty = { stresses: [], generators: [], solutions: [], groups: [] };
  assert.deepStrictEqual(parseStressDeclarations(undefined), empty);
  assert.deepStrictEqual(parseStressDeclarations('name: x'), empty);
  assert.deepStrictEqual(parseStressDeclarations({ stresses: 'nope', solutions: {} }), empty);
});

test('a half-typed entry costs that entry, never the rest', () => {
  const parsed = parseStressDeclarations({
    generators: [{ name: 'gen' }, { path: 'gens/x.cpp' }, { name: '' }, 'gen', { name: 'gen' }],
    solutions: [{ path: 'sols/a.cpp' }, { outcome: 'wa' }, { path: '' }],
    testcases: [{ name: 'main' }, { name: null }, {}],
    stresses: [
      { name: 'ok', generator: { name: 'gen', args: 7 }, finder: 'sols/a.cpp' },
      { name: 'no-finder', generator: { name: 'gen' } },
      { name: 'no-generator', finder: 'sols/a.cpp' },
      { generator: { name: 'gen' }, finder: 'sols/a.cpp' },
      { name: 'empty-finder', generator: { name: 'gen' }, finder: '' },
    ],
  });
  assert.deepStrictEqual(parsed, {
    stresses: [{ name: 'ok', generator: { name: 'gen', args: undefined }, finder: 'sols/a.cpp' }],
    generators: ['gen'],
    solutions: [{ path: 'sols/a.cpp', outcome: undefined }],
    groups: ['main'],
  });
});

test('an outcome this extension cannot resolve is kept as written', () => {
  const parsed = parseStressDeclarations({ solutions: [{ path: 'a', outcome: 'newer-thing' }] });
  assert.deepStrictEqual(parsed.solutions, [{ path: 'a', outcome: 'newer-thing' }]);
});

test('rbx stress --list --json reads as declarations, globs expanded by rbx', () => {
  const listing = JSON.parse(
    '{"stresses": [{"name": "wa", "generator": {"name": "gen", "args": null}, "finder": "[sols/wa-1.cpp]"},' +
      ' {"name": "", "generator": {"name": "gen"}, "finder": "x"}],' +
      ' "solutions": [{"path": "sols/main.cpp", "outcome": "ACCEPTED"},' +
      ' {"path": "sols/wa-1.cpp", "outcome": "wa"}, {"outcome": "WRONG_ANSWER"}, {"path": "sols/x.cpp"}],' +
      ' "generators": ["gen", "", 3], "groups": ["samples", "main", "main"]}',
  );
  assert.deepStrictEqual(parseStressListing(listing), {
    stresses: [{ name: 'wa', generator: { name: 'gen', args: undefined }, finder: '[sols/wa-1.cpp]' }],
    solutions: [
      { path: 'sols/main.cpp', outcome: 'ACCEPTED' },
      { path: 'sols/wa-1.cpp', outcome: 'WRONG_ANSWER' },
      { path: 'sols/x.cpp', outcome: undefined },
    ],
    generators: ['gen'],
    groups: ['samples', 'main'],
  });
});

test('anything but a listing is no listing, so the caller falls back', () => {
  for (const raw of [undefined, null, [], 'x', { stresses: [], solutions: [], generators: [] }]) {
    assert.strictEqual(parseStressListing(raw), undefined, JSON.stringify(raw));
  }
});

test('a failed listing is one line, the one naming the error', () => {
  const panel = [
    'Usage: rbx stress [OPTIONS] [NAME]',
    "Try 'rbx stress --help' for help.",
    '╭─ Error ──────────────────────────────╮',
    '│ No such option: --list               │',
    '╰──────────────────────────────────────╯',
    '',
  ].join('\n');
  assert.strictEqual(listingFailure(panel), 'No such option: --list');
  assert.strictEqual(listingFailure('something broke\n'), 'something broke');
  assert.strictEqual(listingFailure(''), 'rbx printed no listing');
});

test('the YAML fallback drops the globs only rbx can expand', () => {
  assert.deepStrictEqual(
    ['sols/*.cpp', 'a?.cpp', 'sols/[ab].cpp', 'sols/a.cpp'].map(isGlob),
    [true, true, true, false],
  );
  const declarations = parseStressDeclarations({
    generators: [{ name: 'gen' }, { name: 'gens/*' }],
    solutions: [{ path: 'sols/main.cpp' }, { path: 'sols/wa-*.*', outcome: 'WA' }],
    testcases: [{ name: 'main' }],
  });
  assert.deepStrictEqual(withoutGlobs(declarations), {
    stresses: [],
    generators: ['gen'],
    solutions: [{ path: 'sols/main.cpp', outcome: undefined }],
    groups: ['main'],
  });
});
