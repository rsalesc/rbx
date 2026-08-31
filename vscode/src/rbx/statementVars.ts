/**
 * Which `\VAR{...}` references in a statement get a value badge.
 *
 * Pure: no `vscode` import, so `node --test` covers it directly.
 *
 * Two scopes are badged, and both resolve to exactly one value:
 *
 * - *problem-root* references -- `\VAR{N.max}` and `\VAR{vars.N.max}`.
 * - a *statically named group* -- `\VAR{problem.groups.sub1.vars.N.max}`, its
 *   `vars`-less shorthand, and the `problem.groups['sub-1']` form that a group
 *   name holding a dash can only be reached through.
 *
 * A *loop-bound* group reference (`\VAR{g.N.max}` inside `\BLOCK{for g in
 * groups}`) is still not badged, and that is the standing limit rather than an
 * oversight: one source position renders a different value per iteration, so a
 * single badge would have to lie, name a group, or list several. Contest and
 * the rest of the problem scope resolve against var sets this map does not hold.
 * Every one of those, and every expression that is not a plain dotted name,
 * yields no hint: an absent badge is never wrong.
 *
 * See docs/plans/2026-08-28-vscode-statement-var-hints-design.md (D1) and
 * docs/plans/2026-08-31-vscode-group-var-hints-design.md.
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

/**
 * Everything `rbx vars --json --groups` knows about one package.
 *
 * `groups` holds each testcase group's **resolved** set -- the package vars
 * with that group's overrides applied -- not its raw override block. That is
 * the whole point of asking rbx for it: a subtasks table reads the same name
 * for every group, and a group that overrides nothing would answer nothing at
 * all under the raw block. See `statements/context.GroupView`.
 *
 * An rbx too old to know the flag leaves `groups` empty, and every group
 * reference then simply goes unbadged.
 */
export interface VarsPayload {
  readonly vars: Vars;
  readonly groups: Readonly<Record<string, Vars>>;
}

interface VarReference {
  /** Offset just past the reference's closing brace. */
  readonly end: number;
  /**
   * The testcase group this reference resolves against, absent for a root one.
   *
   * Carried for legibility rather than for lookup -- `expression` already
   * spells it -- and so a consumer can tell the two scopes apart without
   * re-parsing a wire key.
   */
  readonly group?: string;
  /**
   * The canonical expression this reference asks for, ready to hand to
   * `rbx vars --render`. Stripped of any `vars.` prefix, respaced around each
   * pipe, and guaranteed to hold no newline -- it crosses to rbx as one line
   * of stdin and comes back as a key, so a newline in it would be a request
   * nothing could answer.
   *
   * A group reference is prefixed with its group and a tab
   * (`sub1\tN.max | sci`), which is the line protocol `rbx vars --render`
   * reads. So this doubles as the render cache key, and the same name under
   * two groups keys twice -- two questions with two answers.
   *
   * Two spellings that differ only in the spacing around a pipe are therefore
   * one cache key -- *except* where the pipeline holds a quote, which
   * `canonicalize` leaves internally verbatim rather than risk rewriting a
   * string argument. `label|default('x|y')` and `label | default('x|y')` are
   * two keys and two renders of the same thing. That is a deliberate trade:
   * a duplicated render costs time, a corrupted expression costs correctness.
   */
  readonly expression: string;
}

/** A bare `\VAR{N.max}`: the bulk vars map already holds its value. */
export interface ResolvedVarHint extends VarReference {
  readonly filtered: false;
  /** The value's display text, verbatim from `rbx vars --json`. */
  readonly text: string;
}

/**
 * A `\VAR{N.max | sci}`: the raw value would be a lie, because the filter is
 * exactly what decides how the statement typesets it. Only `rbx vars --render`
 * can say what this shows, so no text is carried here.
 */
export interface FilteredVarHint extends VarReference {
  readonly filtered: true;
}

/**
 * Two shapes discriminated on `filtered`, rather than one with a `text` that
 * is sometimes there: the two cases are answered from different places -- the
 * map already in hand versus a render -- and this way the compiler, not a
 * comment, is what stops a caller from badging a filtered reference with a
 * value nobody computed.
 */
