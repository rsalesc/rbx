import sys
from pathlib import Path

_RUNTIME = (
    Path(__file__).resolve().parents[5]
    / 'rbx'
    / 'resources'
    / 'packagers'
    / 'boca_next'
    / 'runtime'
)
if str(_RUNTIME) not in sys.path:
    sys.path.insert(0, str(_RUNTIME))
