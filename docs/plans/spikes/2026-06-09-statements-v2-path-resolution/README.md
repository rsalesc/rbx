# Spike S1 — LaTeX path-resolution proof (statements v2)

Issue: [#557](https://github.com/rsalesc/rbx/issues/557) · Design: `docs/plans/2026-06-09-statements-v2-design.md` §6

**Status: ✅ validated.** The design's overlay + `\subimport` model compiles
end-to-end with **no** `\graphicspath` / `TEXINPUTS` tweaks. §6.4's verbatim
nuance holds exactly as written: I/O must be **root-relative**, content
**import-base-relative**.

This is a throwaway proof — **no product code**. It is committed only so the
result is reproducible and reviewable.

## What it reproduces

The harder of the two layouts — the **contest join** (design §6.2): one contest
root that `\subimport`s two isolated problems, each `\subimport`ing a sample
explanation. (Standalone §6.1 is a strict subset: one problem, merged overlay.)

```
.                                   # overlay ROOT — pdflatex runs here
├── contest.tex                     # joining doc: \usepackage{icpc}, \includegraphics{logo}, \subimport each problem
├── icpc.sty                        # "contest chrome" package (defines \example via \VerbatimInput)
├── logo.png                        # root chrome image
└── .problems/
    ├── A/statements/
    │   ├── statement.tex           # fragment: \includegraphics{fig}; \example{ROOT-REL in}{ROOT-REL out}; \subimport sample
    │   ├── fig.png                 # A's asset (red)
    │   └── .samples/000/
    │       ├── in  out             # printed via root-relative \VerbatimInput
    │       ├── explanation.tex     # \includegraphics{sample-fig} — base-relative to THIS folder
    │       └── sample-fig.png      # green
    └── B/statements/
        ├── statement.tex
        ├── fig.png                 # SAME NAME as A's (purple) — must not collide
        └── .samples/000/{in,out,explanation.tex}
```

`fig.png` is intentionally duplicated (A red / B purple) to prove `\subimport`
isolation keeps same-named assets apart across problems.

## Run it

```bash
python3 gen_pngs.py          # writes the placeholder PNGs (stdlib only, no Pillow)
pdflatex -interaction=nonstopmode -halt-on-error contest.tex
```

Requires `import.sty` + `fancyvrb.sty` (both in a standard TeX Live). Produces a
1-page `contest.pdf`. PNGs and build artifacts are git-ignored.

## Findings (what the compile proved)

Run from the overlay root, `pdflatex contest.tex` succeeds on the **first pass**,
stable across a second pass, **zero warnings, no rerun**. The transcript shows
each asset loaded at its exact expected path:

| Claim (design §6) | Mechanism | Result |
|---|---|---|
| Contest chrome resolves from root | `\usepackage{icpc}` (cwd search) | ✅ `(./icpc.sty …)` |
| Root chrome image resolves | `\includegraphics{logo}` | ✅ `<./logo.png>` |
| Nested `\subimport` contest→problem→sample (3 levels) | `import.sty` | ✅ both fragments + both explanations input |
| Fragment graphics rebase to problem dir | `\includegraphics{fig}` | ✅ `<./.problems/A/statements/fig.png>` — **no `\graphicspath` needed** |
| Explanation graphics rebase to sample dir | `\includegraphics{sample-fig}` | ✅ `<./.problems/A/statements/.samples/000/sample-fig.png>` |
| Same-named assets don't collide across problems | `\subimport` isolation | ✅ A's red `fig.png` and B's purple `fig.png` both load |
| **Sample I/O via `\VerbatimInput` is NOT rebased** | fancyvrb | ✅ **requires root-relative paths** (see below) |

### The §6.4 verbatim nuance — confirmed by negative control

`\VerbatimInput` (what `\example` uses to print sample I/O) does **not** honor the
`\subimport` base. We feed it **root-relative** paths
(`.problems/A/statements/.samples/000/in`) and it resolves them from the compile
cwd (= overlay root). Proof: temporarily repointing A's input to a bogus
root-relative path fails hard with

```
./.problems/A/statements/statement.tex:12: FancyVerb Error:
  No verbatim file .problems/A/statements/.samples/000/DOES-NOT-EXIST
```

— so the reader is genuinely active and path-sensitive, and the root-relative
anchor is load-bearing. Restoring the correct path compiles clean again.

### Adjustments to the design

**None.** §6.4 stands. Two notes that *simplify* the builder contract:

1. **No `\graphicspath` / `TEXINPUTS` plumbing.** `import.sty` rebases
   `\includegraphics` to the subimport base on its own, at every nesting depth.
   The stager need only place files; it never has to inject graphics-path config.
2. **One anchor rule to encode:** LaTeX-content handles (`\subimport`,
   `\includegraphics`, `\input`) are **import-base-relative**; verbatim file
   readers (`\VerbatimInput` for `sample.input`/`sample.output`) are
   **root-relative**. This is the §4 handle split the builders must emit.
