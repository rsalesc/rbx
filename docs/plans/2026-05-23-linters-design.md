# Built-in Linters Design

Date: 2026-05-23
Issue: https://github.com/rsalesc/rbx/issues/476

## Goal

Add support for **built-in linters** in `rbx`: rbx-made linters distributed as
Python code that analyze a problem's source files during compilation and surface
warnings or errors. Ship the first linter, `side_effect`, a C++ linter built on
`tree-sitter-cpp` that flags side-effecting calls used as arguments to other
calls (where C++ leaves argument evaluation order unspecified).

This is distinct from general-purpose code linting: linters here are first-class
rbx components, configured per language in `env.rbx.yml`, run only during the
compilation phase.

## Scope decisions

- **Severity (default):** `side_effect` emits **warnings**, routed to the warning
  stack. The interface still supports errors (→ `RbxException`) for future
  linters. No per-linter `severity` override field in v1.
- **Asset classes:** introduce an explicit `AssetKind` enum rather than reusing
  Pydantic class names.
- **`side_effect` v1 detection:** **hardcoded side-effect family only** (the
  `rnd.next` family from testlib/tgen/jngen). The `SIDE_EFFECT` macro and header
  expansion described in the issue are deferred to a follow-up issue.
- **Side-effect family location:** a maintained hardcoded constant in code (not
  user-configurable in `env.rbx.yml`).

## Architecture

New package `rbx/box/linters/`:

```
rbx/box/linters/
  linter.py        # Linter ABC, LinterMessage, LinterSeverity
  registry.py      # name -> Linter registry + @register decorator
  cpp/
    side_effect.py # first linter
```

### Interface (`linters/linter.py`)

```python
class LinterSeverity(enum.Enum):
    WARNING = 'warning'
    ERROR = 'error'

class LinterMessage(BaseModel):
    severity: LinterSeverity
    message: str
    line: Optional[int] = None   # 1-based
    col: Optional[int] = None    # 1-based

class Linter(abc.ABC):
    name: ClassVar[str]                    # lowercase, referenced in env.rbx.yml
    languages: ClassVar[Set[str]]          # language families it supports, e.g. {'cpp'}
    applies_to: ClassVar[Set[AssetKind]]   # interface restriction; empty == all kinds

    @abc.abstractmethod
    def lint(self, code: CodeItem, source: str) -> List[LinterMessage]: ...
```

`lint()` is synchronous and pure over `(code, source)`. It receives the **raw
source text** of the file (no preprocessing / header expansion).

### Registry (`linters/registry.py`)

A closed, in-process registry — no setuptools entry points or external plugins,
matching "rbx-made linters distributed as Python code".

```python
_REGISTRY: Dict[str, Linter] = {}

def register(linter_cls):    # decorator; instantiates and registers by .name
    ...

def get_linter(name: str) -> Linter: ...   # raises RbxException on unknown name
```

Linter modules are imported once (e.g. from `linters/__init__.py`) so their
`@register` side effects run.

## Config schema (`env.rbx.yml`)

Add `linters` to `EnvironmentLanguage` (`rbx/box/environment.py`), default empty:

```yaml
languages:
  - name: cpp
    linters:
      - side_effect                                      # shorthand
      - {name: side_effect, applies_to: [generators]}    # restricted form
```

New model:

```python
class LinterConfig(BaseModel):
    name: str
    applies_to: Optional[List[AssetKind]] = None  # None/empty == all kinds
```

A field validator on `EnvironmentLanguage.linters` coerces a bare string into
`LinterConfig(name=...)`.

**Effective scope** for a given linter + asset is the intersection of:
- the linter interface's `applies_to` (empty == all), and
- the config entry's `applies_to` (None/empty == all).

A linter runs on an asset only if the asset's language family is in the linter's
`languages` set and the asset's kind is within the effective scope.

## AssetKind & kind resolution

New enum:

```python
class AssetKind(enum.Enum):
    GENERATOR = 'generator'
    VALIDATOR = 'validator'
    SOLUTION = 'solution'
    CHECKER = 'checker'
    INTERACTOR = 'interactor'
    VISUALIZER = 'visualizer'
```

`Solution`, `Generator`, `Checker`, `Interactor`, `Visualizer` are distinct
`CodeItem` subclasses, so their kind is inferable via `isinstance`. **Validators
are plain `CodeItem`** (`schema.py`: `validator: Optional[CodeItem]`) with no
dedicated class, so their kind cannot be inferred from type.

Resolution strategy:
- Add `kind: Optional[AssetKind] = None` to `compile_item()` in `rbx/box/code.py`.
- Auto-derive from `isinstance` for the typed subclasses when `kind` is not given.
- Call sites compiling a bare-`CodeItem` validator (`rbx/box/validators.py`) pass
  `kind=AssetKind.VALIDATOR` explicitly.
- When kind is unknown, kind-restricted linters skip; unrestricted linters run.

## Compile-time integration

Linting runs inside `compile_item()` — the compilation phase. Steps:

1. Resolve the language family for `code`.
2. Resolve `kind` (param or `isinstance`).
3. From the language's `linters` config, resolve each `Linter` via the registry.
4. Filter by language-family support and effective `applies_to` scope.
5. Read the raw source file and run each applicable linter's `lint()`.
6. Route messages:
   - `WARNING` → warning stack (see below).
   - `ERROR` → accumulate and raise a single `RbxException` (via its context
     manager) listing all errors with file + location.

### Warning stack integration

`WarningStack` (`rbx/box/sanitizers/warning_stack.py`) currently keys warnings by
code path with `List[PreprocessLog]`. Add a method to carry linter messages with
text + location so they render alongside compiler warnings, e.g.:

```python
def add_linter_warning(self, code: CodeItem, messages: List[LinterMessage]): ...
```

and include them in `print_warning_stack_report()`.

### Caching caveat (verify during implementation)

The compiler invocation itself is cached via `steps_with_caching.compile()`, but
`compile_item()`'s body re-runs on each call. Linting must run on every build, so
it is placed in `compile_item()`'s body independent of the cached compile step.
**To verify in the plan:** that there is no higher-level memoization of
`compile_item` (e.g. an `alru_cache`) that would swallow repeat lint runs; if
there is, lint outside that boundary or include lint output in the cache.

## The `side_effect` linter (v1)

`linters/cpp/side_effect.py`, built on `tree-sitter-cpp`.

```python
@register
class SideEffectLinter(Linter):
    name = 'side_effect'
    languages = {'cpp'}
    applies_to = set()   # all kinds, restrictable via config
```

### Side-effect family

A maintained module-level constant, seeded with the `rnd.next` family. Modeled as
`(object, method)` patterns to match `rnd.next(...)`:

```python
SIDE_EFFECT_CALLS = {('rnd', 'next')}  # extend as needed
```

### Detection algorithm

1. Parse the source with `tree-sitter-cpp`.
2. Query every `call_expression` node (the "outer" calls).
3. For each outer call, look at its top-level argument expressions
   (`argument_list` children).
4. Count how many top-level arguments **contain** (anywhere in their subtree) a
   call to a known side-effect function.
5. If the count is **>= 2**, emit a `WARNING` at the outer call's start position.

A "known side-effect call" is a `call_expression` whose callee is a
`field_expression` matching `<obj>.<method>` against `SIDE_EFFECT_CALLS`.

### Behavior on the issue's examples

```cpp
some_function(rnd.next(), rnd.next());          // WARN  (2 side-effect args)
some_function(rnd.next(), 3);                   // OK    (1 side-effect arg)
some_function(fn_with_side_effect(), rnd.next()); // OK in v1 (macro not detected)
```

The third case will warn once `SIDE_EFFECT`-macro detection lands (follow-up).

### Covered / not covered

- **Nested calls** are covered: every `call_expression` is scanned, so an inner
  `g(rnd.next(), rnd.next())` warns even when wrapped in another call.
- **`cout << rnd.next() << rnd.next()`** is *not* flagged: `<<` is a
  `binary_expression`, not a `call_expression`, and operator operands are
  sequenced. This matches the issue's scope.

### Deferred (follow-up issue)

- `SIDE_EFFECT` macro detection (`SIDE_EFFECT int fn();`).
- Header expansion so macros/functions declared in included headers (tgen.h,
  jngen.h, testlib.h) are visible. Left as `# TODO(#NNN)` in code.

## Dependencies

Add to `pyproject.toml` (prebuilt wheels, Python >=3.10 satisfied):

- `tree-sitter`
- `tree-sitter-cpp`

Pin to a known-compatible pair (tree-sitter and the grammar package's ABI must
match). Verify `Parser(Language(tree_sitter_cpp.language()))` constructs cleanly
under the chosen versions.

## Error handling

- Unknown linter name in config → `RbxException` at config resolution time, with
  the offending name and the language.
- Unsupported language for a referenced linter → `RbxException` (misconfiguration)
  rather than silent skip, so typos surface.
- A linter raising unexpectedly → wrap in `RbxException` identifying the linter
  and file; do not let it crash compilation opaquely.
- Linter `ERROR` messages → a single aggregated `RbxException`.

## Testing

Unit (linter):
- `side_effect` over C++ snippets: the three issue examples, nested calls,
  single side-effect arg, three+ args, free-function vs method callee,
  `cout <<` chains (no warning), and a clean file (no warnings).
- Parse via the real linter; do not mock the parser.

Framework:
- Registry lookup + unknown-name error.
- Shorthand string → `LinterConfig` coercion.
- `applies_to` intersection (interface ∩ config) and language-family filtering.
- Kind resolution: `isinstance`-derived kinds and explicit validator kind.
- Warning-vs-error routing.

Integration:
- Compile a generator containing an offending `rnd.next(...)` call and assert the
  warning lands on the stack and renders in the report.
- Compile with `applies_to: [generators]` and confirm a solution with the same
  pattern is *not* flagged.

## Follow-ups

- Open an issue for `SIDE_EFFECT` macro detection + header expansion, referenced
  by the `# TODO` in `side_effect.py`.
```