export type VarHint = ResolvedVarHint | FilteredVarHint;

/**
 * Scopes whose values this map does not hold. See the module comment.
 *
 * The two halves of this list are claimed on different grounds:
 *
 * - `problem`, `contest`, `groups` and `vars` are rbx's own. All four sit in
 *   `RESERVED_STATEMENT_VAR_NAMES` (rbx/box/fields.py), which rejects a
 *   top-level var that would shadow a template namespace key, so no legitimate
 *   root var can ever be spelled `problem.x` or `groups.x`. That makes these
 *   four *redundant today*: the lookup below would miss such a name anyway,
 *   because no payload can contain it. They are kept for legibility -- the
 *   list reads as "the scopes a statement can name" -- and so that relaxing
 *   the reserved list does not quietly turn them into wrong badges. Note that
 *   `problems` is just as reserved and is *not* here, which is the tell that
 *   this list is a readable summary rather than a mirror of that frozenset.
 * - `g` and `p` are only *conventional* -- the aliases a template author
 *   happens to bind in `\BLOCK{for g in groups}`. rbx reserves neither, so a
 *   root var genuinely named `g` is legal and `\VAR{g.max}` would then lose a
 *   badge it could have had. That is a deliberate false negative: badging a
 *   loop variable with a root value would be a lie, and under D5 an absent
 *   badge is never wrong.
 */
const FOREIGN_SCOPE = /^(vars\.)?(g|p|problem|contest|groups)\./;

/**
 * A reference into one statically named testcase group, and the rest of it.
 *
 * Tried *before* `FOREIGN_SCOPE`, which claims the whole `problem.` prefix:
 * this is the one corner of that scope whose values the payload holds, and the
 * relaxation is deliberately this narrow. `problem.title` and `problem.params.x`
 * come from a resolved statement, which `rbx vars` never loads.
 *
 * Anchored on `problem.groups` and nothing shorter, because a problem statement
 * has no top-level `groups`: `context.problem_jinja_kwargs` lifts only `vars`,
 * and `groups` lives solely inside `problem.namespace()`.
 *
 * Both spellings, because the dotted one is not always available.
 * `fields.NameField` permits `^[a-zA-Z0-9][a-zA-Z0-9\-_]*$`, so `sub-1` and
 * `1st` are legal group names that Jinja can only reach as
 * `problem.groups['sub-1']` -- supporting only the dot would quietly unbadge
 * every package that names its groups that way. `JinjaGroupsGetter` serves
 * both, so both are real.
 *
 * The quote is backreferenced so `'x"` is not read as a name, and the name
 * itself is matched against the same character class rbx enforces rather than
 * `[^'"]*`: a payload lookup would turn away anything else anyway, and keeping
 * the class here means the regex says what a group name *is*.
 */
