import dataclasses
import io
import logging
import pathlib
import tempfile
import typing
from abc import ABC, abstractmethod
from typing import IO, AnyStr, Dict, List, Optional, Type, TypeVar

import lz4.frame
from pydantic import BaseModel

from rbx import utils
from rbx.grading import grading_context

logger = logging.getLogger(__name__)

TOMBSTONE = 'x'

BaseModelT = TypeVar('BaseModelT', bound=BaseModel)


def copyfileobj(
    source_fobj: IO[AnyStr],
    destination_fobj: IO[AnyStr],
    buffer_size=io.DEFAULT_BUFFER_SIZE,
    maxlen: Optional[int] = None,
):
    """Read all content from one file object and write it to another.
    Repeatedly read from the given source file object, until no content
    is left, and at the same time write the content to the destination
    file object. Never read or write more than the given buffer size.
    Be cooperative with other greenlets by yielding often.
    source_fobj (fileobj): a file object open for reading, in either
        binary or str mode (doesn't need to be buffered).
    destination_fobj (fileobj): a file object open for writing, in the
        same mode as the source (doesn't need to be buffered).
    buffer_size (int): the size of the read/write buffer.
    maxlen (int): the maximum number of bytes to copy. If None, copy all.
    """
    if maxlen is None:
        maxlen = -1
    while maxlen:
        buffer = source_fobj.read(buffer_size)
        if len(buffer) == 0:
            break
        if maxlen > 0 and maxlen < len(buffer):
            buffer = buffer[:maxlen]
        while len(buffer) > 0:
            written = destination_fobj.write(buffer)
            buffer = buffer[written:]
            maxlen -= written


COMPRESSION_LEVEL = 5


class CompressionMetadata(BaseModel):
    compression_level: int


@dataclasses.dataclass
class PendingFile:
    fd: IO[bytes]
    filename: str
    metadata: Dict[str, Optional[BaseModel]] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class FileWithMetadata:
    filename: str
    metadata: List[str]


class Storage(ABC):
    """Abstract base class for all concrete storages."""

    @abstractmethod
    def get_file(self, filename: str) -> IO[bytes]:
        """Retrieve a file from the storage.
        filename (unicode): the path of the file to retrieve.
        return (fileobj): a readable binary file-like object from which
            to read the contents of the file.
        raise (KeyError): if the file cannot be found.
        """
        pass

    @abstractmethod
    def create_file(self, filename: str) -> Optional[PendingFile]:
        """Create an empty file that will live in the storage.
        Once the caller has written the contents to the file, the commit_file()
        method must be called to commit it into the store.
        filename (unicode): the filename of the file to store.
        return (fileobj): a writable binary file-like object on which
            to write the contents of the file, or None if the file is
            already stored.
        """
        pass

    @abstractmethod
    def commit_file(
        self, file: PendingFile, metadata: Optional[Dict[str, BaseModel]] = None
    ) -> bool:
        """Commit a file created by create_file() to be stored.
        Given a file object returned by create_file(), this function populates
        the database to record that this file now legitimately exists and can
        be used.
        file (PendingFile): the file to commit.
        metadata (Dict[str, BaseModel]): the metadata of the file.
        return (bool): True if the file was committed successfully, False if
            there was already a file with the same filename in the database. This
            shouldn't make any difference to the caller, except for testing
            purposes!
        """
        pass

    @abstractmethod
    def set_metadata(self, filename: str, key: str, value: Optional[BaseModel]):
        """Set the metadata of a file given its filename.
        filename (unicode): the filename of the file to set the metadata.
        key (unicode): the key of the metadata to set.
        value (BaseModel): the value of the metadata to set.
        """
        pass

    @abstractmethod
    def get_metadata(
        self, filename: str, key: str, model_cls: Type[BaseModel]
    ) -> Optional[BaseModel]:
        """Get the metadata of a file given its filename and key.
        filename (unicode): the filename of the file to get the metadata.
        key (unicode): the key of the metadata to get.
        model_cls (Type[BaseModel]): the model class of the metadata.
        return (BaseModel): the value of the metadata.
        raise (KeyError): if the file cannot be found.
        """
        pass

    @abstractmethod
    def list_metadata(self, filename: str) -> List[str]:
        """List the metadata of a file given its filename.
        filename (unicode): the filename of the file to list the metadata.
        return (List[str]): the list of metadata keys.
        """
        pass

    @abstractmethod
    def exists(self, filename: str) -> bool:
        """Check if a file exists in the storage."""
        pass

    @abstractmethod
    def get_size(self, filename: str) -> int:
        """Return the size of a file given its filename.
        filename (unicode): the filename of the file to calculate the size
            of.
        return (int): the size of the file, in bytes.
        raise (KeyError): if the file cannot be found.
        """
        pass

    @abstractmethod
    def delete(self, filename: str):
        """Delete a file from the storage.
        filename (unicode): the filename of the file to delete.
        """
        pass

    @abstractmethod
    def list(self) -> List[FileWithMetadata]:
        """List the files available in the storage.
        return ([(unicode, unicode)]): a list of pairs, each
            representing a file in the form (filename, description).
        """
        pass

    @abstractmethod
    def path_for_symlink(self, filename: str) -> Optional[pathlib.Path]:
        pass

    @abstractmethod
    def filename_from_symlink(self, link: pathlib.Path) -> Optional[str]:
        pass


