import * as assert from 'assert';
import { test } from 'node:test';

import {
  Artifact,
  DiffArtifact,
  asTestcaseLayout,
  channelArtifact,
  inputArtifact,
  isDiff,
  labelPrefix,
  layoutCommand,
  paneKindOf,
} from './panes';
import type { TestcaseRun } from './store';

function testcase(over: Partial<TestcaseRun> = {}): TestcaseRun {
  return {
    entry: { group: 'main', index: 0 },
    stem: '1-gen-000',
    inputPath: '/w/a/.rbx/tests/main/1-gen-000.in',
    answerPath: '/w/a/.rbx/tests/main/1-gen-000.out',
    outputPath: '/w/a/.rbx/runs/0/main/1-gen-000.out',
    stderrPaths: [
      '/w/a/.rbx/runs/0/main/1-gen-000.err',
      '/w/a/.rbx/runs/0/main/1-gen-000.sol.err',
    ],
    logPath: '/w/a/.rbx/runs/0/main/1-gen-000.log',
    interactionPath: '/w/a/.rbx/runs/0/main/1-gen-000.pio',
    ...over,
  };
}

// Recognising our own tabs is what keeps a dragged pane where the user put it:
// the opener reuses the group it finds one in, and only lays out a grid when it
// finds none. A pane it fails to recognise is a pane it opens a second copy of,
// on top of whatever the user was doing.

test('a pane is recognised by the last segment of its display path', () => {
  assert.strictEqual(paneKindOf('/sols%2Fwa.cpp/main/1-gen-000/input.in'), 'input');
  assert.strictEqual(paneKindOf('/sols%2Fwa.cpp/main/1-gen-000/output.out'), 'channel');
  assert.strictEqual(paneKindOf('/sols%2Fwa.cpp/main/1-gen-000/answer.out'), 'channel');
  assert.strictEqual(paneKindOf('/sols%2Fwa.cpp/main/1-gen-000/stderr.err'), 'channel');
  assert.strictEqual(paneKindOf('/sols%2Fwa.cpp/main/1-gen-000/run.log'), 'channel');
});

test('a pane stays the same pane when the testcase changes', () => {
  // Everything but the last segment moves with the selection; matching on the
  // whole path would lose the pane on the very first arrow key.
  assert.strictEqual(
    paneKindOf('/sols%2Fmain.cpp/samples/000/input.in'),
    paneKindOf('/sols%2Fwa.cpp/edge/9-gen-042/input.in'),
  );
});

test('a tab that is not ours is not claimed', () => {
  // The compiler output travels on the same scheme, and it is not a pane. Nor
  // is a bare directory or an empty path.
  assert.strictEqual(paneKindOf('/sols%2Fbroken.cpp/compile.log'), undefined);
  assert.strictEqual(paneKindOf('/sols%2Fwa.cpp/main/1-gen-000'), undefined);
  assert.strictEqual(paneKindOf('/'), undefined);
  assert.strictEqual(paneKindOf(''), undefined);
});

test('the out channel is the diff, and the others are single files', () => {
  const run = testcase();
  const out = channelArtifact('out', run);
  assert.ok(isDiff(out));
  const diff = out as DiffArtifact;
  assert.deepStrictEqual(diff.left.paths, [run.outputPath]);
  assert.deepStrictEqual(diff.right.paths, [run.answerPath]);

  const err = channelArtifact('err', run) as Artifact;
  assert.ok(!isDiff(err));
  // Both spellings, most likely first: a communication task writes the
  // solution's stderr to `<stem>.sol.err` instead.
  assert.deepStrictEqual(err.paths, run.stderrPaths);

  const log = channelArtifact('log', run) as Artifact;
  assert.deepStrictEqual(log.paths, [run.logPath]);
});

test('every artifact a pane opens is recognised as that pane', () => {
  // The round trip the whole arrangement rests on: a label that opened into a
  // pane has to be a label that finds the pane again.
  const run = testcase();
  const prefix = labelPrefix('sols/wa.cpp', 'main', '1-gen-000');
  const labels = [
    inputArtifact(run).label,
    ...['err', 'log'].map((channel) => (channelArtifact(channel as 'err', run) as Artifact).label),
    (channelArtifact('out', run) as DiffArtifact).left.label,
    (channelArtifact('out', run) as DiffArtifact).right.label,
  ];
  const kinds = labels.map((label) => paneKindOf(`/${prefix}/${label}`));
  assert.deepStrictEqual(kinds, ['input', 'channel', 'channel', 'channel', 'channel']);
});

test('the layout setting picks a built-in layout command, and defaults to below', () => {
  assert.strictEqual(asTestcaseLayout('below'), 'below');
  assert.strictEqual(asTestcaseLayout('beside'), 'beside');
  // Anything else is the default: the setting is window-scoped and a user can
  // type into it, and a layout command that does not exist would throw.
  //
  // `below` and not `beside`, so the diff spans the full editor width: VS Code
  // drops a narrow diff to an inline view on its own, and a channel pane given
  // half of an already-narrowed editor area is narrow.
  assert.strictEqual(asTestcaseLayout(undefined), 'below');
  assert.strictEqual(asTestcaseLayout('sideways'), 'below');

  assert.strictEqual(
    layoutCommand('beside'),
    'workbench.action.editorLayoutTwoColumns',
  );
  assert.strictEqual(layoutCommand('below'), 'workbench.action.editorLayoutTwoRows');
});
