import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Union


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

    def ensure(
        self, cache_dir: Union[str, 'os.PathLike[str]'], runner: Callable[..., int]
    ) -> Path:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / '{}-{}'.format(self.name, self.cache_key())

        # Cache hit: a non-empty published binary already exists.
        if target.exists() and target.stat().st_size > 0:
            return target

        # Cache miss: compile to unique temp paths, then atomically publish.
        src_fd, src_name = tempfile.mkstemp(dir=str(cache_dir), suffix='.src')
        out_fd, out_name = tempfile.mkstemp(dir=str(cache_dir), suffix='.out')
        os.close(out_fd)
        # The unique temp output must not exist when the compiler runs, so it
        # creates a fresh binary rather than appending to an empty placeholder.
        os.unlink(out_name)
        try:
            with os.fdopen(src_fd, 'wb') as f:
                f.write(self.source)

            rendered_argv = [
                arg.replace('{src}', src_name).replace('{out}', out_name)
                for arg in self.compile_argv
            ]
            rc = runner(rendered_argv)
            if rc != 0:
                raise RuntimeError('failed to compile {}'.format(self.name))

            # Atomic publish (os.replace is atomic on POSIX): concurrent judges
            # never observe a partial binary at the final target path.
            os.replace(out_name, str(target))
            return target
        finally:
            for leftover in (src_name, out_name):
                try:
                    os.unlink(leftover)
                except OSError:
                    pass
