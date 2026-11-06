import * as assert from 'assert';
import { test } from 'node:test';

import { parseInspect } from '../rbx/limitsInspect';
import fixture from './limitsRender.fixture.json';
import { renderDocument } from './limitsRender';

// `rbx time-inspect -p demo` on a two-group profile with a hand-set JVM limit.
const parsed = parseInspect(JSON.stringify(fixture));

test('renders every group, its solutions and the staleness banner', () => {
  assert.ok(parsed.ok);
  const html = renderDocument({ result: parsed.result, updating: false });
  assert.match(html, /cpp, c/);
  assert.match(html, /java, kotlin/);
  assert.match(html, /quadratic\.java: TLE margin &lt; ×1\.5/);
  assert.doesNotMatch(html, /would pass|would be accepted/);
  assert.match(html, /class="sol hue-[a-z]+[^"]*" data-action="open" data-path="solutions\/slow\/quadratic\.java"/);
  assert.doesNotMatch(html, /ratio/);
  assert.match(html, /estimated 1200 ms/);
  assert.match(html, /Solutions changed since this profile was estimated/);
  assert.match(html, /4× cpp = 2000 ms/);
});

test('renders rbx errors and host errors instead of the document', () => {
  const html = renderDocument({
    result: { version: 1, profile: 'x', path: 'p', errors: ['bad yaml'] },
    updating: false,
  });
  assert.match(html, /bad yaml/);
  assert.match(renderDocument({ updating: false, error: 'no rbx' }), /no rbx/);
});

test('a slow solution finishing within the limit itself would be accepted; past it, it only loses margin', () => {
  assert.ok(parsed.ok);
  const java = (limit: number) => {
    const rows = (parsed.result.rows ?? []).map((row) => (row.key === '1' ? { ...row, timeLimit: limit } : row));
    return renderDocument({ result: { ...parsed.result, rows }, updating: false });
  };
  // quadratic.java finishes at 2100 ms.
  assert.match(java(1500), /margin &lt; ×1\.5/);
  assert.doesNotMatch(java(1500), /would be accepted/);
  assert.match(java(2200), /would be accepted/);
});

test('says when a profile inherits the package limits, or was never estimated', () => {
  assert.ok(parsed.ok);
  const inherits = renderDocument({ result: { ...parsed.result, inheritFromPackage: true }, updating: false });
  assert.match(inherits, /uses the limits in problem\.rbx\.yml/);
  assert.match(inherits, /data-action="inherit" checked/);

  const bare = renderDocument({
    result: { ...parsed.result, editable: false, rows: [], hasSolutions: false },
    updating: false,
  });
  assert.match(bare, /Not an estimated profile/);
});

test('draws no "margins hold" chip, and dims checks while rbx catches up', () => {
  assert.ok(parsed.ok);
  const html = renderDocument({ result: parsed.result, updating: true });
  assert.doesNotMatch(html, /margins hold|consistent with/);
  assert.match(html, /<main class="[^"]*updating/);
  assert.match(html, /checking…/);
  // Nothing is ever disabled: clicks always count.
  assert.doesNotMatch(html, /<button[^>]*disabled/);
});

test('the navigation bar lists every problem and the current one tabs', () => {
  assert.ok(parsed.ok);
  const html = renderDocument({
    result: parsed.result,
    updating: false,
    nav: {
      root: '/c/A',
      profile: 'demo',
      problems: [
        { root: '/c/A', label: 'A · thanks', profiles: ['demo', 'local', 'moj'] },
        { root: '/c/B', label: 'B · other', profiles: [] },
      ],
    },
  });
  assert.match(html, /<option value="\/c\/A" selected>A · thanks — demo, local, moj<\/option>/);
  assert.match(html, /<option value="\/c\/B" disabled>B · other — no profiles<\/option>/);
  assert.match(html, /class="tab active" data-action="navProfile" data-profile="demo"/);
  assert.equal((html.match(/data-action="navProfile"/g) ?? []).length, 3);
});

test('appends the last run under the estimate, flagged when it ran at another limit', () => {
  assert.ok(parsed.ok);
  const result = parsed.result;
  const rows = (result.rows ?? []).map((row) =>
    row.key === '0'
      ? {
          ...row,
          runSolutions: [
            {
              path: 'solutions/wrong/review-no-wrap.cpp',
              language: 'cpp',
              expectedOutcome: 'INCORRECT',
              outcome: 'wrong-answer',
              matchesExpectation: true,
              complete: true,
              maxTime: 12,
              timeLimit: 500,
            },
            {
              path: 'solutions/slow/brute.cpp',
              language: 'cpp',
              expectedOutcome: 'TIME_LIMIT_EXCEEDED',
              outcome: 'accepted',
              matchesExpectation: false,
              complete: true,
              maxTime: 300,
              timeLimit: 400,
            },
          ],
        }
      : row,
  );
  const html = renderDocument({
    result: { ...result, rows, lastRun: { profiles: ['demo'], finished: true } },
    updating: false,
  });
  assert.match(html, /From the last run/);
  assert.equal((html.match(/class="run-row"/g) ?? []).length, 2);
  // Judged at 400 while the group's limit is 500: said, never re-judged.
  assert.match(html, /at 400 ms ⚠/);
  assert.match(html, /AC ≠ TLE/);
});
