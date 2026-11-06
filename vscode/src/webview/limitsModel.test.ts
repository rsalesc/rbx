import * as assert from 'assert';
import { test } from 'node:test';

import { parseInspect } from '../rbx/limitsInspect';
import fixture from './limitsRender.fixture.json';
import { canDropOptimistic, snapLimit, stepProblem, withOptimistic } from './limitsModel';
import type { NavInfo, ViewState } from './limitsRender';

const parsed = parseInspect(JSON.stringify(fixture));

test('optimistic limits are laid over rbx answer and mark it as a step behind', () => {
  assert.ok(parsed.ok);
  const state: ViewState = { result: parsed.result, updating: false };

  assert.strictEqual(withOptimistic(state, new Map()), state);

  const shown = withOptimistic(state, new Map([['1', 1700], ['base', 600]]));
  assert.strictEqual(shown.updating, true);
  assert.strictEqual(shown.result?.timeLimit, 600);
  assert.strictEqual(shown.result?.rows?.find((r) => r.key === '1')?.timeLimit, 1700);
  // Untouched rows and rbx's own answer are left alone.
  assert.strictEqual(shown.result?.rows?.find((r) => r.key === '0')?.timeLimit, 500);
  assert.strictEqual(parsed.result.rows?.find((r) => r.key === '1')?.timeLimit, 1500);
});

test('optimistic values go only once rbx answered for the latest edit', () => {
  const idle = (seq: number): ViewState => ({ updating: false, seq });
  assert.strictEqual(canDropOptimistic(idle(3), 3, false), true);
  // An answer to edit 2 while edit 3 is on its way: keep the value on screen.
  assert.strictEqual(canDropOptimistic(idle(2), 3, false), false);
  assert.strictEqual(canDropOptimistic({ updating: true, seq: 3 }, 3, false), false);
  assert.strictEqual(canDropOptimistic(idle(3), 3, true), false);
});

test('limits snap to positive multiples of the step', () => {
  assert.strictEqual(snapLimit(1234, 100), 1200);
  assert.strictEqual(snapLimit(1250, 100), 1300);
  assert.strictEqual(snapLimit(20, 100), 100);
  assert.strictEqual(snapLimit(-300, 100), 100);
});

test('stepping between problems skips the ones without a profile and wraps', () => {
  const nav: NavInfo = {
    root: '/c/A',
    profile: 'local',
    problems: [
      { root: '/c/A', label: 'A', profiles: ['local', 'moj'] },
      { root: '/c/B', label: 'B', profiles: [] },
      { root: '/c/C', label: 'C', profiles: ['local'] },
    ],
  };
  assert.strictEqual(stepProblem(nav, 1)?.root, '/c/C');
  assert.strictEqual(stepProblem(nav, -1)?.root, '/c/C');
  assert.strictEqual(stepProblem({ ...nav, root: '/c/C' }, 1)?.root, '/c/A');
  assert.strictEqual(stepProblem({ ...nav, problems: nav.problems.slice(0, 2) }, 1), undefined);
});
