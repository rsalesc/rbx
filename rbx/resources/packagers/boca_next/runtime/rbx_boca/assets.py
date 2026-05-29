import hashlib
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class NativeAsset:
    name: str
    source: bytes
    compile_argv: List[str]  # template; may contain {src} and {out} tokens

    def cache_key(self) -> str:
        h = hashlib.md5()
        h.update(self.source)
        h.update(b'\0')
        h.update('\0'.join(self.compile_argv).encode('utf-8'))
        return h.hexdigest()
