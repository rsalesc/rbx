# Multi-language presets and `rbx lang` Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let a preset be written once for N languages, let packages be created for a subset of them, and let a language be added to (or removed from) an existing problem or contest with one command.

**Architecture:** Additive schema: a `languages:` list on `Package`/`Contest` and `language: "*"` wildcard statement entries with `{lang}` placeholders, expanded inside the existing `expanded_*` properties (wildcards first, then `extends`). A problem inside a contest inherits the contest's list, injected by the package loader. The preset needs no new schema: its template's own `languages:` list and wildcard entries define each language's *language pack* (the files the wildcards resolve to for that language). Creation prunes packs; `rbx lang add/rm/ls` manages them afterwards.

**Tech Stack:** Python 3, Pydantic v2, Typer, ruyaml (comment-preserving yml edits), questionary (prompts), pytest.

Design: `docs/plans/2026-09-20-multi-language-presets-design.md`.

Conventions: single quotes, absolute imports, run only the test files you touch (`uv run pytest <file>`), commit with `/commit` (conventional commits, co-author trailer). `ruff check --fix . && ruff format .` before each commit.

---

### Task 1: Schema — wildcard language and `languages:` lists

**Files:**
- Modify: `rbx/box/statements/schema.py` (StatementLanguage validator, new constants)
- Modify: `rbx/box/schema.py:1336-1350` (Package.languages)
- Modify: `rbx/box/contest/schema.py` (Contest.languages, ContestStatement/Document name pattern)
- Modify: `rbx/box/fields.py` (FNameField variant allowing `{lang}`)
- Test: `tests/rbx/box/statements/test_schema_languages.py` (new)

**Step 1: Write failing tests**

```python
"""Schema tests for wildcard statement languages and `languages:` lists."""

import pathlib

import pytest
from pydantic import ValidationError

from rbx.box.contest.schema import Contest, ContestStatement, Document
from rbx.box.schema import Package
from rbx.box.statements.schema import WILDCARD_LANGUAGE, Statement


def test_wildcard_language_is_accepted_on_problem_statement():
    st = Statement(language='*', file=pathlib.Path('statement/statement-{lang}.rbx.tex'))
    assert st.language == WILDCARD_LANGUAGE
    assert st.is_wildcard


def test_concrete_language_is_not_wildcard():
    assert not Statement(language='en', file=pathlib.Path('a.tex')).is_wildcard


def test_invalid_language_still_rejected():
    with pytest.raises(ValidationError):
        Statement(language='english', file=pathlib.Path('a.tex'))


def test_contest_statement_name_may_carry_lang_placeholder():
    st = ContestStatement(name='statement-{lang}', language='*', file=pathlib.Path('a.rbx.tex'))
    assert st.name == 'statement-{lang}'
    doc = Document(name='info-{lang}', language='*', file=pathlib.Path('i.tex'))
    assert doc.name == 'info-{lang}'


def test_contest_statement_name_rejects_other_placeholders():
    with pytest.raises(ValidationError):
        ContestStatement(name='statement-{foo}', file=pathlib.Path('a.rbx.tex'))


def test_package_languages_list():
    pkg = Package(name='p', timeLimit=1000, memoryLimit=256, languages=['en', 'pt'])
    assert pkg.languages == ['en', 'pt']


def test_package_languages_defaults_to_none():
    pkg = Package(name='p', timeLimit=1000, memoryLimit=256)
    assert pkg.languages is None


def test_languages_list_rejects_wildcard_and_duplicates():
    with pytest.raises(ValidationError):
        Package(name='p', timeLimit=1000, memoryLimit=256, languages=['*'])
    with pytest.raises(ValidationError):
        Contest(name='c', languages=['en', 'en'])


def test_contest_languages_list():
    assert Contest(name='c', languages=['en']).languages == ['en']


def test_dispatcher_rejects_languages():
    with pytest.raises(ValidationError):
        Contest(use_variants=True, languages=['en'])
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/statements/test_schema_languages.py -v`
Expected: ImportError on `WILDCARD_LANGUAGE`.

**Step 3: Implement**

In `rbx/box/statements/schema.py`, next to `validate_statement_language`:

