# MojNext Packager Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `rbx package moj-next`, a packager that emits the MOJ package format as
`mojtools` actually consumes it, without touching the legacy `moj` packager.

**Architecture:** A reusable single-translation-unit amalgamator lands in
`rbx/box/dependencies/`, built on a new *splice* capability added to the dependency
scanner ABC. On top of it, `rbx/box/packaging/moj_next/` emits a calibration-only MOJ
package: no `tl`, a `conf` with the RSS-based memory knob, `sample*`-first test naming,
`tests/score` for POINTS problems, an amalgamated `scripts/checker.cpp` plus mojtools'
canonical `compare.sh` stub, and per-language in-jail scripts driven by a new `moj`
language extension.

**Tech Stack:** Python 3.12+, Pydantic v2, Typer, tree-sitter-cpp, pytest.

**Design doc:** `docs/plans/2026-08-13-moj-next-packager-design.md` — read it first.

**Conventions:** single quotes, absolute imports only, `uv run ruff check --fix . &&
uv run ruff format .` before each commit, and commits follow the `/commit` skill
(conventional commits, `Co-Authored-By: Claude <noreply@anthropic.com>` trailer).

---

## Task 1: Give the scanner ABC a splice capability

Amalgamation needs the byte span of the *whole* `#include` directive so it can replace
it with file content. `CppScanner.rewrite` only renames the quoted path, and
`references()` returns no offsets. Add a third, optional capability.

**Files:**
- Modify: `rbx/box/dependencies/scanner.py`
- Modify: `rbx/box/dependencies/cpp.py`
- Test: `tests/rbx/box/dependencies/test_cpp_spans.py`

**Step 1: Write the failing test**

Create `tests/rbx/box/dependencies/test_cpp_spans.py`:

```python
from rbx.box.dependencies.cpp import CppScanner


def test_reference_spans_covers_whole_directive():
    text = 'int a;\n#include "lib.h"\nint b;\n'
    spans = CppScanner().reference_spans(text)
    assert len(spans) == 1
    start, end, spelling = spans[0]
    assert spelling == 'lib.h'
    assert text[start:end].strip() == '#include "lib.h"'


def test_reference_spans_skips_system_includes():
    text = '#include <vector>\n#include "lib.h"\n'
    spans = CppScanner().reference_spans(text)
    assert [s[2] for s in spans] == ['lib.h']


def test_reference_spans_are_sorted_and_disjoint():
    text = '#include "a.h"\n#include "b.h"\n#include "c.h"\n'
    spans = CppScanner().reference_spans(text)
    assert [s[2] for s in spans] == ['a.h', 'b.h', 'c.h']
    for (_, prev_end, _), (next_start, _, _) in zip(spans, spans[1:]):
        assert prev_end <= next_start


def test_cpp_scanner_can_splice():
    assert CppScanner.can_splice is True
```

**Step 2: Run it and confirm it fails**

```bash
uv run pytest tests/rbx/box/dependencies/test_cpp_spans.py -v
```
Expected: `AttributeError: 'CppScanner' object has no attribute 'reference_spans'`.

**Step 3: Add the capability to the ABC**

In `rbx/box/dependencies/scanner.py`, add to the imports `Tuple`, then inside
`DependencyScanner` after `can_rewrite`:

```python
    # Whether ``reference_spans`` is implemented. Splicing replaces a whole dependency
    # directive with other content (used by amalgamation); renaming via ``rewrite``
    # only substitutes the referenced path.
    can_splice: ClassVar[bool] = False
```

and after `rewrite`:

```python
    def reference_spans(self, text: str) -> List[Tuple[int, int, str]]:
        """Byte spans of each dependency directive in ``text``, with its spelling.

        Returns ``(start, end, spelling)`` triples covering the *entire* directive
        (e.g. the whole ``#include "lib.h"`` line), sorted by ``start`` and mutually
        disjoint, so a caller may splice replacement content into each span. Only
        references a splicing caller could resolve are reported: C++ ``<...>`` system
        includes are omitted, exactly as in ``references``.
        """
        raise NotImplementedError(
            f'{type(self).__name__} does not support dependency splicing.'
        )
```

**Step 4: Implement it for C++**

In `rbx/box/dependencies/cpp.py`, replace `_quoted_include_nodes` with a pair-yielding
version and keep the old name as a thin wrapper:

```python
def _quoted_include_pairs(root: Node) -> Iterator[Tuple[Node, Node]]:
    """Yield ``(preproc_include, string_literal)`` for each quoted ``#include``
    (skips ``<...>`` system includes and never matches includes inside comments)."""
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == 'preproc_include':
            for child in node.children:
                if child.type == 'string_literal':
                    yield node, child
                    break
                if child.type == 'system_lib_string':
                    break
        stack.extend(node.children)


def _quoted_include_nodes(root: Node) -> Iterator[Node]:
    for _, path_node in _quoted_include_pairs(root):
        yield path_node
```

Add `Tuple` to the `typing` import. Then on `CppScanner`, set `can_splice = True`
next to `can_rewrite = True` and add:

```python
    def reference_spans(self, text: str) -> List[Tuple[int, int, str]]:
        tree = _parser().parse(text.encode('utf-8'))
        spans = [
            (include_node.start_byte, include_node.end_byte, _spelling(path_node))
            for include_node, path_node in _quoted_include_pairs(tree.root_node)
        ]
        spans.sort()
        return spans
```

**Step 5: Run the tests**

```bash
uv run pytest tests/rbx/box/dependencies/ -v
```
Expected: PASS, and the pre-existing dependency tests still pass.

**Step 6: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/dependencies/scanner.py rbx/box/dependencies/cpp.py tests/rbx/box/dependencies/test_cpp_spans.py
git commit -m "$(cat <<'EOF'
feat(dependencies): let scanners report dependency directive spans

Amalgamation needs to replace a whole `#include` directive with the
included file's content. `rewrite` only renames the quoted path and
`references` carries no offsets, so add an optional splice capability.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: The amalgamation library

**Files:**
- Create: `rbx/box/dependencies/amalgamation.py`
- Test: `tests/rbx/box/dependencies/test_amalgamation.py`

**Step 1: Write the failing tests**

Create `tests/rbx/box/dependencies/test_amalgamation.py`:

