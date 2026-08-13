# MOJ markdown statements — design

Stacked on #640 (`refactor(statements): extract a reusable statement export
bundle`). That PR extracted `rbx/box/statements/export.py` and shipped
`SubtreeLayout` with **no production consumer**, naming the MOJ statement
packager as the intended first one. This is that consumer.

Today `MojPackager.statement_types()` returns `[]` and a dummy
`docs/enunciado.md` is written instead. This design replaces the dummy with the
real statement, converted to Markdown, with assets placed where MOJ can resolve
them.

## 1. What MOJ actually does with a statement

Everything below is read from `cd-moj/mojtools` (`render-statement.sh`,
`gen-problem-json.sh`, `validate-problem.sh`), not inferred.

**The renderer is pandoc.** `render-statement.sh` is the single source of
statement rendering — the editor's *Pré-visualizar*, `gen-problem-json.sh` and
`validate-problem.sh` all call it, so "what you preview is what the student
sees". It runs:

```
pandoc -f markdown --mathml -s --embed-resources --resource-path=<dir of enunciado> …
```

Consequences that shape every decision here:

- **The consumer is pandoc.** Producing pandoc-flavored Markdown is not a
  liability, it is the target dialect. Fenced divs, grid tables and attribute
  spans all round-trip.
- **Math is free.** `$…$` survives to MathML; nothing needs converting.
- **Images are base64-embedded**, resolved against `--resource-path`. A
  reference must be relative to that directory, and its *format* must be one a
  browser renders.
- The statement may be `docs/enunciado.{md,org,tex}`.

**Sample notes are a separate document root.** The current format is
`docs/notes/<sample>.md`, one file per test, paired **by name** (the legacy
`docs/sample-notes.json` is by index). `gen-problem-json.sh` renders each with:

```
pandoc -f markdown -t html --embed-resources --resource-path="$PKG/docs"
```

Note the resource path: **`docs/`, not `docs/notes/`**, even though the note
file lives in `docs/notes/`. A note's image reference resolves against `docs/`.
This is load-bearing and looks like a bug at the call site, so it gets a comment
and a test.

**The release gate.** `validate-problem.sh` hard-requires headings matched from
the **raw file text** as `^\s*#{1,3}\s*(entrada|input)` and
`…(saída|saida|output)`. It soft-warns (`render_warnings`) on an
`## Exemplos`-style heading or any ``` fence — MOJ injects the examples itself
from `tests/input/sample*` — and on a note with no matching sample.

**The title comes from the field**, not the document: `render-statement.sh`
injects `<h1>` from `display_title` and strips a legacy `% Title` first line. So
rbx must emit no title.

## 2. Rejected: ship `docs/enunciado.tex`

MOJ accepts `.tex` and would run `pandoc -f latex` on it, which would make this
whole PR a file copy. It does not work: the mandatory `## Entrada`/`## Saída`
check greps **markdown headings out of the raw source**, so a `.tex` statement
can never pass the release gate regardless of how well it renders.

## 3. Converter: pandoc, via pypandoc

`pypandoc` is already a hard rbx dependency (`md_blocks_to_rbxtex`, the plain-md
PDF path), so this adds no package — it only widens who needs the pandoc binary,
which §4 makes an explicit, diagnosable requirement.

