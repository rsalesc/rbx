"""A `StupidSandbox` whose programs run in a container.

Everything about the box -- creating it, staging and symlinking files into it,
reading outputs back, cleaning it up -- is inherited unchanged and happens on the
host. Only the two methods that start processes are forwarded, to an agent in a
container that sees the box at the same absolute path and runs them with the
very same `StupidSandbox` code (see `docker_agent`). What the container adds is
the machine those programs run on: a Linux kernel that honours the stack and
address-space limits macOS ignores, no network, a read-only view of the host and
a cap on processes.

Which container, and how it is brought up, is the business of `rbx.box`
(`docker_runtime`): this layer only knows a `DockerBackend`, and `bind()` turns
one into a sandbox type `get_sandbox_type()` can hand out.
"""

from __future__ import annotations

import pathlib
from typing import ClassVar, List, Optional, Protocol, Tuple, Type

from rbx import utils
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.sandbox import CommunicationParams, SandboxLog, SandboxParams
from rbx.grading.judge.sandboxes.docker_agent import AgentClient
from rbx.grading.judge.sandboxes.stupid_sandbox import StupidSandbox


class DockerBackend(Protocol):
    def box_root(self) -> pathlib.Path:
        """Directory boxes are created in; mounted read-write at the same path."""
        ...

    def client(self) -> AgentClient:
        """The agent to send programs to, bringing its container up if needed."""
        ...

    def fingerprint(self) -> str:
        """Identity of the image programs run in, for cache keys."""
        ...

    def not_found_hint(self, executable: str) -> str:
        """What to tell the user when `executable` is missing from the image."""
        ...

    def is_visible(self, path: pathlib.Path) -> bool:
        """Whether the container sees `path` at the same location."""
        ...


class DockerSandbox(StupidSandbox):
    backend: ClassVar[Optional[DockerBackend]] = None

    @classmethod
    def bind(cls, backend: DockerBackend) -> Type['DockerSandbox']:
        return type(cls.__name__, (cls,), {'backend': backend})

    @classmethod
    def _backend(cls) -> DockerBackend:
        if cls.backend is None:
            raise RuntimeError('DockerSandbox used without a backend; see bind().')
        return cls.backend

    def __init__(
        self,
        file_cacher: Optional[FileCacher] = None,
        name: Optional[str] = None,
        temp_dir: Optional[pathlib.Path] = None,
        path: Optional[pathlib.Path] = None,
    ):
        # Boxes must live where the container can see them, whatever directory
        # the caller had in mind.
        box_root = self._backend().box_root()
        box_root.mkdir(parents=True, exist_ok=True)
        super().__init__(file_cacher, name, box_root, path)

    @classmethod
    def runs_on_host(cls) -> bool:
        return False

    def cache_fingerprint(self) -> Optional[str]:
        return self._backend().fingerprint()

    def program_not_found_hint(self, executable: str) -> Optional[str]:
        return self._backend().not_found_hint(executable)

    def create_symlink(
        self, path: pathlib.Path, from_path: pathlib.Path, override: bool = False
    ) -> Optional[pathlib.Path]:
        # A link to somewhere the container cannot see would dangle in there.
        # Returning None is the contract for "symlinks unsupported": callers fall
        # back to copying the file into the box. The usual case is the transient
        # file cache, which lives in a private temp directory.
        if not self._backend().is_visible(utils.abspath(from_path)):
            return None
        return super().create_symlink(path, from_path, override=override)

    def run(self, command: List[str], params: SandboxParams) -> SandboxLog:
        return self._backend().client().run(self.get_root_path(), command, params)

    def run_communication(
        self,
        command: List[str],
        params: SandboxParams,
        interactor_command: List[str],
        interactor_params: SandboxParams,
        communication_params: Optional[CommunicationParams] = None,
    ) -> Tuple[SandboxLog, SandboxLog]:
        return (
            self._backend()
            .client()
            .run_communication(
                self.get_root_path(),
                command,
                params,
                interactor_command,
                interactor_params,
                communication_params or CommunicationParams(),
            )
        )
