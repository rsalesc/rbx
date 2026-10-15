import * as assert from 'assert';
import { test } from 'node:test';

import type { StressStatus, StressViewModel } from '../rbx/stressViewModel';
import {
  formatClock,
  renderDeclared,
  renderElapsed,
  renderFindings,
  renderStatus,
} from './stressRender';

// Written as models rather than built from a manifest: the renderer's contract
// is the model, and stressViewModel.test.ts covers how one is made.

const STATUS: StressStatus = {
  state: 'running',
  label: 'Running',
  hue: 'blue',
  executed: 42,
  skipped: 3,
  findings: 1,
  findingsLimit: 2,
  elapsed: 4,
  timeout: 10,
  startedAtMs: 1_000_000,
  spec: 'wa-small',
};

function model(overrides: Partial<StressViewModel> = {}): StressViewModel {
  return {
    noPackage: false,
    dispatch: true,
    declared: [{ name: 'wa-small', summary: 'gen [1..10] · [sols/wa.cpp] ~ WA' }],
    status: STATUS,
    findings: [
      {
        k: 1,
        call: 'gen 5 <seed>',
        duration: '1.3 s',
        chips: [{ solution: 'wa.cpp', path: 'sols/wa.cpp', short: 'WA', icon: 'close', hue: 'red' }],
        canCompare: true,
      },
    ],
    session: '2026-10-15T12:00:00+00:00',
    ...overrides,
  };
}

test('the clock reads m:ss, ticking from the start while running', () => {
  assert.strictEqual(formatClock(0), '0:00');
  assert.strictEqual(formatClock(65.9), '1:05');
  assert.strictEqual(renderElapsed(STATUS, 1_000_000 + 7_500), '0:07 / 0:10');
  // Never past the budget, and never behind what the manifest already said.
  assert.strictEqual(renderElapsed(STATUS, 1_000_000 + 60_000), '0:10 / 0:10');
  assert.strictEqual(renderElapsed(STATUS, 1_000_000), '0:04 / 0:10');
  const done = { ...STATUS, state: 'done' as const, startedAtMs: undefined, elapsed: 9 };
  assert.strictEqual(renderElapsed(done, 9_999_999_999), '0:09 / 0:10');
  assert.strictEqual(renderElapsed({ ...done, timeout: undefined }, 0), '0:09');
});

test('declared stresses get Run and Edit, and New stress closes the list', () => {
  const html = renderDeclared(model());
  assert.match(html, /data-action="run-declared" data-name="wa-small"/);
  assert.match(html, /data-action="edit-declared" data-name="wa-small"/);
  assert.match(html, /data-action="new"/);
  assert.match(html, /aria-label="Run wa-small"/);
});

test('without dispatch, nothing offers to run', () => {
  const html = renderDeclared(model({ dispatch: false })) + renderStatus(model({ dispatch: false }), 0);
  assert.doesNotMatch(html, /run-declared|edit-declared|data-action="new"|data-action="stop"/);
});

test('names and calls are escaped', () => {
  const html =
    renderDeclared(model({ declared: [{ name: '<x>"', summary: 'a & b' }] })) +
    renderFindings(
      model({
        findings: [{ k: 2, call: 'gen <b>', chips: [], canCompare: false, promoted: '<g>' }],
      }),
    );
  assert.doesNotMatch(html, /<x>|<b>|<g>/);
  assert.match(html, /&lt;x&gt;/);
  assert.match(html, /in &lt;g&gt;/);
});

test('the status line: state, clock, counters, spec, and Stop only while running', () => {
  const running = renderStatus(model(), 1_000_000 + 5_000);
  assert.match(running, /hue-blue">Running</);
  assert.match(running, /0:05 \/ 0:10/);
  assert.match(running, /42 run · 3 skipped · 1\/2 found/);
  assert.match(running, /<code>wa-small<\/code>/);
  assert.match(running, /data-action="stop"/);
  const stale = renderStatus(
    model({ status: { ...STATUS, state: 'stale', label: 'Stopped', hue: 'orange', skipped: 0 } }),
    0,
  );
  assert.doesNotMatch(stale, /data-action="stop"/);
  assert.doesNotMatch(stale, /skipped/);
});

test('finding rows: index, call, chips, and Compare only when there is a pair', () => {
  const html = renderFindings(model());
  assert.match(html, /#1<\/span>/);
  assert.match(html, /gen 5 &lt;seed&gt;/);
  assert.match(html, /hue-red/);
  assert.match(html, /wa\.cpp WA/);
  for (const action of ['open', 'compare', 'copy', 'promote']) {
    assert.match(html, new RegExp(`data-action="${action}" data-k="1"`));
  }
  const single = renderFindings(
    model({ findings: [{ ...model().findings[0], canCompare: false }] }),
  );
  assert.doesNotMatch(single, /data-action="compare"/);
});

test('empty states', () => {
  const none = model({ noPackage: true });
  assert.match(renderDeclared(none), /No rbx problem selected/);
  assert.strictEqual(renderStatus(none, 0), '');
  assert.strictEqual(renderFindings(none), '');

  const fresh = model({ status: undefined, findings: [] });
  assert.match(renderFindings(fresh), /Run a stress to see findings here/);
  assert.strictEqual(renderStatus(fresh, 0), '');

  assert.match(renderFindings(model({ findings: [] })), /No findings yet/);
  assert.match(
    renderFindings(model({ findings: [], status: { ...STATUS, state: 'done' } })),
    /No findings in this session/,
  );
});
