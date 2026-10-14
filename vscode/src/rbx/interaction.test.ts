import * as assert from 'assert';
import { test } from 'node:test';

import {
  DEFAULT_LINE_WARNING,
  InteractionParseError,
  countLines,
  decorationWindow,
  needsConfirmation,
  windowCovers,
  RAW_BANNER,
  documentText,
  footerText,
  interactionDocument,
  interactionFileText,
  parseInteraction,
  renderInteraction,
  transcriptSiblings,
} from './interaction';

// The parser cases mirror `parse_interaction`'s tests in
// tests/rbx/box/testcase_utils_test.py, so the two cannot drift apart unseen.

test('parseInteraction reads the prefixes from the header', () => {
  const interaction = parseInteraction(
    'INTERACTOR:\nSOLUTION:\nINTERACTOR: Hello\nSOLUTION: Hi there\n' +
      'INTERACTOR: How are you?\nSOLUTION: Good!\n',
    false,
  );
  assert.deepStrictEqual(interaction, {
    prefixes: ['INTERACTOR:', 'SOLUTION:'],
    entries: [
      { pipe: 'interactor', data: ' Hello' },
      { pipe: 'solution', data: ' Hi there' },
      { pipe: 'interactor', data: ' How are you?' },
      { pipe: 'solution', data: ' Good!' },
    ],
  });
});

test('parseInteraction uses fixed prefixes for .interaction files', () => {
  const interaction = parseInteraction('<Hello\n>Hi\n', true);
  assert.deepStrictEqual(interaction, {
    prefixes: ['<', '>'],
    entries: [
      { pipe: 'interactor', data: 'Hello' },
      { pipe: 'solution', data: 'Hi' },
    ],
  });
});

test('parseInteraction keeps leading whitespace and drops trailing whitespace', () => {
  const interaction = parseInteraction(
    'I:\nS:\nI:    Leading spaces\nS: Trailing spaces    \nI: \tTab indented\n',
    false,
  );
  assert.deepStrictEqual(
    interaction.entries.map((entry) => entry.data),
    ['    Leading spaces', ' Trailing spaces', ' \tTab indented'],
  );
});

test('parseInteraction with one header line reads an empty solution prefix', () => {
  assert.deepStrictEqual(parseInteraction('Only one line\n', false), {
    prefixes: ['Only one line', ''],
    entries: [],
  });
});

test('parseInteraction rejects a line matching no prefix', () => {
  assert.throws(
    () =>
      parseInteraction('INTERACTOR:\nSOLUTION:\nINVALID: This line does not match\n', false),
    (error: unknown) =>
      error instanceof InteractionParseError &&
      error.message.includes('Invalid line in interaction file'),
  );
});

test('parseInteraction with only the header has no entries', () => {
  assert.deepStrictEqual(parseInteraction('INTERACTOR:\nSOLUTION:\n', false).entries, []);
});

test('parseInteraction recognises the stderr prefix', () => {
  const interaction = parseInteraction('< 3\n! reading n\n> 1 2 3\n! done\n', true);
  assert.deepStrictEqual(interaction.entries, [
    { pipe: 'interactor', data: ' 3' },
    { pipe: 'stderr', data: ' reading n' },
    { pipe: 'solution', data: ' 1 2 3' },
    { pipe: 'stderr', data: ' done' },
  ]);
});

test('parseInteraction reads a .pio as rbx writes it', () => {
  const interaction = parseInteraction('<\n>\n<5 100\n>? 3\n<<\n', false);
  assert.deepStrictEqual(interaction.entries, [
    { pipe: 'interactor', data: '5 100' },
    { pipe: 'solution', data: '? 3' },
    { pipe: 'interactor', data: '<' },
  ]);
});

test('renderInteraction keeps payload only, one line per entry', () => {
  const rendered = renderInteraction(parseInteraction('<\n>\n<5 100\n>? 3\n!lo=4\n<<\n', false));
  assert.strictEqual(rendered.text, '5 100\n? 3\nlo=4\n<');
  assert.deepStrictEqual(rendered.pipes, ['interactor', 'solution', 'stderr', 'interactor']);
});

test('renderInteraction groups turns, and stderr neither breaks nor starts one', () => {
  const rendered = renderInteraction(
    parseInteraction('<\n>\n<n\n<m\n>a\n!dbg\n>b\n<r\n>c\n!tail\n', false),
  );
  assert.deepStrictEqual(rendered.turns, [
    { pipe: 'interactor', start: 0, end: 1, ordinal: 1 },
    { pipe: 'solution', start: 2, end: 4, ordinal: 1 },
    { pipe: 'interactor', start: 5, end: 5, ordinal: 2 },
    { pipe: 'solution', start: 6, end: 6, ordinal: 2 },
  ]);
  assert.strictEqual(rendered.solutionTurns, 2);
  assert.strictEqual(rendered.lastSpeaker, 'solution');
});

