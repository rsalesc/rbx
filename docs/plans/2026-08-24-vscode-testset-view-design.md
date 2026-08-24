# VS Code Testset view: the `rbx build` half of the extension

The extension today shows one thing: what a `rbx run` produced. The other half
of a setter's loop -- *what is even in the testset* -- has no surface at all,
and `rbx ui`'s `TestExplorerScreen` (the "Explore tests built by `rbx build`"
flow) is the thing being ported.

## The obstacle: `rbx build` leaves no provenance on disk

Everything the TUI shows about a testcase's origin -- the generator call, the
generator script line, the validator, the model solution -- is computed
in-process by `extract_generation_testcases_from_groups()`. A finished
`rbx build` leaves only:

```
<pkg>/build/tests/<group>/<stem>.in
<pkg>/build/tests/<group>/<stem>.out
<pkg>/build/tests/<group>/visualization/<stem>.<ext>
```

The rich `GenerationTestcaseEntry` list reaches disk exactly once, inside
`.rbx/runs/skeleton.yml` -- which **`rbx run` writes, and `rbx build` does
not**. Validator `hit_bounds`, the constraint-coverage data
`print_validation_report` renders, is computed and then discarded entirely.

The extension is a pure reader (D2 of the M1 design): it never spawns rbx,
because every rbx invocation has side effects on the package cache and could
race a run already in flight. So the fix is on the rbx side -- publish what the
build already knows.

## D1. Three surfaces, by how often each is looked at

| surface | id | holds |
| --- | --- | --- |
| sidebar webview view | `rbx.testset` ("Tests"), beside `rbx.run` | group/testcase list, filter, metadata card |
| editor panes | existing `testcasePanes.ts` | `input.in` \| `answer.out`, replaced in place while arrowing |
| editor webview panel | `rbx: Testset` | visualization gallery, constraint coverage, testset stats |

The sidebar is ~300px and does not try to be wide. Everything that wants width
-- a gallery, a coverage matrix, a stats table -- gets a deliberate open, and
the panel live-follows the sidebar selection the same way the panes already do.

Rejected: an editor-tab dashboard *only*. It costs a deliberate open for the
one thing looked at constantly (which test is this, where did it come from),
and abandons the always-visible surface the Run view established.

## D2. `build/testset.yml`

`rbx build` writes one manifest, **last** -- after generation, validation,
outputs and visualizers. Written last is load-bearing: a reader that sees the
manifest knows everything it names has already landed, which is what lets the
watcher be a single glob instead of a settling heuristic.

```yaml
version: 1
task_type: BATCH
groups:  [{name, score, deps, subgroups, vars}]     # vars = effective, merged
entries: [GenerationTestcaseEntry, ...]             # verbatim, as skeleton.entries
tests:                                              # per-entry extras, keyed group+index
  - group: main
    index: 0
    validation: {ok: true, validator: validator.cpp, message: null}
    visualization: {input: build/tests/main/visualization/1-gen-000.svg, output: null}
    input_size: 4211
    output_size: 12
validation:                                         # absent under -v0
  - {group: main, validator: validator.cpp, bounds: {n: [true, false], m: [true, true]}}
```

Four decisions inside that shape:

- **`entries` is dumped verbatim.** It is the same `GenerationTestcaseEntry`
  the skeleton embeds, so the extension's existing `parseTestcaseEntry` is
  reused unchanged. Everything new lives in sibling keys, where an old reader
  ignores it and a new reader finds it.
- **Per-entry extras ride in a parallel `tests` list**, not as new fields on
  `GenerationTestcaseEntry`. Extending that model would change `skeleton.yml`
  too, for the benefit of one consumer.
- **Subset builds replace, never merge.** `generate_testcases` rmtree's the whole
  of `build/tests` before it looks at the group filter (`generators.py:475`), so
  after `rbx build --groups main` the other groups' testcases are genuinely gone
  from disk -- a merged manifest would assert testcases that no longer exist.
  The manifest always describes exactly what the build just produced; after a
  subset build the testset really is only those groups.

  > This corrects the first draft of this design, which specified a merge. The
  > merge was written without knowing the wipe ignores the group filter, and
  > would have made the manifest lie about the one thing it exists to report.
- **Sizes are stamped at dump time**, so the extension never stats thousands of
  files to draw a list.

