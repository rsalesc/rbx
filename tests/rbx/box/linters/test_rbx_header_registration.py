import rbx.box.linters  # noqa: F401  (triggers self-registration)
from rbx.box.linters import registry
from rbx.box.linters.asset_kind import AssetKind


def test_rbx_header_is_registered_and_scoped_to_generators():
    linter = registry.get_linter('rbx-header')
    assert linter.name == 'rbx-header'
    assert linter.applies_to == {AssetKind.GENERATOR}