```python
import pytest

from rbx.box.dependencies.amalgamation import AmalgamationError, amalgamate


def test_inlines_a_quoted_include(tmp_path):
    (tmp_path / 'lib.h').write_text('int helper();\n')
    root = tmp_path / 'main.cpp'
    root.write_text('#include "lib.h"\nint main(){}\n')

    result = amalgamate(root)

    text = result.content.decode()
    assert 'int helper();' in text
    assert '#include "lib.h"' not in text
    assert result.inlined[0] == root.resolve()


def test_inlines_a_diamond_only_once(tmp_path):
    (tmp_path / 'base.h').write_text('int base;\n')
    (tmp_path / 'a.h').write_text('#include "base.h"\nint a;\n')
    (tmp_path / 'b.h').write_text('#include "base.h"\nint b;\n')
    root = tmp_path / 'main.cpp'
    root.write_text('#include "a.h"\n#include "b.h"\nint main(){}\n')

    text = amalgamate(root).content.decode()

    assert text.count('int base;') == 1
    assert 'int a;' in text and 'int b;' in text


def test_drops_pragma_once(tmp_path):
    (tmp_path / 'lib.h').write_text('#pragma once\nint helper();\n')
    root = tmp_path / 'main.cpp'
    root.write_text('#include "lib.h"\nint main(){}\n')

    assert '#pragma once' not in amalgamate(root).content.decode()


def test_keeps_system_includes(tmp_path):
    root = tmp_path / 'main.cpp'
    root.write_text('#include <vector>\nint main(){}\n')

    assert '#include <vector>' in amalgamate(root).content.decode()


def test_resolves_from_extra_roots(tmp_path):
    builtin = tmp_path / 'builtin'
    builtin.mkdir()
    (builtin / 'testlib.h').write_text('int testlib_marker;\n')
    root = tmp_path / 'main.cpp'
    root.write_text('#include "testlib.h"\nint main(){}\n')

    result = amalgamate(root, extra_roots=[builtin])

    assert 'int testlib_marker;' in result.content.decode()


def test_errors_on_unresolvable_include(tmp_path):
    root = tmp_path / 'main.cpp'
    root.write_text('#include "nope.h"\nint main(){}\n')

    with pytest.raises(AmalgamationError) as exc:
        amalgamate(root)
    assert 'nope.h' in str(exc.value)
    assert 'main.cpp' in str(exc.value)


def test_keep_predicate_preserves_a_spelling(tmp_path):
    root = tmp_path / 'main.cpp'
    root.write_text('#include "nope.h"\nint main(){}\n')

    result = amalgamate(root, keep=lambda spelling: spelling == 'nope.h')

    assert '#include "nope.h"' in result.content.decode()
    assert result.kept == ['nope.h']


def test_tolerates_include_cycles(tmp_path):
    (tmp_path / 'a.h').write_text('#include "b.h"\nint a;\n')
    (tmp_path / 'b.h').write_text('#include "a.h"\nint b;\n')
    root = tmp_path / 'main.cpp'
    root.write_text('#include "a.h"\nint main(){}\n')

    text = amalgamate(root).content.decode()

    assert text.count('int a;') == 1
    assert text.count('int b;') == 1


def test_errors_on_unknown_extension(tmp_path):
    root = tmp_path / 'main.rs'
    root.write_text('fn main() {}\n')

    with pytest.raises(AmalgamationError):
        amalgamate(root)
```

**Step 2: Run and confirm failure**

```bash
uv run pytest tests/rbx/box/dependencies/test_amalgamation.py -v
```
Expected: `ModuleNotFoundError: No module named 'rbx.box.dependencies.amalgamation'`.

**Step 3: Implement the library**

Create `rbx/box/dependencies/amalgamation.py`:

```python
import dataclasses
import pathlib
import re
from typing import Callable, List, Optional, Sequence, Set

from rbx import utils
from rbx.box.dependencies import scanner as deps_scanner
from rbx.box.dependencies.scanner import DependencyScanner
from rbx.box.exception import RbxException

# Suffix -> registered scanner name, used when the caller does not pass a scanner.
_SCANNER_BY_SUFFIX = {
    '.c': 'cpp',
    '.cc': 'cpp',
    '.cpp': 'cpp',
    '.cxx': 'cpp',
    '.h': 'cpp',
    '.hh': 'cpp',
    '.hpp': 'cpp',
    '.hxx': 'cpp',
}

_PRAGMA_ONCE = re.compile(r'^[ \t]*#[ \t]*pragma[ \t]+once[ \t]*\r?\n?', re.MULTILINE)


class AmalgamationError(RbxException):
    """A source could not be reduced to a single self-contained translation unit."""


@dataclasses.dataclass(frozen=True)
class AmalgamationResult:
    """The outcome of :func:`amalgamate`.

    ``content`` is the single translation unit. ``inlined`` lists every file that
    contributed, in the order it was inlined (``root`` first). ``kept`` lists the
    spellings that were deliberately left as directives, in encounter order.
    """

    content: bytes
    inlined: List[pathlib.Path]
    kept: List[str]


def _infer_scanner(root: pathlib.Path) -> DependencyScanner:
    name = _SCANNER_BY_SUFFIX.get(root.suffix.lower())
    if name is None:
        raise AmalgamationError(
            f'Cannot amalgamate {root}: no dependency scanner is known for the '
            f'{root.suffix!r} extension. Pass an explicit `scanner=`.'
        )
    found = deps_scanner.get_scanner(name)
    if found is None:
        raise AmalgamationError(f'Dependency scanner {name!r} is not registered.')
    return found


def _resolve(
    spelling: str,
    including_file: pathlib.Path,
    extra_roots: Sequence[pathlib.Path],
) -> Optional[pathlib.Path]:
    """Resolve ``spelling`` beside the including file first, then in ``extra_roots``.

    Unlike the scanners' own resolution, this is deliberately *not* confined to the
    package root: amalgamation must reach builtin headers (testlib, rbx.h) that live
    in the app's resources.
    """
    candidates = [including_file.parent / spelling]
    candidates.extend(root / spelling for root in extra_roots)
    for candidate in candidates:
        resolved = utils.abspath(candidate)
        if resolved.is_file():
            return resolved
    return None


def amalgamate(
    root: pathlib.Path,
    *,
    extra_roots: Sequence[pathlib.Path] = (),
    keep: Optional[Callable[[str], bool]] = None,
    scanner: Optional[DependencyScanner] = None,
) -> AmalgamationResult:
    """Reduce ``root`` and its dependency closure to one self-contained source.

    Every resolvable dependency directive is replaced by the referenced file's own
    amalgamated content, each file contributing at most once (keyed on its resolved
    path), so diamonds collapse and cycles terminate. ``#pragma once`` is dropped,
    since the deduplication above already guarantees single inclusion and the pragma
    would otherwise warn in a merged unit. References the scanner does not report --
    C++ ``<...>`` system includes -- are untouched.

    A directive that cannot be resolved raises :class:`AmalgamationError` naming the
    including file and the spelling, unless ``keep`` returns ``True`` for it, in which
    case the directive survives verbatim.

    ``extra_roots`` are extra search directories for otherwise unresolvable spellings;
    this is how callers make builtin headers (``testlib.h``, ``rbx.h``) inlinable
    without this module knowing what they are.
    """
    root = utils.abspath(root)
    used_scanner = scanner if scanner is not None else _infer_scanner(root)
    if not used_scanner.can_splice:
        raise AmalgamationError(
            f'Cannot amalgamate {root}: the {used_scanner.name!r} dependency scanner '
            'does not support splicing.'
        )

    inlined: List[pathlib.Path] = []
    kept: List[str] = []
    visited: Set[pathlib.Path] = set()

    def render(path: pathlib.Path) -> bytes:
        if path in visited:
            return b''
        visited.add(path)
        inlined.append(path)

        text = _PRAGMA_ONCE.sub('', path.read_text(encoding='utf-8'))
        data = text.encode('utf-8')
        out = bytearray()
        pos = 0
        for start, end, spelling in used_scanner.reference_spans(text):
            out += data[pos:start]
            target = _resolve(spelling, path, extra_roots)
            if target is None:
                if keep is not None and keep(spelling):
                    kept.append(spelling)
                    out += data[start:end]
                else:
                    raise AmalgamationError(
                        f'Cannot amalgamate {root}: {path} references {spelling!r}, '
                        'which does not resolve to a file. Move the dependency next '
                        'to the source, add its directory to the search roots, or '
                        'drop the reference.'
                    )
            else:
                out += f'// amalgamated from {target}\n'.encode('utf-8')
                out += render(target)
                out += b'\n'
            pos = end
        out += data[pos:]
        return bytes(out)

    content = render(root)
    return AmalgamationResult(content=content, inlined=inlined, kept=kept)
```

