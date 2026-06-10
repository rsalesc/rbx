# Polygon statement-upload grilling: e2e suites + audit — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a separate, locally-runnable `pdflatex` e2e category that grills the
statements-v2 Polygon API upload path (`rbx package polygon -u`) end-to-end with a
recording fake instead of real network, plus a written audit of the upload logic.

**Architecture:** Patch the single client factory
`rbx.box.packaging.polygon.upload._get_polygon_api()` with a `RecordingPolygon`
that serializes every `save_statement` / `save_statement_resource` call to disk.
A new `polygon_upload` matcher in the e2e YAML DSL asserts the captured payload
(statement fields, uploaded resource names, and `\includegraphics` referential
integrity). The current `mock_pdflatex` fixture becomes conditional so
`pdflatex`-marked scenarios hit the real binary (needed for TikZ externalization).

**Tech Stack:** Python 3.12, pytest, Pydantic v2, Typer `CliRunner`, mise, pdflatex
(with TikZ `external` + `-shell-escape`).

**Design doc:** `docs/plans/2026-06-10-polygon-statement-upload-e2e-design.md`

---

## Conventions for the executor

- This repo uses **single quotes**, absolute imports only, ruff. Run
  `uv run ruff format <files>` + `uv run ruff check --fix <files>` before each commit.
- Commits MUST follow Conventional Commits (commitizen). Use the `/commit` workflow
  in `.claude/skills/commit.md`. Append the trailer
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- We are already in worktree `issue-586-polygon-statement-e2e`.
- Pre-existing local failures unrelated to this work (checker/validator/sandbox/docker
  C++ tests) are expected; do not chase them.

---

## Phase A — e2e harness: marker, recording fake, matcher, conditional pdflatex

### Task A1: Register the `pdflatex` marker

**Files:**
- Modify: `tests/e2e/spec.py:136`
- Modify: `pytest.ini:3-9`

**Step 1: Add to the allowlist**

In `tests/e2e/spec.py` change:
```python
_ALLOWED_MARKERS = frozenset({'slow', 'docker'})
```
to:
```python
_ALLOWED_MARKERS = frozenset({'slow', 'docker', 'pdflatex'})
```

**Step 2: Register in pytest.ini**

Add under `markers =`:
```
    pdflatex: mark test as requiring a real pdflatex (with TikZ) install
```

**Step 3: Verify markers parse**

Run: `uv run pytest tests/e2e/test_collection.py -q` (or the spec tests)
Expected: PASS (no "unknown markers" error).

**Step 4: Commit**

```bash
git add tests/e2e/spec.py pytest.ini
git commit -m "test(e2e): allow a pdflatex marker for real-LaTeX scenarios"
```

---

### Task A2: Recording Polygon fake (`tests/e2e/polygon_capture.py`)

This module is the heart of the verification: a fake that satisfies the surface
`upload_problem()` touches and serializes statement + resource uploads to disk.

**Files:**
- Create: `tests/e2e/polygon_capture.py`
- Test: `tests/e2e/test_polygon_capture.py`

**Surface the fake must satisfy** (from `rbx/box/packaging/polygon/upload.py`):
- Client (`_get_polygon_api()` return): `problems_list(name=...) -> []`,
  `problem_create(name) -> RecordingProblem`.
- Problem: `update_info(info)`, `save_file(type=,name=,file=,source_type=)`,
  `set_checker(name)`, `set_interactor(name)`, `set_validator(name)`,
  `save_solution(name, content, source_type=, tag=)`, `solutions() -> []`,
  `save_test(testset=, test_index=, test_input=, **kw)`,
  `save_script(testset=, source=)`,
  `save_statement(lang=, problem_statement=) -> RECORD`,
  `save_statement_resource(name=, file=) -> RECORD`, `commit_changes()`.

The `save_statement` / `save_statement_resource` calls happen on worker threads
(`ThreadPoolExecutor`), so writes use a lock and per-file names (no shared mutable
list).

**Capture layout** under the capture dir (default `<pkg>/.rbx/polygon_capture/`):
- `statements/<uploaded_lang>.json` — `{name, legend, input, output, interaction, notes}`
- `resources/<normalized_name>` — raw bytes
- `resources.json` — sorted list of uploaded resource names
- `calls.json` — ordered list of `{method, ...}` for non-statement calls (debug/audit)

**Step 1: Write the failing test** (`tests/e2e/test_polygon_capture.py`)

