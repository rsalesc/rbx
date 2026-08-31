import * as assert from 'assert';
import { test } from 'node:test';

import { scanStatementVars, Vars, VarsPayload } from './statementVars';

/**
 * The foreign-scope keys are deliberately *resolvable*, so that the scope
 * guard is what turns them away rather than the lookup -- otherwise the guard
 * would be untestable.
 *
 * Only the `g.` and `p.` keys are reachable in a real payload: a nested var
 * block named `g` really does flatten to `g.N.max` in `rbx vars --json`. The
 * `problem.`/`contest.`/`groups.`/`vars.problem.` ones cannot occur, because
 * those roots sit in `RESERVED_STATEMENT_VAR_NAMES`; they are here purely to
 * prove the GUARD rejects them, not to stand in for anything rbx could emit.
 *
 * Values are strings because that is what `rbx vars --json` emits -- see the
 * `Vars` doc comment.
 */
const VARS: Vars = {
  'N.max': '100000',
  'A.max': '1000000000',
  'BIG.max': '1000000000000000007',
  flag: 'True',
  label: 'foo',
  g: '3',
  'g.N.max': '7',
  'groups.g.vars.N.max': '7',
  'p.N.max': '7',
  'problem.N.max': '7',
  'contest.year': '7',
  'vars.problem.N.max': '7',
};

/**
 * Two groups whose sets differ from the root one and from each other, plus a
 * name only reachable through the bracket form.
 *
 * `sub1` overrides `N.max` and inherits `A.max`, which is the pairing that
 * makes a badge worth drawing at all: the extension resolves against the
 * group's *resolved* set, so the inherited name has to answer here exactly as
 * the overridden one does.
 */
const GROUPS: Readonly<Record<string, Vars>> = {
  sub1: { 'N.max': '10', 'A.max': '1000000000' },
  sub2: { 'N.max': '1000', 'A.max': '1000000000' },
  // A legal group name (`fields.NameField` allows dashes and a leading digit)
  // that Jinja cannot reach with a dot.
  'sub-3': { 'N.max': '100000', 'A.max': '1000000000' },
};

const PAYLOAD: VarsPayload = { vars: VARS, groups: GROUPS };

const scan = (text: string) => scanStatementVars(text, PAYLOAD);

/**
 * The badge texts of a scan, a filtered reference contributing none.
 *
 * `VarHint` carries `text` only on its unfiltered arm, so this narrows once
 * here rather than at every assertion. A reference that unexpectedly turned
 * filtered shows up as a missing text, which is what these tests watch for.
 */
const texts = (source: string) =>
  scan(source).flatMap((hint) => (hint.filtered ? [] : [hint.text]));

test('the shorthand and the long form both resolve', () => {
  assert.deepStrictEqual(scan('$N \\le \\VAR{N.max}$'), [
    { end: 18, expression: 'N.max', filtered: false, text: '100000' },
  ]);
  assert.deepStrictEqual(
    texts('$N \\le \\VAR{vars.N.max}$'),
    ['100000'],
  );
});

test('an unfiltered reference carries the expression it was resolved from', () => {
  assert.deepStrictEqual(scan('$N \\le \\VAR{vars.N.max}$'), [
    { end: 23, expression: 'N.max', filtered: false, text: '100000' },
  ]);
});

test('a filtered reference is reported without a value, for rendering', () => {
  // The raw value would be a lie under a filter: `sci` typesets `100000` as
  // `10^{5}`. The caller renders `expression` instead of badging `text`.
  assert.deepStrictEqual(scan('\\VAR{N.max | sci}'), [
    { end: 17, expression: 'N.max | sci', filtered: true },
  ]);
});

test('the same pipeline spelled differently is one expression', () => {
  const spellings = [
    '\\VAR{N.max|sci}',
    '\\VAR{N.max | sci}',
    '\\VAR{N.max |sci}',
    '\\VAR{N.max| sci}',
    '\\VAR{  N.max   |   sci  }',
    '\\VAR{N.max\n | sci}',
  ];
  for (const text of spellings) {
    assert.deepStrictEqual(
      scan(text).map((hint) => hint.expression),
      ['N.max | sci'],
      text,
    );
  }
});

test('the `vars.` prefix is dropped from the expression too', () => {
  // rbx's renderer accepts both spellings, so dropping the prefix costs
  // nothing and lets the two share one cache entry.
  assert.deepStrictEqual(
    scan('\\VAR{vars.N.max | sci}').map((hint) => hint.expression),
    ['N.max | sci'],
  );
});

test('a multi-stage pipeline is captured whole', () => {
  assert.deepStrictEqual(
    scan('\\VAR{N.max|sci|upper}').map((hint) => hint.expression),
    ['N.max | sci | upper'],
  );
});

