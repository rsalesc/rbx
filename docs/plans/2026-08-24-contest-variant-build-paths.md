# Variant-scoped contest build paths Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give each contest variant its own contest-level build subtree, so building `div1` and `div2` no longer overwrites the other's statements, scratch overlays and packages.

**Architecture:** All three colliding artifacts already read their location from `contest_package.get_contest_build_path()`. We add a resolver that reports the selected variant id, split today's accessor into an unscoped `get_contest_root_build_path()` plus a variant-scoped `get_contest_build_path()` that appends `variants/<id>`, and point `rbx clean` at the unscoped one. No call site of the three artifacts changes.

**Tech Stack:** Python 3, Pydantic v2, Typer, pytest. Design doc: [`2026-08-24-contest-variant-build-paths-design.md`](2026-08-24-contest-variant-build-paths-design.md).

**Background you need:**

- A contest directory is marked by `contest.rbx.yml`. Sibling `contest.<id>.rbx.yml` files are *variants*. When `contest.rbx.yml` says `use_variants: true` it is a *dispatcher* (a sentinel, not a real contest) and there is no default; otherwise it is a real contest and is the default selection. See `rbx/box/contest/contest_package.py:discover_contest_variants`.
- Selection comes from `-C <id>` / `RBX_CONTEST`, stored in a contextvar and read by `find_contest_yaml`.
- Because all variants live in one directory, `find_contest()` returns the same path for all of them — which is why they share `build/`.
- **Testing rule from `CLAUDE.md`: run only the test files your change touches.** Never run the full suite; it is slow and causes spurious sandbox wall-clock timeouts.
- **Commits: you MUST follow `.claude/skills/commit.md`** (commitizen conventional commits; the pre-commit hook rejects anything else). Every commit message below already conforms.

---

### Task 1: Resolve the selected variant id

**Files:**
- Modify: `rbx/box/contest/contest_package.py` (add near `VARIANT_GLOB` at line 19, and a new function after `find_contest` at line 209)
- Test: `tests/rbx/box/contest/test_contest_package.py`

**Step 1: Write the failing tests**

Add this class to `tests/rbx/box/contest/test_contest_package.py`, right before `class TestContestBuildPaths`:

```python
class TestSelectedVariantId:
    @pytest.fixture(autouse=True)
    def _clear_caches(self):
        cp_module.find_contest_yaml.cache_clear()
        yield
        cp_module.find_contest_yaml.cache_clear()

    def test_canonical_returns_none(self, tmp_path: pathlib.Path):
        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')

        assert cp_module.get_selected_variant_id(tmp_path) is None

    def test_sibling_of_real_contest_returns_id(self, tmp_path: pathlib.Path):
        from rbx.box.contest.contest_state import selected_variant_id_var

        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')
        (tmp_path / 'contest.div2.rbx.yml').write_text('name: div2-c\n')

        token = selected_variant_id_var.set('div2')
        try:
            assert cp_module.get_selected_variant_id(tmp_path) == 'div2'
        finally:
            selected_variant_id_var.reset(token)

    def test_dispatcher_with_selection_returns_id(self, tmp_path: pathlib.Path):
        from rbx.box.contest.contest_state import selected_variant_id_var

        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-c\n')

        token = selected_variant_id_var.set('div1')
        try:
            assert cp_module.get_selected_variant_id(tmp_path) == 'div1'
        finally:
            selected_variant_id_var.reset(token)

    def test_dispatcher_without_selection_dies(self, tmp_path: pathlib.Path):
        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-c\n')

        with pytest.raises(typer.Exit):
            cp_module.get_selected_variant_id(tmp_path)
```

Make sure `typer`, `pytest` and `pathlib` are imported at the top of the test file; add `import typer` if it is missing.

**Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/rbx/box/contest/test_contest_package.py::TestSelectedVariantId -v
```

Expected: FAIL — `AttributeError: module ... has no attribute 'get_selected_variant_id'`.

**Step 3: Write the implementation**

In `rbx/box/contest/contest_package.py`, add the constant next to `VARIANT_GLOB` (line 19):

```python
VARIANT_BUILD_DIRNAME = 'variants'
```

Then add this function immediately after `find_contest` (which ends at line 209):

```python
def get_selected_variant_id(root: pathlib.Path = pathlib.Path()) -> Optional[str]:
    """The id of the resolved contest variant, or None for the canonical.

    Resolves through `find_contest_yaml` so it can never disagree with the rest
    of the codebase about which contest is selected, then reads the id straight
    off the resolved filename: `contest.rbx.yml` is the canonical (None),
    `contest.<id>.rbx.yml` is variant `<id>`. Ids are already validated at
    discovery time by `discover_contest_variants`.

    Dies like every other contest accessor when no contest resolves -- notably
    a dispatcher with no selection.
    """
    yaml_path = find_contest_yaml(root)
    if yaml_path is None:
        _die_no_contest(root)
    if yaml_path.name == YAML_NAME:
        return None
    return yaml_path.name[len('contest.') : -len('.rbx.yml')]
```

Deliberately **not** `@functools.cache`d: it is a thin wrapper over the already-cached `find_contest_yaml`, and leaving it uncached means one less cache to invalidate.

**Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/rbx/box/contest/test_contest_package.py::TestSelectedVariantId -v
```

Expected: 4 passed.

**Step 5: Commit**

```bash
git add rbx/box/contest/contest_package.py tests/rbx/box/contest/test_contest_package.py
git commit -m "$(cat <<'EOF'
feat(contest): resolve the selected contest variant id

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Split the build path into scoped and unscoped accessors

**Files:**
- Modify: `rbx/box/contest/contest_package.py:212-221`
- Test: `tests/rbx/box/contest/test_contest_package.py` (class `TestContestBuildPaths`, line 303)

**Step 1: Write the failing tests**

Extend the existing `_clear_caches` fixture of `TestContestBuildPaths` to clear the new accessor:

```python
    @pytest.fixture(autouse=True)
    def _clear_caches(self):
        cp_module.find_contest_yaml.cache_clear()
        cp_module.get_contest_build_path.cache_clear()
        cp_module.get_contest_root_build_path.cache_clear()
        cp_module.get_contest_statements_build_path.cache_clear()
        yield
        cp_module.find_contest_yaml.cache_clear()
        cp_module.get_contest_build_path.cache_clear()
        cp_module.get_contest_root_build_path.cache_clear()
        cp_module.get_contest_statements_build_path.cache_clear()
```

Then add these tests to the same class:

```python
    def test_sibling_variant_nests_under_variants(self, tmp_path: pathlib.Path):
        from rbx.box.contest.contest_state import selected_variant_id_var

        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')
        (tmp_path / 'contest.div2.rbx.yml').write_text('name: div2-c\n')

        token = selected_variant_id_var.set('div2')
        try:
            assert (
                cp_module.get_contest_build_path(tmp_path)
                == tmp_path / 'build' / 'variants' / 'div2'
            )
            assert (
                cp_module.get_contest_statements_build_path(tmp_path)
                == tmp_path / 'build' / 'variants' / 'div2' / 'statements'
            )
        finally:
            selected_variant_id_var.reset(token)

    def test_dispatcher_variant_nests_under_variants(self, tmp_path: pathlib.Path):
        from rbx.box.contest.contest_state import selected_variant_id_var

        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-c\n')

        token = selected_variant_id_var.set('div1')
        try:
            assert (
                cp_module.get_contest_build_path(tmp_path)
                == tmp_path / 'build' / 'variants' / 'div1'
            )
        finally:
            selected_variant_id_var.reset(token)

    def test_variant_honors_custom_build_dir(self, tmp_path: pathlib.Path):
        from unittest import mock

        from rbx.box.contest.contest_state import selected_variant_id_var

        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')
        (tmp_path / 'contest.div2.rbx.yml').write_text('name: div2-c\n')

        token = selected_variant_id_var.set('div2')
        try:
            with mock.patch.object(
                cp_module.environment, 'get_build_dir', return_value=pathlib.Path('out')
            ):
                cp_module.get_contest_build_path.cache_clear()
                cp_module.get_contest_root_build_path.cache_clear()
                assert (
                    cp_module.get_contest_build_path(tmp_path)
                    == tmp_path / 'out' / 'variants' / 'div2'
                )
        finally:
            selected_variant_id_var.reset(token)

    def test_root_build_path_ignores_selection(self, tmp_path: pathlib.Path):
        from rbx.box.contest.contest_state import selected_variant_id_var

        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')
        (tmp_path / 'contest.div2.rbx.yml').write_text('name: div2-c\n')

        token = selected_variant_id_var.set('div2')
        try:
            assert cp_module.get_contest_root_build_path(tmp_path) == tmp_path / 'build'
        finally:
            selected_variant_id_var.reset(token)

    def test_root_build_path_works_without_selection_in_dispatcher(
        self, tmp_path: pathlib.Path
    ):
        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-c\n')

        assert cp_module.get_contest_root_build_path(tmp_path) == tmp_path / 'build'
