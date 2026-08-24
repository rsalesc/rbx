# Visualizations as real files Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `build/tests/**/visualization/*` real files instead of symlinks into content-addressed storage, so anything that types a file by its extension (a browser, Finder, the VS Code panel's `<iframe>`) renders a visualization instead of showing its source.

**Architecture:** A new `symlink: bool = True` field on `GradingFileOutput`, honoured at the single place that materializes a hashed output (`_copy_hashed_files` in `rbx/grading/caching.py`), and set to `False` by `run_visualizer`. The copy branch it falls through to already exists — it is what runs today on a storage backend without `path_for_symlink`. Cache keys, digest inference and the storage layout are untouched.

**Tech Stack:** Python 3, pydantic v2 models, pytest (`pytest-asyncio`), `uv run` for everything.

**Design:** [`2026-08-24-visualization-symlink-design.md`](2026-08-24-visualization-symlink-design.md)

---

### Task 1: `GradingFileOutput.symlink`, honoured by the cache

**Files:**
- Modify: `rbx/grading/steps.py:177-195` (the `GradingFileOutput` model)
- Modify: `rbx/grading/caching.py:270-292` (`_copy_hashed_files`)
- Modify: `rbx/grading/caching.py:132-149` (`_maybe_check_integrity`, comment only)
- Test: `tests/rbx/grading/caching_test.py`

**Step 1: Write the failing test**

Append to `tests/rbx/grading/caching_test.py`. The existing `_run_from` helper at the
top of the file builds the artifacts, so this test needs its own variant that can set
the flag — add both:

```python
async def _run_writing(
    src: pathlib.Path,
    out: pathlib.Path,
    sandbox: SandboxBase,
    dependency_cache: DependencyCache,
    symlink: bool = True,
) -> GradingArtifacts:
    artifacts = GradingArtifacts()
    artifacts.inputs.append(
        GradingFileInput(src=src, dest=pathlib.Path('executable.py'))
    )
    artifacts.outputs.append(
        GradingFileOutput(
            src=pathlib.Path('box-out.txt'), dest=out, symlink=symlink
        )
    )
    await steps_with_caching.run(
        f'{sys.executable} executable.py',
        params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
        sandbox=sandbox,
        artifacts=artifacts,
        dependency_cache=dependency_cache,
        metadata=RunLogMetadata(),
    )
    return artifacts


async def test_output_is_a_symlink_into_storage_by_default(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    src = cleandir / 'executable.py'
    src.write_text('print(7)')

    await _run_writing(src, pathlib.Path('out.txt'), sandbox, dependency_cache)

    assert (cleandir / 'out.txt').is_symlink()


async def test_output_with_symlink_disabled_is_a_real_file(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    # A visualization is opened by a browser, which types a symlink by its
    # target -- and a storage blob is named by its digest, with no extension.
    src = cleandir / 'executable.py'
    src.write_text('print(7)')

    await _run_writing(
        src, pathlib.Path('out.txt'), sandbox, dependency_cache, symlink=False
    )

    out = cleandir / 'out.txt'
    assert not out.is_symlink()
    assert out.is_file()
    assert out.read_text().strip() == '7'


async def test_output_with_symlink_disabled_stays_a_real_file_when_cached(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    # The second run is a cache hit, which materializes through the same
    # function -- the file it restores must be a copy too.
    src = cleandir / 'executable.py'
    src.write_text('print(7)')

    await _run_writing(
        src, pathlib.Path('first.txt'), sandbox, dependency_cache, symlink=False
    )
    await _run_writing(
        src, pathlib.Path('second.txt'), sandbox, dependency_cache, symlink=False
    )

    second = cleandir / 'second.txt'
    assert not second.is_symlink()
    assert second.read_text().strip() == '7'
```

**Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/rbx/grading/caching_test.py -k symlink -v`

Expected: the two `symlink=False` tests FAIL. Pydantic's `extra` handling on
`GradingFileOutput` decides the shape of the failure — either a
`ValidationError` for an unknown `symlink` field, or (if extras are ignored)
an `AssertionError` on `not out.is_symlink()`. The default-behaviour test
should already PASS; if it does not, stop — the test backend is not
symlinking and the rest of the plan needs rechecking.

**Step 3: Add the field**

In `rbx/grading/steps.py`, inside `GradingFileOutput`, after the `hash` field:

```python
    # Whether the destination may be a symlink into the storage. Turn this off
    # for an artifact something outside rbx opens by path: a symlink is typed
    # by its target, and a storage blob is named by its digest, so it has no
    # extension to type it by.
    symlink: bool = True
```

**Step 4: Honour it where the file is materialized**

In `rbx/grading/caching.py`, in `_copy_hashed_files`, change the condition
guarding the symlink branch:

```python
            if (
                output.symlink
                and (
                    path_to_symlink := await cacher.path_for_symlink(
                        output.digest.value
                    )
                )
                is not None
            ):
                # Use a symlink to the file in the persistent cache, if available.
                output.dest.unlink(missing_ok=True)
                output.dest.parent.mkdir(parents=True, exist_ok=True)
                output.dest.symlink_to(path_to_symlink)
            else:
                # Otherwise, copy it.
