"""Build snapshots one at a time in the background, most wanted first."""

import dataclasses
import pathlib
import threading
from typing import Callable, Dict, List, Optional

QUEUED, BUILDING, READY, FAILED = 'queued', 'building', 'ready', 'failed'


@dataclasses.dataclass
class BuiltSite:
    """A built snapshot and where each of its pages came from."""

    root: pathlib.Path
    pages: set
    sources: Dict[str, str]  # built page path -> markdown source path


class Builder:
    """Builds snapshots on one worker thread.

    `build` turns a sha into a BuiltSite and may raise; it is never called for
    the same sha twice at once. `prioritize` moves a sha to the front.
    """

    def __init__(
        self,
        build: Callable[[str], BuiltSite],
        log: Callable[[str], None] = lambda message: None,
    ):
        self._build = build
        self._log = log
        self._cond = threading.Condition()
        self._queue: List[str] = []
        self.status: Dict[str, str] = {}
        self.errors: Dict[str, str] = {}
        self.sites: Dict[str, BuiltSite] = {}
        self._worker: Optional[threading.Thread] = None
        # Called on the worker thread after each background build succeeds.
        self.on_ready: Callable[[str], None] = lambda sha: None

    def add(self, sha: str, site: BuiltSite):
        """Register a snapshot that was built elsewhere."""
        with self._cond:
            self.sites[sha] = site
            self.status[sha] = READY
            self._cond.notify_all()

    def _run(self, sha: str):
        try:
            site = self._build(sha)
        except Exception as exc:  # noqa: BLE001 - surfaced through status
            with self._cond:
                self.status[sha] = FAILED
                self.errors[sha] = str(exc)
                self._cond.notify_all()
            self._log(f'Build of {sha[:10]} failed: {exc}')
            return
        with self._cond:
            self.sites[sha] = site
            self.status[sha] = READY
            self.errors.pop(sha, None)
            self._cond.notify_all()
        try:
            self.on_ready(sha)
        except Exception as exc:  # noqa: BLE001 - a hook must not stop the queue
            self._log(f'After building {sha[:10]}: {exc}')

    def enqueue(self, shas: List[str]):
        with self._cond:
            for sha in shas:
                if sha not in self.status:
                    self.status[sha] = QUEUED
                    self._queue.append(sha)
            self._cond.notify_all()
        self._start()

    def prioritize(self, sha: str):
        with self._cond:
            if self.status.get(sha) in (READY, BUILDING):
                return
            if sha in self._queue:
                self._queue.remove(sha)
            self.status[sha] = QUEUED
            self.errors.pop(sha, None)
            self._queue.insert(0, sha)
            self._cond.notify_all()
        self._start()

    def wait(self, sha: str, timeout: Optional[float] = None) -> str:
        with self._cond:
            self._cond.wait_for(
                lambda: self.status.get(sha) in (READY, FAILED), timeout=timeout
            )
            return self.status.get(sha, QUEUED)

    def _start(self):
        with self._cond:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._loop, daemon=True)
                self._worker.start()

    def _loop(self):
        while True:
            with self._cond:
                if not self._queue:
                    self._worker = None
                    return
                sha = self._queue.pop(0)
                self.status[sha] = BUILDING
            self._run(sha)
