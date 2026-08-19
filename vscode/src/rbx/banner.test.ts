import * as assert from 'assert';
import { test } from 'node:test';

import { DEFAULT_BANNER_MODE, asBannerMode, bannerFor, bannerLine } from './banner';
import { DeclaredAsset } from './manifest';

const PARTIAL: DeclaredAsset = {
  path: 'sols/partial.cpp',
  role: 'solution',
  expectation: 'ACCEPTED_OR_TLE',
  perGroup: [{ group: 'group3', expectation: 'TIME_LIMIT_EXCEEDED' }],
};

test('the banner leads with the badge the Explorer uses', () => {
  const banner = bannerFor(PARTIAL);
  assert.strictEqual(banner?.badge, '✓⧖');
  assert.strictEqual(banner?.colorId, 'rbx.expectedAccepted');
});

test('the declaration reads pooled first, then the per-group overrides', () => {
  assert.strictEqual(bannerFor(PARTIAL)?.declaration, 'accepted-or-tle · group3: time-limit-exceeded');
});

test('the wildcard override is spelled out rather than left as a glyph', () => {
  const banner = bannerFor({
    path: 'sols/partial.cpp',
    role: 'solution',
    expectation: 'INCORRECT',
    perGroup: [
      { group: '*', expectation: 'ACCEPTED' },
      { group: 'group3', expectation: 'TIME_LIMIT_EXCEEDED' },
    ],
  });
  assert.strictEqual(banner?.declaration, 'incorrect · each group: accepted · group3: time-limit-exceeded');
});

test('a solution promising nothing says so in words', () => {
  const banner = bannerFor({ path: 'sols/x.cpp', role: 'solution', expectation: 'ANY' });
  assert.strictEqual(banner?.badge, '?');
  assert.strictEqual(banner?.declaration, 'no outcome declared');
  assert.strictEqual(banner?.colorId, 'rbx.expectedAny');
});

test('an expectation from a newer rbx is shown as the setter spelled it', () => {
  const banner = bannerFor({
    path: 'sols/x.cpp',
    role: 'solution',
    expectation: 'partially-accepted',
  });
  assert.strictEqual(banner?.declaration, 'partially-accepted');
});

test('only solutions get a banner', () => {
  assert.strictEqual(bannerFor({ path: 'gen.cpp', role: 'generator' }), undefined);
  assert.strictEqual(bannerFor({ path: 'sols/x.cpp', role: 'solution' }), undefined);
});

/**
 * The right-hand slot is the last run's, and ships empty: laying the space out
 * is this issue, filling it is the next one. The line must read as a finished
 * sentence with nothing in it.
 */
test('the line is the badge and the declaration until a run fills the right slot', () => {
  const banner = bannerFor(PARTIAL);
  assert.ok(banner !== undefined);
  assert.strictEqual(bannerLine(banner), '✓⧖  accepted-or-tle · group3: time-limit-exceeded');
  assert.ok(bannerLine(banner, 'last run — WA').startsWith('✓⧖  accepted-or-tle · group3: time-limit-exceeded'));
  assert.ok(bannerLine(banner, 'last run — WA').endsWith('last run — WA'));
});

test('the tooltip names the file as a solution and spells every layer out', () => {
  const tooltip = bannerFor(PARTIAL)?.tooltip ?? '';
  assert.ok(tooltip.includes('solution'), tooltip);
  assert.ok(tooltip.includes('AC or TLE'), tooltip);
  assert.ok(tooltip.includes('group3'), tooltip);
  assert.ok(tooltip.includes('TLE'), tooltip);
});

test('an unset or unrecognized banner mode falls back to the default', () => {
  assert.strictEqual(asBannerMode('inline'), 'inline');
  assert.strictEqual(asBannerMode('off'), 'off');
  assert.strictEqual(asBannerMode('banner'), 'banner');
  assert.strictEqual(asBannerMode(undefined), DEFAULT_BANNER_MODE);
  assert.strictEqual(asBannerMode('block'), DEFAULT_BANNER_MODE);
});