The input is not arbitrary LaTeX. `get_processed_statement_blocks(normalize=True)`
has already reduced it to the **Polygon TeX subset** — a closed set of ~25
commands and 6 environments (`PolygonTeXConfig.allowed_commands`, mirroring the
[official manual](https://polygon.codeforces.com/docs/statements-tex-manual)),
with unrestricted MathJax inside `$…$`.

The whole subset was run through `pandoc -f latex -t markdown` and round-tripped
back to HTML the way MOJ does. It survives: `\multicolumn` becomes a grid table
with a real `colspan`, `\sout`/`\textsc`/`\underline`/`\epigraph` map to
attribute spans and divs pandoc reads back, tabular alignment is preserved, and
`\includegraphics` keeps its relative path. `lstlisting` becomes an *indented*
code block, so it does not trip the fence warning.

A hand-written TexSoup converter was considered and rejected: it would
reimplement tabular (alignment specs, `\multicolumn`/`\multirow`/`\hline`/
`\cline`), nested lists, `\verb` delimiters and paragraph rules — several hundred
lines with a long tail — to produce worse output than the tool the judge itself
runs.

### Two defects that must be corrected, not shipped

1. **Phantom figure captions.** Pandoc's LaTeX reader emits `![image](f.png)`,
   and non-empty alt text triggers `implicit_figures` on MOJ's side, captioning
   every figure "image". The alt is cleared via a pandoc **JSON-AST** pass
   (`-t json` → clear `Image` alt → `-f json -t markdown`) rather than a regex,
   which also gives later fixes a home.
2. **Gate leakage.** A converted block containing a fence or an
   `## Exemplos`-style heading would trip `render_warnings`. Packaging fails with
   the offending block named, rather than shipping a package that warns.

## 4. External tool registry — `rbx/tooling.py` (new)

rbx shells out to several tools with no shared story: `latex.py` does an inline
`command_exists('pdflatex')` plus an ad-hoc console error, `install_tex_packages`
silently no-ops when `texliveonfly` is absent, and pypandoc raises a bare
`OSError` when pandoc is missing. This PR adds a third such tool, so it
generalizes the pattern instead.

```python
@dataclasses.dataclass(frozen=True)
class ExternalTool:
    name: str                       # 'poppler'
    executable: str                 # 'pdftoppm'
    probe_flags: List[str]          # ['-v']
    purpose: str                    # why rbx needs it, shown on failure
    install_hints: Dict[str, str]   # platform -> command

    def is_available(self) -> bool: ...
    def ensure(self) -> None: ...   # actionable console error + typer.Exit
    def run(self, args, **kwargs) -> subprocess.CompletedProcess: ...
```

`ensure()` prints the purpose and the install command for the running platform
(`brew install poppler` / `apt install poppler-utils` / …) — the explanation
lives on the tool, the way `Removed()` field hints live on the field.

Registered: `PDFLATEX`, `TEXLIVEONFLY`, `PANDOC`, `PDFTOPPM`. All four call sites
migrate, so the registry is the single pattern from the start rather than a
fourth one.

## 5. Statement selection

- `statement_types()` → `[StatementType.rbxTeX]`, and `statement_export_params()`
  forces externalize + demacro exactly as `PolygonPackager` does, so
  `blocks.sub.yml` and `macros.json` exist for the export pipeline to read.
- `rbx package moj --language <lang>`, mirroring `rbx package polygon
  --language`. It defaults to the topmost statement, and `display_title`
  resolves from **the same** statement, so the rendered `<h1>` and the body can
  never come from different languages.
- A package with no statements keeps today's `DUMMY_STATEMENT` fallback: MOJ
  requires the two headings, and a statement-less package must still package.

## 6. Layout and the `docs/` remap base

```
docs/enunciado.md              body
docs/notes/sample001.md        per-sample explanations, paired by test name
docs/assets/…                  statement-scope assets
docs/samples/{index}/…         sample-scope assets
```

`SubtreeLayout` is configured with `document_dirs['body'] = 'docs'` and
`document_dirs['sample_explanation'] = 'docs'` — **constant**, because that is
what mojtools passes as `--resource-path` for notes (§1). The note *file* still
lives in `docs/notes/`; only the remap base differs.

### This requires relaxing a constraint in #640

`SubtreeLayout` currently **requires** an `{index}` placeholder in
`document_dirs['sample_explanation']` and rejects a constant — so the layout, as
shipped, cannot express its own intended first consumer.

The rule's stated rationale is that entries from different samples would
otherwise "collide into one path". That holds for `asset_roots[SAMPLE]`, where
many files land in the directory, and it stays required there. It does not hold
for `document_dir`, which is only the **base a remap is computed against**: two
samples sharing `docs/` derive identical references for shared statement-scope
assets (correct — it is the same file) and distinct ones for their own
sample-scope assets, which live under `docs/samples/{index}/`.

So `{index}` becomes **optional** for the document slot: still permitted, still
rejected on slots that have no index, still required for `asset_roots[SAMPLE]`.
The change lands here rather than in #640 so that PR stays mergeable as reviewed,
with the MOJ case as its motivating test.

## 7. PDF assets

MOJ renders to HTML and base64-embeds. An `<img src="fig.pdf">` is broken in
every browser, and rbx's TikZ externalization produces exactly that. rbx has no
rasterizer today and PyMuPDF is AGPL, incompatible with rbx's Apache-2.0.

`pdftoppm` (poppler) is shelled out to through the §4 registry:

- A layout wrapper maps a `.pdf` placement to `.png`, so the derived remap
  already points at the rasterized name. Extension mangling is an existing
  layout concern (`keep_extension`), so this is in-idiom rather than a special
  case bolted onto the packager.
- A post-`materialize()` pass converts each placed PDF with
  `pdftoppm -png -r 300 -singlefile`.
- Poppler absent → **packaging refuses**, listing the figures that need it. This
  follows the rule the MOJ packager already lives by: refuse rather than ship
  something that breaks on the judge.

SVG passes through untouched — pandoc embeds it fine.

## 8. Known limitation, documented not fixed

`gen-problem-json.sh` renders sample notes **without** `--mathml`, unlike the
body. Math inside an explanation therefore reaches the student as literal
`\(x\)`. Nothing in the package can fix this; rbx warns when a note contains
math, and it is reported upstream.

## 9. Testing

- **Unit.** Golden files for each subset construct through the converter (pandoc
  version floor pinned; goldens catch drift), heading assembly per language, note
  file naming against `naming.py`, alt-text clearing, the gate guard, and the
  constant-`docs/` remap for both slots.
- **Rasterization.** PDF → PNG placement and reference rewriting, plus the
  refusal path with poppler stubbed absent.
- **End-to-end against the real judge tooling.** Package a fixture carrying an
  image and a sample explanation, then run mojtools' actual
  `render-statement.sh` and `validate-problem.sh` over the output when
  `MOJTOOLS_DIR` is set (skipped otherwise), asserting `secao_entrada`,
  `secao_saida` and `html_builds` pass with **empty** `render_warnings`. This is
  the check that matters: it exercises the same renderer the student sees.
