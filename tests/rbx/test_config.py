import pathlib

import pytest

from rbx import config


def test_get_resources_dir_returns_existing_directory():
    path = config.get_resources_dir(pathlib.Path('presets') / 'default' / 'contest')
    assert path.is_dir()
    assert (path / 'contest.rbx.yml').is_file()


def test_get_resources_dir_raises_for_missing():
    with pytest.raises(FileNotFoundError):
        config.get_resources_dir(pathlib.Path('does') / 'not' / 'exist')