**Step 4: Run the tests**

```bash
uv run pytest tests/rbx/box/dependencies/test_amalgamation.py -v
```
Expected: PASS (9 tests).

**Step 5: Verify the output actually compiles**

Add to the same test file:

```python
import shutil
import subprocess


@pytest.mark.skipif(shutil.which('g++') is None, reason='g++ not available')
def test_amalgamated_output_compiles(tmp_path):
    (tmp_path / 'lib.h').write_text('#pragma once\ninline int helper(){return 7;}\n')
    root = tmp_path / 'main.cpp'
    root.write_text(
        '#include <cstdio>\n#include "lib.h"\n'
        'int main(){printf("%d\\n", helper());}\n'
    )

    out = tmp_path / 'amalgamated.cpp'
    out.write_bytes(amalgamate(root).content)

    proc = subprocess.run(
        ['g++', '-std=gnu++17', '-o', str(tmp_path / 'a.out'), str(out)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
```

Run it, expect PASS (or skip when `g++` is absent).

**Step 6: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/dependencies/amalgamation.py tests/rbx/box/dependencies/test_amalgamation.py
git commit -m "$(cat <<'EOF'
feat(dependencies): add a reusable source amalgamator

MOJ's checker bridge compiles the package's checker with only testlib.h
reachable, so a checker including rbx.h or a local header cannot work
there. Reduce a source and its closure to one translation unit, keeping
the machinery package-agnostic so other flat targets can reuse it.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: The `moj` language extension

**Files:**
- Create: `rbx/box/packaging/moj_next/__init__.py` (empty)
- Create: `rbx/box/packaging/moj_next/extension.py`
- Create: `rbx/box/packaging/moj_next/moj_language_utils.py`
- Modify: `rbx/box/extensions.py`
- Modify: `rbx/resources/presets/default/env.rbx.yml`
- Test: `tests/rbx/box/packaging/moj_next/__init__.py` (empty)
- Test: `tests/rbx/box/packaging/moj_next/test_moj_language_utils.py`

**Step 1: Write the failing test**

```python
from rbx.box.packaging.moj_next.extension import MojLanguageExtension
from rbx.box.packaging.moj_next.moj_language_utils import (
    get_emitted_moj_languages,
    get_moj_template_name,
)


def test_default_env_emits_the_five_preset_languages(testing_pkg):
    testing_pkg.save()
    assert set(get_emitted_moj_languages()) >= {'c', 'cpp', 'py', 'java', 'kt'}


def test_template_defaults_to_the_language_name(testing_pkg):
    testing_pkg.save()
    assert get_moj_template_name('cpp') == 'cpp'


def test_template_is_required_when_languages_is_set():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MojLanguageExtension(languages=['cpp'])


def test_flags_default_to_none():
    assert MojLanguageExtension().flags is None
```

**Step 2: Run and confirm failure.**

**Step 3: Implement `extension.py`**

```python
import typing

from pydantic import ConfigDict, Field, model_validator

from rbx.utils import RejectsRemovedFields

# The language ids mojtools ships a `lang/<id>/` directory for. `py2`/`py3` are legacy
# spellings that `build-and-test.sh` normalizes to `py`; they stay accepted so a
# package can carry a `scripts/py3` override for a legacy judge.
MojLanguage = typing.Literal[
    'apl', 'c', 'cpp', 'cs', 'go', 'hs', 'java', 'js', 'kt', 'ml',
    'pas', 'pl', 'py', 'py2', 'py3', 'riscv', 'rs', 'sh', 'spim',
]


class MojLanguageExtension(RejectsRemovedFields):
    """Language-level extensions for MOJ packaging.

    Mirrors ``BocaLanguageExtension``: an rbx language declares which MOJ language ids
    it maps to, and which on-disk script template to emit for them.
    """

    model_config = ConfigDict(extra='forbid')

    languages: typing.Optional[typing.List[str]] = Field(
        default=None,
        description='MOJ language ids this rbx language maps to. The first entry is '
        'the canonical one; every entry gets its own scripts/<id>/ directory.',
    )
    template: typing.Optional[str] = Field(
        default=None,
        description='On-disk template dir under '
        'rbx/resources/packagers/moj_next/scripts/ to source the per-language '
        'compile.sh and run.sh from. Required whenever `languages` is set.',
    )
    flags: typing.Optional[str] = Field(
        default=None,
        description='Compilation flags substituted into the template. Unset uses the '
        "template's own default.",
    )

    @model_validator(mode='after')
    def _require_template_with_languages(self) -> 'MojLanguageExtension':
        if self.languages and not self.template:
            raise ValueError(
                'A `template` is required when `languages` is set on a MOJ language '
                'extension. Set `template` to one of the on-disk template dirs '
                '(c, cpp, java, kt, py).'
            )
        return self

    @property
    def resolved_languages(self) -> typing.List[str]:
        return self.languages or []

    @property
    def primary_language(self) -> typing.Optional[str]:
        langs = self.resolved_languages
        return langs[0] if langs else None

    @property
    def resolved_template(self) -> typing.Optional[str]:
        return self.template
```

**Step 4: Implement `moj_language_utils.py`**

Model it on `boca_language_utils.py` — same three functions, same name-fallback
behavior, reading the `moj` extension key:

```python
import typing

from rbx.box.environment import get_environment
from rbx.box.packaging.moj_next.extension import MojLanguage, MojLanguageExtension


def get_rbx_language_from_moj_language(moj_language: str) -> typing.Optional[str]:
    for language in get_environment().languages:
        extension = language.get_extension_or_default('moj', MojLanguageExtension)
        if moj_language in extension.resolved_languages:
            return language.name
    return None


def get_moj_language_extension(moj_language: str) -> MojLanguageExtension:
    """The extension of the rbx language that declares ``moj_language``, or an empty
    one when no rbx language claims it."""
    rbx_name = get_rbx_language_from_moj_language(moj_language)
    for language in get_environment().languages:
        if language.name == rbx_name:
            return language.get_extension_or_default('moj', MojLanguageExtension)
    return MojLanguageExtension()


def get_moj_template_name(moj_language: str) -> str:
    """The on-disk template dir to source scripts from when emitting
    ``moj_language``. Falls back to the id itself when no rbx language claims it."""
    return get_moj_language_extension(moj_language).resolved_template or moj_language


def get_emitted_moj_languages() -> typing.List[MojLanguage]:
    """The ordered, deduplicated MOJ language ids to emit script dirs for: the union
    of every rbx language's `moj` extension `languages`, plus a name fallback for a
    zero-config rbx language whose own name is a MOJ id."""
    seen: typing.Dict[str, None] = {}
    moj_literals = set(typing.get_args(MojLanguage))
    for language in get_environment().languages:
        extension = language.get_extension_or_default('moj', MojLanguageExtension)
        resolved = extension.resolved_languages
        if resolved:
            for moj_lang in resolved:
                seen.setdefault(moj_lang, None)
        elif language.name in moj_literals:
            seen.setdefault(language.name, None)
    return typing.cast(typing.List[MojLanguage], list(seen.keys()))
```

**Step 5: Register the extension**

In `rbx/box/extensions.py`, add the import and the field on `LanguageExtensions`:

```python
from rbx.box.packaging.moj_next.extension import MojLanguageExtension
...
    moj: Optional[MojLanguageExtension] = Field(
        default=None, description='Language-level extensions for MOJ packaging.'
    )
```

**Step 6: Declare the preset mappings**