test('filter arguments survive', () => {
  assert.deepStrictEqual(
    scan("\\VAR{N.max | sci(9)} \\VAR{label | default('x|y')}").map((hint) => hint.expression),
    ['N.max | sci(9)', "label | default('x|y')"],
  );
});

test('a quoted pipeline keys on itself, spacing and all', () => {
  // The documented exception to one-spelling-one-key: respacing a pipeline
  // that holds a quote could rewrite a string argument, so only the space
  // before the first pipe is imposed and the rest stands as written. Two
  // spellings, two renders of the same thing -- time, not correctness.
  assert.deepStrictEqual(
    scan("\\VAR{label|default('x|y')} \\VAR{label |   default('x|y')}").map(
      (hint) => hint.expression,
    ),
    ["label |default('x|y')", "label |   default('x|y')"],
  );
});

test('an expression that would still hold a newline gets no hint', () => {
  // Expressions cross to `rbx vars --render` one per line of stdin and come
  // back as the keys of its reply, so a newline would split one request into
  // two that nothing can answer. Respacing launders the newline around a pipe,
  // but not one inside an argument or anywhere in a quoted pipeline.
  for (const text of ["\\VAR{label | default('x')\n | upper}", '\\VAR{N.max | sci(9,\n 3)}']) {
    assert.deepStrictEqual(scan(text), [], text);
  }
});

test('a pipeline with an empty stage gets no hint', () => {
  // `N.max |` is what every half-typed filter looks like, and neither it nor
  // `N.max ||sci` is an expression rbx could render.
  for (const text of ['\\VAR{N.max |}', '\\VAR{N.max ||sci}', '\\VAR{N.max | | sci}']) {
    assert.deepStrictEqual(scan(text), [], text);
  }
});

test('a pipeline over an unknown name gets no hint either', () => {
  // The base of a filtered reference is the very value being rendered, so a
  // name the map does not hold is as hopeless here as it is unfiltered -- and
  // rendering it would cost a process to find that out.
  assert.deepStrictEqual(scan('\\VAR{N.mx | sci}'), []);
});

test('several references on one line each get a hint', () => {
  assert.deepStrictEqual(
    texts('$\\VAR{N.max}$ and $\\VAR{A.max}$'),
    ['100000', '1000000000'],
  );
});

test('non-root scopes are left alone', () => {
  for (const expression of [
    'g.N.max',
    'groups.g.vars.N.max',
    'p.N.max',
    'problem.N.max',
    'contest.year',
    'vars.problem.N.max',
  ]) {
    assert.deepStrictEqual(scan(`\\VAR{${expression}}`), [], expression);
  }
});

test('expressions that are not a plain name are left alone', () => {
  for (const expression of ['N.max + 1', 'len(x)', "N.max if x else 'y'", '']) {
    assert.deepStrictEqual(scan(`\\VAR{${expression}}`), [], expression);
  }
});

test('an unknown name gets no hint, which is how a typo shows up', () => {
  assert.deepStrictEqual(scan('\\VAR{N.mx}'), []);
});

test('a name inherited from Object.prototype is not a var', () => {
  for (const expression of ['constructor', 'toString', 'hasOwnProperty']) {
    assert.deepStrictEqual(scan(`\\VAR{${expression}}`), [], expression);
  }
});

test('a commented line is skipped', () => {
  assert.deepStrictEqual(scan('%# $\\VAR{N.max}$'), []);
  assert.deepStrictEqual(scan('  % $\\VAR{N.max}$'), []);
});

test('a comment opened mid-line is skipped too', () => {
  assert.deepStrictEqual(scan('$N$ is bounded. % TODO: \\VAR{N.max}'), []);
});

test('an escaped percent does not open a comment', () => {
  assert.deepStrictEqual(
    texts('50\\% of \\VAR{N.max}'),
    ['100000'],
  );
  // A literal backslash before the percent: the percent is a real comment.
  assert.deepStrictEqual(scan('a \\\\% b \\VAR{N.max}'), []);
});

test('an escaped VAR is not a reference', () => {
  assert.deepStrictEqual(scan('\\\\VAR{N.max}'), []);
  // ...but a literal backslash followed by a real reference still is.
  assert.deepStrictEqual(
    texts('\\\\\\VAR{N.max}'),
    ['100000'],
  );
});

test('non-numeric values are shown verbatim', () => {
  assert.deepStrictEqual(
    texts('\\VAR{flag} \\VAR{label}'),
    ['True', 'foo'],
  );
});

test('an integer too large for a double keeps every digit', () => {
  // The reason values cross as strings at all: as a JSON number this would
  // come back from `JSON.parse` as 1000000000000000000, and the badge would
  // confidently show a bound the statement does not have.
  assert.deepStrictEqual(
    texts('$N \\le \\VAR{BIG.max}$'),
    ['1000000000000000007'],
  );
});

