import enum
from typing import Optional

from rbx.box.schema import (
    Checker,
    CodeItem,
    Generator,
    Interactor,
    Solution,
    Visualizer,
)


class AssetKind(enum.Enum):
    GENERATOR = 'generator'
    VALIDATOR = 'validator'
    SOLUTION = 'solution'
    CHECKER = 'checker'
    INTERACTOR = 'interactor'
    VISUALIZER = 'visualizer'


# Order matters: check most-specific subclasses first.
_TYPE_TO_KIND = [
    (Solution, AssetKind.SOLUTION),
    (Generator, AssetKind.GENERATOR),
    (Checker, AssetKind.CHECKER),
    (Interactor, AssetKind.INTERACTOR),
    (Visualizer, AssetKind.VISUALIZER),
]


def infer_asset_kind(code: CodeItem) -> Optional[AssetKind]:
    """Infer the asset kind from the CodeItem subclass.

    Validators are plain CodeItems with no dedicated subclass, so they return
    None here; callers that know the role pass the kind explicitly.
    """
    for cls, kind in _TYPE_TO_KIND:
        if isinstance(code, cls):
            return kind
    return None
