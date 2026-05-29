# BocaNext Layer 2 Runtime (`rbx_boca`) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the judge-side Python runtime library (`rbx_boca`) that BocaNext bundles into each `.pyz` to compile, run, and judge BOCA submissions — replacing the duplicated bash scripts with one tested, composable, stdlib-only package.

**Architecture:** `rbx_boca` is a standalone, stdlib-only Python package authored in the rbx source tree and (later, by Layer 1 — issue #489) zipapp-bundled into each `compile/run/compare/limits/tests` script. This plan builds Layer 2 ONLY. It is structured bottom-up: pure logic first (verdicts, manifest, language engine, safeexec argv), then side-effecting units behind injectable seams (sandbox/asset executors, tasks), then the entrypoint dispatcher and a `zipapp`-based integration harness with a stub `safeexec`. Layer 1 (env→spec resolution, real bundling, CLI) is out of scope.

**Tech Stack:** Python 3.8+ stdlib only (`dataclasses`, `pathlib`, `subprocess`, `hashlib`, `zipapp`, `resource`, `signal`), pytest. No third-party runtime deps — the bundle must run on a bare BOCA judge.

**Design reference:** `docs/plans/2026-05-29-boca-next-python-packager-design.md`. Source of truth for current behavior: `rbx/resources/packagers/boca/` (esp. `interactor_run.sh`, `compare.sh`, `pipe.c`, `safeexec.c`, `run/*`, `compile/*`).

**Conventions:**
- Project enforces Conventional Commits via commitizen. Use the `/commit` skill workflow for each commit step; the messages below are the intended subjects.
- Absolute imports only (ruff `TID`). Inside `rbx_boca`, import as `rbx_boca.<module>` so imports are identical in-repo and in-bundle.
- Single quotes (ruff format). Run `uv run ruff format .` and `uv run ruff check --fix .` before each commit.
- Run tests with `uv run pytest tests/rbx/box/packaging/boca_next/ -v`.

---

## Phase 0 — Scaffolding

### Task 0.1: Create the runtime package and make it importable in tests

**Files:**
- Create: `rbx/resources/packagers/boca_next/runtime/rbx_boca/__init__.py` (empty)
- Create: `tests/rbx/box/packaging/boca_next/__init__.py` (empty)
- Create: `tests/rbx/box/packaging/boca_next/conftest.py`
- Test: `tests/rbx/box/packaging/boca_next/test_import.py`

**Step 1: Write the failing test**

```python
# tests/rbx/box/packaging/boca_next/test_import.py
def test_rbx_boca_importable():
    import rbx_boca  # noqa: F401
```

**Step 2: Run it to verify it fails**

Run: `uv run pytest tests/rbx/box/packaging/boca_next/test_import.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rbx_boca'`

**Step 3: Make it importable**

Create the empty `__init__.py` files above, then the conftest that puts the runtime dir on `sys.path` exactly as the `.pyz` does on the judge:

```python
# tests/rbx/box/packaging/boca_next/conftest.py
import sys
from pathlib import Path

_RUNTIME = (
    Path(__file__).resolve().parents[4]
    / 'rbx'
    / 'resources'
    / 'packagers'
    / 'boca_next'
    / 'runtime'
)
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))
```

> Verify `parents[4]` resolves to the repo root from
> `tests/rbx/box/packaging/boca_next/conftest.py` (4 levels up). Adjust the index
> if the test fails to find the runtime.

**Step 4: Run it to verify it passes**

Run: `uv run pytest tests/rbx/box/packaging/boca_next/test_import.py -v`
Expected: PASS

**Step 5: Commit**

`chore: scaffold rbx_boca runtime package and test harness`

---

## Phase 1 — `verdicts.py` (pure exit-code logic)

This is the highest-value, fully-pure module. Behavior verified against
`rbx/resources/packagers/boca/compare.sh` and `interactor_run.sh`.

### Task 1.1: `PipeLog` parser

**Files:**
- Create: `rbx/resources/packagers/boca_next/runtime/rbx_boca/verdicts.py`
- Test: `tests/rbx/box/packaging/boca_next/test_verdicts.py`

**Step 1: Write the failing test**

```python
# tests/rbx/box/packaging/boca_next/test_verdicts.py
import pytest
from rbx_boca import verdicts


def test_pipelog_parses_three_lines():
    log = verdicts.PipeLog.parse('2\n0\n1\n')
    assert log == verdicts.PipeLog(first_tag=2, solution_status=0, interactor_status=1)


def test_pipelog_tolerates_whitespace():
    log = verdicts.PipeLog.parse(' 1 \n 139 \n 0 \n')
    assert log == verdicts.PipeLog(first_tag=1, solution_status=139, interactor_status=0)


def test_pipelog_rejects_short_log():
    with pytest.raises(ValueError):
        verdicts.PipeLog.parse('1\n0\n')
```

**Step 2: Run to verify it fails** — `ModuleNotFoundError`/`AttributeError`.

**Step 3: Implement**

```python
# rbx/resources/packagers/boca_next/runtime/rbx_boca/verdicts.py
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PipeLog:
    """Parsed pipe.log: see rbx/resources/packagers/boca/pipe.c lines 359-362."""

    first_tag: int  # 1 = solution exited first, 2 = interactor exited first
    solution_status: int  # bash-like: 0-255, or 128+signal
    interactor_status: int

    @staticmethod
    def parse(text: str) -> 'PipeLog':
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() != '']
        if len(lines) < 3:
            raise ValueError(f'pipe.log must have 3 numeric lines, got: {text!r}')
        return PipeLog(int(lines[0]), int(lines[1]), int(lines[2]))
```

**Step 4: Run to verify it passes.**

**Step 5: Commit** — `feat: add PipeLog parser to rbx_boca verdicts`

### Task 1.2: `batch_run_exit` mapper

**Step 1: Write the failing test** (append to `test_verdicts.py`)

```python
@pytest.mark.parametrize(
    'safeexec_exit,expected',
    [
        (0, 0),     # OK
        (3, 3),     # TLE
        (7, 7),     # MLE
        (2, 2),     # RTE (signal)
        (9, 9),     # RTE (abnormal)
        (10, 10),   # boundary: not remapped
        (11, 9),    # child nonzero (1+10) -> RTE
        (52, 9),    # child nonzero (42+10) -> RTE
    ],
)
def test_batch_run_exit(safeexec_exit, expected):
    assert verdicts.batch_run_exit(safeexec_exit) == expected
```

**Step 2: Run to verify it fails.**

**Step 3: Implement** (append to `verdicts.py`)

```python
def batch_run_exit(safeexec_exit: int) -> int:
    """Map safeexec's exit code to the run-script exit code BOCA expects.

    Mirrors rbx/resources/packagers/boca/run/* : codes > 10 (child exited with
    nonzero N, reported as N+10) collapse to 9 (runtime error).
    """
    return 9 if safeexec_exit > 10 else safeexec_exit
```

**Step 4: Run to verify it passes. Step 5: Commit** — `feat: add batch_run_exit mapper`

### Task 1.3: `compare_verdict` mapper

**Step 1: Write the failing test**

```python
# testlib branch (interactor wrote 'testlib exitcode N'): 1,2->WA 3->43 else->47
@pytest.mark.parametrize(
    'testlib,expected', [(1, 6), (2, 6), (3, 43), (4, 47), (5, 47)]
)
def test_compare_verdict_testlib(testlib, expected):
    assert verdicts.compare_verdict(testlib_code=testlib, checker_exit=None) == expected


# checker branch: 0->AC 1,2->WA 3->43 else->47
@pytest.mark.parametrize(
    'checker,expected', [(0, 4), (1, 6), (2, 6), (3, 43), (4, 47), (9, 47)]
)
def test_compare_verdict_checker(checker, expected):
    assert verdicts.compare_verdict(testlib_code=None, checker_exit=checker) == expected
```

**Step 2: Run to verify it fails.**

**Step 3: Implement** (append). Maps verified against `compare.sh:7-48`.

```python
def compare_verdict(
    testlib_code: Optional[int], checker_exit: Optional[int]
) -> int:
    """BOCA compare exit code. See rbx/resources/packagers/boca/compare.sh.

    AC=4, WA=6, JUDGE_ERROR=43, OTHER_ERROR=47.
    """
    if testlib_code is not None:
        if testlib_code in (1, 2):
            return 6
        if testlib_code == 3:
            return 43
        return 47
    if checker_exit == 0:
        return 4
    if checker_exit in (1, 2):
        return 6
    if checker_exit == 3:
        return 43
    return 47
```

**Step 4: Run. Step 5: Commit** — `feat: add compare_verdict mapper`

### Task 1.4: `interactive_run_decision` — the 6-level priority logic

**Step 1: Write the failing test.** Cases below are derived directly from
`interactor_run.sh:108-157` (`first_tag` 1=solution, 2=interactor).

```python
D = verdicts.RunDecision

@pytest.mark.parametrize(
    'first_tag,ecsf,ecint,expected',
    [
        # L1: interactor first, crashed (ecint not in 0..4) -> judge error 4
        (2, 0, 139, D(run_exit=4, testlib_code=None)),
        (2, 0, 5, D(run_exit=4, testlib_code=None)),
        # L2: solution TLE/MLE beats everything below
        (1, 3, 0, D(run_exit=3, testlib_code=None)),
        (1, 7, 0, D(run_exit=7, testlib_code=None)),
        (2, 3, 1, D(run_exit=3, testlib_code=None)),  # even if interactor said WA
        # L3: interactor first with testlib verdict 1..4 -> run_exit 0 + code
        (2, 0, 1, D(run_exit=0, testlib_code=1)),
        (2, 0, 2, D(run_exit=0, testlib_code=2)),
        (2, 0, 3, D(run_exit=0, testlib_code=3)),
        (2, 0, 4, D(run_exit=0, testlib_code=4)),
        # L3: interactor first, ecint 0 -> fall through (solution ok) -> success
        (2, 0, 0, D(run_exit=0, testlib_code=None)),
        # L4: solution nonzero (RTE), interactor not first / ecint 0
        (1, 11, 0, D(run_exit=11, testlib_code=None)),
        # L5: solution first ok, interactor reported error afterwards
        (1, 0, 1, D(run_exit=0, testlib_code=1)),
        (1, 0, 5, D(run_exit=4, testlib_code=None)),
        # L6: all clean
        (1, 0, 0, D(run_exit=0, testlib_code=None)),
    ],
)
def test_interactive_run_decision(first_tag, ecsf, ecint, expected):
    assert verdicts.interactive_run_decision(first_tag, ecsf, ecint) == expected
```

**Step 2: Run to verify it fails.**

**Step 3: Implement** (append). `check_interactor` mirrors `interactor_run.sh:118-131`.

```python
@dataclass(frozen=True)
class RunDecision:
    run_exit: int
    testlib_code: Optional[int]


def _check_interactor(ecint: int) -> Optional['RunDecision']:
    """interactor_run.sh check_interactor: 0->pass(None); 1..4->emit code, exit 0;
    else->judge error (exit 4)."""
    if ecint == 0:
        return None
    if 1 <= ecint <= 4:
        return RunDecision(run_exit=0, testlib_code=ecint)
    return RunDecision(run_exit=4, testlib_code=None)


def interactive_run_decision(
    first_tag: int, ecsf: int, ecint: int
) -> RunDecision:
    """Ordered priority logic from interactor_run.sh:133-157.

    Ordering IS the spec: resource limits (TLE/MLE) beat the interactor verdict,
    which beats a solution RTE.
    """
    interactor_first = first_tag == 2
    is_testlib = 0 <= ecint <= 4

    # 1. interactor crashed before solution
    if interactor_first and not is_testlib:
        return _check_interactor(ecint)  # -> run_exit 4

    # 2. solution TLE (3) / MLE (7)
    if ecsf in (3, 7):
        return RunDecision(run_exit=ecsf, testlib_code=None)

    # 3. interactor finished first -> its verdict
    if interactor_first:
        decided = _check_interactor(ecint)
        if decided is not None:
            return decided  # ecint==0 falls through

    # 4. solution error
    if ecsf != 0:
        return RunDecision(run_exit=ecsf, testlib_code=None)

    # 5. interactor error regardless of order
    decided = _check_interactor(ecint)
    if decided is not None:
        return decided

    # 6. success -> compare decides
    return RunDecision(run_exit=0, testlib_code=None)
```

**Step 4: Run. Step 5: Commit** — `feat: add interactive_run_decision priority logic`

---

## Phase 2 — `manifest.py` (config dataclasses)

### Task 2.1: `LanguageSpec`, `LimitsConfig`, `TaskConfig`, `LanguageManifest`

**Files:**
- Create: `rbx/resources/packagers/boca_next/runtime/rbx_boca/manifest.py`
- Test: `tests/rbx/box/packaging/boca_next/test_manifest.py`

**Step 1: Write the failing test**

```python
# tests/rbx/box/packaging/boca_next/test_manifest.py
from rbx_boca import manifest

TASK_JSON = '{"task_type": "interactive", "output_kb": 65536}'
LANG_JSON = '''
{
  "language": {
    "id": "cpp",
    "kind": "compiled_static",
    "compiler_argv": ["g++", "{flags}", "-o", "{exe}", "{src}"],
    "compiler_fallbacks": ["/usr/bin/g++"],
    "flags": "-std=c++20 -O2 -lm -static",
    "run_argv": ["{exe}"]
  },
  "limits": {"time_sec": 3, "runs": 2, "memory_mb": 256}
}
'''


def test_task_config_parses():
    t = manifest.TaskConfig.from_json(TASK_JSON)
    assert t.task_type == 'interactive'
    assert t.output_kb == 65536


def test_language_manifest_parses():
    m = manifest.LanguageManifest.from_json(LANG_JSON)
    assert m.language.id == 'cpp'
    assert m.language.kind == 'compiled_static'
    assert m.language.run_argv == ['{exe}']
    assert m.language.build is None
    assert m.language.syntax_check is False
    assert m.language.sandbox_overrides == {}
    assert m.limits.runs == 2


def test_language_spec_optional_fields():
    spec = manifest.LanguageSpec.from_dict(
        {
            'id': 'java',
            'kind': 'jvm_jar',
            'compiler_argv': ['javac', '{src}'],
            'compiler_fallbacks': [],
            'flags': '',
            'run_argv': ['java', '-jar', '{jar}', '{jvm_flags}'],
            'build': 'javac_then_jar',
        }
    )
    assert spec.build == 'javac_then_jar'
```

**Step 2: Run to verify it fails.**

**Step 3: Implement**

```python
# rbx/resources/packagers/boca_next/runtime/rbx_boca/manifest.py
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class LanguageSpec:
    id: str
    kind: str  # 'compiled_static' | 'jvm_jar' | 'interpreted'
    compiler_argv: List[str]
    compiler_fallbacks: List[str]
    flags: str
    run_argv: List[str]
    build: Optional[str] = None  # jvm: 'javac_then_jar' | 'kotlinc_include_runtime'
    syntax_check: bool = False  # interpreted (py3) py_compile pre-check
    sandbox_overrides: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'LanguageSpec':
        return LanguageSpec(
            id=d['id'],
            kind=d['kind'],
            compiler_argv=list(d['compiler_argv']),
            compiler_fallbacks=list(d.get('compiler_fallbacks', [])),
            flags=d.get('flags', ''),
            run_argv=list(d['run_argv']),
            build=d.get('build'),
            syntax_check=bool(d.get('syntax_check', False)),
            sandbox_overrides=dict(d.get('sandbox_overrides', {})),
        )


@dataclass(frozen=True)
class LimitsConfig:
    time_sec: int
    runs: int
    memory_mb: int

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'LimitsConfig':
        return LimitsConfig(
            time_sec=int(d['time_sec']),
            runs=int(d['runs']),
            memory_mb=int(d['memory_mb']),
        )


@dataclass(frozen=True)
class TaskConfig:
    task_type: str  # 'batch' | 'interactive'
    output_kb: int

    @staticmethod
    def from_json(text: str) -> 'TaskConfig':
        d = json.loads(text)
        return TaskConfig(task_type=d['task_type'], output_kb=int(d['output_kb']))


@dataclass(frozen=True)
class LanguageManifest:
    language: LanguageSpec
    limits: LimitsConfig

    @staticmethod
    def from_json(text: str) -> 'LanguageManifest':
        d = json.loads(text)
        return LanguageManifest(
            language=LanguageSpec.from_dict(d['language']),
            limits=LimitsConfig.from_dict(d['limits']),
        )
```

**Step 4: Run. Step 5: Commit** — `feat: add rbx_boca manifest dataclasses`

---

## Phase 3 — `languages.py` (kind engine)

### Task 3.1: `render_argv` template helper

**Files:**
- Create: `rbx/resources/packagers/boca_next/runtime/rbx_boca/languages.py`
- Test: `tests/rbx/box/packaging/boca_next/test_languages.py`

**Step 1: Write the failing test**

```python
# tests/rbx/box/packaging/boca_next/test_languages.py
from rbx_boca import languages


def test_render_argv_string_substitution():
    out = languages.render_argv(
        ['g++', '{flags}', '-o', '{exe}', '{src}'],
        flags='-O2 -static',
        exe='run.exe',
        src='sol.cpp',
    )
    # '{flags}' is a lone token whose value contains spaces -> split into args
    assert out == ['g++', '-O2', '-static', '-o', 'run.exe', 'sol.cpp']


def test_render_argv_list_splice():
    out = languages.render_argv(
        ['java', '{jvm_flags}', '-jar', '{jar}'],
        jvm_flags=['-Xmx256000K', '-Xss25600K'],
        jar='run.jar',
    )
    assert out == ['java', '-Xmx256000K', '-Xss25600K', '-jar', 'run.jar']


def test_render_argv_empty_token_dropped():
    out = languages.render_argv(['cc', '{flags}', '{src}'], flags='', src='a.c')
    assert out == ['cc', 'a.c']
```

**Step 2: Run to verify it fails.**

**Step 3: Implement**

```python
# rbx/resources/packagers/boca_next/runtime/rbx_boca/languages.py
from typing import Any, Dict, List

from rbx_boca.manifest import LanguageSpec


def render_argv(template: List[str], **subst: Any) -> List[str]:
    """Expand a {token} argv template.

    - A lone token '{name}' whose value is a list splices the list in.
    - A lone token '{name}' whose value is a str is shlex-style split on
      whitespace (so '-O2 -static' becomes two args); an empty value is dropped.
    - Tokens embedded in larger strings are str-replaced (no splitting).
    """
    out: List[str] = []
    for tok in template:
        if tok.startswith('{') and tok.endswith('}') and tok.count('{') == 1:
            key = tok[1:-1]
            val = subst.get(key, '')
            if isinstance(val, list):
                out.extend(str(v) for v in val)
            else:
                out.extend(str(val).split())
        else:
            rendered = tok
            for key, val in subst.items():
                if not isinstance(val, list):
                    rendered = rendered.replace('{' + key + '}', str(val))
            out.append(rendered)
    return out
```

**Step 4: Run. Step 5: Commit** — `feat: add render_argv template helper`

### Task 3.2: `resolve_compiler` — binary resolution with fallbacks

**Step 1: Write the failing test**

```python
def test_resolve_compiler_prefers_path(tmp_path, monkeypatch):
    # primary binary present on PATH -> used as-is
    spec = languages.LanguageSpec.from_dict(
        {
            'id': 'cpp', 'kind': 'compiled_static',
            'compiler_argv': ['g++', '{src}'], 'compiler_fallbacks': ['/opt/g++'],
            'flags': '', 'run_argv': ['{exe}'],
        }
    )
    monkeypatch.setattr(languages.shutil, 'which', lambda name: '/usr/bin/g++')
    assert languages.resolve_compiler(spec) == '/usr/bin/g++'


def test_resolve_compiler_uses_fallback(monkeypatch, tmp_path):
    fallback = tmp_path / 'kotlinc'
    fallback.write_text('#!/bin/sh\n')
    fallback.chmod(0o755)
    spec = languages.LanguageSpec.from_dict(
        {
            'id': 'kt', 'kind': 'jvm_jar',
            'compiler_argv': ['kotlinc', '{src}'],
            'compiler_fallbacks': [str(fallback)],
            'flags': '', 'run_argv': ['java', '-jar', '{jar}'],
            'build': 'kotlinc_include_runtime',
        }
    )
    monkeypatch.setattr(languages.shutil, 'which', lambda name: None)
    assert languages.resolve_compiler(spec) == str(fallback)
```

**Step 2: Run to verify it fails.**

**Step 3: Implement** (append to `languages.py`)

```python
import shutil
from pathlib import Path


def resolve_compiler(spec: LanguageSpec) -> str:
    """Resolve the compiler/interpreter binary: PATH lookup of compiler_argv[0],
    then the first executable fallback. Mirrors `which X || X=/usr/bin/X` in the
    bash compile templates."""
    primary = spec.compiler_argv[0]
    found = shutil.which(primary)
    if found:
        return found
    for cand in spec.compiler_fallbacks:
        p = Path(cand)
        if p.is_file() and os.access(cand, os.X_OK):
            return cand
    raise FileNotFoundError(f'compiler not found for {spec.id}: {primary}')
```

> Add `import os` at the top with the other imports.

**Step 4: Run. Step 5: Commit** — `feat: add resolve_compiler with fallbacks`

### Task 3.3: Kind handlers — `build_compile_plan` and `build_run_argv`

This is the core dedup. Each `kind` produces (a) a compile plan and (b) a run
argv, parameterized by the `LanguageSpec`. Behavior verified against
`compile/*` and `run/*`. JVM `{jvm_flags}` = `['-XX:+UseSerialGC',
'-Xmx{mem}K', '-Xss{mem/10}K', '-Xms{mem}K']`; static-link check belongs to
`compiled_static`; `nruns` policy and sandbox profiles live in Phase 4/6 but the
*kind* string drives them.

**Step 1: Write the failing test**

```python
def test_compiled_static_run_argv():
    spec = _spec('cpp', 'compiled_static', run_argv=['{exe}'])
    assert languages.build_run_argv(spec, exe='run.exe', memory_mb=256) == ['run.exe']


def test_jvm_run_argv_injects_jvm_flags():
    spec = _spec(
        'java', 'jvm_jar',
        run_argv=['java', '-jar', '{jar}', '{jvm_flags}'], build='javac_then_jar',
    )
    out = languages.build_run_argv(spec, exe='run.jar', memory_mb=256)
    assert out == [
        'java', '-jar', 'run.jar',
        '-XX:+UseSerialGC', '-Xmx256000K', '-Xss25600K', '-Xms256000K',
    ]


def test_kotlin_run_argv_uses_classpath_mainkt():
    spec = _spec(
        'kt', 'jvm_jar',
        run_argv=['java', '-cp', '{jar}', '{jvm_flags}', 'MainKt'],
        build='kotlinc_include_runtime',
    )
    out = languages.build_run_argv(spec, exe='run.jar', memory_mb=256)
    assert out[:4] == ['java', '-cp', 'run.jar', '-XX:+UseSerialGC']
    assert out[-1] == 'MainKt'


def test_interpreted_run_argv():
    spec = _spec('py3', 'interpreted', run_argv=['{interp}', '{src}'])
    out = languages.build_run_argv(spec, exe='run.exe', memory_mb=256, interp='python3', src='sol.py')
    assert out == ['python3', 'sol.py']
```

Add a `_spec` helper at the top of the test file:

```python
def _spec(id, kind, run_argv, build=None):
    return languages.LanguageSpec.from_dict(
        {
            'id': id, 'kind': kind, 'compiler_argv': ['cc', '{src}'],
            'compiler_fallbacks': [], 'flags': '', 'run_argv': run_argv,
            'build': build,
        }
    )
```

**Step 2: Run to verify it fails.**

**Step 3: Implement** (append). `build_compile_plan` is covered in Task 3.4.

```python
KINDS = ('compiled_static', 'jvm_jar', 'interpreted')


def jvm_flags(memory_mb: int) -> List[str]:
    """JVM memory flags from run/java, run/kt: heap=memory, stack=heap/10."""
    heap_kb = memory_mb * 1000
    stack_kb = heap_kb // 10
    return [
        '-XX:+UseSerialGC',
        f'-Xmx{heap_kb}K',
        f'-Xss{stack_kb}K',
        f'-Xms{heap_kb}K',
    ]


def build_run_argv(spec: LanguageSpec, *, exe: str, memory_mb: int, **extra: Any) -> List[str]:
    if spec.kind not in KINDS:
        raise ValueError(f'unknown kind: {spec.kind}')
    subst: Dict[str, Any] = {'exe': exe, 'jar': exe}
    subst.update(extra)
    if spec.kind == 'jvm_jar':
        subst['jvm_flags'] = jvm_flags(memory_mb)
    return render_argv(spec.run_argv, **subst)
```

**Step 4: Run. Step 5: Commit** — `feat: add kind-driven build_run_argv`

### Task 3.4: `build_compile_plan` per kind

A compile plan is an ordered list of argv steps plus post-checks, executed by the
`compile` entrypoint (Phase 6). Verified against `compile/*`.

- `compiled_static`: one step `render_argv(compiler_argv, flags=..., exe=..., src=...)`; post-check `static_link`.
- `jvm_jar` + `build=javac_then_jar`: compile each `*.java`, then `jar cfm <jar> Manifest.txt *` with a generated `Main-Class` manifest (class name from basename).
- `jvm_jar` + `build=kotlinc_include_runtime`: rename source to `Main.kt`, then `kotlinc -d <jar> -include-runtime Main.kt`.
- `interpreted`: optional `py_compile` syntax check (if `syntax_check`), then write `#!<interp>\n` + source to `<exe>`, `chmod 755`.

**Step 1: Write the failing test**

```python
def test_compile_plan_compiled_static():
    spec = _spec('cpp', 'compiled_static', run_argv=['{exe}'])
    object.__setattr__(spec, 'flags', '-O2 -static')
    plan = languages.build_compile_plan(spec, src='sol.cpp', exe='run.exe', basename='run')
    assert plan.steps[0] == ['cc', 'sol.cpp']  # from compiler_argv in _spec
    assert plan.static_link_check is True


def test_compile_plan_interpreted_writes_shebang_script():
    spec = _spec('py3', 'interpreted', run_argv=['{interp}', '{src}'])
    object.__setattr__(spec, 'syntax_check', True)
    plan = languages.build_compile_plan(
        spec, src='sol.py', exe='run.exe', basename='run', interp='python3'
    )
    assert plan.shebang == '#!python3'
    assert plan.write_script == ('sol.py', 'run.exe')
    assert plan.static_link_check is False
```

> These tests pin the *shape* of `CompilePlan`. Keep the dataclass minimal —
> only fields the `compile` entrypoint consumes. Refine field names while red, but
> keep them stable once green.

**Step 2: Run to verify it fails.**

**Step 3: Implement** a `CompilePlan` dataclass and `build_compile_plan(spec, *, src, exe, basename, **extra)` that branches on `spec.kind`/`spec.build` to populate it. Include the JVM manifest-class derivation and the Kotlin `Main.kt` rename as plan fields. (Author the dataclass to match the asserted fields; add `jar`/`manifest_class` fields for the jvm branch and assert them in added tests.)

**Step 4: Run. Step 5: Commit** — `feat: add build_compile_plan kind handlers`

---

## Phase 4 — `sandbox.py` (safeexec)

### Task 4.1: `SafeExecSpec` + `build_safeexec_argv` (pure)

**Files:**
- Create: `rbx/resources/packagers/boca_next/runtime/rbx_boca/sandbox.py`
- Test: `tests/rbx/box/packaging/boca_next/test_sandbox.py`

Fields/flags verified against `run/*` and `compile/*`:
`-r<runs> -t<cpu> -T<wall> -d<mem_kb> -m<mem_kb> -f<out_kb> -F<fds> [-u<procs>]
-U<uid> -G<gid> -n<n> -C<chdir> [-R<chroot>] -istdin0 -ostdout0 -estderr0`.

**Step 1: Write the failing test**

```python
# tests/rbx/box/packaging/boca_next/test_sandbox.py
from rbx_boca import sandbox


def test_build_safeexec_argv_compiled_run_profile():
    spec = sandbox.SafeExecSpec(
        runs=2, cpu_sec=3, wall_sec=12, mem_kb=256000, out_kb=65536,
        fds=10, procs=None, uid=65534, gid=65534, chdir='.', chroot=None,
        stdin='stdin0', stdout='stdout0', stderr='stderr0',
    )
    argv = sandbox.build_safeexec_argv(spec, program=['./run.exe'])
    assert argv[0].endswith('safeexec') or argv[0] == 'safeexec'
    body = argv[1:]
    assert '-r2' in body and '-t3' in body and '-T12' in body
    assert '-d256000' in body and '-m256000' in body
    assert '-f65536' in body and '-F10' in body
    assert '-U65534' in body and '-G65534' in body
    assert '-C.' in body and '-istdin0' in body
    assert '-ostdout0' in body and '-estderr0' in body
    assert '-u' not in ''.join(body)  # procs None -> no -u flag
    assert body[-1] == './run.exe'


def test_build_safeexec_argv_includes_procs_and_chroot():
    spec = sandbox.SafeExecSpec(
        runs=1, cpu_sec=2, wall_sec=8, mem_kb=512000, out_kb=1024,
        fds=256, procs=256, uid=1, gid=1, chdir='.', chroot='/jail',
        stdin='stdin0', stdout='stdout0', stderr='stderr0',
    )
    argv = sandbox.build_safeexec_argv(spec, program=['java', '-jar', 'run.jar'])
    assert '-u256' in argv and '-R/jail' in argv
    assert argv[-3:] == ['java', '-jar', 'run.jar']
```

**Step 2: Run to verify it fails.**

**Step 3: Implement**

```python
# rbx/resources/packagers/boca_next/runtime/rbx_boca/sandbox.py
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class SafeExecSpec:
    runs: int
    cpu_sec: int
    wall_sec: int
    mem_kb: int
    out_kb: int
    fds: int
    procs: Optional[int]
    uid: int
    gid: int
    chdir: str
    chroot: Optional[str]
    stdin: Optional[str]
    stdout: str
    stderr: str


def build_safeexec_argv(
    spec: SafeExecSpec, program: List[str], *, safeexec: str = 'safeexec'
) -> List[str]:
    argv = [safeexec, f'-r{spec.runs}', f'-t{spec.cpu_sec}', f'-T{spec.wall_sec}']
    argv += [f'-d{spec.mem_kb}', f'-m{spec.mem_kb}', f'-f{spec.out_kb}']
    argv += [f'-F{spec.fds}']
    if spec.procs is not None:
        argv.append(f'-u{spec.procs}')
    argv += [f'-U{spec.uid}', f'-G{spec.gid}', f'-C{spec.chdir}']
    if spec.chroot is not None:
        argv.append(f'-R{spec.chroot}')
    if spec.stdin is not None:
        argv.append(f'-i{spec.stdin}')
    argv += [f'-o{spec.stdout}', f'-e{spec.stderr}']
    argv += list(program)
    return argv
```

**Step 4: Run. Step 5: Commit** — `feat: add build_safeexec_argv`

### Task 4.2: Per-kind safeexec profiles

A pure factory mapping `(kind, phase, limits, overrides)` → `SafeExecSpec`,
encoding the kind defaults (fds 10 vs 256, JVM fixed-large memory, `nruns`
policy: `compiled_static` honors `runs`, others force 1). Apply
`sandbox_overrides` last.

**Step 1: Write the failing test** — assert: compiled_static run profile uses
`fds=10`, `mem_kb=memory*1000`, `runs=limits.runs`; jvm_jar run profile uses
`fds=256`, `procs=256`, fixed large `mem_kb` (e.g. `20000000`), `runs=1`;
interpreted run profile uses `fds=256`, real memory, `runs=1`; and that
`sandbox_overrides={'fds': 99}` wins.

**Step 2–4:** Implement `profile_for(kind, phase, limits, overrides) -> SafeExecSpec` with the constants from `run/*` and `compile/*`; TDD each assertion.

**Step 5: Commit** — `feat: add per-kind safeexec profiles`

### Task 4.3: `SafeExec` executor with injectable `Runner`

**Step 1: Write the failing test**

```python
def test_safeexec_run_invokes_runner_and_returns_exit():
    calls = []

    def fake_runner(argv, **kw):
        calls.append(argv)
        return 7  # MLE

    ex = sandbox.SafeExec(path='/usr/bin/safeexec', runner=fake_runner)
    spec = _minimal_spec()  # helper building a SafeExecSpec
    code = ex.run(spec, program=['./run.exe'])
    assert code == 7
    assert calls[0][0] == '/usr/bin/safeexec'
```

**Step 2–4:** Implement `SafeExec(path, runner)` where `runner` defaults to a
thin `subprocess.call` wrapper; `.run()` builds argv via `build_safeexec_argv`
and delegates. (Locating/compiling `safeexec.c` is handled by `NativeAsset` in
Phase 5; `SafeExec.path` is supplied by the caller.)

**Step 5: Commit** — `feat: add SafeExec executor with injectable runner`

---

## Phase 5 — `assets.py` (`NativeAsset` compile cache)

### Task 5.1: cache-key composition

**Files:**
- Create: `rbx/resources/packagers/boca_next/runtime/rbx_boca/assets.py`
- Test: `tests/rbx/box/packaging/boca_next/test_assets.py`

**Step 1: Write the failing test**

```python
from rbx_boca import assets


def test_cache_key_depends_on_source_and_flags():
    a = assets.NativeAsset(name='checker', source=b'int main(){}', compile_argv=['g++', '-O2'])
    b = assets.NativeAsset(name='checker', source=b'int main(){}', compile_argv=['g++', '-O3'])
    c = assets.NativeAsset(name='checker', source=b'int main(){ }', compile_argv=['g++', '-O2'])
    assert a.cache_key() != b.cache_key()  # flags differ
    assert a.cache_key() != c.cache_key()  # source differs
    assert a.cache_key() == assets.NativeAsset('checker', b'int main(){}', ['g++', '-O2']).cache_key()
```

**Step 2–4:** Implement `NativeAsset` dataclass with
`cache_key()` = `hashlib.md5(source + b'\0' + '\0'.join(compile_argv))`.hexdigest().

**Step 5: Commit** — `feat: add NativeAsset cache key`

### Task 5.2: `.ensure()` cache hit/miss with injectable runner + cache dir

**Step 1: Write the failing test**

```python
def test_ensure_compiles_on_miss_then_caches(tmp_path):
    compiled = []

    def fake_runner(argv, **kw):
        # emulate compiler: create the output file (last token after -o)
        out = argv[argv.index('-o') + 1]
        (tmp_path / out).write_bytes(b'ELF')
        compiled.append(argv)
        return 0

    a = assets.NativeAsset(name='checker', source=b'src', compile_argv=['g++', '-O2', '-o', '{out}', '{src}'])
    out1 = a.ensure(cache_dir=tmp_path, runner=fake_runner)
    out2 = a.ensure(cache_dir=tmp_path, runner=fake_runner)
    assert out1 == out2
    assert out1.exists()
    assert len(compiled) == 1  # second call is a cache hit, no recompile
```

**Step 2–4:** Implement `.ensure(cache_dir, runner)`:
- target = `cache_dir / f'{name}-{cache_key()}'`
- if target exists and is non-empty → return it (cache hit)
- else write source to a temp `.cpp`/`.c`, render `{src}`/`{out}` in `compile_argv` (point `{out}` at a temp path), run; on success atomically move to `target` (`os.replace`) and return it; raise on nonzero.

> Note for executor: the bash uses `/tmp/boca-cache`. The default `cache_dir`
> will be wired in Phase 6 from a module constant; keep it a parameter here for
> testability.

**Step 5: Commit** — `feat: add NativeAsset.ensure with compile cache`

### Task 5.3: concurrency safety (atomic publish)

**Step 1: Write a test** simulating two `.ensure()` calls racing on the same key
(call the compile twice writing to distinct temp paths, then `os.replace` to the
same target) and assert the final target is valid and no partial file is ever
observed. **Implement** by compiling to a unique temp name and `os.replace` onto
the final path (atomic on POSIX). **Commit** — `feat: make asset cache publish atomic`

---

## Phase 6 — `tasks.py` (Batch/Interactive orchestration)

### Task 6.1: `RunContext` + `BatchTask.compile`

**Files:**
- Create: `rbx/resources/packagers/boca_next/runtime/rbx_boca/tasks.py`
- Test: `tests/rbx/box/packaging/boca_next/test_tasks.py`

`RunContext` bundles the parsed manifests, cwd, an injected `runner`, the
resolved asset paths, and the safeexec path — everything the tasks need, all
injectable for tests.

**Step 1: Write the failing test** — a `BatchTask.compile(ctx, src, exe, basename)`
that, given a `compiled_static` spec, calls the runner with the compiler argv
from `build_compile_plan` and (on success) returns 0; assert the runner saw
`g++ ... -o <exe> <src>` and that a non-statically-linked binary triggers the
static-link failure path (stub the `file` check).

**Step 2–4:** Implement `BatchTask.compile` by executing the `CompilePlan`
steps via `ctx.runner` and running post-checks. Reuse `languages.build_compile_plan`.

**Step 5: Commit** — `feat: add BatchTask.compile`

### Task 6.2: `BatchTask.run`

**Step 1: Write the failing test** — `BatchTask.run(ctx, args)` builds the
safeexec argv (via `sandbox.profile_for('compiled_static','run',...)` +
`build_run_argv`), invokes `ctx.safeexec.run(...)` (fake returns 11), and returns
`verdicts.batch_run_exit(11) == 9`.

**Step 2–4:** Implement. Parse the BOCA run args (`basename input timelimit
repetitions memory outputsize_kb`), copy input to `stdin0` (via injected fs ops),
run, map exit.

**Step 5: Commit** — `feat: add BatchTask.run`

### Task 6.3: `BatchTask.compare` + `InteractiveTask.compare`

**Step 1: Write the failing test** — `compare(ctx, args)` for batch runs the
checker (fake returns 1) → `compare_verdict(None, 1) == 6`; for interactive,
when `stdout0` contains `testlib exitcode 3`, returns `compare_verdict(3, None)
== 43` *without* invoking the checker.

**Step 2–4:** Implement a shared `compare` that first greps the team-output file
for `^testlib exitcode` (mirrors `compare.sh:7`), else runs the checker via
`ctx.runner`, then `verdicts.compare_verdict`.

**Step 5: Commit** — `feat: add compare for batch and interactive tasks`

### Task 6.4: `InteractiveTask.run` (fifo + pipe.exe orchestration)

**Step 1: Write the failing test** — with a fake runner that, when invoked with
the `pipe.exe` argv, writes a known `pipe.log` (`2\n0\n1\n`) to cwd and returns 0,
assert `InteractiveTask.run` parses it, applies `interactive_run_decision(2,0,1)`
→ `RunDecision(run_exit=0, testlib_code=1)`, writes `testlib exitcode 1` to
`stdout0`, and returns `0`.

**Step 2–4:** Implement: create fifos (guard with a flag so tests can stub
`os.mkfifo`), build the `pipe.exe` argv (solution-under-safeexec `=`
interactor-launcher command — the launcher command is the re-entrant `.pyz`
sentinel; see Phase 7/8), run via `ctx.runner`, parse `pipe.log`, apply the
decision, emit the testlib line when present, return `run_exit`.

**Step 5: Commit** — `feat: add InteractiveTask.run orchestration`

---

## Phase 7 — `interactor_launcher.py`

### Task 7.1: pure helpers (rlimit, timeout, fd plan)

**Files:**
- Create: `rbx/resources/packagers/boca_next/runtime/rbx_boca/interactor_launcher.py`
- Test: `tests/rbx/box/packaging/boca_next/test_interactor_launcher.py`

**Step 1: Write the failing test** — `address_space_limit() == 1024000 * 1024`
(bytes; bash `ulimit -v 1024000` is KiB), and `watchdog_timeout(wall_sec)` returns
`(term_after=wall_sec, kill_after=5)`.

**Step 2–4:** Implement the pure helpers only.

**Step 5: Commit** — `feat: add interactor launcher pure helpers`

### Task 7.2: `launch()` (integration-covered)

**Step 1:** Implement `launch(argv, *, ittime, notify_fd)`:
- `resource.setrlimit(resource.RLIMIT_AS, (limit, limit))`
- fork a watchdog child that **closes `notify_fd`** (the `exec {fd}>&-` analogue),
  `sleep(ittime)`, `os.killpg(0, SIGTERM)`, `sleep(5)`, `os.killpg(0, SIGKILL)`
- parent `os.execv(argv[0], argv)` (which preserves `notify_fd` open until exit)

> **Risk (from design doc):** the watchdog must NOT inherit `notify_fd`, else
> `pipe.exe` never sees EPOLLHUP and hangs. This is covered by the Phase 9
> integration test, not a unit test (it is pure syscall/exec behavior).

**Step 2:** Defer verification to Phase 9. **Commit** — `feat: add interactor launch()`

---

## Phase 8 — `entrypoints.py` + `__main__`

### Task 8.1: argv parsing + dispatch

**Files:**
- Create: `rbx/resources/packagers/boca_next/runtime/rbx_boca/entrypoints.py`
- Test: `tests/rbx/box/packaging/boca_next/test_entrypoints.py`

**Step 1: Write the failing test** — `entrypoints.main(['compile', 'sol.cpp',
'run', '3', '256'], context_factory=fake)` routes to `Task.compile` with parsed
args; `['run', 'run', 'in', '3', '2', '256', '65536']` routes to `Task.run`;
`['limits']` prints the 4 numbers (`time_sec runs memory_mb output_kb`, one per
line) and returns 0; `['tests']` returns 0; `['__interactor_launcher__', ...]`
routes to `interactor_launcher.launch`. Use a fake `context_factory` and capture
stdout.

**Step 2–4:** Implement `main(argv, context_factory=...)` that selects the entry
by `argv[0]`, builds the `RunContext` (reading `task.json`/`language.json` from
the bundle via `importlib.resources`/`__loader__`), selects `BatchTask` vs
`InteractiveTask` by `task_type`, and dispatches. Keep it thin.

**Step 5: Commit** — `feat: add entrypoints.main dispatcher`

### Task 8.2: `__main__.py` + per-entry generated stubs

`__main__.py` (in the package root of the bundle) calls
`entrypoints.main(sys.argv[1:])`. The per-file `__main__` that Layer 1 generates
will pass the fixed entry name; for Layer 2, ship a single
`rbx_boca/__main__.py` that reads the entry from `argv` so the integration
harness can drive it. (Layer 1 wires the filename→entry mapping.)

**Step 1: Write a test** that runs `python -m rbx_boca limits` in a subprocess
with `PYTHONPATH` set to the runtime dir and a temp cwd containing `task.json`
+ `language.json`, asserting the 4 echoed numbers.

**Step 2–4:** Implement `rbx_boca/__main__.py`.

**Step 5: Commit** — `feat: add rbx_boca __main__ entry`

---

## Phase 9 — Integration harness (zipapp + stub safeexec)

### Task 9.1: bundle builder test helper

**Files:**
- Create: `tests/rbx/box/packaging/boca_next/_bundle.py`
- Test: `tests/rbx/box/packaging/boca_next/test_integration.py`

**Step 1:** Implement `_bundle.build_pyz(dest, task_json, language_json, assets)` using
stdlib `zipapp.create_archive` over a temp dir containing a copy of `rbx_boca/`,
the two JSON files, and an `assets/` dir; shebang `/usr/bin/env python3`. This is a
*test-only* stand-in for Layer 1.

**Step 2:** Write `test_pyz_limits_end_to_end`: build a `.pyz`, run it with
`['limits']`, assert it echoes the 4 numbers. This proves zipimport + manifest
reading works from a real archive.

**Step 5: Commit** — `test: add zipapp bundle integration harness`

### Task 9.2: stub `safeexec` end-to-end batch run

**Step 1:** Add a stub `safeexec` shell script (written to a temp dir, made
executable) that ignores its flags, runs the trailing program, and exits with a
controllable code. Build a batch `.pyz` and drive `compile` then `run` then
`compare` against a trivial "echo" solution + `wcmp`-style stub checker. Assert
the final compare exit code is `4` (AC) for matching output and `6` (WA) for
mismatched.

> If compiling a real checker is too heavy for CI, stub the checker as a
> `NativeAsset` whose `compile_argv` is a no-op script copy. Mark the test
> `@pytest.mark.slow` if it invokes a real compiler.

**Step 5: Commit** — `test: add batch end-to-end run via stub safeexec`

### Task 9.3: interactive end-to-end (the fd-inheritance risk)

**Step 1:** Build an interactive `.pyz`. Provide a stub `pipe.exe` (a small
compiled C from the real `pipe.c`, or — if compilation is unavailable in CI — a
Python stub that mimics its fifo/epoll/`pipe.log` contract) plus a stub
interactor that exits with a chosen testlib code. Drive `run` and assert:
(a) the run completes without hanging (proves the launcher drops `notify_fd`),
(b) `interactive_run_decision` produces the expected `run_exit`/testlib line,
(c) `compare` yields the expected BOCA code.

> Mark `@pytest.mark.slow`/`@pytest.mark.docker` if it needs a compiler/sandbox.
> This is the only coverage for the fd-inheritance/`killpg` risk flagged in the
> design — do not skip it.

**Step 5: Commit** — `test: add interactive end-to-end with launcher fd check`

---

## Phase 10 — Wrap-up

### Task 10.1: module docs + CLAUDE.md pointer

**Step 1:** Add a short `rbx/box/packaging/boca_next/CLAUDE.md` (or a section in
the packaging `CLAUDE.md`) describing the two-layer split, that `rbx_boca` is
stdlib-only and importable via the test conftest, and linking the design doc and
issue #489 (Layer 1). **Commit** — `docs: document rbx_boca runtime`

### Task 10.2: full suite + lint

**Step 1:** Run `uv run pytest tests/rbx/box/packaging/boca_next/ -v` (and
`-m 'not slow and not docker'` for the fast subset), `uv run ruff check .`,
`uv run ruff format --check .`. Fix anything red. **Commit** — `chore: finalize rbx_boca runtime`

---

## Out of scope (Layer 1 — issue #489)

env-config → `LanguageSpec` resolution; package-time limits/`nruns` computation;
real `.pyz` assembly + directory layout; `rbx package boca-next` CLI; embedding
real asset sources (`checker.cpp`, `testlib.h`, `rbx.h`, `interactor.cpp`,
`safeexec.c`, `pipe.c`); deprecating the bash packager.
