#!/usr/bin/env python3
"""
Chunk-level tee for interactive runs.

Takes a marker and a file name as arguments.

Reads from stdin and copies what it reads to:

- stdout (the peer program), as soon as it is read;
- the extra file, verbatim;
- stderr (the merged capture), with the marker prepended to every line.

It reads whatever is available, up to ``CHUNK_BYTES``, rather than one character
at a time: ``os.read`` returns as soon as any bytes are in the pipe, so a program
that writes five bytes and flushes still has them forwarded right away, and a
high-traffic interaction costs one loop iteration per chunk instead of one per
byte (#1035).

The merged capture is shared with the tees of the other direction (and of the
solution's stderr), so only *complete* marked lines are written to it, one
``write`` each batch: a chunk that ends mid-line keeps its tail until the newline
arrives, so another tee can never land in the middle of a marked line. A last
line without a newline is written at EOF.
"""

import os
import sys

CHUNK_BYTES = 64 * 1024


def write_all(fd: int, data) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


def mark_lines(marker: bytes, data) -> bytes:
    # `data` ends with a newline; every line in it gets the marker.
    return b''.join(marker + line + b'\n' for line in bytes(data).split(b'\n')[:-1])


def main() -> None:
    marker = sys.argv[1].encode()
    extra = sys.argv[2]

    inp = sys.stdin.fileno()
    out = sys.stdout.fileno()
    cap = sys.stderr.fileno()

    pending = bytearray()
    with open(extra, 'wb') as f:
        while True:
            chunk = os.read(inp, CHUNK_BYTES)
            if not chunk:
                break

            # Forward to the peer first: the capture stays off the latency path.
            try:
                write_all(out, chunk)
            except BrokenPipeError:
                # The peer is gone. Exit so the writer sees a broken pipe too,
                # exactly as it would without a tee in between.
                pending += chunk
                break

            f.write(chunk)

            newline = chunk.rfind(b'\n')
            if newline < 0:
                pending += chunk
                continue
            pending += chunk[: newline + 1]
            write_all(cap, mark_lines(marker, pending))
            pending = bytearray(chunk[newline + 1 :])

        if pending:
            last_newline = pending.rfind(b'\n')
            complete = pending[: last_newline + 1]
            tail = pending[last_newline + 1 :]
            write_all(
                cap, mark_lines(marker, complete) + (marker + tail if tail else b'')
            )


if __name__ == '__main__':
    main()