In `rbx/resources/presets/default/env.rbx.yml`, add a `moj` block under each
language's `extensions`, alongside the existing `boca` block:

```yaml
# under cpp
      moj:
        languages: ["cpp"]
        template: "cpp"
        flags: "-std=c++20 -O2 -lm -static"
# under c
      moj:
        languages: ["c"]
        template: "c"
        flags: "-std=gnu11 -O2 -lm -static"
# under py
      moj:
        languages: ["py"]
        template: "py"
# under java
      moj:
        languages: ["java"]
        template: "java"
# under kt
      moj:
        languages: ["kt"]
        template: "kt"
```

**Step 7: Run the tests**

```bash
uv run pytest tests/rbx/box/packaging/moj_next/ -v
uv run pytest tests/rbx/box/test_environment.py -v
```
Expected: PASS. If the env preset has a schema-validation test, it must stay green.

**Step 8: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/packaging/moj_next rbx/box/extensions.py rbx/resources/presets/default/env.rbx.yml tests/rbx/box/packaging/moj_next
git commit -m "$(cat <<'EOF'
feat(packaging): add a moj language extension

Mirror the BOCA language extension so an rbx language declares which MOJ
language ids it maps to and which script template to emit, rather than
hardcoding a mapping that a custom env could not redirect.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Bundled script resources

**Files:**
- Create: `rbx/resources/packagers/moj_next/scripts/compare.sh`
- Create: `rbx/resources/packagers/moj_next/scripts/{c,cpp,py,java,kt}/{compile.sh,run.sh}`
- Test: `tests/rbx/box/packaging/moj_next/test_resources.py`

**Step 1: Write the failing test**

```python
from rbx.config import get_default_app_path


def _scripts():
    return get_default_app_path() / 'packagers' / 'moj_next' / 'scripts'


def test_compare_stub_delegates_to_mojtools():
    text = (_scripts() / 'compare.sh').read_text()
    # The bridge must stay upstream: the package carries a pointer, never a copy.
    assert 'MOJTOOLS_DIR' in text
    assert 'checker-bridge.sh' in text
    assert 'exec' in text


def test_every_template_has_compile_and_run():
    for template in ['c', 'cpp', 'py', 'java', 'kt']:
        assert (_scripts() / template / 'compile.sh').is_file()
        assert (_scripts() / template / 'run.sh').is_file()


def test_compile_templates_emit_the_bin_contract():
    for template in ['c', 'cpp', 'py', 'java', 'kt']:
        text = (_scripts() / template / 'compile.sh').read_text()
        # No BIN= line on stdout means Compilation Error, per build-and-test.sh.
        assert 'echo BIN=' in text
        assert 'cd /tmp/rwdir' in text


def test_run_templates_source_binfile():
    for template in ['c', 'cpp', 'py', 'java', 'kt']:
        text = (_scripts() / template / 'run.sh').read_text()
        assert 'source binfile.sh' in text
        assert '/tmp/in' in text and '/tmp/out' in text


def test_jvm_templates_size_the_heap_from_the_problem_limit():
    for template in ['java', 'kt']:
        text = (_scripts() / template / 'run.sh').read_text()
        assert 'MOJ_MEMLIMITMB' in text
        assert 'MOJ_STACKKB' in text
        assert '-jar' in text
```

**Step 2: Run and confirm failure.**

**Step 3: Write `compare.sh`**

This is a byte-copy of mojtools' `testlib/compare-stub.sh`, which is the canonical
stub `install-checker.sh` installs. Do **not** paraphrase it:

```bash
#!/bin/bash
# scripts/compare.sh -- STUB. Emitted by rbx's moj-next packager; equivalent to what
# mojtools' testlib/install-checker.sh installs.
#
# The checker BRIDGE lives in MOJTOOLS (single source):
#   mojtools/testlib/checker-bridge.sh -- compiles THIS package's scripts/checker.cpp
#   on first comparison (cache outside scripts/) and translates the result to the
#   judge's contract.
# This file is only the POINTER: do not edit it, and never copy the bridge here.
# (Packages carrying their own bridge copy is what spread one bwrap bug to 198 of
# them.)
#
# MOJ contract:  compare.sh <team output> <expected> <input>
#                -> exit 4=AC  5=AC,PE  6=WA  (anything else = judge error)
set -u
_pkg="$(cd "$(dirname "$(readlink -f "$0")")/.." 2>/dev/null && pwd)"
_mt="${MOJTOOLS_DIR:-$PWD}"    # build-and-test.sh EXPORTS MOJTOOLS_DIR
_br="$_mt/testlib/checker-bridge.sh"
[[ -x "$_br" ]] || {
  echo "compare.sh: checker bridge not found at '$_br' (MOJTOOLS_DIR='${MOJTOOLS_DIR:-}')"
  exit 7
}
exec "$_br" --pkg "$_pkg" "$@"
```

**Step 4: Write the compile templates**

`cpp/compile.sh` (`c/compile.sh` is the same with `gcc`, `*.c`, and its own default):

```bash
#!/bin/bash
# Runs INSIDE the jail, in a writable /tmp/rwdir already holding the submission.
# Printing `BIN=<artifact>` on stdout is MANDATORY: without it build-and-test.sh
# reports Compilation Error.
exec 2>/tmp/stderrlog > /tmp/out
cd /tmp/rwdir

SRC=$(ls *.cpp *.cc *.cxx 2>/dev/null | head -1)
[[ -n "$SRC" ]] || exit 1

g++ {{rbxFlags}} "$SRC" -o main || exit 1
echo BIN=main
```

`py/compile.sh` — mirror mojtools' own: syntax-check so a syntax error becomes a
Compilation Error rather than a Runtime Error.

```bash
#!/bin/bash
exec 2>/tmp/stderrlog > /tmp/out
cd /tmp/rwdir

BINF=$(ls *.py *.py3 *.py2 2>/dev/null | head -1)
[[ -n "$BINF" ]] || exit 1
PY=python3; command -v pypy3 >/dev/null 2>&1 && PY=pypy3
$PY -m py_compile "$BINF" || exit 1
echo BIN=$BINF
```

`java/compile.sh` — the manifest-jar approach borrowed from
`rbx/resources/packagers/boca/compile/java`, so the runtime never has to elect a main
class:

```bash
#!/bin/bash
exec 2>/tmp/stderrlog > /tmp/out
cd /tmp/rwdir

SRC=$(ls *.java 2>/dev/null | head -1)
[[ -n "$SRC" ]] || exit 1
klass=$(basename "$SRC" .java)
[[ -n "$klass" ]] || klass=Main

export _JAVA_OPTIONS="-Xmx700M -Xms64M"
javac *.java || exit 1

# Name the entry point in the manifest so run.sh is just `java -jar`. Electing the
# class at runtime (grep for main, else `ls *.class`) is locale-dependent once the
# compiler emits nested `Main$X.class` files.
printf 'Main-Class: %s\n' "$klass" > Manifest.txt
jar cfm prog.jar Manifest.txt *.class || exit 1
echo BIN=prog.jar
```

`kt/compile.sh` — `kotlinc -include-runtime` already writes `Main-Class` from
`fun main()`:

```bash
#!/bin/bash
exec 2>/tmp/stderrlog > /tmp/out
cd /tmp/rwdir

SRC=$(ls *.kt 2>/dev/null | head -1)
[[ -n "$SRC" ]] || exit 1

export JAVA_OPTS="-Xmx700M -Xms64M"
kotlinc "$SRC" -include-runtime -d prog.jar || exit 1
echo BIN=prog.jar
```

