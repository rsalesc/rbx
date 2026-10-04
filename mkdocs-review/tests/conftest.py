import subprocess

import pytest


@pytest.fixture
def repo(tmp_path):
    """An empty git repository on `main`, ready to commit to."""

    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)

    git('init', '-q', '-b', 'main')
    git('config', 'user.email', 't@example.com')
    git('config', 'user.name', 't')
    git('config', 'commit.gpgsign', 'false')
    return tmp_path