```python
# A statement whose `language` is the wildcard expands, at load time, into one
# concrete statement per language of the package's effective `languages:` list
# (design 2026-09-20 §1). `{lang}` in its path-like fields is substituted.
WILDCARD_LANGUAGE = '*'
LANG_PLACEHOLDER = '{lang}'


def validate_statement_language(lang: str):
    if lang == WILDCARD_LANGUAGE:
        return lang
    if not re.match(r'^[a-z]{2}$', lang):
        raise ValueError(...)  # keep existing message
    return lang


def validate_concrete_language(lang: str):
    """A language of a `languages:` list: ISO code, never the wildcard."""
    if lang == WILDCARD_LANGUAGE:
        raise ValueError('The `languages` list cannot contain the wildcard "*".')
    return validate_statement_language(lang)


ConcreteLanguage = Annotated[str, AfterValidator(validate_concrete_language)]


def validate_languages_list(langs: Optional[List[str]]) -> Optional[List[str]]:
    if langs is not None and len(set(langs)) != len(langs):
        raise ValueError('The `languages` list must not repeat a language.')
    return langs


LanguagesList = Annotated[
    Optional[List[ConcreteLanguage]], AfterValidator(validate_languages_list)
]
```

Add to `BaseStatement`:

```python
    @property
    def is_wildcard(self) -> bool:
        return self.language == WILDCARD_LANGUAGE
```

In `rbx/box/fields.py` add:

```python
def StatementNameField(**kwargs):
    """Like FNameField, but also admits the literal `{lang}` placeholder that a
    wildcard statement's name carries (it is substituted at expansion time)."""
    return Field(
        pattern=r'^[a-zA-Z0-9{][a-zA-Z0-9\-_{}]*$', min_length=3, max_length=128, **kwargs
    )
```

