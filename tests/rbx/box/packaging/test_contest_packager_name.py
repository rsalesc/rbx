"""`run_contest_packager` reads a contest packager's name off the class.

It does so before instantiating anything -- to look up the saved limits profile
-- so a packager whose `name()` is a plain instance method blows up with a
`TypeError` the moment the command starts. That is how `rbx contest package
boca` broke, so pin the contract for every contest packager we ship.
"""

import pytest

from rbx.box.packaging.contest_main import BocaContestPackager
from rbx.box.packaging.pkg.packager import PkgContestPackager
from rbx.box.packaging.polygon.packager import PolygonContestPackager


@pytest.mark.parametrize(
    ('packager_cls', 'expected_name'),
    [
        (BocaContestPackager, 'boca'),
        (PkgContestPackager, 'pkg'),
        (PolygonContestPackager, 'polygon'),
    ],
)
def test_contest_packager_name_is_readable_from_the_class(packager_cls, expected_name):
    assert packager_cls.name() == expected_name
