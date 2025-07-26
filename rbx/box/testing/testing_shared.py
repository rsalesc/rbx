import os
import pathlib
import shutil
import tempfile
from typing import Optional, Union

from rbx import testing_utils, utils
from rbx.config import get_resources_file
from rbx.testing_utils import get_testdata_path

PathOrStr = Union[os.PathLike, str]


class TestingShared:
    def __init__(self, root: PathOrStr):
        self.root = pathlib.Path(root)
        self._created_tmps = []
        self._old_cwd = None

    def __enter__(self):
        self._old_cwd = pathlib.Path.cwd()
        os.chdir(self.root)
        testing_utils.clear_all_functools_cache()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._old_cwd is not None:
            os.chdir(self._old_cwd)
        self.cleanup()

    def path(self, path: Optional[PathOrStr] = None) -> pathlib.Path:
        if path is None:
            return self.root
        return self.root / path

    def abspath(self, path: PathOrStr) -> pathlib.Path:
        return utils.abspath(self.path(path))

    def mkdtemp(self) -> pathlib.Path:
        temp_dir = pathlib.Path(tempfile.mkdtemp())
        self._created_tmps.append(temp_dir)
        return temp_dir

    def cleanup(self):
        for tmp in self._created_tmps:
            shutil.rmtree(tmp)

    def add_file(
        self, path: PathOrStr, src: Optional[PathOrStr] = None
    ) -> pathlib.Path:
        filename = self.path(path)
        filename.parent.mkdir(parents=True, exist_ok=True)
        if src is not None:
            self.add_from_testdata(path, src)
        else:
            filename.touch()
        return filename

    def relpath(self, path: PathOrStr) -> pathlib.Path:
        path = pathlib.Path(path)
        if not path.is_relative_to(self.root):
            return path
        return path.relative_to(self.root)

    def add_from_testdata(self, path: PathOrStr, src: PathOrStr):
        testdata_path = get_testdata_path()
        testdata_file = testdata_path / src
        if testdata_file.is_file():
            shutil.copy(testdata_file, self.path(path))
        elif testdata_file.is_dir():
            shutil.copytree(testdata_file, self.path(path))
        else:
            raise ValueError(f'{testdata_file} is not a file or directory')

    def add_from_resources(self, path: PathOrStr, src: PathOrStr):
        resources_file = get_resources_file(pathlib.Path(src))
        shutil.copy(resources_file, self.path(path))

    def exists_file(self, path: PathOrStr) -> bool:
        return self.path(path).exists()

    def delete_file(self, path: PathOrStr):
        self.path(path).unlink()

    def copy_from(self, other: 'TestingShared'):
        shutil.copytree(other.root, self.root, dirs_exist_ok=True, symlinks=True)
