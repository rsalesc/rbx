import * as assert from 'assert';
import { test } from 'node:test';

import type { StressDeclarations } from '../rbx/stressDeclarations';
import { defaultLaunch } from '../rbx/stressSpec';
import { INSERT_CHIPS, LauncherView, footerState, renderForm, runBlocker } from './launcherRender';
import { formOf, reduce } from './launcherState';

const DECLS: StressDeclarations = {
  stresses: [
    { name: 'wa-small', generator: { name: 'gen', args: '@' }, finder: '[sols/wa.cpp] ~ WA' },
    { name: 'opaque', generator: { name: 'gen' }, finder: '!([sols/wa.cpp] ~ AC)' },
  ],
  generators: ['gen'],
  solutions: [{ path: 'sols/wa.cpp', outcome: 'WRONG_ANSWER' }],
  groups: ['main'],
};

function view(name: string, decls = DECLS): LauncherView {
  return {
    form: formOf(defaultLaunch({ kind: 'declared', name }), decls),
    declarations: decls,
    vars: [],
  };
}

test('an unrecognized declared finder is a read-only chip with Replace with rows', () => {
  const html = renderForm(view('opaque'));
  assert.match(html, /Custom finder from problem\.rbx\.yml/);
  assert.match(html, /<code>!\(\[sols\/wa\.cpp\] ~ AC\)<\/code>/);
  assert.match(html, /data-act="replace-finder"/);
  assert.doesNotMatch(html, /data-act="add-row"/);
});

test('a recognized declared finder shows its rows and says editing replaces it', () => {
  const html = renderForm(view('wa-small'));
  assert.match(html, /id="row-0-solution"/);
  assert.match(html, /<option value="WRONG_ANSWER" selected>/);
  assert.match(html, /Editing a row replaces it/);
  assert.doesNotMatch(html, /data-act="keep-finder"/);
});

test('a replaced finder offers to use the declared one again', () => {
  const v = view('wa-small');
  const form = reduce(v.form, { type: 'join', join: 'any' }, DECLS);
  assert.match(renderForm({ ...v, form }), /data-act="keep-finder"/);
});

test('names from problem.rbx.yml are escaped wherever they land', () => {
  const evil = '<img src=x onerror=alert(1)>"\'';
  const decls: StressDeclarations = {
    stresses: [{ name: evil, generator: { name: evil, args: evil }, finder: evil }],
    generators: [evil],
    solutions: [{ path: evil }],
    groups: [evil],
  };
  for (const mode of ['declared', 'generator', 'fuzz'] as const) {
    const base = view(evil, decls);
    const form = reduce(
      reduce(reduce(base.form, { type: 'mode', mode }, decls), { type: 'add-row', kind: 'break' }, decls),
      { type: 'row', index: 0, field: 'solution', value: evil },
      decls,
    );
    const html = renderForm({ ...base, form, vars: [evil] });
    assert.doesNotMatch(html, /<img/, mode);
  }
});

test('every control has an id, and every input a label', () => {
  const v = view('wa-small');
  const forms = [
    v.form,
    reduce(v.form, { type: 'mode', mode: 'generator' }, DECLS),
    reduce(v.form, { type: 'mode', mode: 'fuzz' }, DECLS),
  ];
  for (const form of forms) {
    const html = renderForm({ ...v, form, vars: ['N'] });
    const controls = html.match(/<(input|select|button)\b[^>]*>/g) ?? [];
    assert.ok(controls.length > 0);
    for (const control of controls) {
      const id = /\bid="([^"]+)"/.exec(control)?.[1];
      assert.ok(id !== undefined, control);
      const labelled =
        /aria-label=/.test(control) ||
        html.includes(`for="${id}"`) ||
        control.startsWith('<button');
      assert.ok(labelled, control);
    }
  }
});

test('the generator section offers the declared generators and the insert chips', () => {
  const v = view('wa-small');
  const form = reduce(v.form, { type: 'mode', mode: 'generator' }, DECLS);
  const html = renderForm({ ...v, form, vars: ['N', 'M'] });
  assert.match(html, /<datalist id="generator-names"><option value="gen">/);
  assert.strictEqual((html.match(/data-act="insert"/g) ?? []).length, INSERT_CHIPS.length);
  assert.match(html, /<option value="N">N<\/option>/);
});

test('each insert chip selects within the text it types', () => {
  for (const chip of INSERT_CHIPS) {
    assert.ok(chip.select[0] <= chip.select[1] && chip.select[1] <= chip.text.length, chip.label);
  }
  const range = INSERT_CHIPS.find((chip) => chip.label === '[1..10]');
  assert.strictEqual(range?.text.slice(...range.select), '1..10');
});

test('Run is off while the launch cannot run, or while dispatching is', () => {
  const ok = footerState(view('wa-small').form, DECLS);
  assert.strictEqual(ok.command, 'rbx stress wa-small --no-promote');
  assert.strictEqual(runBlocker(ok, true), undefined);
  assert.match(runBlocker(ok, false) ?? '', /turned off/);
  const generator = reduce(view('wa-small').form, { type: 'mode', mode: 'generator' }, DECLS);
  assert.match(runBlocker(footerState(generator, DECLS), true) ?? '', /finder row/);
});
