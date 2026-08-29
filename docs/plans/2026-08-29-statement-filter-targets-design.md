# Target-aware statement filters, and honouring them in the var hints

The inline var hints ship showing the *raw* value of a reference, filter or no
filter: `\VAR{N.max | sci}` badges `100000` while the built statement typesets
`10^{5}`. That was
[a deliberate retreat](2026-08-28-vscode-statement-var-hints-design.md) -- the
alternative on the table was porting `scientific_notation` to TypeScript, which
buys a second implementation of a function whose rules are all edge case.

There is a third option, and it is better than either: let rbx render the whole
expression, and teach the filter what it is rendering *for*.

## D1. The target belongs to the filter, not to the caller

`sci` is not a function with one right answer. Its *rules* -- when to abbreviate
at all, when to pull out a multiplier, when to keep a remainder, when to decline
and print the integer -- are a property of the number. Its *formatting* is a
property of the medium:

| medium | `200000 | sci` |
| --- | --- |
| LaTeX (PDF) | `2 \times 10^{5}` |
| a VS Code inlay hint | `2×10⁵` |

Today `add_builtin_filters(j2_env)` installs one flavour, and every environment
gets LaTeX. The change is to pass what the environment is for:

```python
add_builtin_filters(j2_env, target=FilterTarget.LATEX)
```

The rules stay in one place and keep one set of tests; only a small formatter
differs per target. This is the same reasoning that kept the badge from
re-implementing expansion: one source of truth, rendered per consumer.

### Markdown keeps LaTeX, deliberately

An earlier draft of this design called the Markdown environment a bug, on the
grounds that it installs LaTeX-flavoured filters and therefore emits
`2 \times 10^{5}` into a `.md` statement. That is wrong. A Markdown statement
puts its constraints in `$...$` math, rendered by MathJax or KaTeX, so LaTeX is
exactly what belongs there.

`MARKDOWN` is still a distinct target value, mapping to the LaTeX formatter.
Not because it differs today, but because "these two are the same" is a fact
worth being able to change in one line, and because a reader who finds only
`LATEX` and `TEXT` would reasonably wonder which one Markdown got.

## D2. What the TEXT target renders

Superscript digits for the exponent, `×` for the multiplication, and otherwise
identical decisions to LaTeX:

| value | LATEX | TEXT |
| --- | --- | --- |
| `100000 | sci` | `10^{5}` | `10⁵` |
| `200000 | sci` | `2 \times 10^{5}` | `2×10⁵` |
| `10**18 + 7 | rsci` | `10^{18} + 7` | `10¹⁸ + 7` |
| `100007 | sci` | `100007` | `100007` |
| `532 | sci` | `532` | `532` |

`escape` under TEXT is the identity: a badge is not a document, and there is
nothing to escape into. `parent` and `stem` are about paths and do not vary.

The two must agree on every *decision*, and that is testable: the same table
drives both, and a case that abbreviates in one abbreviates in the other.

## D3. Only a filtered reference costs a spawn

The extension already holds a per-package map of expanded vars, one `rbx vars
--json` per package root, invalidated by the manifest watcher. A plain
`\VAR{N.max}` is answered from that map with no process at all, and that is the
overwhelmingly common case.

A *filtered* reference cannot be: `| sci` is Jinja, and evaluating Jinja is
rbx's job. So the split is by reference shape --

- no pipeline: the bulk map, unchanged, instant;
- a pipeline: an expression rbx must render.

which keeps the cost proportional to how much of the statement actually uses
filters, rather than making every reference pay for the few that do.

The scanner already parses the pipeline in order to ignore it. It stops
ignoring it. Root scope still applies: an expression is sent only if it is a
plain dotted name plus a pipeline, so nothing arbitrary is ever handed to a
renderer.

## D4. The command

```
rbx vars --render --target text
```

Expressions arrive on **stdin**, one per line; the result is a JSON object
keyed by the expression, values already rendered:

```json
{"N.max | sci": "10⁵", "A.max | rsci": "2×10⁹ + 7"}
```

Stdin rather than repeated `--render` flags because `|` in an argument is a
quoting trap in every shell, and because a statement with two dozen filtered
references should still be one call.

An expression that fails to render -- an unknown filter, a bad argument, a name
that is not there -- is **absent from the map** rather than an error. The
extension draws no badge for it, which is D5 of the original design unchanged:
absent is never wrong. `rbx vars --render` still exits 0 in that case; a
non-zero exit is reserved for "this package could not be read at all", which is
the signal the extension already treats as "no badges anywhere".

## D5. Caching, and what typing does

Rendered expressions cache per `(package root, expression)`, **including the
ones that failed**. That last part is what makes typing survivable: the moment
a setter types `\VAR{N.max | sc`, that is a syntactically fine expression which
renders to nothing, and without a negative cache every keystroke would spawn a
process to be told so again.

Unresolved expressions from a document are collected and sent in one spawn.
Hints for everything already known render immediately; `onDidChangeInlayHints`
fires when the batch returns, and the ones that resolved appear. The manifest
watcher drops the whole per-root cache, expressions included, since a changed
`vars` block changes what they render to.

## D6. Testing

The load-bearing test is that **LaTeX output does not move**. A table of
`scientific_notation`'s awkward inputs -- `100007` declining, `532` declining,
`0`, negatives, an exact power, a multiplier, a remainder under `rsci` -- is
asserted against its current output, and the same table drives the TEXT target
so the two cannot disagree about a decision while differing in formatting.

Beyond that: the scanner keeps pipelines and still refuses foreign scopes; the
payload parser accepts the render map; and `rbx vars --render` is covered for
the empty-input, unknown-filter and unknown-name cases.
