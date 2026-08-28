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

/** A var value, as `rbx vars --json` emits it. */
export type VarValue = number | boolean | string;

/** The expanded package vars, keyed by dotted name. */
export type Vars = Readonly<Record<string, VarValue>>;

export interface VarHint {
  /** Offset just past the reference's closing brace. */
  readonly end: number;
  /** The value, rendered for display. */
  readonly text: string;
}

/**
 * Scopes whose values this map does not hold. See the module comment.
 *
 * Safe to claim these names outright: rbx rejects a top-level var that collides
 * with a template namespace key (`vars`, `problem`, `contest`, `groups`, ...),
 * so no legitimate root var can be spelled `problem.x` or `groups.x`. The short
 * aliases `g` and `p` are the loop and problem bindings the templates use.
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

function render(value: VarValue): string {
  return typeof value === 'string' ? value : String(value);
}

/** The value `name` holds, or `undefined` if the map does not hold it. */
function lookup(vars: Vars, name: string): VarValue | undefined {
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

    hints.push({ end: start + match[0].length, text: render(value) });
  }

  return hints;
}
