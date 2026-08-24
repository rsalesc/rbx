import * as assert from 'assert';
import { test } from 'node:test';

import type {
  Coverage,
  GalleryCell,
  PanelUiState,
  PanelViewModel,
} from '../rbx/panelViewModel';
import { EMPTY_PANEL_MODEL } from '../rbx/panelViewModel';
import {
  type PanelAssets,
  renderCoverage,
  renderGallery,
  renderPanel,
  renderStats,
  renderTabs,
} from './panelRender';

// Fixtures are written as view models rather than built from a `Testset`: the
// renderer's contract is the model, and going through `buildPanelViewModel`
// would make these fail for panelViewModel.test.ts's reasons.

function cell(over: Partial<GalleryCell> & Pick<GalleryCell, 'id'>): GalleryCell {
  return {
    group: 'main',
    stem: '000',
    channel: 'input',
    path: 'build/tests/main/visualization/000.svg',
    kind: 'image',
    label: '000',
    extension: 'svg',
    ...over,
  };
}

function model(over: Partial<PanelViewModel> = {}): PanelViewModel {
  return { ...EMPTY_PANEL_MODEL, root: '/w/a', empty: false, ...over };
}

const GALLERY_STATE: PanelUiState = { tab: 'gallery' };

function coverage(over: Partial<Coverage> = {}): Coverage {
  return { reported: true, groups: [], validators: [], rows: [], neverHit: [], ...over };
}

test('an image cell is a lazy img, and its caption names the testcase', () => {
  const assets: PanelAssets = { 'main::000::input': 'https://webview/000.svg' };
  const html = renderGallery(
    model({ gallery: { cells: [cell({ id: 'main::000::input' })], withoutVisualization: 0 } }),
    GALLERY_STATE,
    assets,
  );
  assert.match(html, /<figure class="cell" data-id="main::000::input"/);
  assert.match(html, /<img class="cell-image" loading="lazy" src="https:\/\/webview\/000.svg"/);
  assert.match(html, /<figcaption class="cell-label">000<\/figcaption>/);
  assert.ok(!html.includes('<iframe'), 'an image must not be framed');
});

test('an html cell is framed with an empty sandbox, and never scripted', () => {
  const html = renderGallery(
    model({
      gallery: {
        cells: [cell({ id: 'x', kind: 'html', path: 'build/v/0.html', extension: 'html' })],
        withoutVisualization: 0,
      },
    }),
    GALLERY_STATE,
    { x: 'https://webview/0.html' },
  );
  assert.match(html, /<iframe class="cell-frame" sandbox="" loading="lazy"/);
  assert.ok(!html.includes('allow-scripts'), 'a generated page gets no script execution');
});

test('an unknown extension offers an editor, and says which extension', () => {
  const html = renderGallery(
    model({
      gallery: {
        cells: [cell({ id: 'x', kind: 'other', path: 'build/v/0.dat', extension: 'dat' })],
        withoutVisualization: 0,
      },
    }),
    GALLERY_STATE,
    { x: 'https://webview/0.dat' },
  );
  assert.match(html, /<button class="cell-open" data-open="x"/);
  assert.match(html, /Open \.dat in editor/);
  assert.ok(!html.includes('<img'), 'an unknown extension must never be guessed at');
});

test('a file the manifest names but that is gone renders a placeholder', () => {
  // No asset for the id: the host checked and it is not on disk.
  const html = renderGallery(
    model({ gallery: { cells: [cell({ id: 'x' })], withoutVisualization: 0 } }),
    GALLERY_STATE,
    {},
  );
  assert.match(html, /<div class="cell-missing"/);
  assert.match(html, /missing/);
  assert.ok(!html.includes('<img'), 'a missing file must not become a broken image');
});

test('the gallery shows only the picked group, and reports the rest', () => {
  const gallery = {
    cells: [
      cell({ id: 'main::000::input' }),
      cell({ id: 'big::000::input', group: 'big' }),
    ],
    withoutVisualization: 3,
  };
  const html = renderGallery(model({ gallery }), { tab: 'gallery', group: 'big' }, {});
  assert.ok(html.includes('data-id="big::000::input"'));
  assert.ok(!html.includes('data-id="main::000::input"'));
  assert.match(html, /3 testcase\(s\) produced no visualization/);
});

test('a group with no visualizations says so instead of drawing an empty grid', () => {
  const html = renderGallery(
    model({ gallery: { cells: [], withoutVisualization: 4 } }),
    { tab: 'gallery', group: 'main' },
    {},
  );
  assert.match(html, /No visualizations in group main/);
  assert.ok(!html.includes('<div class="gallery">'));
});

test('a -v0 build explains itself rather than rendering an empty matrix', () => {
  const html = renderCoverage(coverage({ reported: false }));
  assert.match(html, /ran without validation/);
  assert.match(html, /-v0/);
  assert.ok(!html.includes('<table'), 'an empty table would read as "nothing is covered"');
});

test('a validated build with no bounded variables is a different sentence', () => {
  const html = renderCoverage(coverage());
  assert.match(html, /no bounded variables/);
  assert.ok(!html.includes('-v0'));
});