class NullStorage(Storage):
    """This backend is always empty, it just drops each file that
    receives. It looks mostly like /dev/null. It is useful when you
    want to just rely on the caching capabilities of FileCacher for
    very short-lived and local storages.

    """

    def get_file(self, digest: str) -> IO[bytes]:
        raise KeyError('File not found.')

    def create_file(self, digest: str) -> Optional[PendingFile]:
        return None

    def commit_file(
        self, file: PendingFile, metadata: Optional[Dict[str, BaseModel]] = None
    ) -> bool:
        return False

    def set_metadata(self, filename: str, key: str, value: Optional[BaseModel]):
        pass

    def get_metadata(
        self, filename: str, key: str, model_cls: Type[BaseModel]
    ) -> Optional[BaseModel]:
        raise KeyError('File not found.')

    def list_metadata(self, filename: str) -> List[str]:
        return []

    def exists(self, filename: str) -> bool:
        return False

    def get_size(self, digest: str) -> int:
        raise KeyError('File not found.')

    def delete(self, digest: str):
        pass

    def list(self) -> List[FileWithMetadata]:
        return list()

    def path_for_symlink(self, digest: str) -> Optional[pathlib.Path]:
        return None

    def filename_from_symlink(self, link: pathlib.Path) -> Optional[str]:
        return None