**Step 5: Write the run templates**

`c/run.sh` and `cpp/run.sh`:

```bash
#!/bin/bash
exec &>/tmp/stderrlog
cd /tmp/dir
source binfile.sh
exec ./$BIN < /tmp/in > /tmp/out
```

`py/run.sh`:

```bash
#!/bin/bash
exec &>/tmp/stderrlog
cd /tmp/dir
source binfile.sh
command -v pypy3 >/dev/null 2>&1 && exec pypy3 ./$BIN < /tmp/in > /tmp/out
exec python3 ./$BIN < /tmp/in > /tmp/out
```

`java/run.sh` and `kt/run.sh` are identical — the manifest jar makes them so:

```bash
#!/bin/bash
exec &>/tmp/stderrlog
cd /tmp/dir
source binfile.sh
# binfile.sh is generated by build-and-test.sh and is the only channel carrying the
# problem's limits into the jail. JVM threads ignore the main thread's ulimit -s, so
# the stack has to be mirrored into -Xss explicitly.
exec java -Xms10m -Xmx${MOJ_MEMLIMITMB:-500}m -Xss${MOJ_STACKKB:-131072}k \
     -jar "$BIN" < /tmp/in > /tmp/out
```

**Step 6: Check the resources ship**

Confirm `pyproject.toml` includes `rbx/resources/**` in the wheel (it already ships
`rbx/resources/packagers/moj`). If the packaging config enumerates directories
explicitly, add `moj_next`.

```bash
uv run pytest tests/rbx/box/packaging/moj_next/test_resources.py -v
```
Expected: PASS.

**Step 7: Commit**

```bash
git add rbx/resources/packagers/moj_next tests/rbx/box/packaging/moj_next/test_resources.py
git commit -m "$(cat <<'EOF'
feat(packaging): bundle moj-next compare stub and language scripts

The compare driver runs on the judge host, so it ships as mojtools'
canonical stub rather than a private bridge copy. Only the in-jail
compile/run scripts are real copies. Java and Kotlin name the entry
point in a jar manifest, which avoids MOJ's locale-dependent runtime
class election.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Test naming and the score file (pure functions first)

Keep this logic pure and separately testable — it is where the format's sharp edges
live.

**Files:**
- Create: `rbx/box/packaging/moj_next/naming.py`
- Test: `tests/rbx/box/packaging/moj_next/test_naming.py`

**Step 1: Write the failing tests**

```python
import pytest

from rbx.box.exception import RbxException
from rbx.box.packaging.moj_next.naming import (
    SAMPLES_GLOB,
    ScoreGroup,
    build_score_file,
    sanitize_group_name,
    test_name,
)


def test_sample_names_start_with_sample():
    assert test_name('samples', group_index=0, index=1, is_sample=True) == 'sample001'


def test_non_sample_names_carry_a_group_index():
    assert test_name('easy', group_index=1, index=3, is_sample=False) == 't01_easy_003'


def test_samples_sort_before_other_tests():
    # MOJ's judging loop is a plain lexicographic glob over tests/input/*.
    names = sorted(
        [
            test_name('easy', group_index=1, index=1, is_sample=False),
            test_name('samples', group_index=0, index=1, is_sample=True),
        ]
    )
    assert names[0].startswith('sample')


def test_group_names_are_sanitized():
    # A dash would break score-summary.sh, which splits the line on IFS='-'.
    assert '-' not in sanitize_group_name('main-group')
    assert sanitize_group_name('main-group') == 'main_group'
    assert sanitize_group_name('a b/c') == 'a_b_c'


def test_score_file_lists_groups_in_order():
    content = build_score_file(
        [
            ScoreGroup(glob=SAMPLES_GLOB, weight=0),
            ScoreGroup(glob='t01_easy_*', weight=40),
            ScoreGroup(glob='t02_full_*', weight=60),
        ]
    )
    assert content == (
        'sample* - 0 pontos\n't01_easy_* - 40 pontos\n't02_full_* - 60 pontos\n'
    )


def test_score_file_rejects_non_integer_weights():
    # score-summary.sh extracts the weight with ${SCORE//[^0-9]/}, so 40.5 -> 405.
    with pytest.raises(RbxException) as exc:
        build_score_file([ScoreGroup(glob='t01_easy_*', weight=40.5)])
    assert 'integer' in str(exc.value).lower()


def test_score_group_glob_matches_moj_group_name_derivation():
    # score-summary.sh derives a group name by stripping the trailing '*' from the
    # glob, and matches a test by stripping its trailing digits. Both must agree.
    name = test_name('easy', group_index=1, index=7, is_sample=False)
    glob = 't01_easy_*'
    assert name.rstrip('0123456789') == glob[:-1]
```

**Step 2: Run and confirm failure.**

**Step 3: Implement `naming.py`**

```python
import dataclasses
import re
from typing import List, Sequence

from rbx.box.exception import RbxException

# Samples must be named `sample*`: MOJ picks the statement's examples from
# tests/input/sample* and `validate-problem.sh` hard-fails a package without them.
SAMPLE_PREFIX = 'sample'
SAMPLES_GLOB = 'sample*'

# Non-sample tests are prefixed so they sort AFTER samples in MOJ's lexicographic
# judging loop, which is also the order the statement presents them in.
TESTSET_PREFIX = 't'


def sanitize_group_name(name: str) -> str:
    """Reduce a group name to `[A-Za-z0-9_]`.

    A `-` in particular must not survive: `score-summary.sh` parses each
    `tests/score` line with `IFS='-'`, so a dash would corrupt the weight.
    """
    return re.sub(r'[^A-Za-z0-9_]', '_', name)


def group_prefix(group_name: str, group_index: int) -> str:
    """The shared prefix of every test in a group, without the trailing `*`."""
    return f'{TESTSET_PREFIX}{group_index:02d}_{sanitize_group_name(group_name)}_'


def group_glob(group_name: str, group_index: int) -> str:
    return f'{group_prefix(group_name, group_index)}*'


def test_name(group_name: str, group_index: int, index: int, is_sample: bool) -> str:
    if is_sample:
        return f'{SAMPLE_PREFIX}{index:03d}'
    return f'{group_prefix(group_name, group_index)}{index:03d}'


@dataclasses.dataclass(frozen=True)
class ScoreGroup:
    glob: str
    weight: float


def build_score_file(groups: Sequence[ScoreGroup]) -> str:
    """Render `tests/score`.

    Each line is `<glob> - <weight> pontos`. Groups are all-or-nothing and the
    problem's value is the sum of the weights.
    """
    lines: List[str] = []
    for group in groups:
        if float(group.weight) != int(group.weight):
            raise RbxException(
                f'MOJ group weights must be integers, but group {group.glob!r} scores '
                f'{group.weight}. MOJ parses the weight by stripping non-digits, so '
                f'{group.weight} would be read as {str(group.weight).replace(".", "")}.'
            )
        lines.append(f'{group.glob} - {int(group.weight)} pontos')
    return '\n'.join(lines) + '\n'
