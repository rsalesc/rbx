#!/usr/bin/env python3
"""
Capture tee for interactive runs: one process for every pipe of a run.

Usage:

    chunk_tee.py [--line] --routes <marker> <in> <out> <extra> [...]
    chunk_tee.py <marker> <extra>

A route reads the pipe numbered <in> and copies what it reads to:

- the pipe numbered <out> (the peer program), as soon as it is read; `-` means
  no peer;
- the <extra> file, verbatim;
- stderr (the merged capture), with <marker> prepended to every line.

The second form is one route from stdin to stdout.

One tee serves every route of a run instead of one tee per pipe: each tee is one
more process a message has to wake on its way, and waking a process on another
CPU is what costs in a VM. Measured in the Docker image (Docker Desktop, 8
vCPUs), a fanout round trip at 2 to 16 processes took 40-67 us with a tee per
pipe and 23-30 us with this one, against 11-19 us with no tee at all. It also
writes the merged capture in exactly the order it moved the data, so a reply
can never be logged ahead of the line it answers.

A route reads whatever is available, up to ``CHUNK_BYTES``, rather than one
character at a time: ``os.read`` returns as soon as any bytes are in the pipe,
so a program that writes five bytes and flushes still has them forwarded right
away, and a high-traffic interaction costs one loop iteration per chunk instead
of one per byte (#1035). With ``--line`` it forwards only whole lines, holding
a partial one back until its newline (or EOF).

Only *complete* marked lines are written to the merged capture: a chunk that
ends mid-line keeps its tail until the newline arrives, so whatever else
appends there can never land in the middle of a marked line. A last line
without a newline is written at the route's EOF, with one.

Writes to a peer never block the other routes: what a peer has not taken yet
waits here, and a route stops reading while ``CHUNK_BYTES`` of it are waiting,
so a writer still blocks on a peer that does not read, as it would without a
tee. When a peer is gone, its route closes the pipe it reads, so the writer sees
a broken pipe exactly as it would without a tee in between, and no traceback
lands in the capture.
"""

import os
import select
import sys

CHUNK_BYTES = 64 * 1024
READ = select.POLLIN | select.POLLHUP | select.POLLERR
WRITE = select.POLLOUT | select.POLLERR


def write_all(fd: int, data) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


def mark_lines(marker: bytes, data) -> bytes:
    # `data` ends with a newline; every line in it gets the marker.
    return b''.join(marker + line + b'\n' for line in bytes(data).split(b'\n')[:-1])


class KQueue:
    """`select.poll`'s interface over a kqueue, for macOS (which has no epoll):
    a wait costs the same however many descriptors are watched."""

    def __init__(self) -> None:
        self.kq = select.kqueue()
        self.masks = {}

    def _filters(self, mask: int):
        filters = []
        if mask & select.POLLIN:
            filters.append(select.KQ_FILTER_READ)
        if mask & select.POLLOUT:
            filters.append(select.KQ_FILTER_WRITE)
        return filters

    def _change(self, fd: int, old: int, new: int) -> None:
        changes = [
            select.kevent(fd, f, select.KQ_EV_DELETE)
            for f in self._filters(old)
            if f not in self._filters(new)
        ] + [
            select.kevent(fd, f, select.KQ_EV_ADD)
            for f in self._filters(new)
            if f not in self._filters(old)
        ]
        self.masks[fd] = new
        if changes:
            self.kq.control(changes, 0, 0)

    def register(self, fd: int, mask: int) -> None:
        self._change(fd, 0, mask)

    def modify(self, fd: int, mask: int) -> None:
        self._change(fd, self.masks[fd], mask)

    def unregister(self, fd: int) -> None:
        self._change(fd, self.masks.pop(fd), 0)

    def poll(self, timeout: int):
        events = self.kq.control(None, 64, None if timeout < 0 else timeout)
        return [(event.ident, event.filter) for event in events]


def make_poller():
    # Each waits in one system call whatever the number of descriptors.
    if hasattr(select, 'epoll'):
        return select.epoll()
    if hasattr(select, 'kqueue'):
        return KQueue()
    return select.poll()


class Route:
    def __init__(self, marker: bytes, src: int, dst, extra, line: bool):
        self.marker = marker
        self.src = src
        # The peer's pipe, or None once it is closed (or when there is none).
        self.dst = dst
        self.extra = extra
        self.line = line
        # The tail of the last chunk, after its last newline: not captured yet
        # (and, with `line`, not forwarded yet either). Grown in place, so a
        # line spanning many chunks costs a copy per chunk, not per byte read.
        self.tail = bytearray()
        # Complete lines read but not captured yet: the read that took them
        # writes them after forwarding, unless the forward ended the route.
        self.lines = bytearray()
        # Read, and still to be written to the peer.
        self.out = bytearray()
        # Whether `src` is still read: until its EOF, or its peer is gone.
        self.reading = True
        self.done = False