```python
import json

from rbx.box.packaging.polygon import polygon_api as api
from tests.e2e import polygon_capture


def test_recording_problem_serializes_statement_and_resources(tmp_path):
    capture_dir = tmp_path / 'cap'
    polygon_capture.set_capture_dir(capture_dir)
    try:
        client = polygon_capture.make_recording_polygon()
        assert client.problems_list(name='x') == []
        problem = client.problem_create('x')
        problem.save_statement_resource(name='img__d.png', file=b'PNG')
        problem.save_statement(
            lang='english',
            problem_statement=api.Statement(
                encoding='utf-8',
                name='Title',
                legend=r'\includegraphics{img__d.png}',
                input='in',
                output='out',
                notes='',
            ),
        )
        problem.commit_changes()
    finally:
        polygon_capture.reset_capture_dir()

    data = json.loads((capture_dir / 'statements' / 'english.json').read_text())
    assert data['name'] == 'Title'
    assert r'\includegraphics{img__d.png}' in data['legend']
    assert (capture_dir / 'resources' / 'img__d.png').read_bytes() == b'PNG'
    assert 'img__d.png' in json.loads((capture_dir / 'resources.json').read_text())
```

**Step 2: Run it — expect failure** (`ModuleNotFoundError: tests.e2e.polygon_capture`)

Run: `uv run pytest tests/e2e/test_polygon_capture.py -q`

**Step 3: Implement `tests/e2e/polygon_capture.py`**

```python
"""A recording fake for the Polygon API client used by e2e statement-upload
scenarios. Patched in over ``rbx.box.packaging.polygon.upload._get_polygon_api``
so ``rbx package polygon -u`` performs no network I/O while every uploaded
statement and statement resource is serialized to disk for the
``polygon_upload`` e2e matcher to assert on.
"""

import json
import threading
from pathlib import Path
from typing import List, Optional

# Module-level holder for the active capture directory. The e2e runner sets this
# to ``<pkg_tmpdir>/.rbx/polygon_capture`` before each scenario's steps and resets
# it afterwards, so concurrent scenarios in one process do not leak.
_CAPTURE_DIR: Optional[Path] = None
_LOCK = threading.Lock()


def set_capture_dir(path: Path) -> None:
    global _CAPTURE_DIR
    _CAPTURE_DIR = Path(path)


def get_capture_dir() -> Optional[Path]:
    return _CAPTURE_DIR


def reset_capture_dir() -> None:
    global _CAPTURE_DIR
    _CAPTURE_DIR = None


class RecordingProblem:
    def __init__(self, capture_dir: Path):
        self._dir = capture_dir
        (self._dir / 'statements').mkdir(parents=True, exist_ok=True)
        (self._dir / 'resources').mkdir(parents=True, exist_ok=True)
        self._resources: List[str] = []
        self._calls: List[dict] = []

    # --- recorded statement surface -------------------------------------
    def save_statement(self, lang: str, problem_statement) -> None:
        s = problem_statement
        payload = {
            'name': s.name,
            'legend': s.legend,
            'input': s.input,
            'output': s.output,
            'interaction': getattr(s, 'interaction', None),
            'notes': s.notes,
        }
        with _LOCK:
            (self._dir / 'statements' / f'{lang}.json').write_text(
                json.dumps(payload, ensure_ascii=False, indent=2)
            )

    def save_statement_resource(self, name: str, file: bytes) -> None:
        with _LOCK:
            (self._dir / 'resources' / name).write_bytes(file)
            self._resources.append(name)
            (self._dir / 'resources.json').write_text(
                json.dumps(sorted(set(self._resources)), ensure_ascii=False, indent=2)
            )

    # --- everything else: record-and-ignore ------------------------------
    def _record(self, method: str, **kw) -> None:
        with _LOCK:
            self._calls.append({'method': method, **{k: str(v) for k, v in kw.items()}})
            (self._dir / 'calls.json').write_text(
                json.dumps(self._calls, ensure_ascii=False, indent=2)
            )

    def update_info(self, info) -> None:
        self._record('update_info')

    def save_file(self, type=None, name=None, file=None, source_type=None) -> None:
        self._record('save_file', name=name, type=type)

    def set_checker(self, name) -> None:
        self._record('set_checker', name=name)

    def set_interactor(self, name) -> None:
        self._record('set_interactor', name=name)

    def set_validator(self, name) -> None:
        self._record('set_validator', name=name)

    def save_solution(self, name, content, source_type=None, tag=None) -> None:
        self._record('save_solution', name=name, tag=tag)

    def solutions(self) -> list:
        return []

    def save_test(self, *args, **kw) -> None:
        self._record('save_test', index=kw.get('test_index'))

    def save_script(self, testset=None, source=None) -> None:
        self._record('save_script', testset=testset)

    def commit_changes(self) -> None:
        self._record('commit_changes')


class RecordingPolygon:
    def __init__(self, capture_dir: Path):
        self._dir = capture_dir

    def problems_list(self, name: Optional[str] = None) -> list:
        return []

    def problem_create(self, name: str) -> RecordingProblem:
        return RecordingProblem(self._dir)


def make_recording_polygon(*args, **kwargs) -> RecordingPolygon:
    """Factory patched in over ``upload._get_polygon_api`` (ignores api url/keys)."""
    capture_dir = get_capture_dir()
    if capture_dir is None:
        raise RuntimeError(
            'polygon_capture.make_recording_polygon called with no capture dir set; '
            'the e2e runner must set_capture_dir before running steps'
        )
    capture_dir.mkdir(parents=True, exist_ok=True)
    return RecordingPolygon(capture_dir)
```

