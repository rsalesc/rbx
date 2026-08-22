#!/usr/bin/env python3
"""Generate the tiny placeholder PNGs the spike's \\includegraphics calls need.

Kept out of git (binaries); run this once inside a checkout of the fixture
before compiling. Emits minimal solid-colour RGB PNGs with the stdlib only
(no Pillow), so the spike is reproducible on a bare Python install.
"""

import pathlib
import struct
import zlib


def _png(path: pathlib.Path, w: int, h: int, rgb: tuple[int, int, int]) -> None:
    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return (
            struct.pack('>I', len(data))
            + body
            + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)
        )

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)  # 8-bit RGB
    row = b'\x00' + bytes(rgb) * w
    idat = zlib.compress(row * h)
    path.write_bytes(
        sig + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b'')
    )


HERE = pathlib.Path(__file__).resolve().parent

# (relative path, colour) — names deliberately collide across problems (fig.png)
# to prove \subimport isolation keeps them apart.
IMAGES = {
    'logo.png': (40, 40, (30, 90, 200)),  # contest chrome, referenced from root
    '.problems/A/statements/fig.png': (60, 30, (200, 60, 60)),
    '.problems/A/statements/.samples/000/sample-fig.png': (24, 24, (60, 160, 60)),
    '.problems/B/statements/fig.png': (60, 30, (160, 60, 200)),
}

for rel, (w, h, rgb) in IMAGES.items():
    out = HERE / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    _png(out, w, h, rgb)
    print(f'wrote {rel}')
