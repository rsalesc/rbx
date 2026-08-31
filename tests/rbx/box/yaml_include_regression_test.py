"""Regressions found by adversarial review of the `!include` implementation.

Each test here pins a defect that shipped in the first cut. Keep them: several
are failure modes that produce a raw traceback or silent data loss rather than
an error a user can act on.
"""

from typing import ClassVar

import pydantic
import pytest

from rbx.box.yaml_include import (
    EditSession,
    IncludeError,
    resolve_yaml_file,
    source_of,
)
from rbx.box.yaml_validation import (
    YamlSyntaxError,
    YamlValidationError,
    load_yaml_model,
)


class _Inner(pydantic.BaseModel):
    n: int


class _Model(pydantic.BaseModel):
    # Stands in for a real user-authored config, so it opts in the same way.
    rbx_include_capable: ClassVar[bool] = True

    vars: _Inner


# --------------------------- include-capable configs --------------------------


def test_exactly_the_four_shared_config_kinds_are_include_capable():
    """The boundary is deliberate; widening it needs a matching write path."""
    from rbx.box.contest.schema import Contest
    from rbx.box.environment import Environment
    from rbx.box.presets.schema import Preset
    from rbx.box.schema import LimitsProfile, Package
    from rbx.box.yaml_validation import is_include_capable

    for model in (Package, Contest, Environment, Preset):
        assert is_include_capable(model), model.__name__

    # Rebuilt from their model on save, so an include would not survive.
    from rbx.box.presets.lock_schema import PresetLock

    for model in (LimitsProfile, PresetLock):
        assert not is_include_capable(model), model.__name__


def test_an_include_in_a_non_capable_config_is_refused_with_guidance(tmp_path):
    from rbx.box.schema import LimitsProfile
    from rbx.box.yaml_validation import IncludeNotSupportedError

    path = tmp_path / 'local.rbx.yml'
    path.write_text('timeLimit: 1000\nmodifiers: !include mods.yml\n')

    with pytest.raises(IncludeNotSupportedError) as exc:
        load_yaml_model(path, LimitsProfile)

    message = str(exc.value)
    assert 'LimitsProfile' in message
    assert 'problem.rbx.yml' in message


def test_a_non_capable_config_without_includes_still_loads(tmp_path):
    from rbx.box.schema import LimitsProfile

    path = tmp_path / 'local.rbx.yml'
    path.write_text('timeLimit: 1234\n')

    assert load_yaml_model(path, LimitsProfile).timeLimit == 1234


# ----------------------------- resolution defects -----------------------------


def test_validation_error_under_a_merge_include_renders_a_diagnostic(tmp_path):
    """Merged keys carry no `lc`, which crashed `_locate` with a KeyError."""
    (tmp_path / 'f.yml').write_text('n: not_an_int\n')
    root = tmp_path / 'root.yml'
    root.write_text('vars:\n  <<: !include f.yml\n')

    with pytest.raises(YamlValidationError) as exc:
        load_yaml_model(root, _Model)

    rendered = str(exc.value)
    assert 'f.yml' in rendered
    assert 'not_an_int' in rendered


def test_syntax_error_inside_a_fragment_names_the_fragment(tmp_path):
    (tmp_path / 'f.yml').write_text('# pad\n# pad\na: 1\n  b: 2\n')
    root = tmp_path / 'root.yml'
    root.write_text('vars: !include f.yml\n')

    with pytest.raises(YamlSyntaxError) as exc:
        load_yaml_model(root, _Model)

    rendered = str(exc.value)
    assert 'f.yml' in rendered
    assert 'root.yml' not in rendered


def test_chained_include_stamps_the_file_that_actually_owns_the_value(tmp_path):
    (tmp_path / 'g.yml').write_text('n: 1\n')
    (tmp_path / 'f.yml').write_text('!include g.yml\n')
    root = tmp_path / 'root.yml'
    root.write_text('vars: !include f.yml\n')

    tree, _ = resolve_yaml_file(root)

    assert source_of(tree['vars']) == (tmp_path / 'g.yml').resolve()