**Step 4: Run the test — expect PASS**

Run: `uv run pytest tests/e2e/test_polygon_capture.py -q`

NOTE: confirm `api.Statement(...)` accepts those kwargs (it does — see
`polygon_api.py` `Statement`; `interaction`/`scoring`/`tutorial` are optional). If
`Statement` is a dataclass requiring all positional fields, adapt the test's
construction but NOT the fake.

**Step 5: Commit**

```bash
git add tests/e2e/polygon_capture.py tests/e2e/test_polygon_capture.py
git commit -m "test(e2e): add recording Polygon fake capturing statement uploads"
```

---

### Task A3: `polygon_upload` matcher (spec + assertion)

**Files:**
- Modify: `tests/e2e/spec.py` (add `PolygonUploadMatcher`, `StatementExpect`, and the
  `polygon_upload` field on `Expect`)
- Modify: `tests/e2e/assertions.py` (add `check_polygon_upload`)
- Modify: `tests/e2e/runner.py` (register in `_GENERIC_CHECKS`)
- Test: `tests/e2e/test_polygon_capture.py` (extend with matcher tests)

**Matcher schema** (Pydantic, `extra='forbid'`):
```python
class StatementExpect(_Forbid):
    name_contains: Union[str, List[str], None] = None
    legend_contains: Union[str, List[str], None] = None
    input_contains: Union[str, List[str], None] = None
    output_contains: Union[str, List[str], None] = None
    interaction_contains: Union[str, List[str], None] = None
    notes_contains: Union[str, List[str], None] = None


class PolygonUploadMatcher(_Forbid):
    """Assertions over the recording-fake capture written by ``package polygon -u``.

    ``dir`` is the capture directory relative to the package root (default
    ``.rbx/polygon_capture``; override when the upload ran in a subdir, e.g.
    ``A/.rbx/polygon_capture``).
    """
    dir: str = '.rbx/polygon_capture'
    statements: Dict[str, StatementExpect] = Field(default_factory=dict)
    resources_present: List[str] = Field(default_factory=list)
    resources_absent: List[str] = Field(default_factory=list)
    resources_referenced_consistent: Optional[bool] = None
```
Add `polygon_upload: Optional[PolygonUploadMatcher] = None` to `Expect`.