```

That last one is the behavioural fix for `rbx clean` — today the equivalent call raises `typer.Exit`.

**Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/rbx/box/contest/test_contest_package.py::TestContestBuildPaths -v
```

Expected: the new tests FAIL (`no attribute 'get_contest_root_build_path'`); the four pre-existing ones still pass.

**Step 3: Write the implementation**

Replace `rbx/box/contest/contest_package.py:212-215` with:

```python
@functools.cache
def get_contest_root_build_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    """The contest's build root, shared by every variant.

    Resolves through `find_contest_root`, which needs no variant selection, so
    this works in an unselected dispatcher -- unlike `get_contest_build_path`.
    Use it for operations that are deliberately variant-agnostic (`rbx clean`).
    """
    contest_root = find_contest_root(root)
    if contest_root is None:
        _die_no_contest(root)
    return contest_root / environment.get_build_dir()


# NOTE: cached on `root` alone while depending on the selection contextvar via
# `get_selected_variant_id`, the same caveat `find_contest_yaml` documents above.
# Production resolves the selection once at the CLI callback boundary; tests
# must `cache_clear()` when manipulating the contextvar.
@functools.cache
def get_contest_build_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    """The build path for the *selected* contest variant.

    The canonical keeps the bare build root; every other variant nests under
    `build/variants/<id>/` so variants stop overwriting each other's statements
    and packages.
    """
    build_path = get_contest_root_build_path(root)
    variant_id = get_selected_variant_id(root)
    if variant_id is None:
        return build_path
    return build_path / VARIANT_BUILD_DIRNAME / variant_id
```

Leave `get_contest_statements_build_path` (line 218) exactly as it is — it derives from `get_contest_build_path` and inherits the scoping for free.

**Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/rbx/box/contest/test_contest_package.py -v
```

Expected: all pass, including the pre-existing `TestContestBuildPaths` cases (the canonical path is unchanged).

**Step 5: Verify the three collision sites inherit the change**

No code edit — just confirm by reading that these still route through `get_contest_build_path` and need no change:

```bash
grep -rn "get_contest_build_path\|get_contest_statements_build_path" rbx
```

Expected callers: `rbx/box/cli.py:1737` (fixed in Task 3), `rbx/box/packaging/contest_main.py:83`, `rbx/box/contest/build_contest_statements.py:110,121,474`.

**Step 6: Commit**

```bash
git add rbx/box/contest/contest_package.py tests/rbx/box/contest/test_contest_package.py
git commit -m "$(cat <<'EOF'
fix(contest): scope contest build output per variant

Variants share one contest directory, so contest statements, their scratch
overlays and contest packages all landed on the same paths and overwrote each
other. Non-canonical variants now build under build/variants/<id>/.

Refs #753

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Make `rbx clean` variant-agnostic

**Files:**
- Modify: `rbx/box/cli.py:41` (import) and `rbx/box/cli.py:1730-1737` (`_clean_build_dirs`)

`rbx clean` should wipe the whole contest build root regardless of `-C`: its blast radius must not depend on an easy-to-forget flag. Switching to the unscoped accessor also drops the current hard error when cleaning an unselected dispatcher.

**Step 1: Change the import**

`rbx/box/cli.py:41` currently reads:

```python
from rbx.box.contest.contest_package import find_contest_yaml, get_contest_build_path
```

Change to:

```python
from rbx.box.contest.contest_package import (
    find_contest_yaml,
    get_contest_root_build_path,
)
```

If `get_contest_build_path` is used elsewhere in `cli.py`, keep it in the import list — check with `grep -n get_contest_build_path rbx/box/cli.py` first.

**Step 2: Change the call site**

`rbx/box/cli.py:1730-1737` currently reads:

```python
@cd.within_closest_package
def _clean_build_dirs():
    _clean_dir(pathlib.Path('build'))
    if cd.is_problem_package():
        _clean_dir(package.get_build_path())
    if cd.is_contest_package():
        _clean_dir(get_contest_build_path())
```

Change the last line to:

```python
        # Deliberately unscoped: clean wipes every variant's subtree, so its
        # blast radius does not depend on whether -C was passed.
        _clean_dir(get_contest_root_build_path())
```

**Step 3: Verify manually**

From a scratch copy of the multi-contest fixture:

```bash
cp -r <repo>/tests/e2e/testdata/multi-contest /tmp/mc && cd /tmp/mc
mkdir -p build/variants/div1 build/variants/div2
touch build/variants/div1/contest.zip
uv run --directory <repo> rbx clean
ls build            # expected: "No such file or directory"
```

The key assertion is that this no longer exits 1 with the "Multiple contests are defined" picker, which is what happens on `main` today.

**Step 4: Run the CLI tests touching clean**

```bash
uv run pytest tests/rbx/box/cli -k clean -v
```

Expected: PASS (or "no tests ran" if there is no clean coverage — that is fine, do not add CLI-suite tests, they are slow).

**Step 5: Commit**

```bash
git add rbx/box/cli.py
git commit -m "$(cat <<'EOF'
fix(contest): make rbx clean wipe every variant's build subtree

Clean now targets the shared contest build root rather than the selected
variant's, which also stops it erroring in an unselected dispatcher.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Report the variant in the contest statement build summary

**Files:**
- Modify: `rbx/box/contest/statements.py:14-17` (import) and `:212`
- Test: `tests/rbx/box/contest/test_statements.py` (create if absent)

Now that artifacts land in different subtrees, the summary must say which one.

**Step 1: Write the failing test**

Create or append to `tests/rbx/box/contest/test_statements.py`:

```python
from rbx.box.contest import statements as contest_statements
from rbx.box.statements.schema import StatementKind


def test_built_rule_title_without_variant():
    assert (
        contest_statements.built_rule_title(StatementKind.STATEMENTS, None)
        == 'Built statements'
    )


def test_built_rule_title_with_variant():
    assert (
        contest_statements.built_rule_title(StatementKind.STATEMENTS, 'div2')
        == 'Built statements (variant: div2)'
    )
```

Taking the id as a parameter keeps this a pure function — no contest directory, no contextvar, no mocking.

**Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/rbx/box/contest/test_statements.py -v
```

Expected: FAIL — `AttributeError: module 'rbx.box.contest.statements' has no attribute 'built_rule_title'`.

**Step 3: Write the implementation**

In `rbx/box/contest/statements.py`, extend the `contest_package` import (line 14):

```python
from rbx.box.contest.contest_package import (
    find_contest_package_or_die,
    get_selected_variant_id,
    within_contest,
)
```

Add the helper just above `_execute_build`:

```python
def built_rule_title(kind: StatementKind, variant_id: Optional[str]) -> str:
    """The summary rule title, naming the contest variant when one is selected
    so it is clear which `build/variants/<id>/` subtree the artifacts landed in."""
    if variant_id is None:
        return f'Built {kind.value}'
    return f'Built {kind.value} (variant: {variant_id})'
```

Then change line 212 from:

```python
    console.console.rule(title=f'Built {kind.value}')
```

to:

```python
    console.console.rule(title=built_rule_title(kind, get_selected_variant_id()))
```

**Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/rbx/box/contest/test_statements.py -v
```

Expected: 2 passed.

**Step 5: Commit**

```bash
git add rbx/box/contest/statements.py tests/rbx/box/contest/test_statements.py
git commit -m "$(cat <<'EOF'
feat(contest): name the variant in the statement build summary

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: End-to-end proof that two variants coexist