```

**Step 4: Run the tests**

```bash
uv run pytest tests/rbx/box/packaging/moj_next/test_naming.py -v
```
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/packaging/moj_next/naming.py tests/rbx/box/packaging/moj_next/test_naming.py
git commit -m "$(cat <<'EOF'
feat(packaging): add moj-next test naming and score rendering

Samples must be named sample* and sort before the testset, and MOJ
derives a test's group by stripping trailing digits, so the naming and
the tests/score globs have to agree by construction. Reject fractional
weights: MOJ strips non-digits, silently turning 40.5 into 405.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: The packager — metadata, conf, statement, tests

**Files:**
- Create: `rbx/box/packaging/moj_next/packager.py`
- Test: `tests/rbx/box/packaging/moj_next/test_packager.py`

Build the packager incrementally. This task covers everything except the checker,
solutions and language scripts.

**Step 1: Write the failing tests**

```python
from rbx.box.packaging.moj_next.packager import MojNextPackager
from rbx.box.schema import TaskType


def test_rejects_interactive_problems():
    assert MojNextPackager.task_types() == [TaskType.BATCH]


def test_builds_no_statements():
    # MOJ's statement format is not supported yet; a dummy enunciado is written
    # instead, so nothing should be built.
    assert MojNextPackager(testcase_entries=[]).statement_types() == []


def test_writes_the_mandatory_metadata_files(moj_next_package):
    assert (moj_next_package / 'author').read_text().strip() != ''
    assert (moj_next_package / 'tags').exists()


def test_writes_a_statement_with_the_mandatory_sections(moj_next_package):
    text = (moj_next_package / 'docs' / 'enunciado.md').read_text()
    # validate-problem.sh hard-fails without these two headings.
    assert '## Entrada' in text
    assert '## Saída' in text
    # A fenced block trips its soft "example written by hand" warning.
    assert '```' not in text


def test_does_not_write_server_owned_or_calibrated_files(moj_next_package):
    assert not (moj_next_package / 'tl').exists()
    assert not (moj_next_package / '.moj-meta.json').exists()
    # testlib.h in scripts/ would take precedence over the mojtools-vendored one.
    assert not (moj_next_package / 'scripts' / 'testlib.h').exists()


def test_conf_uses_the_rss_memory_knob(moj_next_package):
    conf = (moj_next_package / 'conf').read_text()
    assert 'MEMLIMITMB=' in conf
    # ULIMITS[-v] is the legacy knob; MEMLIMITMB deliberately replaces it.
    assert 'ULIMITS[-v]' not in conf
    assert 'ULIMITS[-f]=' in conf
    assert 'TLMOD[calibrafactor]=1.35' in conf
```

Add a `moj_next_package` fixture in `tests/rbx/box/packaging/moj_next/conftest.py`
that builds a minimal package and returns the unpacked output directory. Model it on
how `tests/rbx/box/packaging/e2e` or the boca tests drive a packager; if no such
helper exists, call `packager.package(build_path, into_path, [])` directly with a
`testing_pkg` and return `into_path`.

**Step 2: Run and confirm failure.**

**Step 3: Implement the packager skeleton**

```python
import pathlib
import shutil
from typing import List

from rbx.box import package
from rbx.box.packaging.packager import BasePackager, BuiltStatement
from rbx.box.schema import TaskType
from rbx.box.statements.schema import StatementType

# MOJ hard-requires an `author` file and rbx has no author field, so a clear
# placeholder keeps validate-problem.sh green until the setter fills it in.
DEFAULT_AUTHOR = 'Unknown\n'

# No title (the renderer injects an <h1> from the server-side display_title), no
# examples (MOJ injects them from tests/input/sample*), and no fenced blocks (they
# trip validate-problem.sh's hand-written-example warning).
DUMMY_STATEMENT = """Enunciado ainda não disponível.

## Entrada

A descrever.

## Saída

A descrever.
"""


class MojNextPackager(BasePackager):
    @classmethod
    def name(cls) -> str:
        return 'moj-next'

    @classmethod
    def task_types(cls) -> List[TaskType]:
        # MOJ's interactive support uses its own arbiter protocol, not a testlib
        # interactor. The legacy `moj` packager still covers interactive problems.
        return [TaskType.BATCH]

    def statement_types(self) -> List[StatementType]:
        return []

    def _write_conf(self, into_path: pathlib.Path) -> None:
        pkg = package.find_problem_package_or_die()
        lines = [
            '# Generated by rbx. Do not edit by hand.',
            '',
            '# Memory limit by measured peak RSS. Setting this also makes MOJ drop the',
            '# virtual-memory ulimit, which unfairly penalizes JVM/Go, and feeds the',
            '# JVM -Xmx through binfile.sh.',
            f'MEMLIMITMB={pkg.memoryLimit}',
            '',
            f'ULIMITS[-f]={pkg.outputLimit}',
            '',
            "# MOJ measures the time limit; it is never authored. The judge runs every",
            '# sols/good solution, takes the worst time per language, and multiplies by',
            '# this factor.',
            '# TODO(rbx): derive this from the authored timeLimit divided by the',
            '# measured model-solution runtime, so the calibrated limit lands near the',
            "# problem's own time limit.",
            'TLMOD[calibrafactor]=1.35',
            '',
        ]
        (into_path / 'conf').write_text('\n'.join(lines))

    def package(
        self,
        build_path: pathlib.Path,
        into_path: pathlib.Path,
        built_statements: List[BuiltStatement],
    ) -> pathlib.Path:
        into_path.mkdir(parents=True, exist_ok=True)

        (into_path / 'author').write_text(DEFAULT_AUTHOR)
        (into_path / 'tags').write_text('')
        self._write_conf(into_path)

        docs_path = into_path / 'docs'
        docs_path.mkdir(parents=True, exist_ok=True)
        (docs_path / 'enunciado.md').write_text(DUMMY_STATEMENT)

        self._write_tests(into_path)

        shutil.make_archive(str(build_path / self.package_basename()), 'zip', into_path)
        return (build_path / self.package_basename()).with_suffix('.zip')
```

**Step 4: Implement `_write_tests`**

Walk `self.get_built_testcase_entries()`, grouping by `entry.group_entry.group`.
Determine the group index from the order of `pkg.testcases`; treat the group whose
name is `samples` as the sample group. For each entry write
`tests/input/<name>` and `tests/output/<name>` using `naming.test_name`, copying
`entry.metadata.copied_to.inputPath` / `.outputPath` (touch an empty output when the
output path is `None`, matching the legacy packager).

Raise an `RbxException` when no sample testcase exists, explaining that MOJ's
`examples_present` check is a hard gate.

**Step 5: Add and run the test-emission tests**

```python
def test_samples_are_named_sample_and_come_first(moj_next_package):
    names = sorted(p.name for p in (moj_next_package / 'tests' / 'input').iterdir())
    assert names[0].startswith('sample')
    assert all(
        (moj_next_package / 'tests' / 'output' / name).exists() for name in names
    )


def test_every_input_has_a_paired_output(moj_next_package):
    inputs = {p.name for p in (moj_next_package / 'tests' / 'input').iterdir()}
    outputs = {p.name for p in (moj_next_package / 'tests' / 'output').iterdir()}
    assert inputs == outputs
```

```bash
uv run pytest tests/rbx/box/packaging/moj_next/test_packager.py -v
```
Expected: PASS.

**Step 6: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/packaging/moj_next/packager.py tests/rbx/box/packaging/moj_next
git commit -m "$(cat <<'EOF'
feat(packaging): emit moj-next metadata, conf and tests

Ship no tl: MOJ measures the time limit and the conf carries the only
limit knobs. Use MEMLIMITMB rather than the legacy virtual-memory
ulimit, and name samples so they satisfy MOJ's mandatory examples check.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `tests/score` for POINTS problems

**Files:**
- Modify: `rbx/box/packaging/moj_next/packager.py`
- Test: `tests/rbx/box/packaging/moj_next/test_score.py`

**Step 1: Write the failing tests**

```python
def test_binary_problems_emit_no_score_file(moj_next_binary_package):
    # Without tests/score MOJ scores by percentage of tests and still requires all
    # of them to pass, which is the correct ICPC semantics.
    assert not (moj_next_binary_package / 'tests' / 'score').exists()


