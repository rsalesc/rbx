import * as assert from 'assert';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

import { expectationSpelling } from './expectation';
import { normalizeExpectation } from './manifest';
import { shortName } from './outcome';

/**
 * rbx's verdict enums, dumped by scripts/gen_vscode_enums.py.
 *
 * The tables in expectation.ts, manifest.ts and outcome.ts are written by hand,
 * one display decision per row, and a member rbx grows after them degrades to
 * the neutral "unknown" rendering rather than failing anything. That is the
 * right behaviour for an *old extension* meeting a new rbx, and the wrong one
 * for a release: `MLE_OR_RTE` shipped half-supported that way (#901). A Python
 * test keeps this file current, and these keep the tables covering it.
 */
interface RbxEnums {
  readonly ExpectedOutcome: Record<string, readonly string[]>;
  readonly Outcome: readonly string[];
}

const ENUMS: RbxEnums = JSON.parse(
  readFileSync(join(__dirname, '..', '..', 'src', 'rbx', 'rbxEnums.json'), 'utf8'),
);

test('every ExpectedOutcome member rbx has is displayed, not shown as unknown', () => {
  // `expectationSpelling` hands an unknown member back untouched; a known one
  // comes back kebab-cased, which no upper-case member name already is.
  const unknown = Object.keys(ENUMS.ExpectedOutcome).filter(
    (member) => expectationSpelling(member) === member,
  );
  assert.deepStrictEqual(unknown, [], 'add these to DISPLAY in expectation.ts');
});

test('every ExpectedOutcome spelling rbx accepts resolves to its member', () => {
  const wrong: string[] = [];
  for (const [member, aliases] of Object.entries(ENUMS.ExpectedOutcome)) {
    for (const spelling of [member, ...aliases]) {
      const resolved = normalizeExpectation(spelling);
      if (resolved !== member) {
        wrong.push(`${spelling} -> ${resolved}, expected ${member}`);
      }
    }
  }
  assert.deepStrictEqual(wrong, [], 'add these to ALIASES in manifest.ts');
});

test('every Outcome rbx writes to a .eval has its own short name', () => {
  // `XX` is the "newer than this extension" fallback, as in rbx itself.
  const unknown = ENUMS.Outcome.filter((outcome) => shortName(outcome) === 'XX');
  assert.deepStrictEqual(unknown, [], 'add these to DISPLAY in outcome.ts');
});