**Files:**
- Modify: `tests/e2e/testdata/multi-contest/e2e.rbx.yml`

The `multi-contest` fixture is already a dispatcher with `div1` (problems A, B) and `div2`. `rbx contest package pkg` writes `<build>/contest.zip` (`rbx/box/packaging/pkg/packager.py:140`), so with the fix the two variants land in different subtrees. On `main` the second run would silently overwrite the first.

**Step 1: Write the failing scenario**

Append to `tests/e2e/testdata/multi-contest/e2e.rbx.yml`:

```yaml
  - name: contest-package-per-variant-does-not-collide
    description: >-
      Packaging two variants in a row leaves both packages on disk, each under
      its own build/variants/<id>/ subtree, instead of the second overwriting
      the first.
    markers: [slow]
    steps:
      - cmd: -C div1 contest package pkg
        expect:
          files_exist:
            - build/variants/div1/contest.zip
      - cmd: -C div2 contest package pkg
        expect:
          files_exist:
            - build/variants/div1/contest.zip
            - build/variants/div2/contest.zip
```

Read [`tests/e2e/README.md`](../../tests/e2e/README.md) first and confirm `files_exist` and `markers` are spelled as the schema expects — the existing scenarios in this same file use both.

**Step 2: Run the e2e suite for this fixture**

```bash
mise run test-e2e -- -k multi-contest
```

Expected: PASS. If you had run it before Task 2, the second step would fail on the missing `build/variants/div1/contest.zip`.

**Step 3: Commit**

```bash
git add tests/e2e/testdata/multi-contest/e2e.rbx.yml
git commit -m "$(cat <<'EOF'
test(contest): cover per-variant contest package paths end to end

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Documentation

**Files:**
- Modify: `docs/setters/statements/contest.md:120-124` and `:142-145`
- Modify: `docs/setters/cheatsheet.md:638-644`

Follow the [documentation writing-style guide](docs-writing-style-guide.md): introduce a concept before using it, and never forward-reference a mechanism the reader has not met.

**Step 1: Update the contest book output path**

`docs/setters/statements/contest.md` currently says the build writes
`build/<statement-name>[-<profile>].pdf`. Add, right after that paragraph:

```markdown
When a contest variant is selected with `-C <id>`, the output nests under
`build/variants/<id>/` instead, so building one variant never overwrites
another's book. The default contest keeps the bare `build/` path.
```

**Step 2: Add the problem-level caveat**

After the paragraph at `:142-145` about building a single problem with `rbx st b`, add:

```markdown
!!! warning "Problem artifacts are not variant-scoped yet"
    A problem's own `build/` directory is shared across variants. A statement
    built there picks up the selected contest's chrome and the problem's letter
    in that contest, but always lands on the same path — so switching variants
    overwrites it. Rebuild after switching, and see
    [#753](https://github.com/rsalesc/rbx/issues/753).
```

**Step 3: Note the layout in the cheatsheet**

In `docs/setters/cheatsheet.md`, extend item 2 of the multi-contest list (line 642) with a sentence:

```markdown
    Each selected variant builds into `build/variants/<id>/`; the default contest
    builds into `build/`.
```

**Step 4: Verify the docs build**

```bash
uv run mkdocs build 2>&1 | tail -20
```

Expected: builds. **Ignore the `--strict` failure** — there are ~9 pre-existing unrelated warnings, so verify with a non-strict build. Also: **`mkdocs build` regenerates the checked-in CLI reference `docs/setters/reference/cli.md`** — revert that file before committing:

```bash
git checkout -- docs/setters/reference/cli.md
```

**Step 5: Commit**

```bash
git add docs/setters/statements/contest.md docs/setters/cheatsheet.md
git commit -m "$(cat <<'EOF'
docs(contest): document per-variant build paths

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/rbx/box/contest -v
mise run test-e2e -- -k multi-contest
```

Do **not** run the full test suite. Then open a PR against `main` referencing this plan and linking #753 as the deferred follow-up.