def test_points_problems_emit_a_score_file(moj_next_points_package):
    content = (moj_next_points_package / 'tests' / 'score').read_text()
    assert content.startswith('sample* - 0 pontos')
    assert ' pontos' in content


def test_every_test_matches_exactly_one_score_group(moj_next_points_package):
    import fnmatch

    globs = [
        line.split(' - ')[0]
        for line in (moj_next_points_package / 'tests' / 'score')
        .read_text()
        .splitlines()
        if line.strip() and not line.startswith('#')
    ]
    for path in (moj_next_points_package / 'tests' / 'input').iterdir():
        matched = [g for g in globs if fnmatch.fnmatch(path.name, g)]
        assert len(matched) == 1, f'{path.name} matched {matched}'
```

**Step 2: Run and confirm failure.**

**Step 3: Implement**

In `package()`, when `pkg.scoring == ScoreType.POINTS`, build the `ScoreGroup` list —
`ScoreGroup(SAMPLES_GLOB, weight=<samples group score or 0>)` followed by one
`ScoreGroup(group_glob(name, index), weight=group.score)` per non-sample group in
`pkg.testcases` order — and write `build_score_file(...)` to `tests/score`.

**Step 4: Run the tests, expect PASS.**

**Step 5: Commit**

```bash
git add rbx/box/packaging/moj_next/packager.py tests/rbx/box/packaging/moj_next/test_score.py
git commit -m "$(cat <<'EOF'
feat(packaging): emit tests/score for moj-next points problems

MOJ has no per-test partial credit: a checker returning _points is a
judge error there, so subtasks must go through tests/score groups.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: The amalgamated checker

**Files:**
- Modify: `rbx/box/packaging/moj_next/packager.py`
- Test: `tests/rbx/box/packaging/moj_next/test_checker.py`

**Step 1: Write the failing tests**

```python
def test_checker_is_a_single_self_contained_file(moj_next_package):
    scripts = moj_next_package / 'scripts'
    text = (scripts / 'checker.cpp').read_text()
    # The bridge binds only checker.cpp and testlib.h into the jail, so nothing else
    # may be referenced.
    assert '#include "testlib.h"' not in text
    assert '#include "rbx.h"' not in text
    assert not (scripts / 'testlib.h').exists()
    assert not (scripts / 'rbx.h').exists()


def test_checker_inlines_testlib(moj_next_package):
    text = (moj_next_package / 'scripts' / 'checker.cpp').read_text()
    assert 'registerTestlibCmd' in text or 'InStream' in text


def test_compare_is_the_canonical_stub(moj_next_package):
    from rbx.config import get_default_app_path

    emitted = moj_next_package / 'scripts' / 'compare.sh'
    bundled = (
        get_default_app_path() / 'packagers' / 'moj_next' / 'scripts' / 'compare.sh'
    )
    assert emitted.read_bytes() == bundled.read_bytes()
    assert emitted.stat().st_mode & 0o111, 'compare.sh must be executable'


def test_refuses_an_unresolvable_checker_include(testing_pkg):
    import pytest

    from rbx.box.exception import RbxException

    testing_pkg.add_file('check.cpp').write_text(
        '#include "../outside/lib.h"\n#include "testlib.h"\nint main(){}\n'
    )
    testing_pkg.set_checker('check.cpp')
    testing_pkg.save()

    with pytest.raises((RbxException, SystemExit)):
        MojNextPackager(testcase_entries=[])._amalgamate_checker()  # noqa: SLF001


def test_warns_about_partial_scoring_checkers(testing_pkg, capsys):
    testing_pkg.add_file('check.cpp').write_text(
        '#include "testlib.h"\nint main(){ quitp(0.5, "half"); }\n'
    )
    testing_pkg.set_checker('check.cpp')
    testing_pkg.save()

    MojNextPackager(testcase_entries=[])._amalgamate_checker()  # noqa: SLF001

    assert 'quitp' in capsys.readouterr().out
```

**Step 2: Run and confirm failure.**

**Step 3: Implement**

Add to the packager:

```python
    def _builtin_header_roots(self) -> List[pathlib.Path]:
        """Directories holding the headers rbx injects beside a source.

        These are what make `testlib.h` and `rbx.h` inlinable; the amalgamator itself
        knows nothing about them.
        """
        return [get_testlib().parent, header.get_header().parent]

    def _amalgamate_checker(self) -> bytes:
        checker = package.get_checker_or_builtin()
        try:
            result = amalgamate(
                utils.abspath(checker.path),
                extra_roots=self._builtin_header_roots(),
            )
        except AmalgamationError as e:
            console.console.print(
                f'[error]Cannot package {checker.href()} for MOJ.[/error]\n'
                f'[error]{e}[/error]\n'
                '[error]MOJ compiles the checker with only checker.cpp and testlib.h '
                'reachable, so it must reduce to a single self-contained file.[/error]'
            )
            raise typer.Exit(1) from e
        text = result.content.decode()
        if 'quitp' in text or '_points' in text:
            console.console.print(
                '[warning]The checker calls [item]quitp[/item]/[item]_points[/item], '
                'but MOJ maps testlib partial results to a judge error. Use '
                '[item]tests/score[/item] groups for subtasks instead.[/warning]'
            )
        return result.content
```

Call it from `package()`, writing `scripts/checker.cpp` and copying the bundled
`compare.sh` with `chmod(0o755)`.

**Step 4: Add a compile check**

```python
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('g++') is None, reason='g++ not available')
def test_amalgamated_checker_compiles_at_gnupp17(moj_next_package, tmp_path):
    # MOJ's bridge compiles with -std=gnu++17 and these forced includes.
    proc = subprocess.run(
        [
            'g++', '-O2', '-std=gnu++17',
            '-include', 'cassert', '-include', 'cstring', '-include', 'cstdint',
            '-o', str(tmp_path / 'checker'),
            str(moj_next_package / 'scripts' / 'checker.cpp'),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
```

```bash
uv run pytest tests/rbx/box/packaging/moj_next/test_checker.py -v
```
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/packaging/moj_next/packager.py tests/rbx/box/packaging/moj_next/test_checker.py
git commit -m "$(cat <<'EOF'
feat(packaging): ship an amalgamated checker for moj-next

MOJ's bridge binds only checker.cpp and testlib.h into the compile jail,
so a checker including rbx.h or a local header would fail every test
with a judge error. Inline the whole closure and refuse to package when
it cannot be inlined, rather than shipping something that always UEs.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Solutions

**Files:**
- Modify: `rbx/box/packaging/moj_next/packager.py`
- Test: `tests/rbx/box/packaging/moj_next/test_solutions.py`

**Step 1: Write the failing tests**

