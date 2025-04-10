import atexit
import fcntl
import io
import logging
import os
import pathlib
import shutil
import tempfile
import typing
from typing import IO, List, Optional

from rbx.grading.judge import digester, storage

logger = logging.getLogger(__name__)


class TombstoneError(RuntimeError):
    """An error that represents the file cacher trying to read
    files that have been deleted from the database.

    """

    pass


class FileCacher:
    """This class implement a local cache for files stored as FSObject
    in the database.

    """

    # This value is very arbitrary, and in this case we want it to be a
    # one-size-fits-all, since we use it for many conversions. It has
    # been chosen arbitrarily based on performance tests on my machine.
    # A few consideration on the value it could assume follow:
    # - The page size of large objects is LOBLKSIZE, which is BLCKSZ/4
    #   (BLCKSZ is the block size of the PostgreSQL database, which is
    #   set during pre-build configuration). BLCKSZ is by default 8192,
    #   therefore LOBLKSIZE is 2048. See:
    #   http://www.postgresql.org/docs/9.0/static/catalog-pg-largeobject.html
    # - The `io' module defines a DEFAULT_BUFFER_SIZE constant, whose
    #   value is 8192.
    # CHUNK_SIZE should be a multiple of these values.
    CHUNK_SIZE = 1024 * 1024  # 1 MiB

    backend: storage.Storage
    shared: bool
    file_dir: pathlib.Path
    temp_dir: pathlib.Path
    folder: Optional[pathlib.Path]

    def __init__(
        self,
        backend: storage.Storage,
        shared: bool = False,
        folder: Optional[pathlib.Path] = None,
    ):
        """Initialize."""

        self.backend = backend
        self.shared = shared
        self.folder = folder

        # First we create the config directories.
        if folder:
            self._create_directory_or_die(folder)

        if not self.is_shared():
            self.file_dir = pathlib.Path(tempfile.mkdtemp())
            # Delete this directory on exit since it has a random name and
            # won't be used again.
            atexit.register(lambda: shutil.rmtree(str(self.file_dir)))
        else:
            assert folder is not None
            self.file_dir = folder / 'fs-cache-shared'
        self._create_directory_or_die(self.file_dir)

        # Temp dir must be a subdirectory of file_dir to avoid cross-filesystem
        # moves.
        self.temp_dir = pathlib.Path(
            tempfile.mkdtemp(dir=self.file_dir, prefix='_temp')
        )
        atexit.register(lambda: shutil.rmtree(str(self.temp_dir)))
        # Just to make sure it was created.

    def is_shared(self) -> bool:
        """Return whether the cache directory is shared with other services."""
        return self.shared

    @staticmethod
    def _create_directory_or_die(directory: pathlib.Path):
        """Create directory and ensure it exists, or raise a RuntimeError."""
        directory.mkdir(parents=True, exist_ok=True)

    def precache_lock(self) -> Optional[IO[bytes]]:
        """Lock the (shared) cache for precaching if it is currently unlocked.

        Locking is optional: Any process can perform normal cache operations
        at any time whether the cache is locked or not.

        The locking mechanism's only purpose is to avoid wasting resources by
        ensuring that on each machine, only one worker precaches at any time.

        return (fileobj|None): The lock file if the cache was previously
            unlocked. Closing the file object will release the lock.
            None if the cache was already locked.

        """
        lock_file = self.file_dir / 'cache_lock'
        fobj = lock_file.open('wb')
        returned = False
        try:
            fcntl.flock(fobj, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            # This exception is raised only if the errno is EWOULDBLOCK,
            # which means that the file is already locked.
            return None
        else:
            returned = True
            return fobj
        finally:
            if not returned:
                fobj.close()

    def _load(self, digest: str, cache_only: bool) -> Optional[IO[bytes]]:
        """Load a file into the cache and open it for reading.

        cache_only (bool): don't open the file for reading.

        return (fileobj): a readable binary file-like object from which
            to read the contents of the file (None if cache_only is True).

        raise (KeyError): if the file cannot be found.

        """
        cache_file_path = self.file_dir / digest

        if cache_only:
            if cache_file_path.exists():
                return None
        else:
            try:
                return cache_file_path.open('rb')
            except FileNotFoundError:
                pass

        logger.debug('File %s not in cache, downloading ' 'from database.', digest)

        ftmp_handle, temp_file_path = tempfile.mkstemp(dir=self.temp_dir, text=False)
        temp_file_path = pathlib.Path(temp_file_path)
        with open(ftmp_handle, 'wb') as ftmp, self.backend.get_file(digest) as fobj:
            storage.copyfileobj(fobj, ftmp, self.CHUNK_SIZE)

        if not cache_only:
            # We allow anyone to delete files from the cache directory
            # self.file_dir at any time. Hence, cache_file_path might no
            # longer exist an instant after we create it. Opening the
            # temporary file before renaming it circumvents this issue.
            # (Note that the temporary file may not be manually deleted!)
            fd = temp_file_path.open('rb')

        # Then move it to its real location (this operation is atomic
        # by POSIX requirement)
        temp_file_path.rename(cache_file_path)

        logger.debug('File %s downloaded.', digest)

        if not cache_only:
            return fd

    def cache_file(self, digest: str):
        """Load a file into the cache.

        Ask the backend to provide the file and store it in the cache for the
        benefit of future accesses, unless the file is already cached.
        Note that the cached file might still be deleted at any time, so it
        cannot be assumed to actually exist after this function completes.
        Always use the get_file* functions to access a file.

        digest (unicode): the digest of the file to get.

        raise (KeyError): if the file cannot be found.
        raise (TombstoneError): if the digest is the tombstone

        """
        if digest == storage.TOMBSTONE:
            raise TombstoneError()

        self._load(digest, True)

    def get_file(self, digest: str) -> IO[bytes]:
        """Retrieve a file from the storage.

        If it's available in the cache use that copy, without querying
        the backend. Otherwise ask the backend to provide it, and store
        it in the cache for the benefit of future accesses.

        The file is returned as a file-object. Other interfaces are
        available as `get_file_content', `get_file_to_fobj' and `get_
        file_to_path'.

        digest (unicode): the digest of the file to get.

        return (fileobj): a readable binary file-like object from which
            to read the contents of the file.

        raise (KeyError): if the file cannot be found.
        raise (TombstoneError): if the digest is the tombstone

        """
        if digest == storage.TOMBSTONE:
            raise TombstoneError()

        logger.debug('Getting file %s.', digest)

        return typing.cast(IO[bytes], self._load(digest, False))

    def path_for_symlink(self, digest: str) -> Optional[pathlib.Path]:
        if digest == storage.TOMBSTONE:
            raise TombstoneError()

        logger.debug('Getting symlink file path %s.', digest)
        return self.backend.path_for_symlink(digest)

    def get_file_content(self, digest: str) -> bytes:
        """Retrieve a file from the storage.

        See `get_file'. This method returns the content of the file, as
        a binary string.

        digest (unicode): the digest of the file to get.

        return (bytes): the content of the retrieved file.

        raise (KeyError): if the file cannot be found.
        raise (TombstoneError): if the digest is the tombstone

        """
        if digest == storage.TOMBSTONE:
            raise TombstoneError()
        with self.get_file(digest) as src:
            return src.read()

    def get_file_to_fobj(self, digest: str, dst: IO[bytes]):
        """Retrieve a file from the storage.

        See `get_file'. This method will write the content of the file
        to the given file-object.

        digest (unicode): the digest of the file to get.
        dst (fileobj): a writable binary file-like object on which to
            write the contents of the file.

        raise (KeyError): if the file cannot be found.
        raise (TombstoneError): if the digest is the tombstone

        """
        if digest == storage.TOMBSTONE:
            raise TombstoneError()
        with self.get_file(digest) as src:
            storage.copyfileobj(src, dst, self.CHUNK_SIZE)

    def get_file_to_path(self, digest: str, dst_path: pathlib.Path):
        """Retrieve a file from the storage.

        See `get_file'. This method will write the content of a file
        to the given file-system location.

        digest (unicode): the digest of the file to get.
        dst_path (string): an accessible location on the file-system on
            which to write the contents of the file.

        raise (KeyError): if the file cannot be found.

        """
        if digest == storage.TOMBSTONE:
            raise TombstoneError()
        with self.get_file(digest) as src:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            with dst_path.open('wb') as dst:
                storage.copyfileobj(src, dst, self.CHUNK_SIZE)

    def put_file_from_fobj(self, src: IO[bytes], desc: str = '') -> str:
        """Store a file in the storage.

        If it's already (for some reason...) in the cache send that
        copy to the backend. Otherwise store it in the file-system
        cache first.

        The file is obtained from a file-object. Other interfaces are
        available as `put_file_content', `put_file_from_path'.

        src (fileobj): a readable binary file-like object from which
            to read the contents of the file.
        desc (unicode): the (optional) description to associate to the
            file.

        return (unicode): the digest of the stored file.

        """
        logger.debug('Reading input file to store on the database.')

        # Unfortunately, we have to read the whole file-obj to compute
        # the digest but we take that chance to save it to a temporary
        # path so that we then just need to move it. Hoping that both
        # locations will be on the same filesystem, that should be way
        # faster than reading the whole file-obj again (as it could be
        # compressed or require network communication).
        # XXX We're *almost* reimplementing copyfileobj.
        with tempfile.NamedTemporaryFile(
            'wb', delete=False, dir=str(self.temp_dir)
        ) as dst:
            d = digester.Digester()
            buf = src.read(self.CHUNK_SIZE)
            while len(buf) > 0:
                d.update(buf)
                while len(buf) > 0:
                    written = dst.write(buf)
                    if written is None:
                        break
                    buf = buf[written:]
                buf = src.read(self.CHUNK_SIZE)
            digest = d.digest()
            dst.flush()

            logger.debug('File has digest %s.', digest)

            cache_file_path = self.file_dir / digest

            # Store the file in the backend. We do that even if the file
            # was already in the cache
            # because there's a (small) chance that the file got removed
            # from the backend but somehow remained in the cache.
            # We read from the temporary file before moving it to
            # cache_file_path because the latter might be deleted before
            # we get a chance to open it.
            with open(dst.name, 'rb') as src:
                pending_file = self.backend.create_file(digest)
                if pending_file is not None:
                    storage.copyfileobj(src, pending_file.fd, self.CHUNK_SIZE)
                    self.backend.commit_file(pending_file, desc)

            os.rename(dst.name, cache_file_path)

        return digest

    def put_file_content(self, content: bytes, desc: str = '') -> str:
        """Store a file in the storage.

        See `put_file_from_fobj'. This method will read the content of
        the file from the given binary string.

        content (bytes): the content of the file to store.
        desc (unicode): the (optional) description to associate to the
            file.

        return (unicode): the digest of the stored file.

        """
        with io.BytesIO(content) as src:
            return self.put_file_from_fobj(src, desc)

    def put_file_text(self, text: str, desc: str = '') -> str:
        return self.put_file_content(text.encode('utf-8'), desc)

    def put_file_from_path(self, src_path: pathlib.Path, desc: str = '') -> str:
        """Store a file in the storage.

        See `put_file_from_fobj'. This method will read the content of
        the file from the given file-system location.

        src_path (Path): an accessible location on the file-system
            from which to read the contents of the file.
        desc (unicode): the (optional) description to associate to the
            file.

        return (unicode): the digest of the stored file.

        """
        with src_path.open('rb') as src:
            return self.put_file_from_fobj(src, desc)

    def describe(self, digest: str) -> str:
        """Return the description of a file given its digest.

        digest (unicode): the digest of the file to describe.

        return (unicode): the description of the file.

        raise (KeyError): if the file cannot be found.

        """
        if digest == storage.TOMBSTONE:
            raise TombstoneError()
        return self.backend.describe(digest)

    def get_size(self, digest: str) -> int:
        """Return the size of a file given its digest.

        digest (unicode): the digest of the file to calculate the size
            of.

        return (int): the size of the file, in bytes.

        raise (KeyError): if the file cannot be found.
        raise (TombstoneError): if the digest is the tombstone

        """
        if digest == storage.TOMBSTONE:
            raise TombstoneError()
        return self.backend.get_size(digest)

    def delete(self, digest: str):
        """Delete a file from the backend and the local cache.

        digest (unicode): the digest of the file to delete.

        """
        if digest == storage.TOMBSTONE:
            return
        self.drop(digest)
        self.backend.delete(digest)

    def drop(self, digest):
        """Delete a file only from the local cache.

        digest (unicode): the file to delete.

        """
        if digest == storage.TOMBSTONE:
            return
        cache_file_path: pathlib.Path = self.file_dir / digest
        cache_file_path.unlink(missing_ok=True)

    def purge_cache(self):
        """Empty the local cache.

        This function must not be called if the cache directory is shared.

        """
        self.destroy_cache()
        self.file_dir.mkdir(parents=True, exist_ok=True)
        if self.folder is not None:
            self.folder.mkdir(parents=True, exist_ok=True)

    def destroy_cache(self):
        """Completely remove and destroy the cache.

        Nothing that could have been created by this object will be
        left on disk. After that, this instance isn't usable anymore.

        This function must not be called if the cache directory is shared.

        """
        if self.is_shared():
            raise Exception('You may not destroy a shared cache.')
        shutil.rmtree(str(self.file_dir))

    def list(self) -> List[storage.FileWithDescription]:
        """List the files available in the storage.

        return ([(unicode, unicode)]): a list of pairs, each
            representing a file in the form (digest, description).

        """
        return self.backend.list()

    def check_backend_integrity(self, delete: bool = False) -> bool:
        """Check the integrity of the backend.

        Request all the files from the backend. For each of them the
        digest is recomputed and checked against the one recorded in
        the backend.

        If mismatches are found, they are reported with ERROR
        severity. The method returns False if at least a mismatch is
        found, True otherwise.

        delete (bool): if True, files with wrong digest are deleted.

        """
        clean = True
        for fwd in self.list():
            digest = fwd.filename
            d = digester.Digester()
            with self.backend.get_file(digest) as fobj:
                buf = fobj.read(self.CHUNK_SIZE)
                while len(buf) > 0:
                    d.update(buf)
                    buf = fobj.read(self.CHUNK_SIZE)
            computed_digest = d.digest()
            if digest != computed_digest:
                logger.error(
                    'File with hash %s actually has hash %s', digest, computed_digest
                )
                if delete:
                    self.delete(digest)
                clean = False

        return clean
