/**
 * The interaction transcript of a communication task, as the `io` channel shows it.
 *
 * rbx writes the dialogue between the interactor and the solution as a `.pio`
 * file: two header lines naming the prefixes (`<` for the interactor, `>` for
 * the solution), then one line per line either side wrote, glued to its prefix.
 * Lines starting with `!` are the solution's stderr, folded in. Generated
 * samples use the same format under `.interaction`, with the prefixes fixed and
 * no header.
 *
 * The channel shows the *payload* only -- `? 3`, not `>? 3` -- so that copying a
 * line copies data, and says who wrote each line with decorations instead
 * (`interactionDecorations.ts`). Everything that decides what those decorations
 * are lives here, away from `vscode`, so `node --test` can hold it to account.
 *
 * See `docs/plans/2026-10-14-vscode-interaction-channel-design.md`.
 */
import { isAccepted, shortName } from './outcome';

/** Who wrote a line. `stderr` is the solution's stderr, folded in. */
export type Pipe = 'interactor' | 'solution' | 'stderr';

export interface InteractionEntry {
  readonly pipe: Pipe;
  /** The line without its prefix and without trailing whitespace. */
  readonly data: string;
}

export interface Interaction {
  /** The interactor's and the solution's prefixes, in that order. */
  readonly prefixes: readonly [string, string];
  readonly entries: readonly InteractionEntry[];
}

/** The prefix rbx marks a folded-in stderr line with (`STDERR_PREFIX`). */
export const STDERR_PREFIX = '!';

export class InteractionParseError extends Error {}

/**
 * Parse a transcript, mirroring `rbx.box.testcase_utils.parse_interaction`.
 *
 * `fixedPrefixes` is for `.interaction` files, whose prefixes are always `<`
 * and `>` and which carry no header; anything else (a `.pio`) reads them from
 * its first two lines.
 *
 * One deliberate difference: Python stops at the first blank line, this skips
 * blank lines. rbx never writes one mid-file -- an empty line the solution
 * prints is still recorded as a bare `>` -- so the two agree on everything rbx
 * produces, and this one does not silently drop the tail of a hand-edited file.
 */
export function parseInteraction(text: string, fixedPrefixes: boolean): Interaction {
  const lines = text.split(/\r?\n/);
  let interactorPrefix = '<';
  let solutionPrefix = '>';
  let body = lines;
  if (!fixedPrefixes) {
    interactorPrefix = (lines[0] ?? '').trim();
    solutionPrefix = (lines[1] ?? '').trim();
    body = lines.slice(2);
  }

  const entries: InteractionEntry[] = [];
  for (const raw of body) {
    const line = raw.trim();
    if (line === '') {
      continue;
    }
    // Same order as Python: a line that matches both prefixes belongs to the
    // interactor, and an empty prefix matches everything.
    if (line.startsWith(interactorPrefix)) {
      entries.push({ pipe: 'interactor', data: line.slice(interactorPrefix.length).trimEnd() });
    } else if (line.startsWith(solutionPrefix)) {
      entries.push({ pipe: 'solution', data: line.slice(solutionPrefix.length).trimEnd() });
    } else if (line.startsWith(STDERR_PREFIX)) {
      entries.push({ pipe: 'stderr', data: line.slice(STDERR_PREFIX.length).trimEnd() });
    } else {
      throw new InteractionParseError(
        `Invalid line in interaction file. Expected the line to start with the ` +
          `interactor or solution prefix (${interactorPrefix} or ${solutionPrefix}).`,
      );
    }
  }
  return { prefixes: [interactorPrefix, solutionPrefix], entries };
}

/**
 * One uninterrupted stretch of a single side talking.
 *
 * Stderr does not interrupt a turn: a solution that logs between two lines of
 * one answer is still giving one answer. It does not *start* one either, so a
 * turn spans from its first to its last line of the side, with any stderr in
 * between inside it.
 */
