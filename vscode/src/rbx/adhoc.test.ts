import * as assert from 'assert';
import { test } from 'node:test';

import { chooseSource, describeAdhoc } from './adhoc';
import { parseSkeleton } from './model';
import { PackageRun } from './store';

test('an ad-hoc run is named the way the setter asked for it', () => {
  assert.strictEqual(describeAdhoc({ group: 'samples', index: 1 }), 'samples/1');
  assert.strictEqual(
    describeAdhoc({ group: 'main', index: 4, generatorName: 'gen', generatorArgs: '5' }),
    'main/4',
  );
  assert.strictEqual(
    describeAdhoc({ group: 'interactive', index: 0, generatorName: 'gen', generatorArgs: '10 20' }),
    'gen 10 20',
  );
  assert.strictEqual(describeAdhoc({ group: 'interactive', index: 0 }), 'typed input');
  assert.strictEqual(describeAdhoc(undefined), 'ad-hoc run');
});

function adhocRun(): PackageRun {
  const skeleton = parseSkeleton({
    solutions: [],
    entries: [{ group_entry: { group: 'main', index: 3 } }],
  });
  assert.ok(skeleton !== undefined);
  return { skeleton, solutions: [], findings: [] };
}

test('with no ad-hoc run on disk, the view shows the run and offers no toggle', () => {
  assert.deepStrictEqual(chooseSource('irun', undefined), { source: 'run' });
  assert.deepStrictEqual(chooseSource('run', undefined), { source: 'run' });
});

test('with an ad-hoc run on disk, the view shows what was asked and offers both', () => {
  assert.deepStrictEqual(chooseSource('irun', adhocRun()), {
    source: 'irun',
    choice: { selected: 'irun', adhoc: 'main/3' },
  });
  assert.strictEqual(chooseSource('run', adhocRun()).source, 'run');
});
