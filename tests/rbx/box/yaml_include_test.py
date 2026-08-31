import io

import pytest

from rbx.box.yaml_include import (
    IncludeError,
    is_include,
    make_yaml,
    resolve_yaml_file,
    tag_value,
)


def test_merge_key_include_loads_without_error():
    doc = 'vars:\n  <<: !include shared/vars.yml\n  warmup: true\n'
    data = make_yaml().load(doc)
    assert 'warmup' in data['vars']


def test_merge_key_include_round_trips_byte_identically():
    doc = 'vars:\n  <<: !include shared/vars.yml\n  warmup: true\nname: x\n'
    yaml = make_yaml()
    buf = io.StringIO()
    yaml.dump(yaml.load(doc), buf)
    assert buf.getvalue() == doc


def test_plain_include_is_a_tagged_scalar():
    data = make_yaml().load('statements: !include shared/st.yml\n')
    node = data['statements']
    assert is_include(node)
    assert tag_value(node) == '!include'
    assert node.value == 'shared/st.yml'


def test_tag_value_normalises_both_ruyaml_representations():
    """Parser nodes carry `tag` as a str, constructed scalars wrap it in Tag."""

    class NodeLike:
        tag = '!include'

    class TagObj:
        value = '!include'

    class ScalarLike:
        tag = TagObj()

    assert tag_value(NodeLike()) == '!include'
    assert tag_value(ScalarLike()) == '!include'
    assert tag_value(object()) == ''


def test_plain_include_round_trips_with_comments():
    doc = 'name: warmup\n# keep me\nstatements: !include shared/st.yml\n'
    yaml = make_yaml()
    buf = io.StringIO()
    yaml.dump(yaml.load(doc), buf)
    assert buf.getvalue() == doc


# ----------------------------- whole-node includes ----------------------------


def test_resolves_mapping_include(tmp_path):
    (tmp_path / 'frag.yml').write_text('a: 1\nb: 2\n')
    (tmp_path / 'main.yml').write_text('top: !include frag.yml\n')
    data, sources = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data['top']) == {'a': 1, 'b': 2}
    assert sources == {
        (tmp_path / 'main.yml').resolve(),
        (tmp_path / 'frag.yml').resolve(),
    }


def test_resolves_sequence_include(tmp_path):
    (tmp_path / 'list.yml').write_text('- x\n- y\n')
    (tmp_path / 'main.yml').write_text('items: !include list.yml\n')
    data, _ = resolve_yaml_file(tmp_path / 'main.yml')
    assert list(data['items']) == ['x', 'y']


def test_resolves_include_at_document_root(tmp_path):
    (tmp_path / 'frag.yml').write_text('a: 1\n')
    (tmp_path / 'main.yml').write_text('!include frag.yml\n')
    data, _ = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data) == {'a': 1}


def test_resolves_include_inside_a_sequence_item(tmp_path):
    (tmp_path / 'frag.yml').write_text('name: st\n')
    (tmp_path / 'main.yml').write_text('statements:\n- !include frag.yml\n')
    data, _ = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data['statements'][0]) == {'name': 'st'}


def test_file_without_includes_is_unchanged(tmp_path):
    (tmp_path / 'main.yml').write_text('a: 1\nb:\n- x\n')
    data, sources = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data) == {'a': 1, 'b': ['x']}
    assert sources == {(tmp_path / 'main.yml').resolve()}


# ------------------------------ merge-key form -------------------------------


def test_merge_key_include_merges_under_explicit_keys(tmp_path):
    (tmp_path / 'frag.yml').write_text('a: 1\nb: 2\n')
    (tmp_path / 'main.yml').write_text(
        'vars:\n  <<: !include frag.yml\n  b: 99\n  c: 3\n'
    )
    data, _ = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data['vars']) == {'a': 1, 'b': 99, 'c': 3}


def test_merge_key_include_is_shallow(tmp_path):
    """Documented limitation: `<<` replaces a sibling map wholesale."""
    (tmp_path / 'frag.yml').write_text('m:\n  x: 1\n  y: 2\n')
    (tmp_path / 'main.yml').write_text('v:\n  <<: !include frag.yml\n  m:\n    x: 9\n')
    data, _ = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data['v']['m']) == {'x': 9}


def test_merge_key_include_nested_one_level(tmp_path):
    (tmp_path / 'st.yml').write_text('pt: a\nen: b\n')
    (tmp_path / 'main.yml').write_text(
        'vars:\n  titles:\n    <<: !include st.yml\n    pt: override\n'
    )
    data, _ = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data['vars']['titles']) == {'pt': 'override', 'en': 'b'}


def test_merge_key_include_of_a_sequence_is_an_error(tmp_path):
    (tmp_path / 'frag.yml').write_text('- x\n')
    (tmp_path / 'main.yml').write_text('v:\n  <<: !include frag.yml\n')
    with pytest.raises(IncludeError) as exc:
        resolve_yaml_file(tmp_path / 'main.yml')
    assert 'mapping' in str(exc.value).lower()


# ---------------------------- paths, cycles, errors ---------------------------


def test_nested_include_resolves_relative_to_its_own_directory(tmp_path):
    sub = tmp_path / 'shared'
    sub.mkdir()
    (sub / 'inner.yml').write_text('v: 1\n')
    (sub / 'outer.yml').write_text('nested: !include inner.yml\n')
    (tmp_path / 'main.yml').write_text('top: !include shared/outer.yml\n')
    data, sources = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data['top']['nested']) == {'v': 1}
    assert (sub / 'inner.yml').resolve() in sources


def test_cycle_is_reported_with_the_chain(tmp_path):
    (tmp_path / 'a.yml').write_text('x: !include b.yml\n')
    (tmp_path / 'b.yml').write_text('y: !include a.yml\n')
    with pytest.raises(IncludeError) as exc:
        resolve_yaml_file(tmp_path / 'a.yml')
    assert 'cycle' in str(exc.value).lower()
    assert 'a.yml' in str(exc.value)


def test_self_include_is_a_cycle(tmp_path):
    (tmp_path / 'a.yml').write_text('x: !include a.yml\n')
    with pytest.raises(IncludeError) as exc:
        resolve_yaml_file(tmp_path / 'a.yml')
    assert 'cycle' in str(exc.value).lower()


def test_missing_fragment_names_the_path_and_the_includer(tmp_path):
    (tmp_path / 'main.yml').write_text('x: !include nope.yml\n')
    with pytest.raises(IncludeError) as exc:
        resolve_yaml_file(tmp_path / 'main.yml')
    assert 'nope.yml' in str(exc.value)
    assert 'main.yml' in str(exc.value)


def test_absolute_path_is_rejected(tmp_path):
    (tmp_path / 'main.yml').write_text('x: !include /etc/passwd\n')
    with pytest.raises(IncludeError) as exc:
        resolve_yaml_file(tmp_path / 'main.yml')
    assert 'absolute' in str(exc.value).lower()


def test_the_same_fragment_may_be_included_twice(tmp_path):
    """Diamond includes are fine; only a true cycle is an error."""
    (tmp_path / 'frag.yml').write_text('a: 1\n')
    (tmp_path / 'main.yml').write_text(
        'one: !include frag.yml\ntwo: !include frag.yml\n'
    )
    data, _ = resolve_yaml_file(tmp_path / 'main.yml')
    assert dict(data['one']) == dict(data['two']) == {'a': 1}