def test_a_quoted_merge_key_is_not_deleted(tmp_path):
    """`"<<"` is an ordinary string key; only a real merge key may be consumed."""
    root = tmp_path / 'root.yml'
    root.write_text('vars:\n  "<<": hello\n  keep: 1\n')

    tree, _ = resolve_yaml_file(root)

    assert dict(tree['vars']) == {'<<': 'hello', 'keep': 1}


def test_a_non_scalar_include_payload_is_refused_cleanly(tmp_path):
    root = tmp_path / 'root.yml'
    root.write_text('a: !include [x.yml, y.yml]\n')

    with pytest.raises(IncludeError) as exc:
        resolve_yaml_file(root)

    assert 'path' in str(exc.value).lower()


# ------------------------------- editing defects ------------------------------


def test_a_read_only_session_does_not_rewrite_the_file(tmp_path):
    """Reading a value marked the file dirty, reformatting it on save."""
    main = tmp_path / 'contest.rbx.yml'
    original = "---\nname: 'c'\nproblems:\n  - short_name: 'A'\n"
    main.write_text(original)

    session = EditSession(main)
    _ = session.target('problems').value  # read only
    session.save()

    assert main.read_text() == original


def test_a_session_that_changes_nothing_reports_no_touched_files(tmp_path):
    main = tmp_path / 'contest.rbx.yml'
    main.write_text('problems:\n- short_name: A\n')

    session = EditSession(main)
    _ = session.target('problems').value

    assert session.touched_files() == set()


def test_value_of_a_sequence_index_returns_the_element(tmp_path):
    main = tmp_path / 'contest.rbx.yml'
    main.write_text('problems:\n- short_name: A\n- short_name: B\n')

    target = EditSession(main).target('problems', 0)

    assert target.value is not None
    assert dict(target.value) == {'short_name': 'A'}


def test_editing_through_a_target_held_across_a_rebind_still_lands(tmp_path):
    """The target re-resolves, so it writes into the live tree, not an orphan."""
    main = tmp_path / 'p.yml'
    main.write_text('a:\n  b: 1\n')

    session = EditSession(main)
    inner = session.target('a', 'b')
    session.target('a').replace({'b': 1, 'c': 3})
    inner.replace(99)
    session.save()

    text = main.read_text()
    assert 'b: 99' in text
    assert 'c: 3' in text


def test_target_creates_missing_intermediate_keys(tmp_path):
    """`rbx time --integrate` writes modifiers.<lang>.time into a bare package."""
    main = tmp_path / 'problem.rbx.yml'
    main.write_text('name: p\ntimeLimit: 1000\n')

    session = EditSession(main)
    session.target('modifiers', 'cpp', 'time').replace(3000)
    session.save()

    text = main.read_text()
    assert 'modifiers:' in text
    assert 'cpp:' in text
    assert 'time: 3000' in text


def test_target_creates_a_missing_language_under_existing_modifiers(tmp_path):
    main = tmp_path / 'problem.rbx.yml'
    main.write_text('modifiers:\n  java:\n    time: 5000\n')

    session = EditSession(main)
    session.target('modifiers', 'cpp', 'time').replace(3000)
    session.save()

    text = main.read_text()
    assert 'java:' in text
    assert 'cpp:' in text


def test_save_commits_nothing_when_any_target_file_is_unwritable(tmp_path):
    """One read-only file must not leave a multi-file change half applied."""
    frag = tmp_path / 'frag.yml'
    frag.write_text('items:\n- a\n')
    main = tmp_path / 'contest.rbx.yml'
    main.write_text('n: 1\nx: !include frag.yml\n')

    session = EditSession(main)
    session.target('x', 'items').value.append('b')
    session.target('n').replace(2)

    original_frag = frag.read_text()
    original_main = main.read_text()
    main.chmod(0o444)
    try:
        with pytest.raises(IncludeError):
            session.save()
        assert frag.read_text() == original_frag
        assert main.read_text() == original_main
    finally:
        main.chmod(0o644)
