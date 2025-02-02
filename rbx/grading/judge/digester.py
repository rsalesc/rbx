import hashlib
from typing import IO

import gevent


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
        gevent.sleep(0)
        buf = f.read(chunk_size)


def digest_cooperatively(f: IO[bytes], chunk_size: int = 2**20):
    d = Digester()
    digest_cooperatively_into_digester(f, d, chunk_size)
    return d.digest()
