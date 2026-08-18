import hashlib
import pathlib
from typing import IO, Dict, Tuple


class Digester:
    """Simple wrapper of hashlib using our preferred hasher."""

    def __init__(self):
        self._hasher = hashlib.sha1()

    def update(self, b):
        """Add the bytes b to the hasher."""
        self._hasher.update(b)

    def digest(self):
        """Return the digest as an hex string."""
        return self._hasher.digest().hex()


def digest_cooperatively_into_digester(
    f: IO[bytes], digester: Digester, chunk_size: int = 2**20
):
    buf = f.read(chunk_size)
    while len(buf) > 0:
        digester.update(buf)
        buf = f.read(chunk_size)


def digest_cooperatively(f: IO[bytes], chunk_size: int = 2**20):
    d = Digester()
    digest_cooperatively_into_digester(f, d, chunk_size)
    return d.digest()


def digest_file(path: pathlib.Path):
    with open(path, 'rb') as f:
        return digest_cooperatively(f)


_DIGEST_MEMO: Dict[Tuple[str, int, int, int, int], str] = {}


def digest_file_memoized(path: pathlib.Path) -> str:
    """Digest a file, reusing the result while its stat signature is unchanged.

    The same path is hashed many times within a single invocation (every
    compilation re-keys on the precompiled headers, which are hundreds of
    megabytes). Keying on identity + size + mtime keeps that to once.
    """
    try:
        st = path.stat()
    except OSError:
        return digest_file(path)
    key = (str(path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    memoized = _DIGEST_MEMO.get(key)
    if memoized is not None:
        return memoized
    digest = digest_file(path)
    _DIGEST_MEMO[key] = digest
    return digest