test('a root var named exactly `g` still resolves', () => {
  // FOREIGN_SCOPE only claims `g.`, with the dot: `g` alone is an ordinary
  // root var, and refusing it would cost a badge for nothing.
  assert.deepStrictEqual(
    texts('\\VAR{g}'),
    ['3'],
  );
});

test('a reference wrapped across a newline still resolves', () => {
  // `[^}]*` spans newlines, while `isCommented` only inspects the line the
  // reference opens on.
  assert.deepStrictEqual(
    scan('$N \\le \\VAR{N.max\n | sci}$').map((hint) => hint.expression),
    ['N.max | sci'],
  );
});

test('the hint sits just after the closing brace', () => {
  const text = 'abc \\VAR{N.max} def';
  const [hint] = scan(text);
  assert.strictEqual(text[hint.end - 1], '}');
});

test('offsets are absolute across lines, and a comment ends at its newline', () => {
  const text = '% $\\VAR{A.max}$\n$N \\le \\VAR{N.max}$\n';
  const hints = scan(text);
  assert.deepStrictEqual(texts(text), ['100000']);
  assert.strictEqual(text.slice(hints[0].end - 6, hints[0].end), 'N.max}');
});

test('scanning is repeatable, so no regex state leaks between calls', () => {
  const text = '\\VAR{N.max} \\VAR{A.max}';
  assert.deepStrictEqual(scan(text), scan(text));
});

test('a statically named group resolves against that group', () => {
  assert.deepStrictEqual(scan('$N \\le \\VAR{problem.groups.sub1.vars.N.max}$'), [
    {
      end: 43,
      expression: 'sub1\tN.max',
      filtered: false,
      group: 'sub1',
      text: '10',
    },
  ]);
});

test('the group shorthand keys the same as the long form', () => {
  // `g.N.max` is shorthand for `g.vars.N.max` (#630), and both spellings share
  // one wire key: rbx resolves them identically, so the shorter one is what
  // crosses and one render answers both.
  const shorthand = scan('\\VAR{problem.groups.sub2.N.max}');
  const longForm = scan('\\VAR{problem.groups.sub2.vars.N.max}');
  assert.deepStrictEqual(texts('\\VAR{problem.groups.sub2.N.max}'), ['1000']);
  assert.strictEqual(shorthand[0].expression, 'sub2\tN.max');
  assert.strictEqual(longForm[0].expression, 'sub2\tN.max');
});

test('a group reaches its inherited names, not only its overrides', () => {
  // The payload carries each group's *resolved* set, so a name no group
  // overrides badges the package value rather than nothing at all.
  assert.deepStrictEqual(texts('\\VAR{problem.groups.sub1.A.max}'), ['1000000000']);
});

test('the bracket form reaches a group a dot cannot', () => {
  // `sub-3` is a legal group name and `problem.groups.sub-3.N.max` is not a
  // Jinja expression, so the quoted form is the only spelling a statement can
  // use -- and dropping it would silently unbadge whole packages.
  assert.deepStrictEqual(texts("\\VAR{problem.groups['sub-3'].vars.N.max}"), ['100000']);
  assert.deepStrictEqual(texts('\\VAR{problem.groups["sub-3"].N.max}'), ['100000']);
});

test('a filtered group reference carries the group on its wire key', () => {
  assert.deepStrictEqual(
    scan('\\VAR{problem.groups.sub1.N.max | sci}').map((hint) => hint.expression),
    ['sub1\tN.max | sci'],
  );
});

test('a group the payload does not hold is left alone', () => {
  // A renamed or deleted group. The badge would otherwise have to come from
  // the root set, which is the wrong number under the old name.
  assert.deepStrictEqual(scan('\\VAR{problem.groups.nosuch.N.max}'), []);
});

test('a name absent from a group is left alone', () => {
  // `flag` is a root var and no group carries it; the group scope answers only
  // out of its own resolved set.
  assert.deepStrictEqual(scan('\\VAR{problem.groups.sub1.flag}'), []);
});

test('a group model field is left alone', () => {
  // `problem.groups.sub1.name` is the *model* field, and `GroupView` gives it
  // precedence over the var shorthand. No var can be called `name`
  // (RESERVED_STATEMENT_VAR_NAMES), so the lookup misses and nothing is drawn.
  assert.deepStrictEqual(scan('\\VAR{problem.groups.sub1.name}'), []);
});

test('the rest of the problem scope stays foreign', () => {
  // Only `problem.groups.<name>` is admitted: everything else under `problem`
  // is answered by a resolved statement, which `rbx vars` deliberately never
  // loads.
  for (const expression of [
    'problem.title',
    'problem.params.foo',
    'problem.groups',
    'problem.groups.sub1',
    'p.groups.sub1.N.max',
    'g.N.max',
  ]) {
    assert.deepStrictEqual(scan(`\\VAR{${expression}}`), [], expression);
  }
});
