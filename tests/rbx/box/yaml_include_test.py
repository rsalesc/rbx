import io

from rbx.box.yaml_include import is_include, make_yaml, tag_value


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