```python
def test_accepted_solutions_go_to_good(moj_next_package):
    good = list((moj_next_package / 'sols' / 'good').iterdir())
    assert good, 'MOJ calibrates the time limit from sols/good'


def test_outcomes_map_to_directories(moj_next_package_with_all_outcomes):
    root = moj_next_package_with_all_outcomes / 'sols'
    assert (root / 'good').is_dir()
    assert (root / 'slow').is_dir()
    assert (root / 'wrong').is_dir()


def test_solutions_are_amalgamated(testing_pkg):
    testing_pkg.add_file('lib.h').write_text('#pragma once\nint k(){return 1;}\n')
    testing_pkg.add_solution(
        'sol.cpp', outcome='accepted'
    ).write_text('#include "lib.h"\nint main(){return k()-1;}\n')
    testing_pkg.save()
    # A solution is compiled from a single file inside the jail.
    content = MojNextPackager(testcase_entries=[])._solution_content(  # noqa: SLF001
        ...
    )
    assert b'int k()' in content
    assert b'#include "lib.h"' not in content


def test_basename_collision_in_one_tag_is_an_error(testing_pkg):
    import pytest

    from rbx.box.exception import RbxException

    testing_pkg.add_solution('a/sol.cpp', outcome='accepted')
    testing_pkg.add_solution('b/sol.cpp', outcome='accepted')
    testing_pkg.save()

    with pytest.raises((RbxException, SystemExit)):
        MojNextPackager(testcase_entries=[])._write_solutions(...)  # noqa: SLF001
```

Adjust the private-method signatures to whatever you implement; keep the assertions.

**Step 2: Run and confirm failure.**

**Step 3: Implement**

```python
    def _tag_for(self, solution) -> Optional[str]:
        outcome = solution.outcome
        if outcome == ExpectedOutcome.ACCEPTED:
            return 'good'
        if outcome == ExpectedOutcome.ACCEPTED_OR_TLE:
            return 'pass'
        if outcome.is_slow():
            return 'slow'
        if outcome == ExpectedOutcome.ANY:
            return None
        return 'wrong'
```

Write each solution under `sols/<tag>/<basename>`, preserving the basename (Java
requires the filename to match its public class). Error on a basename collision inside
one tag directory. Amalgamate C/C++ solutions through the same library; for other
languages, error when the closure has more than one file. Warn and skip `ANY`. Error
when no solution lands in `good/`, since MOJ cannot calibrate without one.

**Step 4: Run the tests, expect PASS.**

**Step 5: Commit**

```bash
git add rbx/box/packaging/moj_next/packager.py tests/rbx/box/packaging/moj_next/test_solutions.py
git commit -m "$(cat <<'EOF'
feat(packaging): emit moj-next solutions by expected outcome

Solutions are compiled from a single file inside MOJ's jail, so they get
the same amalgamation treatment as the checker. Preserve basenames,
because Java requires the filename to match its public class.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Per-language scripts

**Files:**
- Modify: `rbx/box/packaging/moj_next/packager.py`
- Test: `tests/rbx/box/packaging/moj_next/test_language_scripts.py`

**Step 1: Write the failing tests**

```python
def test_emits_a_script_dir_per_declared_language(moj_next_package):
    scripts = moj_next_package / 'scripts'
    for language in ['c', 'cpp', 'py', 'java', 'kt']:
        assert (scripts / language / 'compile.sh').is_file()
        assert (scripts / language / 'run.sh').is_file()


def test_scripts_are_executable(moj_next_package):
    # Without +x the judge gets "Permission denied" and every test is a judge error.
    for path in (moj_next_package / 'scripts').rglob('*.sh'):
        assert path.stat().st_mode & 0o111, path


def test_flags_are_substituted(moj_next_package):
    text = (moj_next_package / 'scripts' / 'cpp' / 'compile.sh').read_text()
    assert '{{rbxFlags}}' not in text
    assert '-std=c++20' in text
```

**Step 2: Run and confirm failure.**

**Step 3: Implement**

For each id from `get_emitted_moj_languages()`, copy
`packagers/moj_next/scripts/<get_moj_template_name(id)>/` into `scripts/<id>/`,
substituting `{{rbxFlags}}` from the language extension's `flags` (falling back to the
template's own default when unset — simplest is to leave the placeholder absent from
templates that need no flags, and to skip substitution when `flags` is `None` by
substituting a sensible per-template default). `chmod(0o755)` every `.sh`.

Warn and skip when a template directory is missing, so an env declaring an exotic MOJ
id does not break packaging.

**Step 4: Run the tests, expect PASS.**

**Step 5: Commit**

```bash
git add rbx/box/packaging/moj_next/packager.py tests/rbx/box/packaging/moj_next/test_language_scripts.py
git commit -m "$(cat <<'EOF'
feat(packaging): emit moj-next per-language jail scripts

These run inside the jail, where mojtools does not exist, so they are
real copies rather than stubs -- the opposite of compare.sh.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: CLI wiring

**Files:**
- Modify: `rbx/box/packaging/main.py`
- Test: `tests/rbx/box/packaging/moj_next/test_cli.py`

**Step 1: Write the failing test**

```python
from typer.testing import CliRunner

from rbx.box.packaging.main import app


def test_moj_next_command_is_registered():
    result = CliRunner().invoke(app, ['--help'])
    assert 'moj-next' in result.output
```

**Step 2: Run and confirm failure.**

**Step 3: Implement**

Add to `rbx/box/packaging/main.py`, after the `moj` command:

```python
@app.command('moj-next', help='Build a package for MOJ (new format).')
@package.within_problem
@syncer.sync
async def moj_next(
    verification: environment.VerificationParam,
):
    from rbx.box.packaging.moj_next.packager import MojNextPackager

    await run_packager(MojNextPackager, verification=verification)
```

**Step 4: Run an end-to-end smoke**

```bash
uv run pytest tests/rbx/box/packaging/moj_next/ -v
```
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/packaging/main.py tests/rbx/box/packaging/moj_next/test_cli.py
git commit -m "$(cat <<'EOF'
feat(packaging): add the rbx package moj-next command

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Documentation

**Files:**
- Create: `rbx/box/packaging/moj_next/CLAUDE.md`
- Modify: `rbx/box/packaging/CLAUDE.md`

**Step 1: Write `moj_next/CLAUDE.md`**

Model it on `rbx/box/packaging/boca_next/CLAUDE.md`. Cover: why it is separate from
`moj`; the stub-versus-copy rule and which files fall on each side; calibration-only
time limits and the `calibrafactor` TODO; the single-file checker constraint and where
the amalgamator lives; the test naming scheme and why samples sort first; the
`tests/score` guardrails; and a pointer to both plan documents.

**Step 2: Update `rbx/box/packaging/CLAUDE.md`**

Add a `### MOJ Next (moj_next/)` section under the format implementations, add the
`rbx package moj-next` row to the CLI table, and add a sentence to the Source
Flattening section pointing at `dependencies/amalgamation.py` as the sibling tool for
targets that need one translation unit rather than a flat namespace.

**Step 3: Full verification**

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest --ignore=tests/rbx/box/cli -n auto
```

Expected: the new tests pass. Note that this repository has known pre-existing local
failures (C++/sandbox/docker tests, a stale walltime test, a completion spec drift
test) — confirm any failure you see is one of those and is untouched by this branch,
by checking it also fails on `main`.

**Step 4: Commit**

```bash
git add rbx/box/packaging/moj_next/CLAUDE.md rbx/box/packaging/CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(packaging): document the moj-next packager

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Open the pull request

```bash
git push -u origin worktree-moj-next-packager
gh pr create --draft --title 'feat(packaging): add a moj-next packager' --body '...'
```

If `gh` fails with the classic-Projects GraphQL error or an `api.github.com` timeout,
fall back to `gh api` with `--resolve` as recorded in the project's notes.

The PR body should summarize: what MOJ's format actually requires, why this is a
separate packager rather than a change to `moj`, the calibration-only decision and its
consequence, the single-file checker constraint, and the known gaps from §11 of the
design doc.
