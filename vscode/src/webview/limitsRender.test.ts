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