export interface Turn {
  readonly pipe: 'interactor' | 'solution';
  /** First and last line of the turn, 0-based and inclusive. */
  readonly start: number;
  readonly end: number;
  /** 1-based, counted per side: the solution's turns are its queries. */
  readonly ordinal: number;
}

export interface RenderedInteraction {
  /** The document text: one line per entry, payload only. */
  readonly text: string;
  /** Who wrote each line of `text`. */
  readonly pipes: readonly Pipe[];
  readonly turns: readonly Turn[];
  /** How many turns the solution took -- for most protocols, its query count. */
  readonly solutionTurns: number;
  /** Whoever wrote the last non-stderr line, or nothing for an empty dialogue. */
  readonly lastSpeaker?: 'interactor' | 'solution';
}

export function renderInteraction(interaction: Interaction): RenderedInteraction {
  const pipes = interaction.entries.map((entry) => entry.pipe);
  const turns: Turn[] = [];
  const ordinals = { interactor: 0, solution: 0 };
  let open: { pipe: 'interactor' | 'solution'; start: number; end: number } | undefined;
  const close = (): void => {
    if (open !== undefined) {
      ordinals[open.pipe] += 1;
      turns.push({ ...open, ordinal: ordinals[open.pipe] });
    }
  };
  pipes.forEach((pipe, line) => {
    if (pipe === 'stderr') {
      return;
    }
    if (open !== undefined && open.pipe === pipe) {
      open.end = line;
      return;
    }
    close();
    open = { pipe, start: line, end: line };
  });
  close();

  return {
    text: interaction.entries.map((entry) => entry.data).join('\n'),
    pipes,
    turns,
    solutionTurns: ordinals.solution,
    lastSpeaker: turns.length === 0 ? undefined : turns[turns.length - 1].pipe,
  };
}

/** The first line of the document when the file is shown raw. */
export const RAW_BANNER =
  'Not a parseable interaction -- the processes may not have communicated ' +
  'properly. Showing the raw file.';

/**
 * What the `io` channel's document holds for a transcript file.
 *
 * The rendered payload when the file parses, and otherwise the raw file under a
 * one-line banner -- the same fallback `rbx ui`'s interaction box makes, because
 * an unparseable transcript is usually the most interesting one to read.
 */
export type InteractionDocument =
  | { readonly kind: 'parsed'; readonly rendered: RenderedInteraction }
  | { readonly kind: 'raw'; readonly text: string };

export function interactionDocument(raw: string, realPath: string): InteractionDocument {
  try {
    const interaction = parseInteraction(raw, realPath.endsWith('.interaction'));
    return { kind: 'parsed', rendered: renderInteraction(interaction) };
  } catch (error) {
    if (!(error instanceof InteractionParseError)) {
      throw error;
    }
    return { kind: 'raw', text: `${RAW_BANNER}\n${raw}` };
  }
}

export function documentText(document: InteractionDocument): string {
  return document.kind === 'parsed' ? document.rendered.text : document.text;
}

/**
 * The transcript back in `.interaction` form: `<`, `>` and `!` prefixes.
 *
 * What `rbx.copyInteraction` puts on the clipboard -- the format a statement
 * sample's `.interaction` file is written in, so a run can become a sample.
 */
export function interactionFileText(interaction: Interaction): string {
  const prefix: Record<Pipe, string> = {
    interactor: '<',
    solution: '>',
    stderr: STDERR_PREFIX,
  };
  return interaction.entries.map((entry) => prefix[entry.pipe] + entry.data).join('\n') + '\n';
}

/** What the footer under the last line says. */
export interface FooterFacts {
  readonly outcome?: string;
  /** The interactor's stderr, whole; only its last non-empty line is shown. */
  readonly interactorStderr?: string;
}

/**
 * The one-line summary decorated after the transcript's last line.
 *
 * `✕ WA · 101 solution turns · interactor spoke last · int.err: wrong answer`.
 * Every clause is optional except the turn count. "Spoke last" is the clause
 * the transcript alone cannot make obvious at a glance: whether it was the
 * solution that went quiet or the interactor that stopped answering.
 */