**Referential-integrity semantics** (`resources_referenced_consistent: true`):
parse every `\includegraphics{...}` (and `\includegraphics[opts]{...}`) argument
across all uploaded statement fields; for each referenced token assert a matching
uploaded resource exists. Match rule: exact name match against the uploaded resource
set; if no exact match, also accept a match where the reference equals an uploaded
resource name with its suffix stripped (covers `\includegraphics{img__d}` ↔
`img__d.png`). Any reference with no match fails the assertion and the message lists
the orphan reference plus the available resource names (this is the assertion that
surfaces the root-vs-subdir remap asymmetry bug, audit finding #1/#3).

**Step 1: Write failing matcher tests** (append to `tests/e2e/test_polygon_capture.py`)

```python
import pytest

from tests.e2e.assertions import AssertionContext, check_polygon_upload
from tests.e2e.spec import PolygonUploadMatcher


def _ctx(pkg_root):
    return AssertionContext(package_root=pkg_root, stdout='', stderr='')


def _write_capture(pkg_root, *, legend, resources):
    import json
    cap = pkg_root / '.rbx' / 'polygon_capture'
    (cap / 'statements').mkdir(parents=True, exist_ok=True)
    (cap / 'resources').mkdir(parents=True, exist_ok=True)
    (cap / 'statements' / 'english.json').write_text(json.dumps({
        'name': 'Title', 'legend': legend, 'input': 'in', 'output': 'out',
        'interaction': None, 'notes': '',
    }))
    for r in resources:
        (cap / 'resources' / r).write_bytes(b'x')
    (cap / 'resources.json').write_text(json.dumps(sorted(resources)))


def test_polygon_upload_matcher_passes(tmp_path):
    _write_capture(tmp_path, legend=r'\includegraphics{foo.pdf}', resources=['foo.pdf'])
    m = PolygonUploadMatcher(
        statements={'english': {'legend_contains': 'includegraphics', 'name_contains': 'Title'}},
        resources_present=['foo.pdf'],
        resources_referenced_consistent=True,
    )
    check_polygon_upload(_ctx(tmp_path), m)  # no raise


def test_polygon_upload_matcher_detects_orphan_reference(tmp_path):
    _write_capture(tmp_path, legend=r'\includegraphics{missing.pdf}', resources=['foo.pdf'])
    m = PolygonUploadMatcher(resources_referenced_consistent=True)
    with pytest.raises(AssertionError, match='missing.pdf'):
        check_polygon_upload(_ctx(tmp_path), m)
```

**Step 2: Run — expect failure** (`ImportError: PolygonUploadMatcher` / `check_polygon_upload`)

**Step 3: Implement the schema** in `tests/e2e/spec.py` (add the two classes above
near the other matchers; add the `polygon_upload` field to `Expect`). The
`StatementExpect` value in the `statements` dict is coerced from a plain dict by
Pydantic automatically.

**Step 4: Implement `check_polygon_upload`** in `tests/e2e/assertions.py`:

```python
import json
import re

_INCLUDEGRAPHICS_RE = re.compile(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}')


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def check_polygon_upload(ctx: 'AssertionContext', matcher) -> None:
    cap = ctx.package_root / matcher.dir
    if not cap.is_dir():
        raise AssertionError(f'polygon capture dir not found: {matcher.dir}')

    resources_json = cap / 'resources.json'
    uploaded = set(json.loads(resources_json.read_text())) if resources_json.is_file() else set()

    for name in matcher.resources_present:
        if name not in uploaded:
            raise AssertionError(
                f'expected uploaded resource {name!r}; uploaded: {sorted(uploaded)}'
            )
    for name in matcher.resources_absent:
        if name in uploaded:
            raise AssertionError(f'resource {name!r} should NOT have been uploaded')

    statements = {}
    for lang, expect in matcher.statements.items():
        path = cap / 'statements' / f'{lang}.json'
        if not path.is_file():
            raise AssertionError(
                f'no statement uploaded for language {lang!r}; '
                f'present: {[p.stem for p in (cap / "statements").glob("*.json")]}'
            )
        data = json.loads(path.read_text())
        statements[lang] = data
        for field in ('name', 'legend', 'input', 'output', 'interaction', 'notes'):
            for needle in _as_list(getattr(expect, f'{field}_contains')):
                if needle not in (data.get(field) or ''):
                    raise AssertionError(
                        f'statement[{lang}].{field} missing {needle!r}; '
                        f'got: {data.get(field)!r}'
                    )

    if matcher.resources_referenced_consistent:
        # Load every uploaded statement (not just the asserted ones).
        all_statements = {
            p.stem: json.loads(p.read_text())
            for p in (cap / 'statements').glob('*.json')
        }
        stems = {n: n.rsplit('.', 1)[0] for n in uploaded}
        for lang, data in all_statements.items():
            for field in ('legend', 'input', 'output', 'interaction', 'notes'):
                text = data.get(field) or ''
                for ref in _INCLUDEGRAPHICS_RE.findall(text):
                    ok = ref in uploaded or ref in stems.values() or any(
                        ref == s for s in stems.values()
                    )
                    if not ok:
                        raise AssertionError(
                            f'statement[{lang}].{field} references \\includegraphics'
                            f'{{{ref}}} but no matching resource was uploaded; '
                            f'uploaded: {sorted(uploaded)}'
                        )
```

**Step 5: Register the check** in `tests/e2e/runner.py` `_GENERIC_CHECKS` (add the
import and the tuple entry):
```python
from tests.e2e.assertions import (..., check_polygon_upload, ...)
...
    ('polygon_upload', check_polygon_upload),
```
Note: `_run_generic_assertions` already skips `None` values, so non-polygon scenarios
are unaffected.

**Step 6: Run matcher tests — expect PASS**

Run: `uv run pytest tests/e2e/test_polygon_capture.py -q`

**Step 7: Commit**

```bash
git add tests/e2e/spec.py tests/e2e/assertions.py tests/e2e/runner.py tests/e2e/test_polygon_capture.py
git commit -m "test(e2e): add polygon_upload matcher with includegraphics integrity check"
```

---

### Task A4: Wire the capture dir + conditional pdflatex into the runner/conftest

**Files:**
- Modify: `tests/e2e/runner.py` (`E2EScenarioItem.runtest`: set/reset capture dir)
- Modify: `tests/e2e/conftest.py` (recording-fake autouse fixture; conditional
  `mock_pdflatex`)

**Step 1 (runner): set the capture dir around the steps.**

In `E2EScenarioItem.runtest`, after `pkg_dir` is established and before the steps
loop, set the capture dir; reset in `finally`:
```python
from tests.e2e import polygon_capture
...
            polygon_capture.set_capture_dir(pkg_dir / CACHE_DIR_NAME / 'polygon_capture')
            try:
                testing_utils.clear_all_functools_cache()
                with _snapshot_e2e_contextvars():
                    for step in self.scenario.steps:
                        run_step(self.path, self.scenario.name, step, pkg_dir)
            finally:
                polygon_capture.reset_capture_dir()
                testing_utils.clear_all_functools_cache()
                ...
```
`CACHE_DIR_NAME` is already imported in runner.py and equals `.rbx` (verify); the
matcher default `dir` (`.rbx/polygon_capture`) must match it. If `CACHE_DIR_NAME` is
not literally `.rbx`, set the matcher default and this path from the same constant or
hardcode `.rbx` in both consistently. (Confirm `CACHE_DIR_NAME == '.rbx'` via
`python -c "from rbx.config import CACHE_DIR_NAME; print(CACHE_DIR_NAME)"`.)

**Step 2 (conftest): patch the client factory (autouse, function-scoped).**

```python
@pytest.fixture(autouse=True)
def mock_polygon_api(monkeypatch):
    from tests.e2e import polygon_capture
    monkeypatch.setattr(
        'rbx.box.packaging.polygon.upload._get_polygon_api',
        polygon_capture.make_recording_polygon,
    )
```
This is harmless for non-upload scenarios (never called).

**Step 3 (conftest): make `mock_pdflatex` conditional.**

Replace the session-scoped `mock_pdflatex` with a function-scoped one that skips the
stub for `pdflatex`-marked items (and skips the test when the binary is missing):
```python
import shutil

@pytest.fixture(autouse=True)
def mock_pdflatex(request, monkeypatch):
    if request.node.get_closest_marker('pdflatex'):
        if shutil.which('pdflatex') is None:
            pytest.skip('pdflatex not installed; required by this scenario')
        return  # use the real Latex.build_pdf (real TikZ externalization)
    monkeypatch.setattr(
        'rbx.box.statements.latex.Latex.build_pdf',
        lambda *args, **kwargs: LatexResult(
            result=subprocess.CompletedProcess(args='', returncode=0, stdout=b'', stderr=b''),
            pdf=b'',
        ),
    )
```
Delete the now-unused session-scoped variant and the `monkeysession` use for it
(keep `monkeysession` if other fixtures still use it — `mock_app_path`,
`precompilation_should_use_tmp_cache` do; leave those as-is).

**Step 4: Sanity-run the existing (mocked) statement scenarios — must still pass.**

Run: `uv run pytest -m 'e2e and not docker and not pdflatex' -k 'with_statement or default_preset' -q`
Expected: the existing `with-statement` and `default-preset` scenarios still PASS
(they have no `pdflatex` marker, so the stub still applies).

**Step 5: Commit**

```bash
git add tests/e2e/runner.py tests/e2e/conftest.py
git commit -m "test(e2e): wire polygon capture + make pdflatex mock conditional on marker"
```

---

### Task A5: mise tasks for the pdflatex e2e category

**Files:**
- Modify: `mise.toml:37-39` (and the default `test-e2e`)

**Step 1: Edit tasks.** Change `test-e2e` to exclude pdflatex and add a dedicated task:
```toml
[tasks.test-e2e]
description = "Run e2e tests"
run = "pytest -m 'e2e and not docker and not pdflatex'"

[tasks.test-e2e-pdflatex]
description = "Run e2e tests that need a real pdflatex (TikZ externalization)"
run = "pytest -m 'e2e and pdflatex and not docker' -v"
```
(Leave `test`, `test-slow`, `test-docker` unchanged.)

**Step 2: Verify selection (no scenarios yet → 0 selected, exit ok).**

Run: `uv run pytest -m 'e2e and pdflatex and not docker' -q`
Expected: "no tests ran" (exit 5) — acceptable before fixtures exist; do not commit a
broken selector. Also run `uv run pytest -m 'e2e and not docker and not pdflatex' -q`
and confirm the existing e2e suite still collects/passes.

**Step 3: Commit**

```bash
git add mise.toml
git commit -m "build(mise): add test-e2e-pdflatex task; exclude pdflatex from test-e2e"
```

---

## Phase B — Suite 1: default-preset statement upload

### Task B1: Fixture `tests/e2e/testdata/polygon-default-preset/`

Seed from the real `default` preset problem package (proven by the existing
`default-preset` fixture) and grill the full upload.

**Files:**
- Create: `tests/e2e/testdata/polygon-default-preset/e2e.rbx.yml`
- Create: `tests/e2e/testdata/polygon-default-preset/.gitignore` (copy of
  `tests/e2e/testdata/default-preset/.gitignore`)

**`e2e.rbx.yml`:**
```yaml
scenarios:
  - name: polygon-upload-default-preset
    markers: [pdflatex]
    seed_from_preset: default
    description: >
      Seed the real rbx default-preset problem package, build it, build the
      standalone statement with a real pdflatex, then run the Polygon API upload
      against a recording fake (no network) and assert the captured statement
      blocks. Exercises the bundled-default standalone template + sample
      explanation merged into notes.
    steps:
      - cmd: build
        expect:
          tests:
            groups:
              samples: 2
      - cmd: st b
        expect:
          files_exist:
            - build/statement-en.pdf
      - cmd: package polygon -u --upload-as-english
        expect:
          stdout_contains: "uploaded successfully"
          polygon_upload:
            statements:
              english:
                name_contains: "New problem"
                legend_contains: ["A + B", "A", "B"]
                input_contains: "single line"
                output_contains: "sum"
                notes_contains:
                  - "No notes"
                  - "Explanation for example 1"
            resources_referenced_consistent: true
```

Notes / fallbacks for the executor:
- Use `--upload-as-english` so the uploaded language key is `english` (see
  `process_statements`: only `--upload-as-english` maps the main lang to `english`;
  otherwise the key is the resolved language name e.g. `english` already for `en`?).
  CONFIRM the actual key by inspecting `cap/statements/*.json` after a first run and
  adjust the `statements:` key to match (`code_to_langs(['en'])[0]`).
- The default-preset statement has no images/TikZ, so
  `resources_referenced_consistent: true` holds vacuously (no `\includegraphics`).
- If the full `package polygon -u` proves fragile (e.g. generator/test extraction on
  a samples-only build), fall back to `package polygon -u --upload-only statements`
  — it skips the source/solution/test upload and isolates the statement path. Record
  the choice in the scenario `description`.
- The `notes_contains: "Explanation for example 1"` assertion proves the sample
  explanation (from `statement/samples/000.rbx.tex`) was merged into `notes`.

**Step 1: Run the scenario** (real pdflatex required):

Run: `uv run pytest tests/e2e/testdata/polygon-default-preset/e2e.rbx.yml -v`

**Step 2: Inspect/adjust.** On first run, if assertions about exact field text fail,
read the captured JSON the test wrote (re-run with the fake pointing at a tmp, or add
a temporary `-s` print) and tune the `*_contains` needles to the real rendered text.
Keep needles minimal and robust (short, stable substrings).

**Step 3: Commit**

```bash
git add tests/e2e/testdata/polygon-default-preset/
git commit -m "test(e2e): grill polygon statement upload on the default preset"
```

---

## Phase C — Suite 2: bespoke TikZ + images + sample-explanation assets

### Task C1: Fixture package `tests/e2e/testdata/polygon-tikz-assets/`

A self-contained contest + one problem `A` exercising, simultaneously: a TikZ picture
in the legend, a root-level static image in the statement, a subdirectory static image
in the statement (to exercise the `/`→`__` remap), a TikZ picture in a sample
explanation, and an image in a sample explanation.

**Files (create all):**
- `tests/e2e/testdata/polygon-tikz-assets/e2e.rbx.yml`
- `tests/e2e/testdata/polygon-tikz-assets/contest.rbx.yml`
- `tests/e2e/testdata/polygon-tikz-assets/statements/problem-standalone.rbx.tex`
- `tests/e2e/testdata/polygon-tikz-assets/statements/problem-in-contest.rbx.tex`
- `tests/e2e/testdata/polygon-tikz-assets/statements/contest.rbx.tex`
- `tests/e2e/testdata/polygon-tikz-assets/A/problem.rbx.yml`
- `tests/e2e/testdata/polygon-tikz-assets/A/sols/main.cpp`
- `tests/e2e/testdata/polygon-tikz-assets/A/gens/gen.cpp`
- `tests/e2e/testdata/polygon-tikz-assets/A/statement/statement.rbx.tex`
- `tests/e2e/testdata/polygon-tikz-assets/A/statement/pic.png` (root-level asset)
- `tests/e2e/testdata/polygon-tikz-assets/A/statement/img/diagram.png` (subdir asset)
- `tests/e2e/testdata/polygon-tikz-assets/A/statement/samples/000.in`
- `tests/e2e/testdata/polygon-tikz-assets/A/statement/samples/000.rbx.tex` (explanation
  with TikZ + an image)
- `tests/e2e/testdata/polygon-tikz-assets/A/statement/samples/expl.png` (explanation image)
- `tests/e2e/testdata/polygon-tikz-assets/.gitignore`

Model the contest + templates on `tests/e2e/testdata/with-statement/` (kept minimal so
the real pdflatex compile is fast and the externalized set is fully controlled).

**Tiny PNG generation** (one valid 1×1 PNG, reused for all three images):
```bash
python -c "import base64,pathlib; \
b=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='); \
[pathlib.Path(p).parent.mkdir(parents=True,exist_ok=True) or pathlib.Path(p).write_bytes(b) for p in [ \
 'tests/e2e/testdata/polygon-tikz-assets/A/statement/pic.png', \
 'tests/e2e/testdata/polygon-tikz-assets/A/statement/img/diagram.png', \
 'tests/e2e/testdata/polygon-tikz-assets/A/statement/samples/expl.png']]"
```

**`contest.rbx.yml`** (mirror with-statement):
```yaml
name: polygon-tikz-assets
titles:
  en: TikZ Assets Contest

problems:
  - short_name: A

statements:
  - name: main-en
    language: en
    file: statements/contest.rbx.tex
    type: rbx-tex
    standaloneProblemTemplate: statements/problem-standalone.rbx.tex
    contestProblemTemplate: statements/problem-in-contest.rbx.tex
```

**`A/problem.rbx.yml`:**
```yaml
name: tikz-assets
timeLimit: 1000
memoryLimit: 256

generators:
  - name: gen
    path: gens/gen.cpp

solutions:
  - path: sols/main.cpp
    outcome: ac

testcases:
  - name: samples
    testcaseGlob: statement/samples/*.in

statements:
  - language: en
    title: TikZ Assets
    file: statement/statement.rbx.tex
    type: rbx-tex
```

**`A/statement/statement.rbx.tex`** — legend has TikZ + a root image + a subdir image:
```latex
%- block legend
Here is a diagram drawn with TikZ:

\begin{tikzpicture}
  \draw (0,0) -- (1,1) -- (2,0) -- cycle;
\end{tikzpicture}

A root-level static image: \includegraphics[width=1cm]{pic}.

A nested static image: \includegraphics[width=1cm]{img/diagram}.
%- endblock

%- block input
A single line with two integers $A$ and $B$.
%- endblock

%- block output
The sum $A + B$.
%- endblock

%- block notes
See the example explanation below.
%- endblock
```

**`A/statement/samples/000.rbx.tex`** — explanation with TikZ + an image:
```latex
%- block en
The figure illustrates the example:

\begin{tikzpicture}
  \draw (0,0) circle (0.5);
\end{tikzpicture}

And an attached image: \includegraphics[width=1cm]{samples/expl}.
%- endblock
```
(`000.in` contains e.g. `3 7`; `gen.cpp`/`main.cpp` are A+B copies of the
with-statement fixture.)

**Standalone/in-contest/contest templates:** copy
`tests/e2e/testdata/with-statement/statements/*.rbx.tex` verbatim (they render
`problem.blocks.legend/input/output` + samples; that is sufficient — the asset macros
live inside the blocks).

**`e2e.rbx.yml`:**
```yaml
scenarios:
  - name: polygon-upload-tikz-and-images
    markers: [pdflatex]
    description: >
      One problem carrying, simultaneously, a TikZ picture in the legend, a
      root-level static image, a nested (subdir) static image, plus a sample
      explanation that itself contains a TikZ picture and an image. Build the
      statement with a real pdflatex (TikZ externalized to PDFs), then run the
      Polygon upload against the recording fake and assert every referenced
      asset was uploaded as a resource and that \includegraphics references in
      the uploaded blocks resolve (referential integrity).
    steps:
      - cmd: build
        cwd: A
      - cmd: st b
        cwd: A
        expect:
          files_exist:
            - A/build/statement-en.pdf
      - cmd: package polygon -u --upload-as-english --upload-only statements
        cwd: A
        expect:
          stdout_contains: "uploaded successfully"
          polygon_upload:
            dir: A/.rbx/polygon_capture
            statements:
              english:
                legend_contains: ["includegraphics"]
                notes_contains: ["Explanation for example 1"]
            resources_present:
              - "img__diagram.png"
            resources_referenced_consistent: true
```

Executor notes / expected discoveries (this is the grilling — record outcomes in the
audit, Task D/E):
- The **subdir** image `img/diagram` → uploaded as `img__diagram.png` with a block
  rewrite (so it is in `resources_present` and consistent).
- The **root** image `pic` → uploaded as `pic.png` but the block keeps
  `\includegraphics{pic}` (no remap entry). The integrity check accepts this via the
  suffix-stripped match (`pic` ↔ `pic.png` stem). If the actual block text differs
  (e.g. keeps `{pic}` while the resource is `pic.png`), confirm whether Polygon would
  resolve it; document the asymmetry in the audit regardless.
- The **legend TikZ** → one externalized PDF, uploaded as
  `artifacts__tikz_figures__<label>.pdf`, block rewritten to match → consistent.
- The **sample-explanation TikZ and image** are the high-risk case (audit #4). If they
  are NOT externalized/uploaded (e.g. raw `\tikzpicture` survives in `notes`, or
  `samples/expl` is never uploaded), `resources_referenced_consistent: true` and/or
  `notes_contains` will fail. When that happens:
  1. Confirm it is a real bug (inspect the captured `notes` and `resources.json`).
  2. Document it in the audit (Task E) as a finding.
  3. Mark the failing assertion's scenario `xfail` by SPLITTING the explanation-asset
     assertions into their own scenario and adding it to an xfail list — but the e2e
     DSL has no per-scenario xfail. Instead, encode the *current* (buggy) behavior in
     this scenario so the suite is green and accurately documents reality, and add a
     second scenario `polygon-explanation-assets-known-gap` whose assertions encode the
     DESIRED behavior and register it as xfail in `conftest.py`
     `pytest_collection_modifyitems` (add `item.add_marker(pytest.mark.xfail(reason=...))`
     when `item.name == 'polygon-explanation-assets-known-gap'`). Keep the xfail
     non-strict (`strict=False`) so it flips to xpass when fixed.
  - If, instead, explanation assets DO externalize/upload correctly, drop the xfail
    scenario and assert the explanation image resource is present.

**Step 1: Generate PNGs** (command above).

**Step 2: Run the scenario:**

Run: `uv run pytest tests/e2e/testdata/polygon-tikz-assets/e2e.rbx.yml -v`

**Step 3: Iterate** on assertions to match observed-correct behavior; split out and
xfail the genuinely-broken parts (per notes above). Capture findings for the audit.

**Step 4: Commit**

```bash
git add tests/e2e/testdata/polygon-tikz-assets/
git commit -m "test(e2e): grill polygon upload of tikz + image + explanation assets"
```

---

## Phase D — Run the full pdflatex suite; classify failures

### Task D1: Run and triage

**Step 1:** `uv run pytest -m 'e2e and pdflatex and not docker' -v` (or
`mise run test-e2e-pdflatex`).

**Step 2:** For each failure, decide: (a) my assertion/fixture is wrong → fix it; or
(b) a real upload bug → leave the scenario encoding actual behavior, add an xfail
scenario encoding desired behavior, and note it for the audit. Do NOT change
`rbx/box/...` upload logic in this PR (fixes are a separate PR per the design).

**Step 3:** Re-run until green (real xpass-free except intended xfails). Commit any
fixture/assertion adjustments with `test(e2e): ...` messages.

---

## Phase E — Written audit

### Task E1: `docs/plans/2026-06-10-polygon-statement-upload-audit.md`

**Files:**
- Create: `docs/plans/2026-06-10-polygon-statement-upload-audit.md`

Write the audit with: a short data-flow recap; then a table/section per risk area
with a verdict (correct / suspicious / bug), the evidence (which scenario + which
captured artifact demonstrates it), and a recommended follow-up fix. Cover at least:

1. Resource-name rewriting — `_replace_resources` naive per-key `str.replace`
   (substring-collision / ordering risk); the **root-vs-subdir remap asymmetry**
   (`upload.py:613-623`: only multi-parent assets get a `res` remap entry).
2. TikZ externalization round-trip (legend) — verdict from Suite 2 (should be
   correct: `artifacts/tikz_figures/<label>` ↔ `artifacts__tikz_figures__<label>.pdf`).
3. Subdirectory asset flattening (`img/diagram` ↔ `img__diagram.png`) — verdict.
4. **Sample-explanation assets** — whether explanation TikZ/images are externalized,
   uploaded, and path-rewritten when merged into `notes` (the most likely gap).
5. Macro filter/expansion; notes merge ordering (`upload.py:660-669`); interaction
   only for COMMUNICATION; `--upload-as-english` language mapping; 255-char comment
   cap (`api.COMMENT_LENGTH_LIMIT`).

Each finding links the scenario name and, where a bug is confirmed, the xfail marker
that documents it. End with a prioritized follow-up-fix list (for the separate PR).

**Step 1: Write the doc.** **Step 2: Commit**

```bash
git add docs/plans/2026-06-10-polygon-statement-upload-audit.md
git commit -m "docs(statements): audit of the polygon statement-upload path (#586)"
```

---

## Phase F — Verification & wrap-up

### Task F1: Full verification

**Step 1:** `uv run ruff format . && uv run ruff check .` → clean (only touched files).

**Step 2:** Default suite unaffected:
`uv run pytest tests/e2e -m 'e2e and not docker and not pdflatex' -q` → PASS
(existing scenarios + our matcher unit tests).

**Step 3:** pdflatex suite green:
`mise run test-e2e-pdflatex` → PASS (with intended xfails only).

**Step 4:** `uv run pytest tests/e2e/test_polygon_capture.py -q` → PASS.

### Task F2: Docs touch-ups

- Update `tests/e2e/README.md` to document the `pdflatex` marker, the
  `test-e2e-pdflatex` command, and the `polygon_upload` matcher (schema + the
  `resources_referenced_consistent` semantics).
- If warranted, add one line to `rbx/box/packaging/CLAUDE.md` pointing at the new
  audit doc / e2e coverage.

Commit: `docs(e2e): document pdflatex marker and polygon_upload matcher`.

### Task F3: Finish the branch

Use the superpowers:finishing-a-development-branch skill to open a PR referencing
#586. PR body: summary of the e2e harness additions, the two suites, the audit
findings (with the prioritized follow-up-fix list noted as out-of-scope for this PR).

---

## Open items the executor must resolve at implementation time

1. **Capture-dir constant**: confirm `rbx.config.CACHE_DIR_NAME == '.rbx'` so the
   matcher default (`.rbx/polygon_capture`) and runner path agree.
2. **`api.Statement` constructor**: confirm kwargs (`encoding/name/legend/input/
   output/interaction/notes`) — adjust only the *test*, never the fake interface.
3. **Uploaded language key**: confirm the `statements/<lang>.json` key for `en`
   (`code_to_langs(['en'])[0]`, e.g. `english`) and with/without `--upload-as-english`;
   set the matcher `statements:` keys accordingly.
4. **Full `-u` vs `--upload-only statements`** for Suite 1: prefer full `-u`; fall
   back to `--upload-only statements` if the samples-only build makes test/generator
   extraction fragile. Record the choice in the scenario description.
5. **Explanation-asset behavior** (Suite 2): determine empirically whether explanation
   TikZ/images externalize+upload; encode actual behavior green + an xfail scenario for
   the desired behavior if it is a real gap.
