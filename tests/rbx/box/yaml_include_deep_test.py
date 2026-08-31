"""`<<: !include_deep` -- recursive merge, for inheriting a whole config.

`<<: !include` is shallow, matching what `<<` means in YAML: a sibling map is
replaced wholesale. That is wrong for inheriting a config and overriding one
leaf of it, which is what `!include_deep` is for.
"""

from typing import ClassVar, Dict, List, Optional

import pydantic
import pytest

from rbx.box.yaml_include import IncludeError, resolve_yaml_file
from rbx.box.yaml_validation import YamlValidationError, load_yaml_model


def _plain(node):
    if hasattr(node, 'items'):
        return {key: _plain(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_plain(value) for value in node]
    return node


PARENT = """\
name: main
vars:
  year: 2026
  warmup: false
  short_titles:
    pt: Primeira fase
    en: First phase
problems:
- short_name: A
tutorials:
- name: editorial-pt
"""


def test_deep_merge_keeps_sibling_keys_at_depth(tmp_path):
    (tmp_path / 'contest.rbx.yml').write_text(PARENT)
    child = tmp_path / 'contest.warmup.rbx.yml'
    child.write_text(
        '<<: !include_deep contest.rbx.yml\nname: warmup\nvars:\n  warmup: true\n'
    )

    data, _ = resolve_yaml_file(child)

    assert _plain(data['vars']) == {
        'year': 2026,
        'warmup': True,
        'short_titles': {'pt': 'Primeira fase', 'en': 'First phase'},
    }
    assert data['name'] == 'warmup'


def test_deep_merge_recurses_more_than_one_level(tmp_path):
    (tmp_path / 'contest.rbx.yml').write_text(PARENT)
    child = tmp_path / 'contest.warmup.rbx.yml'
    child.write_text(
        '<<: !include_deep contest.rbx.yml\n'
        'name: w\n'
        'vars:\n'
        '  short_titles:\n'
        '    pt: Aquecimento\n'
    )

    data, _ = resolve_yaml_file(child)

    assert _plain(data['vars']['short_titles']) == {
        'pt': 'Aquecimento',
        'en': 'First phase',
    }


def test_deep_merge_replaces_lists_rather_than_concatenating(tmp_path):
    """A variant declaring its own problems must not inherit the parent's too."""
    (tmp_path / 'contest.rbx.yml').write_text(PARENT)
    child = tmp_path / 'contest.warmup.rbx.yml'
    child.write_text(
        '<<: !include_deep contest.rbx.yml\nname: w\nproblems:\n- short_name: Z\n'
    )

    data, _ = resolve_yaml_file(child)

    assert _plain(data['problems']) == [{'short_name': 'Z'}]


def test_an_explicit_empty_list_clears_an_inherited_section(tmp_path):
    (tmp_path / 'contest.rbx.yml').write_text(PARENT)
    child = tmp_path / 'contest.warmup.rbx.yml'
    child.write_text('<<: !include_deep contest.rbx.yml\nname: w\ntutorials: []\n')

    data, _ = resolve_yaml_file(child)

    assert _plain(data['tutorials']) == []


def test_an_unmentioned_section_is_inherited_whole(tmp_path):
    (tmp_path / 'contest.rbx.yml').write_text(PARENT)
    child = tmp_path / 'contest.warmup.rbx.yml'
    child.write_text('<<: !include_deep contest.rbx.yml\nname: w\n')

    data, _ = resolve_yaml_file(child)

    assert _plain(data['tutorials']) == [{'name': 'editorial-pt'}]
    assert _plain(data['problems']) == [{'short_name': 'A'}]


def test_shallow_include_is_still_shallow(tmp_path):
    """The existing tag must not change meaning."""
    (tmp_path / 'contest.rbx.yml').write_text(PARENT)
    child = tmp_path / 'contest.warmup.rbx.yml'
    child.write_text('<<: !include contest.rbx.yml\nname: w\nvars:\n  warmup: true\n')

    data, _ = resolve_yaml_file(child)

    assert _plain(data['vars']) == {'warmup': True}


def test_deep_merge_of_a_fragment_that_itself_includes(tmp_path):
    (tmp_path / 'titles.yml').write_text('pt: from-fragment\n')
    (tmp_path / 'base.yml').write_text('vars:\n  titles: !include titles.yml\n  y: 1\n')
    child = tmp_path / 'child.yml'
    child.write_text('<<: !include_deep base.yml\nvars:\n  z: 2\n')

    data, _ = resolve_yaml_file(child)

    assert _plain(data['vars']) == {'titles': {'pt': 'from-fragment'}, 'y': 1, 'z': 2}


def test_deep_tag_as_a_whole_node_value_is_refused(tmp_path):
    """There is nothing to merge into, so the deep form is meaningless there."""
    (tmp_path / 'f.yml').write_text('a: 1\n')
    root = tmp_path / 'root.yml'
    root.write_text('vars: !include_deep f.yml\n')

    with pytest.raises(IncludeError) as exc:
        resolve_yaml_file(root)

    message = str(exc.value)
    assert '!include' in message


def test_deep_merge_of_a_non_mapping_is_refused(tmp_path):
    (tmp_path / 'f.yml').write_text('- x\n')
    root = tmp_path / 'root.yml'
    root.write_text('vars:\n  <<: !include_deep f.yml\n')

    with pytest.raises(IncludeError) as exc:
        resolve_yaml_file(root)

    assert 'mapping' in str(exc.value).lower()


# --------------------------- diagnostics still work ---------------------------


class _Vars(pydantic.BaseModel):
    n: int


class _Model(pydantic.BaseModel):
    rbx_include_capable: ClassVar[bool] = True

    name: Optional[str] = None
    vars: _Vars
    items: List[Dict[str, int]] = []


def test_a_validation_error_in_a_deep_merged_key_names_the_fragment(tmp_path):
    (tmp_path / 'base.yml').write_text('vars:\n  n: not_an_int\n')
    root = tmp_path / 'root.yml'
    root.write_text('<<: !include_deep base.yml\nname: x\n')

    with pytest.raises(YamlValidationError) as exc:
        load_yaml_model(root, _Model)

    rendered = str(exc.value)
    assert 'base.yml' in rendered
    assert 'not_an_int' in rendered
