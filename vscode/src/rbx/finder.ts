/**
 * The finder rows the stress launcher builds, and the expression they mean.
 *
 * A finder is an expression in rbx's own grammar (rbx/box/stressing/
 * finder_parser.py): `[sols/a.cpp] ~ WRONG_ANSWER && [sols/b.cpp] != [sols/c.cpp]`.
 * The launcher never asks the user to write one (design S5). It offers rows
 * instead -- *Break*, a solution getting some outcome, and *Disagree*, two
 * solutions answering differently -- joined by one All of / Any of toggle, and
 * this module is the whole translation between the two.
 *
 * It goes both ways, but not symmetrically. Rows always compile; an expression
 * is recognized only when it has exactly the shape rows compile to (plus the
 * bare `path` shorthand rbx itself accepts). Everything else -- parentheses,
 * negation, mixed `&&`/`||`, a checker named with `ON`, `==`, a wildcard -- is
 * left alone, so a declared stress with a finder like that is shown as a
 * read-only expression rather than misread as rows that would mean something
 * else. Not a parser of the grammar: recognizing a strict subset is the point.
 */
import { EXPECTED_OUTCOMES, normalizeExpectation } from './manifest';

export type FinderRow =
  /** `[solution] ~ outcome`: the solution's verdict matches an ExpectedOutcome. */
  | { readonly kind: 'break'; readonly solution: string; readonly outcome: string }
  /** `[a] != [b]`: the two solutions' verdicts differ. */
  | { readonly kind: 'disagree'; readonly a: string; readonly b: string };

/** How the rows combine: `all` is `&&`, `any` is `||`. */
export type Join = 'all' | 'any';

/**
 * The outcomes a break row can name: `ExpectedOutcome`'s member names.
 *
 * Not rbx's `Outcome` values (`wrong-answer`), which is what a *run* produced:
 * the grammar's `~` resolves its right-hand side with `ExpectedOutcome(token)`,
 * which takes a member name or an alias, so `~ WRONG_ANSWER` and `~ wa` both
 * work and `~ wrong-answer` does not even lex (`-` is not in a CNAME).
 */
export const FINDER_OUTCOMES: readonly string[] = EXPECTED_OUTCOMES;

/**
 * The outcome a break row preselects for a solution, from what problem.rbx.yml
 * declares it gets.
 *
 * A solution declared to fail some way is stressed to find an input where it
 * does, so its declaration is the answer. A solution declared correct is
 * stressed to find one where it is *not*, which is INCORRECT; so is one that
 * declares nothing, which rbx reads as ANY and which says nothing to go on.
 *
 * ACCEPTED_OR_TLE is the exception: INCORRECT includes a TLE, so it would
 * report as findings the very timeouts the declaration allows. What breaks
 * such a solution is a wrong answer, so that is what is preselected.
 */
export function defaultOutcomeFor(declared?: string): string {
  if (declared === undefined) {
    return 'INCORRECT';
  }
  const member = normalizeExpectation(declared);
  if (member === 'ACCEPTED_OR_TLE') {
    return 'WRONG_ANSWER';
  }
  if (member === 'ACCEPTED' || member === 'ANY') {
    return 'INCORRECT';
  }
  return FINDER_OUTCOMES.includes(member) ? member : 'INCORRECT';
}

/**
 * What a bare path may be made of: anything but whitespace and the characters
 * the grammar reserves -- `( ) [ ] | & ! ~ = $ @ "` and the `:` of `2:checker`.
 * The same set as the grammar's FILENAME terminal, which is the line between
 * a path that can be written bare and one that has to be quoted.
 */
