from rbx.box.linters.asset_kind import AssetKind, infer_asset_kind
from rbx.box.schema import Checker, CodeItem, Generator, Interactor, Solution


def test_infer_asset_kind_for_typed_subclasses():
    assert infer_asset_kind(Generator(path='g.cpp', name='gen')) is AssetKind.GENERATOR
    assert infer_asset_kind(Checker(path='c.cpp')) is AssetKind.CHECKER
    assert infer_asset_kind(Interactor(path='i.cpp')) is AssetKind.INTERACTOR
    assert (
        infer_asset_kind(Solution(path='s.cpp', outcome='accepted'))
        is AssetKind.SOLUTION
    )


def test_infer_asset_kind_for_bare_codeitem_is_none():
    # Validators are bare CodeItems; their kind is not inferable from type.
    assert infer_asset_kind(CodeItem(path='v.cpp')) is None