and an after-validator on `ContestStatement.name`/`Document.name` (a shared `validate_statement_name(name)` in `contest/schema.py`) that rejects any `{`/`}` not forming exactly `{lang}` (i.e. `name.replace('{lang}', 'x')` must match FNameField's original pattern). Use `Annotated[str, AfterValidator(validate_statement_name)]` with `StatementNameField(...)`.

Add to `Package` (after `titles`) and `Contest` (after `titles`):

```python
    languages: LanguagesList = Field(
        default=None,
        description='Languages this package ships statements in. Wildcard '
        'statements (`language: "*"`) expand to one entry per language here. '
        'A problem inside a contest inherits the contest list when unset.',
    )
```

Add `'languages'` to the dispatcher-forbidden tuple in `Contest._validate_dispatcher_or_real`.

**Step 4: Run tests** — expect PASS. Also run `uv run pytest tests/rbx/box/test_schema.py tests/rbx/box/contest/test_contest_schema.py tests/rbx/box/statements/test_schema_v2.py`.

**Step 5: Commit** — `feat(statements): accept wildcard language and languages lists in schemas`

---

### Task 2: Wildcard expander

**Files:**
- Create: `rbx/box/statements/wildcards.py`
- Test: `tests/rbx/box/statements/test_wildcards.py` (new)

**Step 1: Write failing tests**

```python
import pathlib

import pytest

from rbx.box.contest.schema import ContestStatement, Document
from rbx.box.statements.schema import Statement
from rbx.box.statements.wildcards import (
    WildcardExpansionError,
    expand_contest_wildcards,
    expand_problem_wildcards,
    substitute_lang,
)


def test_substitute_lang_in_strings_paths_and_nested_params():
    assert substitute_lang('a-{lang}.tex', 'pt') == 'a-pt.tex'
    assert substitute_lang(pathlib.Path('x/{lang}/s.tex'), 'pt') == pathlib.Path('x/pt/s.tex')
    assert substitute_lang({'a': ['{lang}', 1], 'b': {'c': '{lang}'}}, 'en') == {
        'a': ['en', 1], 'b': {'c': 'en'}
    }


def test_problem_wildcard_expands_per_language_in_list_order():
    sts = [Statement(language='*', file=pathlib.Path('st-{lang}.rbx.tex'), params={'k': '{lang}'})]
    out = expand_problem_wildcards(sts, ['en', 'pt'])
    assert [(s.language, str(s.file), s.params['k']) for s in out] == [
        ('en', 'st-en.rbx.tex', 'en'),
        ('pt', 'st-pt.rbx.tex', 'pt'),
    ]
    assert not any(s.is_wildcard for s in out)


def test_concrete_entry_beats_wildcard_for_same_key():
    sts = [
        Statement(language='*', file=pathlib.Path('st-{lang}.rbx.tex')),
        Statement(language='pt', file=pathlib.Path('special.rbx.tex')),
    ]
    out = expand_problem_wildcards(sts, ['en', 'pt'])
    assert [(s.language, str(s.file)) for s in out] == [
        ('en', 'st-en.rbx.tex'),
        ('pt', 'special.rbx.tex'),
    ]


def test_wildcard_variant_is_preserved_and_keys_stay_unique():
    sts = [
        Statement(language='*', file=pathlib.Path('a-{lang}.tex')),
        Statement(language='*', variant='short', file=pathlib.Path('b-{lang}.tex')),
    ]
    out = expand_problem_wildcards(sts, ['en'])
    assert [(s.language, s.variant) for s in out] == [('en', 'default'), ('en', 'short')]


def test_no_wildcards_is_identity():
    sts = [Statement(language='en', file=pathlib.Path('a.tex'))]
    assert expand_problem_wildcards(sts, None) == sts
    assert expand_problem_wildcards(sts, []) == sts


def test_wildcard_without_languages_errors():
    sts = [Statement(language='*', file=pathlib.Path('a-{lang}.tex'))]
    with pytest.raises(WildcardExpansionError):
        expand_problem_wildcards(sts, None)


def test_contest_wildcard_substitutes_name_templates_and_assets():
    sts = [
        ContestStatement(
            name='statement-{lang}',
            language='*',
            file=pathlib.Path('sheet.rbx.tex'),
            standaloneProblemTemplate=pathlib.Path('p-{lang}.rbx.tex'),
            contestProblemTemplate=pathlib.Path('f.rbx.tex'),
            assets=['img/{lang}/*'],
        )
    ]
    out = expand_contest_wildcards(sts, ['en', 'pt'])
    assert [s.name for s in out] == ['statement-en', 'statement-pt']
    assert str(out[1].standaloneProblemTemplate) == 'p-pt.rbx.tex'
    assert out[1].assets == ['img/pt/*']


def test_contest_concrete_beats_wildcard_by_name():
    sts = [
        ContestStatement(name='statement-{lang}', language='*', file=pathlib.Path('a.rbx.tex')),
        ContestStatement(name='statement-pt', language='pt', file=pathlib.Path('b.rbx.tex')),
    ]
    out = expand_contest_wildcards(sts, ['en', 'pt'])
    assert [(s.name, str(s.file)) for s in out] == [
        ('statement-en', 'a.rbx.tex'),
        ('statement-pt', 'b.rbx.tex'),
    ]


def test_documents_expand_too():
    out = expand_contest_wildcards(
        [Document(name='info-{lang}', language='*', file=pathlib.Path('i.tex'))], ['en']
    )
    assert out[0].name == 'info-en' and out[0].language == 'en'
```

**Step 2: Run** — expect ImportError.

**Step 3: Implement `rbx/box/statements/wildcards.py`**

```python
"""Wildcard statement expansion (design 2026-09-20 §1).

A statement with ``language: "*"`` stands for one statement per language of the
package's effective ``languages:`` list. Expansion substitutes ``{lang}`` in
``name``, ``file``, the two contest templates, ``assets`` and ``params``
values, and yields the concrete entries in list order, one per language. A
concrete entry with the same key (``(language, variant)`` for problems,
``name`` for contests) wins over the expansion, so one language can still be
special-cased. Runs before ``extends`` expansion, so an expanded entry can be
extended by language.
"""

import pathlib
from typing import Any, Callable, Hashable, List, Optional, TypeVar

from rbx.box.exception import RbxException
from rbx.box.statements.schema import LANG_PLACEHOLDER, BaseStatement

T = TypeVar('T', bound=BaseStatement)

_SUBSTITUTED_FIELDS = (
    'name', 'file', 'standaloneProblemTemplate', 'contestProblemTemplate',
    'assets', 'params',
)


class WildcardExpansionError(RbxException):
    pass


def substitute_lang(value: Any, lang: str) -> Any:
    if isinstance(value, str):
        return value.replace(LANG_PLACEHOLDER, lang)
    if isinstance(value, pathlib.Path):
        return pathlib.Path(str(value).replace(LANG_PLACEHOLDER, lang))
    if isinstance(value, list):
        return [substitute_lang(v, lang) for v in value]
    if isinstance(value, dict):
        return {k: substitute_lang(v, lang) for k, v in value.items()}
    return value


def _instantiate(st: T, lang: str) -> T:
    update = {'language': lang}
    for field in _SUBSTITUTED_FIELDS:
        if field in type(st).model_fields and getattr(st, field) is not None:
            update[field] = substitute_lang(getattr(st, field), lang)
    # Re-validate: name patterns and type-dependent rules must hold post-substitution.
    return type(st).model_validate(st.model_copy(update=update).model_dump())


def _expand(statements: List[T], languages: Optional[List[str]], get_key: Callable[[T], Hashable]) -> List[T]:
    if not any(st.is_wildcard for st in statements):
        return statements
    if not languages:
        with WildcardExpansionError() as err:
            err.print(
                '[error]A statement uses [item]language: "*"[/item] but no '
                '[item]languages[/item] list is in effect. Add [item]languages: [en, ...][/item] '
                'to the package (or to its contest).[/error]'
            )
    concrete_keys = {get_key(st) for st in statements if not st.is_wildcard}
    out: List[T] = []
    for st in statements:
        if not st.is_wildcard:
            out.append(st)
            continue
        for lang in languages:
            inst = _instantiate(st, lang)
            if get_key(inst) in concrete_keys:
                continue
            out.append(inst)
    return out


def expand_problem_wildcards(statements, languages):
    return _expand(statements, languages, get_key=lambda st: (st.language, st.variant))


def expand_contest_wildcards(statements, languages):
    return _expand(statements, languages, get_key=lambda st: st.name)
```

(Use `with WildcardExpansionError() as err: err.print(...)` exactly as `expander.py` does — check `RbxException` usage there.)

**Step 4: Run** — PASS. **Step 5: Commit** — `feat(statements): expand wildcard statements per language`

---

### Task 3: Wire expansion into `expanded_*` and effective languages

**Files:**
- Modify: `rbx/box/schema.py` (Package: `_inherited_languages` PrivateAttr, `effective_languages`, `expanded_*`)
- Modify: `rbx/box/contest/schema.py` (Contest: `effective_languages`, `expanded_*`)
- Test: `tests/rbx/box/statements/test_wildcards.py` (append)

**Step 1: Tests**

```python
from rbx.box.contest.schema import Contest
from rbx.box.schema import Package


def _pkg(**kw):
    return Package(name='p', timeLimit=1000, memoryLimit=256, **kw)


def test_package_effective_languages_prefers_own_list():
    assert _pkg(languages=['pt']).effective_languages == ['pt']


def test_package_effective_languages_inherits_from_contest():
    pkg = _pkg(statements=[Statement(language='*', file=pathlib.Path('s-{lang}.tex'))])
    pkg.set_inherited_languages(['en', 'pt'])
    assert pkg.effective_languages == ['en', 'pt']
    assert [s.language for s in pkg.expanded_statements] == ['en', 'pt']


def test_package_effective_languages_derived_from_concrete_entries():
    pkg = _pkg(
        statements=[Statement(language='pt', file=pathlib.Path('a.tex'))],
        tutorials=[Statement(language='en', file=pathlib.Path('b.tex'))],
    )
    assert pkg.effective_languages == ['pt', 'en']


def test_package_wildcard_then_extends():
    pkg = _pkg(
        languages=['en', 'pt'],
        statements=[
            Statement(language='*', file=pathlib.Path('s-{lang}.tex'), params={'x': 1}),
            Statement(language='pt', extends='en'),  # concrete wins, inherits en recipe
        ],
    )
    out = pkg.expanded_statements
    assert [(s.language, str(s.file)) for s in out] == [('en', 's-en.tex'), ('pt', 's-en.tex')]


def test_contest_expanded_uses_own_list():
    c = Contest(
        name='c',
        languages=['en', 'pt'],
        statements=[ContestStatement(name='st-{lang}', language='*', file=pathlib.Path('a.rbx.tex'))],
        documents=[Document(name='info-{lang}', language='*', file=pathlib.Path('i.tex'))],
    )
    assert [s.name for s in c.expanded_statements] == ['st-en', 'st-pt']
    assert [d.name for d in c.expanded_documents] == ['info-en', 'info-pt']


def test_contest_effective_languages_derived_when_unset():
    c = Contest(name='c', statements=[ContestStatement(name='a', language='pt', file=pathlib.Path('a.rbx.tex'))])
    assert c.effective_languages == ['pt']
```

**Step 2: Run** — fails on `effective_languages`.

**Step 3: Implement**

`Package`:

```python
    # Languages inherited from the enclosing contest, injected by the package
    # loader (a model cannot see its contest). Not part of the yml.
    _inherited_languages: Optional[List[str]] = PrivateAttr(default=None)

    def set_inherited_languages(self, languages: Optional[List[str]]) -> None:
        self._inherited_languages = languages

    @property
    def effective_languages(self) -> List[str]:
        """Own `languages:`, else the contest's, else the distinct languages of
        the concrete statement/tutorial entries in order of appearance."""
        if self.languages is not None:
            return list(self.languages)
        if self._inherited_languages is not None:
            return list(self._inherited_languages)
        return _concrete_languages(self.statements + self.tutorials)

    @property
    def expanded_statements(self) -> List[Statement]:
        return expand_problem_statements(
            expand_problem_wildcards(self.statements, self.effective_languages)
        )
```

Put `_concrete_languages(statements)` in `wildcards.py` (dedupe, skip wildcards, preserve order) and use it on both models. `Contest.effective_languages` = own list else derived from statements+tutorials+documents. Contest `expanded_*` wrap `expand_contest_wildcards(...)` inside `expand_contest_statements(...)`.

**Step 4: Run**; also `uv run pytest tests/rbx/box/statements/test_expander.py tests/rbx/box/statements/test_resolver.py tests/rbx/box/contest/test_contest_schema.py`. **Step 5: Commit** — `feat(statements): expand wildcards in expanded_* using effective languages`

---

### Task 4: Loader injects the contest's languages into problems

**Files:**
- Modify: `rbx/box/contest/contest_package.py` (new `find_contest_languages(root)`)
- Modify: `rbx/box/package.py:69-74` (`find_problem_package`)
- Test: `tests/rbx/box/contest/test_contest_languages.py` (new)

**Step 1: Test** (build a contest on disk in `cleandir`; see `tests/rbx/box/contest/test_contest_loading.py` for how those tests write `contest.rbx.yml` + problem dirs and clear caches — reuse its helpers/fixtures):

```python
def test_problem_inside_contest_inherits_languages(cleandir):
    write contest.rbx.yml: name c, languages [en, pt], problems: [{short_name: A, path: A}]
    write A/problem.rbx.yml: name a, statements: [{language: '*', file: 'st-{lang}.rbx.tex'}]
    clear caches (package.clear_package_cache(), contest_utils.clear_all_caches())
    pkg = package.find_problem_package(pathlib.Path('A'))
    assert pkg.effective_languages == ['en', 'pt']
    assert [s.language for s in pkg.expanded_statements] == ['en', 'pt']


def test_problem_own_list_wins_over_contest(cleandir): ... languages: [pt] in problem → ['pt']


def test_standalone_problem_with_wildcard_and_no_list_errors_on_expansion(cleandir): pytest.raises(WildcardExpansionError)
```

**Step 2: Run** — fails.

**Step 3: Implement**

`contest_package.py`:

```python
@functools.cache
def find_contest_languages(root: pathlib.Path = pathlib.Path()) -> Optional[List[str]]:
    """The selected contest's `languages:` for the package at `root`, or None
    outside a contest / when unset. Loads the contest yml *without* the problem
    folder validation that `find_contest_package` performs, because that
    validation loads every problem and would recurse back into here."""
    contest_yaml_path = find_contest_yaml(root)
    if contest_yaml_path is None:
        return None
    return load_yaml_model(contest_yaml_path, Contest).languages
```

`package.py`:

```python
@functools.cache
def find_problem_package(root=pathlib.Path()) -> Optional[Package]:
    problem_yaml_path = find_problem_yaml(root)
    if not problem_yaml_path:
        return None
    pkg = load_yaml_model(problem_yaml_path, Package)
    # Lazy import: contest_package imports this module.
    from rbx.box.contest.contest_package import find_contest_languages
    pkg.set_inherited_languages(find_contest_languages(problem_yaml_path.parent))
    return pkg
```

Add `find_contest_languages.cache_clear()` wherever `find_contest_yaml.cache_clear()` is called (grep `contest_utils.clear_all_caches` and `package.clear_package_cache`).

Also make `packaging/polygon/importer.py` unaffected (it assigns `pkg.statements`; fine).

**Step 4: Run** this file + `tests/rbx/box/test_package_loading.py` + `tests/rbx/box/contest/test_contest_loading.py`. **Step 5: Commit** — `feat(package): inherit contest languages into problem packages`

---

### Task 5: Language packs — resolve a template's per-language files

**Files:**
- Create: `rbx/box/language_packs.py`
- Test: `tests/rbx/box/test_language_packs.py` (new)
- Test fixture: `tests/rbx/box/testdata/presets/multilang/` (new preset: `preset.rbx.yml` with `problem: problem`, `contest: contest`; problem template with `languages: [en, pt, es]`, wildcard statements/tutorials pointing at `statement/statement-{lang}.rbx.tex` / `statement/editorial-{lang}.rbx.tex`, `titles` for all three, and those six files present; contest template with `languages: [en, pt, es]`, wildcard statements (shared `statements/problem-sheet.rbx.tex`, templates) and `documents` `info-{lang}` on a shared file, `titles` for all three). Keep the tex files tiny.

**Step 1: Tests**

```python
from rbx.box import language_packs as lp

PRESET = pathlib.Path(__file__).parent / 'testdata' / 'presets' / 'multilang'


def test_template_languages():
    assert lp.template_languages(PRESET / 'problem', is_contest=False) == ['en', 'pt', 'es']
    assert lp.template_languages(PRESET / 'contest', is_contest=True) == ['en', 'pt', 'es']


def test_problem_pack_files_are_the_wildcard_expansions():
    assert lp.pack_files(PRESET / 'problem', 'pt', is_contest=False) == [
        pathlib.Path('statement/statement-pt.rbx.tex'),
        pathlib.Path('statement/editorial-pt.rbx.tex'),
    ]


def test_contest_pack_has_no_files_when_chrome_is_shared():
    assert lp.pack_files(PRESET / 'contest', 'pt', is_contest=True) == []


def test_pack_files_ignores_paths_shared_across_languages():
    # A wildcard whose `file` has no {lang} is language-neutral → not in any pack.
    ...(covered by the contest case above)


def test_prune_languages_rewrites_list_deletes_files_and_titles(cleandir):
    shutil.copytree(PRESET / 'problem', 'p')
    lp.prune_languages(pathlib.Path('p'), ['en'], is_contest=False)
    data = ruyaml.YAML().load(pathlib.Path('p/problem.rbx.yml').read_text())
    assert data['languages'] == ['en']
    assert data['titles'] == {'en': ...}
    assert not pathlib.Path('p/statement/statement-pt.rbx.tex').exists()
    assert pathlib.Path('p/statement/statement-en.rbx.tex').exists()


def test_prune_languages_keeps_comments(cleandir): assert a `# comment` line in the template yml survives.


def test_prune_languages_drop_field_when_inheriting(cleandir):
    lp.prune_languages(pathlib.Path('p'), ['en'], is_contest=False, inherit=True)
    → no `languages` key in yml, files pruned to en.


def test_add_language_copies_pack_and_title_idempotently(cleandir):
    copytree → prune to ['en'] → lp.add_language(pathlib.Path('p'), PRESET / 'problem', 'pt', is_contest=False)
    assert list == ['en', 'pt'], files exist, titles has 'pt' (placeholder from template)
    modify statement-pt, run again → unchanged, list unchanged.


def test_add_language_from_existing_language_clones_files(cleandir):
    add 'fr' with from_lang='en' → statement-fr == statement-en content; titles['fr'] == titles['en'].


def test_add_language_unshipped_without_from_errors(cleandir): pytest.raises(typer.Exit) for 'fr'.


def test_remove_language(cleandir):
    lp.remove_language(path, 'pt', delete_files=False) → list without pt, files kept, returns orphaned list
    with delete_files=True → files deleted.
```

**Step 2: Run** — fails.

**Step 3: Implement `rbx/box/language_packs.py`**

Key pieces:

- `_load(template_or_pkg_root, is_contest)` → `Package` or `Contest` via `load_yaml_model` (lazy import of `Contest`).
- `template_languages(path, is_contest) -> List[str]`: the model's `languages` or `[]`.
- `pack_files(path, lang, is_contest) -> List[pathlib.Path]`: for each wildcard entry in `statements`/`tutorials`(/`documents`), take the path-like fields (`file`, `standaloneProblemTemplate`, `contestProblemTemplate`) whose string contains `{lang}`, substitute, dedupe preserving order. `assets` globs with `{lang}` are also substituted and globbed relative to `path` (add to pack if they exist).
- `_yaml_for_edit(root, is_contest)` → `yaml_include.open_for_edit(...)`? Simpler: `package.get_ruyaml(root)`-style helpers exist (`package.get_ruyaml` for problems; check `contest_package` for the contest equivalent, else `utils`/`ruyaml` round-trip loader used in `creation.py`). Use `utils.save_ruyaml`. Do not support `!include`d `languages`/`titles` (call `yaml_include.die_if_write_would_inline_includes` first, as `install_preset_from_dir` does).
- `prune_languages(root, keep, *, is_contest, inherit=False)`: compute `template_langs = languages in yml`; for each `lang not in keep` delete every `pack_files(root, lang)` (the package is a fresh copy of the template so its own wildcards define the packs); delete `titles[lang]`; set `languages = keep` or delete the key when `inherit`. Warn (do not fail) when `keep` contains a language the template does not ship.
- `add_language(root, template_path, lang, *, is_contest, from_lang=None) -> List[pathlib.Path]` (files created): validate `lang` with `validate_concrete_language`; if `from_lang` is None and `lang not in template_languages(template_path)` → print error listing shipped languages and `--from` hint, `raise typer.Exit(1)`; for each `pack_files(root, lang)` (using the package's own wildcards) copy the same relative file from the template (skeleton) or from `pack_files(root, from_lang)` pairwise (clone) unless it already exists; add `titles[lang]` = template's title for `lang` (or `titles[from_lang]`, or the package name) if missing; append `lang` to `languages` if a list exists and lacks it (if the package has no `languages:` key and `inherit` is not the case — i.e. standalone — create the list from `effective_languages + [lang]`). Return created files.
- `remove_language(root, lang, *, is_contest, delete_files=False) -> List[pathlib.Path]` (orphaned/deleted files).
- `list_languages(root, is_contest) -> List[Tuple[str, List[Tuple[pathlib.Path, bool]]]]` for `rbx lang ls`: effective languages with each pack file and whether it exists.

**Step 4: Run** PASS. **Step 5: Commit** — `feat(presets): resolve and manage per-language packs of a template`

---

### Task 6: `--languages` on `rbx create` / `rbx contest create`, inheritance on `rbx contest add`

**Files:**
- Modify: `rbx/box/presets/__init__.py` (`install_problem`/`install_contest` gain `languages: Optional[List[str]]`, new `pick_languages(template, is_contest, languages)`)
- Modify: `rbx/box/creation.py` (`languages` param; `inherit_languages` param for contest add)
- Modify: `rbx/box/cli/commands/create.py`, `rbx/box/contest/main.py` (`--languages/-l` on create; `add` passes the contest's list)
- Test: `tests/rbx/box/presets/test_presets_create.py`, `tests/rbx/box/test_creation.py`, `tests/rbx/box/contest/test_contest_main.py`

**Step 1: Tests**

- `pick_languages`: explicit flag wins (validated against template languages → error if unknown); template with ≤1 language never prompts; multi-language template + TTY → `questionary.checkbox` (mock `sys.stdin.isatty` and `questionary.checkbox`) default all; non-TTY → all languages, no prompt.
- `install_problem(dest, fetch_info, languages=['en'])` against the `multilang` testdata preset (see how `test_presets_create.py`/`test_preset_variants.py` install from a local dir) → pruned as in Task 5.
- `creation.create('x', languages=['en'])` passes through to `install_problem` (stub asserts kwarg).
- `rbx contest add` inside a contest with `languages: [en, pt]` → created problem has no `languages:` key and only en/pt files (drive `contest.main.add` like `test_contest_main.py` does).
- `--languages en,pt` parsing: Typer option `List[str]` with comma-splitting callback (`_split_csv`), reused by both commands (put it in `rbx/box/cli/options.py` or next to existing shared option helpers if any — grep for `callback=` in cli/).

**Step 3: Implement**

```python
def pick_languages(template: ResolvedTemplate, *, is_contest: bool, languages: Optional[List[str]]) -> Optional[List[str]]:
    """Which of the template's languages to keep. None = keep all (no pruning)."""
    shipped = language_packs.template_languages(template.path, is_contest=is_contest)
    if languages is not None:
        unknown = [l for l in languages if l not in shipped]
        if unknown: error listing shipped; raise typer.Exit(1)
        return languages
    if len(shipped) <= 1 or not sys.stdin.isatty():
        return None
    answer = questionary.checkbox('Which languages do you want to keep?', choices=[Choice(l, checked=True) ...]).ask()
    if not answer: raise typer.Exit(1)
    return answer
```

In `install_problem`/`install_contest`, after `_pin_schema_header` and before `materialize_libraries`: `keep = pick_languages(...)`; `if keep is not None: language_packs.prune_languages(dest_pkg, keep, is_contest=..., inherit=inherit_languages)`. Pass `inherit_languages=True` from `creation.create` when `find_contest_yaml()` is not None, and `languages=find_contest_languages(...)` (contest add never prompts).

**Step 5: Commit** — `feat(create): choose which preset languages to keep with --languages`

---

### Task 7: `rbx lang` command group

**Files:**
- Create: `rbx/box/languages_cli.py` (Typer app `app`: `ls`, `add`, `rm`)
- Modify: `rbx/box/cli/__init__.py` (ENTRIES row: `'lang, languages'`, `'rbx.box.languages_cli:app'`, help `'Manage statement languages (sub-command).'`, `rich_help_panel='Management'`, `is_group=True`)
- Modify: `rbx/box/completion/_spec.py` via `uv run python -m rbx.box.completion.serialize && uv run ruff format rbx/box/completion/_spec.py`
- Test: `tests/rbx/box/test_languages_cli.py` (new), `tests/rbx/box/lazy_cli_test.py` (should pass unchanged; it pins ENTRIES to the module)

Behaviour (drive with `typer.testing.CliRunner` on the lazily-materialised root app, as `test_contest_main.py` / `test_run_cli.py` do):

- Resolve context: `find_contest_yaml()` → contest mode; else `find_problem_yaml()` → problem mode; else error. In problem mode, if `find_contest_yaml()` also resolves (problem inside a contest) → `add`/`rm` refuse: "run at the contest root".
- `ls`: print a table per package (Rich): language, each pack file, ✓/✗.
- `add <lang> [--from <lang>]`: template = `presets.get_active_template(root, is_contest=...)` (contest mode: contest template for the contest root, problem template for each problem via each problem's own lock — `get_active_template(problem_root, is_contest=False, variant=<locked variant>)`, see `_read_locked_variant`). Call `language_packs.add_language` on the contest then each problem; print created files. Clear caches after.
- `rm <lang> [--delete-files]`: `language_packs.remove_language` on contest + problems; print orphaned/deleted files.

Tests: create a contest from the `multilang` preset pruned to `[en]` with two problems (reuse Task 6 machinery), then `lang add pt` → contest list `[en, pt]`, each problem has `statement-pt.rbx.tex`, no `languages:` key in problems; run twice → idempotent; `lang add fr` → exit 1 mentioning `en, pt, es`; `lang add fr --from en` → clones; `lang rm pt` keeps files and lists them; `--delete-files` deletes; `lang ls` output contains `pt` rows; running `add` inside a problem of a contest exits 1.

**Commit** — `feat(cli): add rbx lang to list, add and remove statement languages`

---

### Task 8: Move the bundled default preset to wildcards

**Files:**
- Modify: `rbx/resources/presets/default/problem/problem.rbx.yml`, `problem-interactive/problem.rbx.yml`: add `languages: ["en"]` after `titles`; replace the `statements`/`tutorials` entries with wildcard ones (`file: "statement/statement-{lang}.rbx.tex"`, keep the `# Open this file...` comments and `params`); rename `statement/statement.rbx.tex` → `statement-en.rbx.tex`, `editorial.rbx.tex` → `editorial-en.rbx.tex` (both variants).
- Modify: `rbx/resources/presets/default/contest/contest.rbx.yml`: `languages: ["en"]`; statements/tutorials/documents become `name: "statement-{lang}"` etc. with `language: "*"` and the shared files.
- Grep tests and docs for `statement/statement.rbx.tex`, `statement-en`, `editorial-en` and update paths (`tests/rbx/box/presets/test_default_preset_variants.py`, e2e fixtures under `tests/e2e/testdata` that were created from the preset — only if they reference the preset's paths; do not touch fixtures that are their own packages). Grep `docs/` for the old paths and update.
- Test: `uv run pytest tests/rbx/box/presets tests/rbx/box/statements/test_standalone_build.py tests/rbx/box/contest/test_contest_build_v2.py`; also create a problem and a contest from the local preset with `uv run rbx create tmp-p --local` in `$CLAUDE_JOB_DIR/tmp` and `uv run rbx st b` inside it (pdflatex may be missing: assert the join/resolution gets as far as compilation).

**Commit** — `feat(presets): declare the default preset's statements with wildcard languages`

---

### Task 9: Docs

**Files:**
- Modify: `docs/setters/statements/index.md` or `writing.md` (introduce `languages:` and `language: "*"` where multi-language statements are first explained; follow `docs/plans/docs-writing-style-guide.md`: introduce before use)
- Modify: `docs/setters/statements/contest.md` (contest-side wildcard example next to the existing `extends` section)
- Modify: `docs/setters/presets/index.md` (how a preset ships several languages; `--languages`; `rbx lang`)
- Modify: `docs/setters/cheatsheet.md` (add `rbx lang add pt`)
- Modify: `rbx/box/statements/CLAUDE.md` (one paragraph: wildcard expansion runs before `extends`, effective languages, loader injection)
- Do NOT touch `docs/setters/reference/cli.md` or `docs/schemas/` (generated).

Verify with `uv run mkdocs build` (non-strict; ~9 pre-existing strict warnings are unrelated).

**Commit** — `docs(statements): document wildcard languages, --languages and rbx lang`

---

### Task 10: e2e scenario

**Files:**
- Create: `tests/e2e/testdata/multilang-contest/` — a contest package created from the `multilang` testdata preset with `--languages en` and two problems (commit the resulting tree minus build artefacts; keep tex tiny), plus `e2e.rbx.yml` with a scenario: `contest statements build` → assert `build/statements/statement-en.pdf` exists and no `-pt`; `lang add pt`; `contest statements build` → assert `statement-pt.pdf` exists. Use the stubbed `pdflatex` (default e2e mode). See `tests/e2e/README.md` for the schema and an existing contest fixture for the layout.

Run: `uv run pytest tests/e2e/testdata/multilang-contest/ -v`

**Commit** — `test(e2e): cover adding a language to a contest with rbx lang`

---

### Task 11: Finish

- `uv run ruff check . && uv run ruff format --check .`
- Run every test file touched above once more, plus `tests/rbx/box/lazy_cli_test.py`, `tests/rbx/box/completion/drift_test.py`, `tests/rbx/box/dump_cli_docs_test.py`.
- Push the branch, open a draft PR (`gh` may need the `curl --resolve` workaround from memory if `api.github.com` is unreachable).
