/**
 * Which `\VAR{...}` references in a statement get a value badge.
 *
 * Pure: no `vscode` import, so `node --test` covers it directly.
 *
 * Only *problem-root* references are badged -- `\VAR{N.max}` and
 * `\VAR{vars.N.max}`. A group reference (`\VAR{g.N.max}`) renders a different
 * value per loop iteration, so a single badge would have to lie or to name the
 * group; contest and problem scopes resolve against var sets this map does not
 * hold. Every one of those, and every expression that is not a plain dotted
 * name, yields no hint: an absent badge is never wrong.
 *
 * See docs/plans/2026-08-28-vscode-statement-var-hints-design.md (D1).
 */

/**
 * The expanded package vars, keyed by dotted name.
 *
 * Values are strings, not numbers: `rbx vars --json` renders each one to the
 * text the statement will show and emits *that*. A JSON number would be an
 * IEEE double by the time `JSON.parse` was done with it, so a bound like
 * `10**18 + 7` would silently badge as `1000000000000000000` and `10**21` as
 * `1e+21`. Nothing here does arithmetic on a value, so text is all it needs.
 */
export type Vars = Readonly<Record<string, string>>;

export interface VarHint {
  /** Offset just past the reference's closing brace. */
  readonly end: number;
  /** The value's display text, verbatim from `rbx vars --json`. */
  readonly text: string;
}

/**
 * Scopes whose values this map does not hold. See the module comment.
 *
 * The two halves of this list are claimed on different grounds:
 *
 * - `problem`, `contest`, `groups` and `vars` are rbx's own. All four sit in
 *   `RESERVED_STATEMENT_VAR_NAMES` (rbx/box/fields.py), which rejects a
 *   top-level var that would shadow a template namespace key, so no legitimate
 *   root var can ever be spelled `problem.x` or `groups.x`. Claiming them
 *   costs nothing.
 * - `g` and `p` are only *conventional* -- the aliases a template author
 *   happens to bind in `\BLOCK{for g in groups}`. rbx reserves neither, so a
 *   root var genuinely named `g` is legal and `\VAR{g.max}` would then lose a
 *   badge it could have had. That is a deliberate false negative: badging a
 *   loop variable with a root value would be a lie, and under D5 an absent
 *   badge is never wrong.
 */
const FOREIGN_SCOPE = /^(vars\.)?(g|p|problem|contest|groups)\./;

/** A plain dotted name, with an optional filter pipeline we ignore. */
const REFERENCE = /^\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*(?:\|[^}]*)?$/;

const OCCURRENCE = /\\VAR\{([^}]*)\}/g;

/** How many backslashes immediately precede `offset`. */
function backslashesBefore(text: string, offset: number): number {
  let count = 0;
  for (let i = offset - 1; i >= 0 && text[i] === '\\'; i -= 1) {
    count += 1;
  }
  return count;
}

/**
 * Whether a comment already runs at `offset`.
 *
 * Both comment syntaxes a statement can use open with a percent -- LaTeX's `%`
 * and rbxTeX's Jinja line comment `%#` -- and both run to the end of the line,
 * so one unescaped percent earlier on the line is enough. `\%` is a literal
 * percent and opens nothing; `\\%` is a literal backslash and then a comment,
 * hence the parity check.
 */
function isCommented(text: string, offset: number): boolean {
  const lineStart = text.lastIndexOf('\n', offset - 1) + 1;
  for (let i = lineStart; i < offset; i += 1) {
    if (text[i] === '%' && backslashesBefore(text, i) % 2 === 0) {
      return true;
    }
  }
  return false;
}

/**
 * Whether the backslash at `offset` is itself escaped, making the `\VAR` a
 * literal rather than a reference. An odd run of backslashes before it means
 * the last one pairs off with the one the match consumed.
 */
function isEscaped(text: string, offset: number): boolean {
  return backslashesBefore(text, offset) % 2 === 1;
}

/** The value `name` holds, or `undefined` if the map does not hold it. */
function lookup(vars: Vars, name: string): string | undefined {
  // Own-property only: a name like `constructor` or `toString` is a typo, not
  // a var, and must not resolve to whatever `Object.prototype` carries.
  return Object.prototype.hasOwnProperty.call(vars, name) ? vars[name] : undefined;
}

export function scanStatementVars(text: string, vars: Vars): VarHint[] {
  const hints: VarHint[] = [];
  const occurrence = new RegExp(OCCURRENCE);

  for (let match = occurrence.exec(text); match; match = occurrence.exec(text)) {
    const start = match.index;
    if (isEscaped(text, start) || isCommented(text, start)) {
      continue;
    }

    const expression = match[1].trim();
    if (FOREIGN_SCOPE.test(expression)) {
      continue;
    }

    const parsed = REFERENCE.exec(expression);
    if (!parsed) {
      continue;
    }

    const value = lookup(vars, parsed[1].replace(/^vars\./, ''));
    if (value === undefined) {
      continue;
    }

    hints.push({ end: start + match[0].length, text: value });
  }

  return hints;
}