class Tee:
    def __init__(self, routes, cap: int):
        self.cap = cap
        # Level-triggered either way; epoll where there is one, so a wake-up
        # costs the same however many routes there are.
        self.poller = make_poller()
        self.by_fd = {}
        # What each watched descriptor is watched for.
        self.watched = {}
        self.live = len(routes)
        for route in routes:
            self.by_fd[route.src] = route
            self.watch(route.src, READ)
            if route.dst is not None:
                # Only ever written as far as it has room (`flush`).
                os.set_blocking(route.dst, False)
                self.by_fd[route.dst] = route

    def watch(self, fd: int, mask: int) -> None:
        if self.watched.get(fd, 0) == mask:
            return
        if not mask:
            del self.watched[fd]
            self.poller.unregister(fd)
        elif fd in self.watched:
            self.watched[fd] = mask
            self.poller.modify(fd, mask)
        else:
            self.watched[fd] = mask
            self.poller.register(fd, mask)

    def close(self, fd: int) -> None:
        self.watch(fd, 0)
        if self.by_fd.pop(fd, None) is not None:
            os.close(fd)

    def run(self) -> None:
        while self.live:
            for fd, _ in self.poller.poll(-1):
                route = self.by_fd.get(fd)
                if route is None or fd not in self.watched:
                    continue
                if fd == route.src:
                    self.read(route)
                else:
                    self.flush(route)
                if not route.reading:
                    self.settle(route)

    def read(self, route: Route) -> None:
        chunk = os.read(route.src, CHUNK_BYTES)
        if not chunk:
            self.end(route)
            return
        # Only the new chunk is searched: the tail has no newline. Searching the
        # whole held line again on every read made a long line quadratic.
        newline = chunk.rfind(b'\n')
        if newline < 0:
            route.tail += chunk
        else:
            route.lines = route.tail + chunk[: newline + 1]
            route.tail = bytearray(chunk[newline + 1 :])
        # Forward first: the capture stays off the latency path. With `line`,
        # whole lines only. A forward that finds the peer gone ends the route,
        # and `end` captures these lines, then the tail, in that order.
        self.forward(route, route.lines if route.line else chunk)
        route.extra.write(chunk)
        self.capture(route)

    def capture(self, route: Route) -> None:
        if route.lines:
            write_all(self.cap, mark_lines(route.marker, route.lines))
            route.lines = bytearray()

    def forward(self, route: Route, data) -> None:
        if route.dst is None or not data:
            return
        if not route.out:
            # The usual case, kept short: the peer takes it all at once.
            try:
                written = os.write(route.dst, data)
            except BlockingIOError:
                written = 0
            except BrokenPipeError:
                self.broken(route)
                return
            if written == len(data):
                return
            data = data[written:]
        route.out += data
        self.flush(route)

    def broken(self, route: Route) -> None:
        # The peer is gone, and so is this route: closing what it reads shows
        # its writer a broken pipe too, as without a tee.
        route.out = bytearray()
        assert route.dst is not None
        self.close(route.dst)
        route.dst = None
        if route.reading:
            self.end(route)
        self.close(route.src)

    def flush(self, route: Route) -> None:
        if route.dst is None:
            return
        try:
            while route.out:
                del route.out[: os.write(route.dst, route.out)]
        except BlockingIOError:
            pass
        except BrokenPipeError:
            self.broken(route)
            return
        self.watch(route.dst, WRITE if route.out else 0)
        if route.reading:
            # A writer may run one chunk ahead of its peer; past that it blocks
            # on its own pipe until the peer catches up, as without a tee.
            self.watch(route.src, 0 if len(route.out) >= CHUNK_BYTES else READ)

    def end(self, route: Route) -> None:
        """`src` is read no more: its writer's EOF, or its peer is gone."""
        route.reading = False
        # Not closed (unless the peer is gone): it was kept until exit when
        # every pipe had a tee of its own.
        self.watch(route.src, 0)
        self.capture(route)
        if route.tail:
            tail = bytes(route.tail)
            route.tail = bytearray()
            if route.line:
                self.forward(route, tail)
            # A last line without a newline still ends its record: the capture
            # is shared, and the next append would otherwise land on the same
            # line. (The reader drops line ends anyway.)
            write_all(self.cap, route.marker + tail + b'\n')

    def settle(self, route: Route) -> None:
        if route.reading or route.done:
            return
        if route.dst is not None and not route.out:
            # Everything is through: the peer sees EOF.
            self.close(route.dst)
            route.dst = None
        if route.dst is None:
            route.done = True
            self.live -= 1


def main() -> None:
    args = sys.argv[1:]
    line = False
    if args and args[0] == '--line':
        line = True
        args = args[1:]
    specs = []
    if args and args[0] == '--routes':
        rest = args[1:]
        for i in range(0, len(rest), 4):
            marker, src, dst, extra = rest[i : i + 4]
            specs.append((marker, int(src), None if dst == '-' else int(dst), extra))
    else:
        marker, extra = args
        specs.append((marker, sys.stdin.fileno(), sys.stdout.fileno(), extra))

    routes = []
    for marker, src, dst, extra in specs:
        routes.append(Route(marker.encode(), src, dst, open(extra, 'wb'), line))
    try:
        Tee(routes, sys.stderr.fileno()).run()
    finally:
        for route in routes:
            route.extra.close()


if __name__ == '__main__':
    main()