test('renderInteraction of an empty dialogue has no speaker', () => {
  const rendered = renderInteraction(parseInteraction('<\n>\n', false));
  assert.deepStrictEqual(
    { text: rendered.text, turns: rendered.turns, last: rendered.lastSpeaker },
    { text: '', turns: [], last: undefined },
  );
});

test('interactionDocument falls back to the raw file under a banner', () => {
  const document = interactionDocument('<\n>\ngarbage\n', '/r/1-gen-000.pio');
  assert.deepStrictEqual(document, { kind: 'raw', text: `${RAW_BANNER}\n<\n>\ngarbage\n` });
  assert.strictEqual(documentText(document), `${RAW_BANNER}\n<\n>\ngarbage\n`);
});

test('interactionDocument picks fixed prefixes from the .interaction suffix', () => {
  const document = interactionDocument('<1\n>2\n', '/b/tests/samples/000.interaction');
  assert.strictEqual(documentText(document), '1\n2');
});

test('interactionFileText writes the transcript back with fixed prefixes', () => {
  const interaction = parseInteraction('IN\nOUT\nIN5\nOUT? 3\n!dbg\n', false);
  assert.strictEqual(interactionFileText(interaction), '<5\n>? 3\n!dbg\n');
});

test('footerText says outcome, turns, last speaker and the interactor reason', () => {
  const rendered = renderInteraction(parseInteraction('<\n>\n<5\n>? 3\n<<\n', false));
  assert.strictEqual(
    footerText(rendered, {
      outcome: 'wrong-answer',
      interactorStderr: 'reading\nwrong answer: 101 queries > 100\n\n',
    }),
    '✕ WA · 1 solution turn · interactor spoke last · int.err: wrong answer: 101 queries > 100',
  );
});

test('footerText omits what it does not know', () => {
  const rendered = renderInteraction(parseInteraction('<\n>\n>a\n>b\n<c\n>d\n', false));
  assert.strictEqual(
    footerText(rendered, { outcome: 'accepted', interactorStderr: '  \n' }),
    '✓ AC · 2 solution turns · solution spoke last',
  );
  assert.strictEqual(
    footerText(renderInteraction(parseInteraction('<\n>\n', false)), {}),
    '0 solution turns',
  );
});

test('countLines counts newline-terminated and unterminated last lines', () => {
  const bytes = (text: string): Uint8Array => Buffer.from(text, 'utf8');
  assert.deepStrictEqual(
    ['', 'a\n', 'a\nb', '<\n>\n<1\n'].map((text) => countLines(bytes(text))),
    [0, 1, 2, 3],
  );
});

test('needsConfirmation asks only above a positive threshold', () => {
  assert.strictEqual(needsConfirmation(10_000, DEFAULT_LINE_WARNING), false);
  assert.strictEqual(needsConfirmation(10_001, DEFAULT_LINE_WARNING), true);
  assert.strictEqual(needsConfirmation(1_000_000, 0), false);
});

test('decorationWindow widens the visible lines by the margin, clamped', () => {
  assert.deepStrictEqual(decorationWindow([{ start: 1000, end: 1040 }], 100_000, 500), {
    start: 500,
    end: 1540,
  });
  assert.deepStrictEqual(decorationWindow([{ start: 10, end: 50 }], 300, 500), {
    start: 0,
    end: 299,
  });
  // Folded regions split what is visible into several spans; the window spans them all.
  assert.deepStrictEqual(
    decorationWindow(
      [
        { start: 2000, end: 2010 },
        { start: 5000, end: 5020 },
      ],
      100_000,
      500,
    ),
    { start: 1500, end: 5520 },
  );
  assert.deepStrictEqual(decorationWindow([], 100_000, 500), { start: 0, end: 500 });
});

test('windowCovers redraws only once the viewport nears a decorated edge', () => {
  const window = { start: 500, end: 1540 };
  assert.strictEqual(windowCovers(window, [{ start: 1000, end: 1040 }], 100_000, 500), true);
  // Within half a margin of the bottom edge: time to redraw.
  assert.strictEqual(windowCovers(window, [{ start: 1260, end: 1300 }], 100_000, 500), false);
  assert.strictEqual(windowCovers(window, [{ start: 600, end: 640 }], 100_000, 500), false);
  // At the document's ends there is nothing further to decorate.
  assert.strictEqual(windowCovers({ start: 0, end: 299 }, [{ start: 0, end: 40 }], 300, 500), true);
  assert.strictEqual(
    windowCovers({ start: 99_000, end: 99_999 }, [{ start: 99_950, end: 99_999 }], 100_000, 500),
    true,
  );
});

test('transcriptSiblings finds the eval and interactor stderr of a .pio', () => {
  assert.deepStrictEqual(transcriptSiblings('/p/.rbx/runs/0/main/1-gen-000.pio'), {
    evalPath: '/p/.rbx/runs/0/main/1-gen-000.eval',
    interactorStderrPath: '/p/.rbx/runs/0/main/1-gen-000.int.err',
  });
  assert.strictEqual(transcriptSiblings('/p/build/tests/samples/000.interaction'), undefined);
});