test('the coverage matrix hues each cell and rolls up what is never hit', () => {
  const html = renderCoverage(
    coverage({
      groups: ['main', 'big'],
      validators: ['validator.cpp', undefined],
      rows: [
        {
          variable: 'n',
          cells: [
            { minHit: true, maxHit: true, hue: 'green', value: '100' },
            { minHit: false, maxHit: true, hue: 'yellow' },
          ],
        },
        {
          variable: 'm',
          cells: [{ minHit: false, maxHit: false, hue: 'red' }, undefined],
        },
      ],
      neverHit: ['m'],
    }),
  );
  assert.match(html, /<th scope="col" title="validator.cpp">main<\/th>/);
  assert.match(html, /<th scope="col">big<\/th>/);
  assert.match(html, /<td class="hue-green">/);
  assert.match(html, /<td class="hue-yellow">/);
  assert.match(html, /<td class="hue-red">/);
  // Both ticks always, so a column can be scanned instead of read.
  assert.strictEqual(html.match(/class="tick"/g)?.length, 6);
  assert.match(html, /<td class="cell-none">/);
  assert.match(html, /<span class="cell-value">100<\/span>/);
  assert.match(html, /Never hit at either bound: <code>m<\/code>/);
});

test('coverage with everything hit somewhere says so in the roll-up', () => {
  const html = renderCoverage(
    coverage({
      groups: ['main'],
      validators: [undefined],
      rows: [{ variable: 'n', cells: [{ minHit: true, maxHit: true, hue: 'green' }] }],
    }),
  );
  assert.match(html, /Every variable reaches a bound somewhere/);
});

test('the stats table carries every channel, and a totals row', () => {
  const html = renderStats(
    model({
      taskType: 'BATCH',
      stats: {
        groups: [
          {
            group: 'main',
            count: 2,
            score: '[40/100]',
            deps: ['samples'],
            subgroups: [{ name: 'small', count: 2 }],
            maxInput: '4 KiB',
            totalInput: '6 KiB',
            maxOutput: '200 B',
          },
          {
            group: 'big',
            count: 1,
            deps: [],
            subgroups: [],
          },
        ],
        count: 3,
        maxInput: '4 KiB',
        totalInput: '6 KiB',
        maxOutput: '200 B',
        samples: 1,
      },
    }),
  );
  assert.match(html, /<th scope="row">main<\/th><td class="num">2<\/td>/);
  assert.match(html, /\[40\/100\]/);
  assert.match(html, /<code>samples<\/code>/);
  assert.match(html, /<span class="chip">small 2<\/span>/);
  assert.match(html, /4 KiB/);
  // The `big` row's six unstamped channels show dashes rather than zeroes.
  assert.strictEqual(html.match(/&mdash;/g)?.length, 6);
  assert.match(html, /<tr class="totals">/);
  assert.match(html, /1 sample\(s\)/);
  assert.match(html, /Task type: <code>BATCH<\/code>/);
});

test('the tab strip marks the current tab and disables the picker off the gallery', () => {
  const gallery = renderTabs(model({ groups: ['main', 'big'] }), { tab: 'gallery' });
  assert.match(gallery, /<button class="tab tab-current" role="tab" aria-selected="true" data-tab="gallery">/);
  assert.match(gallery, /<option value="main">main<\/option>/);
  assert.ok(!gallery.includes('disabled'));
  const stats = renderTabs(model({ groups: ['main'] }), { tab: 'stats', group: 'main' });
  assert.match(stats, /data-tab="stats">Stats/);
  assert.match(stats, /<select id="group" class="group-picker" aria-label="Group" disabled>/);
  assert.match(stats, /<option value="main" selected>/);
});

test('the panel renders the tab that is showing, and nothing else', () => {
  const full = model({
    groups: ['main'],
    gallery: { cells: [cell({ id: 'x' })], withoutVisualization: 0 },
    coverage: coverage({ reported: false }),
    stats: { groups: [{ group: 'main', count: 1, deps: [], subgroups: [] }], count: 1, samples: 0 },
  });
  const gallery = renderPanel(full, GALLERY_STATE, { x: 'https://webview/0.svg' });
  assert.match(gallery, /role="tabpanel"/);
  assert.ok(gallery.includes('<img'));
  assert.ok(!gallery.includes('<table'));
  const stats = renderPanel(full, { tab: 'stats' }, {});
  assert.ok(stats.includes('<table class="stats"'));
  assert.ok(!stats.includes('<img'));
  const cov = renderPanel(full, { tab: 'coverage' }, {});
  assert.match(cov, /ran without validation/);
});

test('a package with no manifest points at `rbx build` instead of drawing tabs', () => {
  const html = renderPanel(EMPTY_PANEL_MODEL, GALLERY_STATE, {});
  assert.match(html, /No testset manifest/);
  assert.match(html, /rbx build/);
  assert.ok(!html.includes('role="tablist"'));
});

test('everything interpolated is escaped', () => {
  const html = renderGallery(
    model({
      gallery: {
        cells: [
          cell({
            id: 'x"><script>',
            label: '<b>&',
            path: "a'b.svg",
            kind: 'other',
            extension: "svg'",
          }),
        ],
        withoutVisualization: 0,
      },
    }),
    GALLERY_STATE,
    { 'x"><script>': 'https://webview/a' },
  );
  assert.ok(!html.includes('<script>'), 'an id must not be able to open a tag');
  assert.match(html, /&lt;b&gt;&amp;/);
  assert.match(html, /a&#39;b.svg/);
});