class FilesystemStorage(Storage):
    """This class implements a backend for FileCacher that keeps all
    the files in a file system directory, named after their filename.
    """

    def __init__(self, path: pathlib.Path, compress: bool = False):
        """Initialize the backend.
        path (string): the base path for the storage.
        """
        self.path = path
        self.compress = compress
        # Create the directory if it doesn't exist
        (path / '.metadata').mkdir(parents=True, exist_ok=True)

    def get_file(self, filename: str) -> IO[bytes]:
        """See FileCacherBackend.get_file()."""
        file_path = self.path / filename

        if not file_path.is_file():
            raise KeyError('File not found.')

        compression_metadata = self.get_metadata(
            filename, 'compression', CompressionMetadata
        )
        if compression_metadata is not None:
            return typing.cast(
                IO[bytes],
                lz4.frame.open(
                    file_path,
                    mode='rb',
                    compression_level=compression_metadata.compression_level,
                ),
            )
        return file_path.open('rb')

    def create_file(self, filename: str) -> Optional[PendingFile]:
        """See FileCacherBackend.create_file()."""
        # Check if the file already exists. Return None if so, to inform the
        # caller they don't need to store the file.
        file_path = self.path / filename

        if file_path.is_file():
            return None

        # Create a temporary file in the same directory
        # Use only the basename for the suffix to avoid issues with subdirectories
        filename_basename = pathlib.Path(filename).name
        temp_file = tempfile.NamedTemporaryFile(
            'wb',
            delete=False,
            prefix='.tmp.',
            suffix=f'.{filename_basename}',
            dir=self.path,
        )
        metadata: Dict[str, Optional[BaseModel]] = {'compression': None}
        if self.compress or grading_context.should_compress():
            fd_name = temp_file.name
            level = grading_context.get_compression_level()
            temp_file = typing.cast(
                IO[bytes],
                lz4.frame.open(
                    temp_file,
                    mode='wb',
                    compression_level=level,
                ),
            )
            temp_file.name = fd_name  # type: ignore
            metadata['compression'] = CompressionMetadata(compression_level=level)

        return PendingFile(fd=temp_file, filename=filename, metadata=metadata)

    def commit_file(
        self, file: PendingFile, metadata: Optional[Dict[str, BaseModel]] = None
    ) -> bool:
        """See FileCacherBackend.commit_file()."""
        file.fd.close()

        file_path: pathlib.Path = self.path / file.filename
        file_path.parent.mkdir(parents=True, exist_ok=True)

        for key, value in file.metadata.items():
            self._set_metadata(file.filename, key, value)

        if metadata is not None:
            for key, value in metadata.items():
                self._set_metadata(file.filename, key, value)

        # Move it into place in the cache. Skip if it already exists, and
        # delete the temporary file instead.
        if not file_path.is_file():
            # There is a race condition here if someone else puts the file here
            # between checking and renaming. Put it doesn't matter in practice,
            # because rename will replace the file anyway (which should be
            # identical).
            pathlib.PosixPath(file.fd.name).rename(file_path)
            return True
        else:
            pathlib.PosixPath(file.fd.name).unlink()
            return False

    def _get_metadata_path(self, filename: str, key: str) -> pathlib.Path:
        return self.path / '.metadata' / f'{filename}__{key}.json'

    def _set_metadata(self, filename: str, key: str, value: Optional[BaseModel]):
        if value is None:
            self._get_metadata_path(filename, key).unlink(missing_ok=True)
        else:
            metadata_path = self._get_metadata_path(filename, key)
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.write_text(value.model_dump_json())

    def set_metadata(self, filename: str, key: str, value: Optional[BaseModel]):
        if not self.exists(filename):
            raise KeyError('File not found.')

        self._set_metadata(filename, key, value)

    def get_metadata(
        self, filename: str, key: str, model_cls: Type[BaseModelT]
    ) -> Optional[BaseModelT]:
        path = self._get_metadata_path(filename, key)
        if not path.is_file():
            return None
        return model_cls.model_validate_json(path.read_text())

    def list_metadata(self, filename: str) -> List[str]:
        return [
            path.stem.split('__')[1]
            for path in sorted((self.path / '.metadata').glob(f'{filename}__*.json'))
        ]

    def exists(self, filename: str) -> bool:
        """See FileCacherBackend.exists()."""
        file_path: pathlib.Path = self.path / filename

        return file_path.is_file()

    def get_size(self, filename: str) -> int:
        """See FileCacherBackend.get_size()."""
        file_path: pathlib.Path = self.path / filename

        if not file_path.is_file():
            raise KeyError('File not found.')

        return file_path.stat().st_size

    def delete(self, filename: str):
        """See FileCacherBackend.delete()."""
        file_path: pathlib.Path = self.path / filename

        file_path.unlink(missing_ok=True)
        for key in self.list_metadata(filename):
            self._get_metadata_path(filename, key).unlink(missing_ok=True)

    def list(self) -> List[FileWithMetadata]:
        """See FileCacherBackend.list()."""
        res = []
        for path in self.path.glob('*'):
            if path.is_file():
                filename = str(path.relative_to(self.path))
                res.append(
                    FileWithMetadata(
                        filename=filename,
                        metadata=self.list_metadata(filename),
                    )
                )
        return res

    def path_for_symlink(self, filename: str) -> Optional[pathlib.Path]:
        file_path = self.path / filename
        if not file_path.is_file():
            raise KeyError('File not found.')

        compression_metadata = self.get_metadata(
            filename, 'compression', CompressionMetadata
        )
        if compression_metadata is not None:
            return None
        return file_path

    def filename_from_symlink(self, link: pathlib.Path) -> Optional[str]:
        if not link.is_symlink():
            return None

        # Track visited symlinks to detect circular references
        visited = set()
        current = link
        max_depth = 100  # Reasonable limit to prevent infinite loops
        depth = 0

        while current.is_symlink() and depth < max_depth:
            # Convert to absolute path for consistent comparison
            abs_current = utils.abspath(current)

            # Check for circular reference
            if abs_current in visited:
                return None

            visited.add(abs_current)

            # Read the target of the symlink
            target = current.readlink()

            # If target is relative, resolve it relative to the symlink's parent directory
            if not target.is_absolute():
                current = utils.abspath(current.parent / target)
            else:
                current = utils.abspath(target)

            depth += 1

        # If we hit the depth limit, assume circular reference
        if depth >= max_depth:
            return None

        if not current.is_file():
            return None
        if not current.is_relative_to(self.path):
            return None
        return str(current.relative_to(self.path))
