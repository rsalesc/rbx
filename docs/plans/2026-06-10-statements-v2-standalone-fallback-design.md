# Statements v2 — contest-less default-template fallback (S15) — Design

Tracking issue: [#571 — statements v2 (deferred): contest-less default-template fallback](https://github.com/rsalesc/rbx/issues/571)
Parent: [#556 — statements v2](https://github.com/rsalesc/rbx/issues/556), design `docs/plans/2026-06-09-statements-v2-design.md` §8.
Status: **approved design**, ready to break into an implementation plan.
Date: 2026-06-10

## 1. Motivation

Statements v2 made a contest **required** to build an *rbx* problem statement: the
contest owns the templates (`standaloneProblemTemplate` / `contestProblemTemplate`).
Building outside a contest is a hard error today (`resolver.require_contest_for_problem`),
and a contest with no matching standalone statement for the problem's
`(language, variant)` is also a hard error (`resolver.select_standalone_contest_statement`).

S15 lifts that restriction for the common "single problem, no contest" workflow:
`rbx st b` (and `rbx tut b`) should build by **synthesizing an implicit standalone
context** from a **bundled default template** when no matching contest statement is
found — with clear messaging. Static types (`tex`/`md`/`pdf`) already build
contest-less; this concerns only the *rbx* types.

## 2. Decisions (resolved during brainstorming)

1. **Trigger = "no matching standalone statement found", from either cause.** The
   fallback fires when there are **0** standalone candidates — whether because there
   is no contest at all (case a), or a contest is present but defines no
   `standaloneProblemTemplate` for this `(language, variant)` (case b). `>1`
   candidates **still hard-errors** (ambiguous; design §2.3 unchanged); no
   first-wins, no `--using` flag.
2. **Dispatcher-unselected stays an error.** When a contest *root* exists but is a
   dispatcher with no `-C`/`RBX_CONTEST` selection, that remains a hard error with
   the "pass `-C <id>`" hint (today's `require_contest_for_problem` behavior). We do
   **not** silently fall back there — it is a "you forgot to select a contest"
   situation, not a genuinely contest-less problem.
3. **Reuse the preset chrome as the bundled default.** The fallback points at the
   bundled preset's contest statement chrome
   (`rbx/resources/presets/default/contest/statements/`): `problem.rbx.tex`
   (`standaloneProblemTemplate`), `editorial-standalone.rbx.tex` (tutorials; renamed
   from `editorial.rbx.tex` in #592 to avoid colliding with a problem's own
   `editorial.rbx.tex`), `icpc.sty`, `logo.png`, the shared `_problem-body.rbx.tex` /
   `_editorial-body.rbx.tex` partials. No new dedicated resource dir; no per-problem
   template override.
4. **Synthetic statement is derived from the preset model, not hardcoded.** Load the
   preset's `contest.rbx.yml` model and `model_copy` its first statement (or
   tutorial) with the problem's `(language, variant)`. No template filenames are
   hardcoded in Python; the fallback auto-tracks preset changes.
5. **Symmetric for statements and tutorials.** Threaded by the existing
   `StatementKind`; `rbx st b` uses the preset `statements` entry, `rbx tut b` the
   preset `tutorials` entry.
6. **Contest metadata from the real contest when present.** In case (b) the
   `contest.*` namespace (`title`/`vars`/`location`/`date`) comes from the real
   contest; in case (a) it uses neutral defaults (empty title/vars, no
   location/date). Only the *template* is the bundled default.
7. **rbxMarkdown-output contest-less default is out of scope.** The preset ships
   only a rbxTeX standalone template, so the bundled fallback targets rbxTeX
   rendering. A markdown-output default is a separate later concern.

## 3. Implementation shape

**Resolver-owned unified resolution.** The real-vs-fallback decision lives in
`resolver.py`, which already owns contest-aware resolution. `build_statement` calls
one function instead of two and renders unchanged downstream.

### 3.1 New: `resolver.resolve_standalone`

```python
@dataclass
class StandaloneResolution:
    contest: Optional[Contest]            # real contest, for contest.* metadata (None in case a)
    contest_statement: ContestStatement   # real (single match) OR synthetic (fallback)
    contest_root: pathlib.Path            # real contest root, OR the bundled preset contest dir
    is_fallback: bool

def resolve_standalone(statement: Statement, kind: StatementKind) -> StandaloneResolution: ...
```

Decision tree:

```
contest = find_contest_for_problem()           # Optional
if contest is None and dispatcher-root-unselected:
    hard error with -C hint                     # decision 2
candidates = standalone candidates in contest matching (language, variant)  # [] if no contest
  exactly 1 -> REAL resolution (contest, candidate, find_contest(), is_fallback=False)
  >1        -> hard error (ambiguous)           # decision 1
  0         -> FALLBACK (decision 1):
                 preset_root  = <bundled preset contest dir>
                 preset_model = load_yaml_model(preset_root / 'contest.rbx.yml', Contest)
                 src = (preset_model.expanded_tutorials if kind == TUTORIALS
                        else preset_model.expanded_statements)[0]
                 synth = src.model_copy(update={'language': statement.language,
                                                'variant': statement.variant})
                 return StandaloneResolution(contest, synth, preset_root, is_fallback=True)
```

- `find_contest_for_problem()` already returns `None` when no contest resolves
  (incl. dispatcher-unselected); the dispatcher hint is detected separately
  (`find_contest_root` + `discover_contest_variants` + no explicit selection), reusing
  the logic now in `require_contest_for_problem`.
- The synthetic statement's `file` stays `statements/problem-sheet.rbx.tex` (from the
  preset), so `chrome_dir = (contest_root / file).parent` resolves to the preset
  `statements/` dir exactly as for a real contest; `standaloneProblemTemplate` stays
  `statements/problem.rbx.tex`.

### 3.2 Resource path helper

`config.get_resources_file` is file-only. Add a directory variant (or resolve the
preset contest dir via `importlib.resources.files('rbx') / 'resources' / 'presets' /
'default' / 'contest'`) returning a real filesystem path the overlay stager can
mirror. rbx ships resources unzipped, so a direct path is fine; wrap in
`importlib.resources.as_file` if zip-safety is desired.

### 3.3 `build_statement` changes

In the `is_rbx()` branch, replace:

```python
contest = resolver.require_contest_for_problem()
contest_statement = resolver.select_standalone_contest_statement(statement, contest_candidates)
contest_root = contest_package.find_contest()
```

with:

```python
res = resolver.resolve_standalone(statement, kind)
contest, contest_statement, contest_root = res.contest, res.contest_statement, res.contest_root
if res.is_fallback:
    console.print('[warning]No contest statement provides a standalone template '
                  f'for {statement.language}/{statement.variant}; building with '
                  "rbx's bundled default template.[/warning]")
```

The rest (`chrome_dir`, `stage_standalone_overlay`, `relativize_template`,
`render_problem_tex`) is unchanged. The `ContestRenderContext` is built from
`res.contest` when present, else neutral defaults:

```python
contest_ctx = ContestRenderContext(
    title=(naming.get_contest_title(lang=statement.language,
                                    statement=contest_statement, contest=contest)
           if contest is not None else ''),
    vars=(contest.expanded_vars if contest is not None else {}),
    params=contest_statement.expanded_vars,
    location=contest_statement.location,
    date=contest_statement.date,
)
```

## 4. Path resolution & collisions (unchanged contract)

`stage_standalone_overlay` mirrors the **whole** chrome dir into the overlay root,
so the fallback pulls in everything in the preset `statements/` dir (incl. the
~414 KB `logo.png`, `instructions.tex`, the contest sheet, editorial files). A
problem-local statement-dir file named like a chrome file still triggers the
collision error — consistent with real-contest behavior, surfaced clearly. This is
documented, not worked around.

## 5. Out of scope

- A dedicated (non-preset) bundled template, or a per-problem template override field.
- Markdown-output contest-less default (decision 7).
- Changing the `>1`-candidates or dispatcher-unselected error behavior (decisions 1, 2).

## 6. Work breakdown

Single reviewable PR is feasible; if split:

- **S15a — resolver fallback.** `resolve_standalone` + `StandaloneResolution`; preset
  model load + rebind; dispatcher-unselected error preserved; resource-dir helper.
  Unit-tested in isolation (no package on disk).
- **S15b — build wiring + messaging.** Swap `build_statement`'s two resolver calls
  for `resolve_standalone`; neutral contest context; fallback warning. Symmetric for
  tutorials via `StatementKind`.
- **S15c — tests + e2e.** Contest-less `rbx st b` / `rbx tut b` fixtures producing
  `build/statement-en.pdf` / `build/tutorial-en.pdf`; a collision fixture asserting
  the clear error; resolver unit tests (0 → synthetic, >1 → error, single → real,
  dispatcher-unselected → `-C` hint).
- **S15d — docs.** Note contest-less builds and the bundled default on the docs site
  and in `rbx/box/statements/CLAUDE.md` (the "a contest is required" line becomes "a
  contest is required, or the bundled default is used").
