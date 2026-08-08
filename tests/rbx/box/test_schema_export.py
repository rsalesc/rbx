"""Tests for the reusable schema exporter and the publishable site tree."""

import json

from rbx.box import schema_export


def test_exports_every_documented_model(tmp_path):
    schema_export.export_schemas(tmp_path)

    names = {p.stem for p in tmp_path.glob('*.json')}

    assert names == {m.__name__ for m in schema_export.MODELS}
    assert 'Package' in names


def _additional_properties_values(node):
    """Every `additionalProperties` value anywhere in the schema."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == 'additionalProperties':
                yield value
            yield from _additional_properties_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from _additional_properties_values(item)


def test_exported_schema_is_valid_json_and_relaxed(tmp_path):
    schema_export.export_schemas(tmp_path)

    schema = json.loads((tmp_path / 'Package.json').read_text())

    assert schema['title'] == 'Package'
    # `additionalProperties: false` is what rejects keys added by newer rbx
    # versions. Dict-typed fields legitimately carry an additionalProperties
    # *schema*, which must survive.
    assert not [v for v in _additional_properties_values(schema) if v is False]
    assert 'vars' in schema['properties']