```

Note the copy branch calls `output.dest.open('wb')` without creating the
parent directory, while the symlink branch does `mkdir`. Check whether the
copy branch needs the same `output.dest.parent.mkdir(parents=True,
exist_ok=True)`; `run_visualizer` already creates the visualization directory
itself, but the branch is now reachable for outputs that do not. Add the
`mkdir` to the copy branch if it is missing.

**Step 5: Note the integrity gap**

In `_maybe_check_integrity`, extend the existing comment so the early return
does not read as an oversight:

```python
    if output.dest is None or not output.dest.is_symlink() or not output.dest.is_file():
        # Only makes sense if the file EXISTS and IS A SYMLINK pointing to an
        # EXISTING storage file.
        # If the storage file ceases to exist, we can simply evict from the cache.
        # An output that opted out of symlinking (`symlink=False`) is a copy
        # and is deliberately not checked: the check is about a storage blob
        # changing under a link, and a copy has no link to change under it.
        return
```

**Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/rbx/grading/caching_test.py -v`

Expected: PASS, including the pre-existing tests in that file.

**Step 7: Commit**

```bash
git add rbx/grading/steps.py rbx/grading/caching.py tests/rbx/grading/caching_test.py
git commit -m "feat(grading): let an output opt out of being a symlink"
```

---

### Task 2: Visualizations opt out

**Files:**
- Modify: `rbx/box/visualizers.py:337-345` (the `outputs=[...]` of `run_visualizer`)
- Test: `tests/rbx/box/test_visualizers.py:153` (`test_run_visualizer_passes_sandbox_args_and_outputs`)

**Step 1: Write the failing assertion**

In `tests/rbx/box/test_visualizers.py`, in
`test_run_visualizer_passes_sandbox_args_and_outputs`, after the existing
`outputs[0].dest` assertion:

```python
    # Not a symlink: a browser types a visualization by the extension of the
    # file the path resolves to, and a storage blob has none.
    assert outputs[0].symlink is False
```

**Step 2: Run it to verify it fails**

Run: `uv run pytest tests/rbx/box/test_visualizers.py::test_run_visualizer_passes_sandbox_args_and_outputs -v`

Expected: FAIL — `assert True is False`.

**Step 3: Set the flag**

In `rbx/box/visualizers.py`, in the `outputs` list passed to `run_item`:

```python
        outputs=[
            GradingFileOutput(
                src=sandbox_path,
                dest=visualization_path,
                optional=True,
                # A visualization is opened by whatever handles its extension
                # -- a browser, the editor, the VS Code panel's <iframe>. A
                # symlink is typed by its target, and the storage blob it
                # would point at is named by its digest.
                symlink=False,
            ),
        ],
```

**Step 4: Run it to verify it passes**

Run: `uv run pytest tests/rbx/box/test_visualizers.py -v`

Expected: PASS, whole file.

**Step 5: Commit**

```bash
git add rbx/box/visualizers.py tests/rbx/box/test_visualizers.py
git commit -m "fix(visualizers): write visualizations as real files"
```

---

### Task 3: Verify end to end against a real package

Unit tests cannot see the thing that was actually broken — how a browser types
the file. Do this by hand.

**Step 1: Rebuild a package that has an HTML visualizer**

```bash
cd ~/Dev/rbx-vscode-contest/apples
rm -rf build
uv run --project ~/Dev/robox.io rbx build --visualize
```

**Step 2: Confirm the artifact is a real file**

```bash
ls -l build/tests/main/visualization/
file build/tests/main/visualization/1-gen-000.html
```

Expected: a regular file (no `->` in `ls -l`, mode starts `-rw`), reported as
`HTML document text`.

**Step 3: Confirm a browser parses it**

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
  --disable-gpu --dump-dom \
  "file://$PWD/build/tests/main/visualization/1-gen-000.html" | head -c 120
```

Expected: starts with `<!DOCTYPE html>` and the page's own markup. A
`<pre style="word-wrap: break-word...">` wrapper means it is still being typed
as plain text and the fix did not take.

**Step 4: Confirm the txt visualization still works**

```bash
ls -l build/tests/samples/visualization/
```

Expected: `1-gen-000.txt`, also a regular file. The group-level `.txt`
visualizer must keep working — it is the case the VS Code panel offers to open
in an editor.

**Step 5: Confirm the VS Code panel renders it**

Launch the extension on that contest and open the testset panel's gallery:

```bash
cd ~/Dev/robox.io && ./run-extension.sh -f ~/Dev/rbx-vscode-contest
```

Expected: the `main` group's cells draw the page (headline `7 + 8 = 15` and a
row of apples), not its source. The `samples` cell still shows the "Open .txt
in editor" affordance.

**Step 6: Check the disk cost is what the design claimed**

```bash
du -sh ~/Dev/rbx-vscode-contest/apples/build/tests
```

Expected: kilobytes for this package. Worth a sentence in the PR if it is not.

---

### Task 4: Ship it

**Step 1: Run the touched tests together**

Run: `uv run pytest tests/rbx/grading/caching_test.py tests/rbx/box/test_visualizers.py -v`

Expected: PASS. Do not run the full suite — see the note in memory about
spurious sandbox wall timeouts.

**Step 2: Lint and format**

```bash
uv run ruff check . && uv run ruff format --check .
```

**Step 3: Commit the design and the plan**

```bash
git add docs/plans/2026-08-24-visualization-symlink-design.md \
        docs/plans/2026-08-24-visualization-symlink.md
git commit -m "docs(plans): design for writing visualizations as real files"
```

**Step 4: Push and open the PR**

```bash
git push -u origin worktree-viz-artifact-no-symlink
gh pr create --base main --title "fix(visualizers): write visualizations as real files, not symlinks"
```

The PR body should carry the measured table from the design doc — the two
`file://` cases and what Chrome does with each — because that is the fact that
makes the change obviously right, and it is not visible from the diff.