const GROUP_REFERENCE =
  /^problem\.groups(?:\.([A-Za-z0-9][\w-]*)|\[\s*(['"])([A-Za-z0-9][\w-]*)\2\s*\])\.([^]*)$/;

/** A reference split into the scope it names and the expression within it. */
interface ScopedReference {
  /** Absent for a root reference. */
  readonly group?: string;
  /** What follows the scope: a dotted name and an optional filter pipeline. */
  readonly rest: string;
}

/**
 * Which var set `inner` asks about, or `undefined` for a scope with no answer.
 *
 * Group first, then the foreign-scope guard, then root. The order is what makes
 * the narrow relaxation safe: `problem.groups.sub1.N.max` is claimed here
 * before `FOREIGN_SCOPE` can reject it for its `problem.` prefix, and every
 * other `problem.` spelling still falls through to that rejection.
 */
function classify(inner: string): ScopedReference | undefined {
  const grouped = GROUP_REFERENCE.exec(inner);
  if (grouped) {
    // One of the two name groups matched; the other is undefined.
    return { group: grouped[1] ?? grouped[3], rest: grouped[4] };
  }
  return FOREIGN_SCOPE.test(inner) ? undefined : { rest: inner };
}

/**
 * A plain dotted name, and the filter pipeline it is piped through, if any.
 *
 * Anchored at both ends and matched against the *trimmed* expression, so a
 * leading `\s*` would be dead and is not here. The `\s*` between the two groups
 * is load bearing: it absorbs the space before the pipe in `N.max | sci`.
 *
 * The pipeline's `[^}]*` can never actually meet a `}` -- `OCCURRENCE` stopped
 * at the first one -- but it is kept over `.*` because it also matches a
 * newline, and a filter pipeline may well be wrapped across lines. Everything
 * else a pipeline may hold rides along in it: further stages, and filter
 * arguments such as `sci(9)` or `default('x')`.
 */
const REFERENCE = /^([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*(\|[^}]*)?$/;

/**
 * One `\VAR{...}` reference and the expression inside it.
 *
 * `[^}]*` stops at the first closing brace, so a reference holding a `}` (a
 * dict literal, say) is not matched as a whole and simply gets no badge. It
 * spans newlines, which `.` would not.
 */
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
 * The comment syntaxes a statement can use open with a percent -- LaTeX's `%`
 * and rbxTeX's Jinja line comment `%#` -- and both run to the end of the line,
 * so one unescaped percent earlier on the line is enough. `\%` is a literal
 * percent and opens nothing; `\\%` is a literal backslash and then a comment,
 * hence the parity check.
 *
 * This is a heuristic, not a parse, and it errs toward silence in both known
 * directions. A Jinja *line statement* opens with `%-`
 * (`line_statement_prefix`, rbx/box/statements/latex_jinja.py), which is not a
 * comment, yet a `\VAR{...}` on such a line is treated as commented and loses
 * its badge. A literal percent inside `\verb|%|` or a verbatim environment
 * likewise suppresses a legitimate hint on the rest of that line. Both are
 * missing badges rather than wrong ones, which D5 allows.
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

/** The resolved set of `group`, or `undefined` if the payload has no such group. */
function varsForGroup(payload: VarsPayload, group: string): Vars | undefined {
  // Own-property only, for the reason `lookup` gives: a group cannot be named
  // `constructor` (`fields.NameField` would allow it, but the payload is built
  // from the declared groups), and reading one off `Object.prototype` would be
  // a var set that is not a var set.
  return Object.hasOwn(payload.groups, group) ? payload.groups[group] : undefined;
}

/** The value `name` holds, or `undefined` if the map does not hold it. */
function lookup(vars: Vars, name: string): string | undefined {
  // Own-property only: a name like `constructor` or `toString` is a typo, not
  // a var, and must not resolve to whatever `Object.prototype` carries.
  return Object.hasOwn(vars, name) ? vars[name] : undefined;
}

/**
 * One canonical spelling of `name | pipeline`, or `undefined` for a pipeline
 * this scanner refuses to ask rbx about.
 *
 * The spelling exists so that `N.max|sci`, `N.max | sci` and a pipeline
 * wrapped across lines are one cache key rather than three renders of the same
 * thing. Only the whitespace *around* each pipe is rewritten; whitespace inside
 * a filter's arguments is left as written, because collapsing it could change
 * what a string argument means, and the worst it costs is a second cache entry
 * for `sci( 9 )` beside `sci(9)`.
 *
 * A pipeline holding a quote is left internally verbatim -- a `|` inside a
 * string argument is a literal, and respacing it would corrupt the expression
 * the renderer is handed. Only the single space joining the name to the first
 * pipe is imposed there, so `label|default('x|y')` canonicalizes to
 * `label |default('x|y')` and keys separately from `label | default('x|y')`.
 *
 * Two pipelines are refused outright:
 *
 * - one with an empty stage (`N.max |`, the state of every half-typed filter,
 *   and `N.max ||sci`). Neither is a Jinja expression, so the render could only
 *   fail, and rejecting them here also spares the caller a double space that
 *   respacing `||` would otherwise produce. The check splits on `|`, which is
 *   only unambiguous when no quote is present, so a quoted pipeline skips it --
 *   at worst one wasted render for something like `N.max | 'x' |`.
 * - one whose canonical form still holds a newline. Expressions cross to
 *   `rbx vars --render` one per line of stdin and come back as the keys of its
 *   reply, so a newline would split one request into two unanswerable ones.
 *   Respacing launders the newline in `N.max\n | sci`, but not the one in
 *   `sci(9,\n 3)` or in any quoted pipeline, which is exactly why the check is
 *   made on the finished expression rather than trusted to the respacing.
 */
function canonicalize(name: string, pipeline: string | undefined): string | undefined {
  if (pipeline === undefined) {
    return name;
  }
  const stages = pipeline.trim();
  const quoted = /['"]/.test(stages);
  if (!quoted && stages.split('|').some((stage, index) => index > 0 && stage.trim() === '')) {
    return undefined;
  }
  const spaced = quoted ? stages : stages.replace(/\s*\|\s*/g, ' | ').trim();
  const expression = `${name} ${spaced}`;
  return expression.includes('\n') ? undefined : expression;
}

export function scanStatementVars(text: string, payload: VarsPayload): VarHint[] {
  const hints: VarHint[] = [];
  // A fresh regex per scan: a `/g` one carries `lastIndex` between calls, so
  // sharing the constant would leak where the previous scan stopped.
  const occurrence = new RegExp(OCCURRENCE);

  for (let match = occurrence.exec(text); match; match = occurrence.exec(text)) {
    const start = match.index;
    if (isEscaped(text, start) || isCommented(text, start)) {
      continue;
    }

    const inner = match[1].trim();
    const scoped = classify(inner);
    if (scoped === undefined) {
      continue;
    }

    // A group the payload does not hold -- renamed, deleted, or one an rbx too
    // old for `--groups` never reported. Resolving it against the root set
    // instead would badge the package value under a group that no longer
    // carries it, which is precisely the confident lie D5 forbids.
    const vars =
      scoped.group === undefined ? payload.vars : varsForGroup(payload, scoped.group);
    if (vars === undefined) {
      continue;
    }

    const parsed = REFERENCE.exec(scoped.rest.trim());
    if (!parsed) {
      continue;
    }

    // The prefix is dropped from the expression too, not just from the lookup:
    // rbx's renderer resolves `N.max` and `vars.N.max` alike, so the shorter
    // spelling is a stable key both forms of the reference can share.
    const name = parsed[1].replace(/^vars\./, '');
    const pipeline = parsed[2];

    // The name is checked against the map even when a pipeline follows. The
    // base of a filtered reference is the value being filtered, so a name the
    // map does not hold is as hopeless here as it is bare -- rendering it would
    // spend a process to learn that a typo is a typo. It does cost the odd
    // legitimate badge (`\VAR{x | default(5)}` over an undefined `x`, or a name
    // bound by a `\BLOCK{set}` in the template), which is the side D5 says to
    // err on, and which a bare reference to such a name already loses.
    const value = lookup(vars, name);
    if (value === undefined) {
      continue;
    }

    // A pipeline `canonicalize` refuses yields no hint at all, rather than a
    // bare-name hint: the badge would then show the unfiltered value, which is
    // the very lie this scanner reports the pipeline to avoid.
    const canonical = canonicalize(name, pipeline);
    if (canonical === undefined) {
      continue;
    }
    // The wire key, which is also the line `rbx vars --render` reads. A root
    // reference keeps the bare expression, so the protocol from before groups
    // were addressable is exactly the subset it was.
    const expression =
      scoped.group === undefined ? canonical : `${scoped.group}\t${canonical}`;
    const scope = scoped.group === undefined ? {} : { group: scoped.group };

    const end = start + match[0].length;
    hints.push(
      pipeline === undefined
        ? { end, ...scope, expression, filtered: false, text: value }
        : { end, ...scope, expression, filtered: true },
    );
  }

  return hints;
}