const BARE_PATH = /^[^\s()[\]|&!~=$@":]+$/;
const BARE_TOKEN = /^[^\s()[\]|&!~=$@":]+/;
/** The grammar's CNAME, which is what an outcome token is. */
const CNAME = /^[A-Za-z_][A-Za-z0-9_+]*$/;

/**
 * Why `path` cannot be named in a finder, or undefined when it can.
 *
 * Quoting covers every reserved character but one: a quoted path runs to the
 * next `"`, and the grammar has no escape, so a path holding a double quote --
 * or a line break, which a quoted path may not span -- cannot be written at all.
 *
 * A single quote is refused too, for the terminal rather than the grammar: the
 * finder reaches rbx as one argument in single quotes (dispatch.ts), and a
 * single-quoted shell word cannot hold one.
 */
export function finderPathProblem(path: string): string | undefined {
  if (path === '') {
    return 'Every row needs a solution.';
  }
  if (path.includes('"')) {
    return `A finder cannot name ${path}: it has a double quote, which no finder can spell.`;
  }
  if (/[\r\n]/.test(path)) {
    return `A finder cannot name ${path}: it has a line break, which no finder can spell.`;
  }
  if (path.includes("'")) {
    return singleQuoteProblem(path);
  }
  return undefined;
}

/**
 * Why `value` cannot be passed to a dispatched rbx command, for holding a
 * single quote.
 *
 * Every argument of a dispatched `stress` or `add-finding` is single-quoted
 * for the terminal's shell (dispatch.ts), which is the only quoting that leaves
 * a finder's `[`, `|`, `&`, `!`, `$` and `"` alone in every shell VS Code
 * may run -- and the one thing it cannot do is hold a single quote.
 */
export function singleQuoteProblem(value: string): string {
  return (
    `${value} has a single quote ('), which cannot be passed through the terminal; ` +
    'rename it, or run the command in a terminal by hand.'
  );
}

/** A path as the grammar wants it: bare when it can be, quoted when it must. */
function spell(path: string): string {
  return BARE_PATH.test(path) ? path : `"${path}"`;
}

function compileRow(row: FinderRow): string {
  return row.kind === 'break'
    ? `[${spell(row.solution)}] ~ ${row.outcome}`
    : `[${spell(row.a)}] != [${spell(row.b)}]`;
}

/**
 * The finder expression the rows mean.
 *
 * Every solution bracketed, even where the grammar would take it bare: the
 * terminal shows this line, and `[a] ~ WA` reads as "a's verdict" where
 * `a ~ WA` reads as nothing in particular. No rows is the empty expression,
 * which the caller is expected not to send.
 */
export function compileFinder(rows: readonly FinderRow[], join: Join): string {
  return rows.map(compileRow).join(join === 'all' ? ' && ' : ' || ');
}

type Token =
  | { readonly kind: 'path'; readonly text: string; readonly quoted: boolean }
  | { readonly kind: '[' | ']' | '~' | '!=' | '&&' | '||' };

/** Split an expression into the tokens rows compile to, or undefined on anything else. */
function tokenize(expr: string): Token[] | undefined {
  const tokens: Token[] = [];
  let rest = expr;
  for (;;) {
    // Spaces only, as the grammar's `%ignore " "`: a tab or a line break
    // outside quotes is something rbx would refuse, so it is not recognized.
    rest = rest.replace(/^ +/, '');
    if (rest === '') {
      return tokens;
    }
    const two = rest.slice(0, 2);
    if (two === '!=' || two === '&&' || two === '||') {
      tokens.push({ kind: two });
      rest = rest.slice(2);
      continue;
    }
    const one = rest[0];
    if (one === '[' || one === ']' || one === '~') {
      tokens.push({ kind: one });
      rest = rest.slice(1);
      continue;
    }
    if (one === '"') {
      const end = rest.indexOf('"', 1);
      const text = end < 0 ? '' : rest.slice(1, end);
      if (text === '' || /[\r\n]/.test(text)) {
        return undefined;
      }
      tokens.push({ kind: 'path', text, quoted: true });
      rest = rest.slice(end + 1);
      continue;
    }
    const bare = BARE_TOKEN.exec(rest);
    if (bare === null) {
      // `(`, `!` not followed by `=`, `==`, `$`, `@`, `:` -- all grammar this
      // module does not recognize, on purpose.
      return undefined;
    }
    tokens.push({ kind: 'path', text: bare[0], quoted: false });
    rest = rest.slice(bare[0].length);
  }
}

/** A cursor over the tokens, for the few productions rows compile to. */
class Reader {
  private at = 0;
  constructor(private readonly tokens: readonly Token[]) {}

  peek(): Token | undefined {
    return this.tokens[this.at];
  }

  next(): Token | undefined {
    return this.tokens[this.at++];
  }

  done(): boolean {
    return this.at >= this.tokens.length;
  }

  /** `[path]`, or -- when `bracketedOnly` is false -- a bare or quoted `path`. */
  solution(bracketedOnly: boolean): string | undefined {
    const first = this.next();
    if (first?.kind === 'path') {
      return bracketedOnly && !first.quoted ? undefined : first.text;
    }
    if (first?.kind !== '[') {
      return undefined;
    }
    const path = this.next();
    const close = this.next();
    return path?.kind === 'path' && close?.kind === ']' ? path.text : undefined;
  }
}

function readRow(reader: Reader, bareOutcome: string): FinderRow | undefined {
  const solution = reader.solution(false);
  if (solution === undefined) {
    return undefined;
  }
  const op = reader.peek();
  if (op?.kind === '~') {
    reader.next();
    const outcome = reader.next();
    if (outcome?.kind !== 'path' || outcome.quoted || !CNAME.test(outcome.text)) {
      return undefined;
    }
    const member = normalizeExpectation(outcome.text);
    return FINDER_OUTCOMES.includes(member)
      ? { kind: 'break', solution, outcome: member }
      : undefined;
  }
  if (op?.kind === '!=') {
    reader.next();
    // Bracketed or quoted only: a bare word after `!=` may be an Outcome
    // (`[a] != WA` compares against a verdict, not a solution), and the
    // grammar's own answer for which is not worth re-deriving here.
    const b = reader.solution(true);
    return b === undefined ? undefined : { kind: 'disagree', a: solution, b };
  }
  return { kind: 'break', solution, outcome: bareOutcome };
}

/**
 * The rows an expression means, or undefined when rows cannot say it.
 *
 * A bare solution (`[a]`, or `a`) is rbx's shorthand for "a gets it wrong",
 * which is `~ INCORRECT` -- except under `--slowest`, where rbx reads it as
 * `~ ANY` instead (every run counts; the slowest are kept). That is the one
 * fact about the expression that lives outside it, so the caller passes it in.
 */
export function recognizeFinder(
  expr: string,
  bareOutcome = 'INCORRECT',
): { rows: FinderRow[]; join: Join } | undefined {
  const tokens = tokenize(expr);
  if (tokens === undefined || tokens.length === 0) {
    return undefined;
  }
  const reader = new Reader(tokens);
  const rows: FinderRow[] = [];
  let join: Join | undefined;
  for (;;) {
    const row = readRow(reader, bareOutcome);
    if (row === undefined) {
      return undefined;
    }
    rows.push(row);
    if (reader.done()) {
      return { rows, join: join ?? 'all' };
    }
    const separator = reader.next();
    const kind: Join | undefined =
      separator?.kind === '&&' ? 'all' : separator?.kind === '||' ? 'any' : undefined;
    // One toggle for every row: `a && b || c` has a precedence the rows have no
    // way to show, so it is not theirs to show.
    if (kind === undefined || (join !== undefined && join !== kind)) {
      return undefined;
    }
    join = kind;
  }
}