Location is `build/`, beside the tests it describes: `clear_built_testcases()`
rmtree's `build/tests` and a fresh build rewrites both, so the two cannot drift;
and `rbx clean`, which wipes `.rbx`, can never orphan it.

**No staleness check.** The manifest is whatever the last build wrote. The
header shows its mtime (`built 3m ago`) as an honest cue and makes no
correctness claim -- a check would have to model which of the package's inputs
feed which group, and be wrong in both directions.

`rbx testcases` and `irun` both call `generate_standalone` into
`build/tests/<group>/`, so between builds a single testcase can be refreshed
without the manifest hearing about it. The next build wipes and rewrites both,
so they cannot drift across a build. This is the stance above, not an exception
to it.

## D3. The data layer, reusing the run's

- `rbx/layout.ts` gains `TESTSET_MANIFEST` and `testsetPath(pkg)`. It stays the
  only module that knows where rbx puts things.
- `rbx/testset.ts` is a tolerant parser over `wire.ts`, degrading field by field
  exactly as `model.ts` does. Nothing in it raises.
- `ArtifactStore` gains `testset()`, cached and invalidated by the watcher --
  same store, same package key as the run, so no second discovery and no way for
  the two views to disagree about which package is active.
- `extension.ts` adds one watcher glob, `**/build/testset.yml`, feeding the
  debounce that already exists.

## D4. The sidebar view

`testsetViewModel.ts` (pure) -> `testsetRender.ts` (pure string) ->
`testsetView.ts` (host seam). The same three-layer split as the Run view, for
the same reason: what a row *means* is decided once, in a file `node --test` can
hold to account, and the renderer is handed strings and hues.

```
[twisty][label ...................][meta][flags]

 v main                              40 · 100
     1-gen-000                   4.1 KiB  #
     1-gen-001                   4.1 KiB  #  !
```

Group rows carry count and score. Testcase rows carry the stem, the input size,
a marker when a visualization exists, and a warning when validation failed. The
meta line sheds channels under a container query in priority order, size last --
the same mechanism, and the same `role`-per-span discipline, as D10 of the run
webview design.

Reused wholesale: `hue.ts`, `gesture.ts`, `style.css`, `problems.ts` (the
problem dropdown), `artifactFs.ts`, and the commands `rbx.openGeneratorScript`
and `rbx.openCopiedFrom`, which already exist and already do exactly this job.

One refactor earns its place: `webview/main.ts` owns the roving-tabindex tree,
the expansion persistence and the filter box. That moves to `webview/tree.ts`
and both clients use it. Copying two hundred lines of keyboard handling into a
second client is how the two surfaces start navigating differently.

`panes.ts` gains an `answer` channel, so a built testcase opens
`input.in` | `answer.out` through the same tab-finding logic that keeps the
user's pane arrangement intact.

## D5. The `rbx: Testset` panel

**Visualizations.** A grid of the current group, or of the current filter's
matches. `.svg/.png/.jpg/.gif/.webp` render as `<img>` through
`asWebviewUri`; `.html` renders in a sandboxed `<iframe>`; any other extension
gets an "open in editor" link rather than a guess -- `Visualizer.extension` is
a free string and the manifest does not promise an image. `localResourceRoots`
extends to the package's `build/` directory and nowhere else.

This is the part of `rbx ui` a terminal cannot do: the TUI has to shell out to
an external viewer, and the setter loses their place.

**Coverage.** Variables down, groups across; each cell two ticks for min-hit and
max-hit, hued green / yellow / red, with a "never hit" roll-up above the table.
Absent, with a one-line explanation, when the build ran `-v0` -- the data does
not exist, and an empty table would read as "nothing is covered".

**Stats.** Per group: count, score, deps, subgroup breakdown, max and total
input size, max output size. Plus package totals and the sample count.

## Testing

- Python: `rbx build` writes a manifest matching the entries it generated; a
  subset build merges rather than truncates; `-v0` omits `validation`. Existing
  `testing_pkg` / `pkg_from_testdata` fixtures.
- Extension: parser tests over hand-written YAML, including a truncated one and
  one from a future version; view-model tests; render snapshots. All under
  `node --test`, none importing `vscode`.

## Non-goals

- **No "Build" button.** The extension still never spawns rbx. Dispatching to a
  terminal is a separate decision with its own race questions.
- **Solution-output visualizers** stay with the Run view, where the output they
  visualize lives.
- **No virtualization** until the rendered row count justifies it, per the run
  view's ~2000-row threshold.