export function footerText(rendered: RenderedInteraction, facts: FooterFacts): string {
  const parts: string[] = [];
  if (facts.outcome !== undefined) {
    parts.push(`${isAccepted(facts.outcome) ? '✓' : '✕'} ${shortName(facts.outcome)}`);
  }
  const turns = rendered.solutionTurns;
  parts.push(`${turns} solution turn${turns === 1 ? '' : 's'}`);
  if (rendered.lastSpeaker !== undefined) {
    parts.push(`${rendered.lastSpeaker} spoke last`);
  }
  const reason = lastLine(facts.interactorStderr);
  if (reason !== undefined) {
    parts.push(`int.err: ${reason}`);
  }
  return parts.join(' · ');
}

function lastLine(text: string | undefined): string | undefined {
  const lines = (text ?? '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== '');
  return lines.length === 0 ? undefined : lines[lines.length - 1];
}

/** A span of lines, 0-based and inclusive. */
export interface LineSpan {
  readonly start: number;
  readonly end: number;
}

/**
 * How far past the visible lines the decorations reach, on either side.
 *
 * Wide enough that a page-down lands on lines already decorated, narrow enough
 * that re-decorating costs a few thousand ranges whatever the transcript's size.
 */
export const DECORATION_MARGIN = 500;

/**
 * The lines to decorate: everything visible, widened by `margin` and clamped.
 *
 * Decorating a whole 10^5-line transcript at once is what stalls the editor --
 * every arrow and tint is a decoration, and each turn counter carries render
 * options of its own. Only the lines near the viewport are decorated instead,
 * and again as it moves; the document still holds every line, so find,
 * go-to-line and copy are untouched.
 */
export function decorationWindow(
  visible: readonly LineSpan[],
  lineCount: number,
  margin: number = DECORATION_MARGIN,
): LineSpan {
  const last = Math.max(0, lineCount - 1);
  if (visible.length === 0) {
    return { start: 0, end: Math.min(last, margin) };
  }
  const start = Math.min(...visible.map((span) => span.start));
  const end = Math.max(...visible.map((span) => span.end));
  return { start: Math.max(0, start - margin), end: Math.min(last, end + margin) };
}

/**
 * Whether the decorations drawn for `window` still cover what is visible, with
 * room to spare.
 *
 * Scrolling fires constantly; re-decorating on every event would redo the same
 * work line by line. Redrawing only once the viewport gets within half a margin
 * of the decorated edge keeps it to one redraw per few hundred lines scrolled.
 * An edge at the document's start or end needs no slack: there is nothing
 * further to decorate.
 */
export function windowCovers(
  window: LineSpan,
  visible: readonly LineSpan[],
  lineCount: number,
  margin: number = DECORATION_MARGIN,
): boolean {
  if (visible.length === 0) {
    return true;
  }
  const slack = Math.floor(margin / 2);
  const start = Math.min(...visible.map((span) => span.start));
  const end = Math.max(...visible.map((span) => span.end));
  const startOk = window.start === 0 || start - slack >= window.start;
  const endOk = window.end >= lineCount - 1 || end + slack <= window.end;
  return startOk && endOk;
}

/**
 * The sibling artifacts a transcript's footer reads, derived from its path.
 *
 * `<stem>.pio` sits beside `<stem>.eval` and `<stem>.int.err` in the same run
 * directory, so the decorations can find them from the document alone without
 * the document having to carry a testcase. A `.interaction` sample has no run
 * and so no siblings.
 */
export function transcriptSiblings(
  realPath: string,
): { readonly evalPath: string; readonly interactorStderrPath: string } | undefined {
  if (!realPath.endsWith('.pio')) {
    return undefined;
  }
  const base = realPath.slice(0, -'.pio'.length);
  return { evalPath: `${base}.eval`, interactorStderrPath: `${base}.int.err` };
}
